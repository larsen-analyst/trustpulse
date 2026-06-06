"""
TrustPulse -- pipeline/ingest/cancer_waiting.py
Ingests NHS Cancer Waiting Times Combined Provider CSV files.

Output:
    data/processed/cancer_waiting_clean.csv

Metrics per trust per month:
    fds_total          : total FDS (28-day faster diagnosis) pathways
    fds_within         : pathways meeting 28-day standard
    fds_performance    : % meeting standard (target 77%)
    t62d_total         : total 62-day treatment pathways
    t62d_within        : pathways meeting 62-day standard
    t62d_performance   : % meeting standard (target 85%)

Source:
    data/raw/cancer_waiting/
    Combined Provider and Commissioner CSV files, April 2022 to March 2026.

Notes:
    - Filter to Basis == 'Provider' and Org_Code not in national aggregates
    - Standards: FDS = 28-day Faster Diagnosis, 62D = 62-day treatment
    - Cancer_Type == 'All' and Referral_Route_or_Stage == 'All' for overall performance
    - Standards changed in October 2023 -- pre/post not directly comparable
      but trend direction is still valid
    - 172 unique provider org codes in 2024-25
"""

import os
import glob
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "cancer_waiting")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "cancer_waiting_clean.csv")

EXCLUDE_CODES = {"Total", "England", "nan", ""}

STANDARDS = {
    "FDS": {"total": "fds_total", "within": "fds_within", "perf": "fds_performance"},
    "62D": {"total": "t62d_total", "within": "t62d_within", "perf": "t62d_performance"},
}


def process_file(filepath):
    """Process one CWT combined CSV file."""
    df = pd.read_csv(filepath, dtype=str, low_memory=False)

    # Filter to provider level, all cancers, all routes
    mask = (
        (df["Basis"] == "Provider") &
        (~df["Org_Code"].isin(EXCLUDE_CODES)) &
        (df["Cancer_Type"].str.upper().isin(["ALL", "ALL CANCERS"])) &
        (df["Referral_Route_or_Stage"].str.upper().isin(["ALL", "ALL ROUTES", "ALL STAGES"]))
    )
    df = df[mask].copy()

    if len(df) == 0:
        # Try without cancer type filter -- some files use different values
        mask2 = (
            (df["Basis"] == "Provider") &
            (~df["Org_Code"].isin(EXCLUDE_CODES))
        )
        df_all = pd.read_csv(filepath, dtype=str, low_memory=False)
        df = df_all[mask2].copy()
        # Keep only rows where Cancer_Type and Referral_Route contain "All"
        df = df[
            df["Cancer_Type"].str.lower().str.contains("all", na=False) &
            df["Referral_Route_or_Stage"].str.lower().str.contains("all", na=False)
        ].copy()

    if len(df) == 0:
        return pd.DataFrame()

    # Parse period
    df["period_date"] = pd.to_datetime(df["Period"], errors="coerce")
    df = df.dropna(subset=["period_date"])

    # Convert numerics
    for col in ["Total", "Within", "Performance"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Extract FDS and 62D separately
    frames = []
    for std_code, cols in STANDARDS.items():
        sub = df[df["Standard_or_Item"] == std_code].copy()
        if sub.empty:
            continue
        agg = sub.groupby(["Org_Code", "Org_Name", "period_date"]).agg(
            total=("Total", "sum"),
            within=("Within", "sum"),
        ).reset_index()
        agg["performance"] = (agg["within"] / agg["total"].replace(0, float("nan"))).round(4)
        agg = agg.rename(columns={
            "Org_Code": "org_code",
            "Org_Name": "org_name",
            "total": cols["total"],
            "within": cols["within"],
            "performance": cols["perf"],
        })
        frames.append(agg)

    if not frames:
        return pd.DataFrame()

    # Merge FDS and 62D on org_code and period_date
    result = frames[0]
    for f in frames[1:]:
        merge_cols = [c for c in ["org_code", "org_name", "period_date"] if c in f.columns]
        result = result.merge(f, on=merge_cols, how="outer")

    return result


def ingest_cancer_waiting():
    print("=" * 60)
    print("TrustPulse | Cancer Waiting Times Ingestion")
    print("=" * 60)

    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))
    print(f"Found {len(files)} CSV files")

    if not files:
        print(f"ERROR: No CSV files found in {RAW_DIR}")
        return

    frames = []
    for i, filepath in enumerate(files, 1):
        basename = os.path.basename(filepath)
        print(f"[{i}/{len(files)}] {basename[:70]}...")
        df = process_file(filepath)
        if df.empty:
            print(f"  WARNING: No usable data extracted")
            continue
        print(f"  Rows: {len(df):,} | Orgs: {df['org_code'].nunique()} | "
              f"Dates: {df['period_date'].min().strftime('%b %Y')} to {df['period_date'].max().strftime('%b %Y')}")
        frames.append(df)

    if not frames:
        print("ERROR: No data extracted from any file.")
        return

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["org_code", "period_date"])
    combined = combined.sort_values(["org_code", "period_date"]).reset_index(drop=True)

    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Rows          : {len(combined):,}")
    print(f"  Columns       : {combined.shape[1]}")
    print(f"  Unique trusts : {combined['org_code'].nunique()}")
    print(f"  Date range    : {combined['period_date'].min().strftime('%B %Y')} to "
          f"{combined['period_date'].max().strftime('%B %Y')}")

    if "fds_performance" in combined.columns:
        latest = combined[combined["period_date"] == combined["period_date"].max()]
        print(f"\n  Latest month FDS performance -- bottom 10:")
        bottom = latest.dropna(subset=["fds_performance"]).nsmallest(10, "fds_performance")
        print(bottom[["org_code", "org_name", "fds_performance", "fds_total"]].to_string(index=False))

    if "t62d_performance" in combined.columns:
        latest = combined[combined["period_date"] == combined["period_date"].max()]
        print(f"\n  Latest month 62-day performance -- bottom 10:")
        bottom = latest.dropna(subset=["t62d_performance"]).nsmallest(10, "t62d_performance")
        print(bottom[["org_code", "org_name", "t62d_performance", "t62d_total"]].to_string(index=False))

    print("\nCancer waiting times ingestion complete.")


if __name__ == "__main__":
    ingest_cancer_waiting()
