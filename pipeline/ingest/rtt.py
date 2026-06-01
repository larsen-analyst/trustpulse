"""
TrustPulse — pipeline/ingest/rtt.py
Ingests raw NHS RTT waiting times ZIP files, derives meaningful metrics
from the 108 weekly wait bucket columns, and saves rtt_clean.csv to data/processed/

Usage:
    python pipeline\ingest\rtt.py

Output:
    data/processed/rtt_clean.csv

Source data:
    data/raw/rtt/  (ZIP files, one per month, each containing one large CSV)

Format notes (confirmed from sample files):
    - Each ZIP contains one CSV named like: 20220430-RTT-APRIL-2022-full-extract-revised.csv
    - Period column values like: RTT-APRIL-2022
    - 108 weekly wait bucket columns: Gt 00 To 01 Weeks SUM 1 ... Gt 104 Weeks SUM 1
    - Key identifier columns: Provider Org Code, Provider Org Name,
      RTT Part Type, RTT Part Description, Treatment Function Code,
      Treatment Function Name, Total, Total All

Derived metrics (raw buckets are discarded after calculation):
    - total_waiting          : Total All column (includes unknown clock start)
    - waiting_under_18_weeks : Sum of week buckets 0 to 17
    - waiting_18_to_52_weeks : Sum of week buckets 18 to 51
    - waiting_over_52_weeks  : Sum of week buckets 52 to 103
    - waiting_over_104_weeks : Gt 104 Weeks SUM 1 bucket
    - pct_within_18_weeks    : waiting_under_18_weeks / total_waiting * 100
    - median_wait_weeks_est  : Weighted midpoint estimate across all buckets

RTT Part Types retained:
    - Part_1: Admitted Pathways
    - Part_2: Incomplete Pathways (primary NHS 18-week target metric)
    - Part_3: Non-Admitted Pathways

Granularity:
    - One row per trust per month per treatment function per RTT part type
    - Enables specialty-level drill-down in the dashboard
    - Aggregate to trust total by grouping on period_date + provider_org_code
"""

import os
import glob
import zipfile
import io
import pandas as pd
import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "rtt")
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED_DIR, "rtt_clean.csv")

# ── Week bucket configuration ─────────────────────────────────────────────────

# The files contain columns named "Gt 00 To 01 Weeks SUM 1" through
# "Gt 103 To 104 Weeks SUM 1" and then "Gt 104 Weeks SUM 1" for 104+.
# We build the expected column names programmatically.

def build_bucket_column_names():
    """
    Build the list of weekly wait bucket column names as they appear in the raw files.
    Returns a list of 105 column names: 104 banded columns + 1 open-ended 104+ column.
    """
    cols = []
    for i in range(104):
        low = str(i).zfill(2)
        high = str(i + 1).zfill(2)
        cols.append(f"Gt {low} To {high} Weeks SUM 1")
    cols.append("Gt 104 Weeks SUM 1")
    return cols


BUCKET_COLS = build_bucket_column_names()

# Week midpoints for median estimation
# Each bucket "Gt N to N+1 weeks" has midpoint N + 0.5
# The 104+ bucket is assigned midpoint 106 (a convention, not exact)
BUCKET_MIDPOINTS = [i + 0.5 for i in range(104)] + [106.0]


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_rtt_period(period_str):
    """
    Convert RTT Period value like 'RTT-APRIL-2022' into a pandas Timestamp.
    Returns NaT if unparseable.
    """
    try:
        stripped = str(period_str).replace("RTT-", "").strip()
        return pd.to_datetime(stripped, format="%B-%Y")
    except Exception:
        return pd.NaT


def estimate_median_wait(bucket_values, midpoints):
    """
    Estimate median wait in weeks using weighted midpoint across all buckets.
    Returns NaN if total is zero or all values are missing.

    This is an approximation. It gives the weighted mean of bucket midpoints,
    which is a reasonable proxy for median wait at trust level.
    Flag to users: this is an estimate derived from banded data, not exact.
    """
    total = np.nansum(bucket_values)
    if total == 0:
        return np.nan
    weighted_sum = np.nansum([v * m for v, m in zip(bucket_values, midpoints)])
    return round(weighted_sum / total, 2)


def load_zip_file(filepath):
    """
    Open a ZIP file, find the CSV inside, and return a DataFrame.
    Returns None if the file cannot be read.
    """
    try:
        with zipfile.ZipFile(filepath, "r") as z:
            csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                print(f"  WARNING: No CSV found inside {os.path.basename(filepath)}")
                return None
            if len(csv_names) > 1:
                print(f"  WARNING: Multiple CSVs in {os.path.basename(filepath)}, using first: {csv_names[0]}")
            with z.open(csv_names[0]) as f:
                df = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8"), dtype=str, low_memory=False)
                return df
    except Exception as e:
        print(f"  WARNING: Could not read {os.path.basename(filepath)}: {e}")
        return None


def derive_metrics(df, available_buckets):
    """
    Given a DataFrame with bucket columns already converted to numeric,
    derive all TrustPulse RTT metrics and return them as new columns.
    Drops the raw bucket columns afterwards.
    """

    # Identify which bucket columns are actually present in this file
    # (column names should be consistent but we check to be safe)
    present_buckets = [c for c in available_buckets if c in df.columns]
    missing_buckets = [c for c in available_buckets if c not in df.columns]
    if missing_buckets:
        print(f"  NOTE: {len(missing_buckets)} bucket columns not found in this file.")
        print(f"  First missing: {missing_buckets[0]}")

    # Convert bucket columns to numeric
    for col in present_buckets:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Map bucket column names to their index position
    bucket_index = {col: i for i, col in enumerate(available_buckets)}

    # Get bucket arrays aligned to our full 105-column list
    def get_bucket_array(row):
        return [row.get(col, 0) for col in available_buckets]

    # Under 18 weeks: buckets index 0 to 17 (Gt 00-01 through Gt 17-18)
    under_18_cols = [available_buckets[i] for i in range(18) if available_buckets[i] in df.columns]
    df["waiting_under_18_weeks"] = df[under_18_cols].sum(axis=1).astype(int)

    # 18 to 52 weeks: buckets index 18 to 51
    w18_52_cols = [available_buckets[i] for i in range(18, 52) if available_buckets[i] in df.columns]
    df["waiting_18_to_52_weeks"] = df[w18_52_cols].sum(axis=1).astype(int)

    # Over 52 weeks: buckets index 52 to 103
    over_52_cols = [available_buckets[i] for i in range(52, 104) if available_buckets[i] in df.columns]
    df["waiting_over_52_weeks"] = df[over_52_cols].sum(axis=1).astype(int)

    # Over 104 weeks: last bucket only
    over_104_col = available_buckets[104]  # "Gt 104 Weeks SUM 1"
    if over_104_col in df.columns:
        df["waiting_over_104_weeks"] = df[over_104_col].astype(int)
    else:
        df["waiting_over_104_weeks"] = 0

    # Total waiting from Total All column (includes unknown clock start date)
    if "total_all" in df.columns:
        df["total_waiting"] = pd.to_numeric(df["total_all"], errors="coerce").fillna(0).astype(int)
    elif "total" in df.columns:
        df["total_waiting"] = pd.to_numeric(df["total"], errors="coerce").fillna(0).astype(int)
    else:
        # Fall back to summing all buckets
        df["total_waiting"] = df[present_buckets].sum(axis=1).astype(int)

    # Percentage within 18 weeks
    df["pct_within_18_weeks"] = np.where(
        df["total_waiting"] > 0,
        (df["waiting_under_18_weeks"] / df["total_waiting"] * 100).round(2),
        np.nan
    )

    # Median wait estimate (weighted mean of bucket midpoints)
    print("  Calculating median wait estimates (this may take a moment)...")
    midpoint_values = [BUCKET_MIDPOINTS[i] for i in range(len(available_buckets))]
    bucket_matrix = df[present_buckets].values
    totals = bucket_matrix.sum(axis=1)
    weighted_sums = (bucket_matrix * midpoint_values[:bucket_matrix.shape[1]]).sum(axis=1)
    df["median_wait_weeks_est"] = np.where(
        totals > 0,
        (weighted_sums / totals).round(2),
        np.nan
    )

    # Drop all raw bucket columns
    df = df.drop(columns=present_buckets)

    return df


# ── Main ingestion logic ──────────────────────────────────────────────────────

def ingest_rtt():
    print("=" * 60)
    print("TrustPulse | RTT Waiting Times Ingestion")
    print("=" * 60)

    # 1. Find all ZIP files
    pattern = os.path.join(RAW_DIR, "*.zip")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"ERROR: No ZIP files found in {RAW_DIR}")
        print("Check that RAW_DIR is correct and files are present.")
        return

    print(f"Found {len(files)} ZIP files in {RAW_DIR}")

    # 2. Load, derive metrics, and collect each month
    frames = []
    for i, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        print(f"\n[{i}/{len(files)}] Processing {filename}...")

        df = load_zip_file(filepath)
        if df is None:
            continue

        print(f"  Raw shape: {df.shape[0]:,} rows x {df.shape[1]} columns")

        # 3. Standardise column names
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # 4. Parse period date
        if "period" not in df.columns:
            print(f"  WARNING: No 'period' column found. Skipping {filename}.")
            continue

        df["period_date"] = df["period"].apply(parse_rtt_period)
        unparsed = df["period_date"].isna().sum()
        if unparsed > 0:
            print(f"  WARNING: {unparsed:,} rows with unparseable period. Dropping.")
            df = df[df["period_date"].notna()].copy()

        # 5. Keep only the columns we need before deriving metrics
        # Identifier columns
        id_cols = [
            "period_date",
            "provider_org_code",
            "provider_org_name",
            "rtt_part_type",
            "rtt_part_description",
            "treatment_function_code",
            "treatment_function_name",
        ]

        # Rename Total All if present
        if "total_all" not in df.columns and "total all" in df.columns:
            df = df.rename(columns={"total all": "total_all"})

        # Check which id columns are actually present
        missing_id = [c for c in id_cols if c not in df.columns]
        if missing_id:
            print(f"  WARNING: Missing identifier columns: {missing_id}")
            id_cols = [c for c in id_cols if c in df.columns]

        # Rebuild bucket column names in lowercase (as they appear after standardisation)
        bucket_cols_lower = [c.lower().replace(" ", "_") for c in BUCKET_COLS]

        # Keep id cols + bucket cols + total cols
        total_cols = [c for c in ["total", "total_all", "patients_with_unknown_clock_start_date"]
                      if c in df.columns]
        keep_cols = id_cols + total_cols + [c for c in bucket_cols_lower if c in df.columns]
        df = df[keep_cols].copy()

        # 6. Derive metrics (pass lowercase bucket names)
        available_buckets_lower = [c for c in bucket_cols_lower if c in df.columns]

        # Convert bucket cols to numeric
        for col in available_buckets_lower:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # Under 18 weeks
        under_18 = available_buckets_lower[:18]
        df["waiting_under_18_weeks"] = df[under_18].sum(axis=1).astype(int)

        # 18 to 52 weeks
        w18_52 = available_buckets_lower[18:52]
        df["waiting_18_to_52_weeks"] = df[w18_52].sum(axis=1).astype(int)

        # Over 52 weeks
        over_52 = available_buckets_lower[52:104]
        df["waiting_over_52_weeks"] = df[over_52].sum(axis=1).astype(int)

        # Over 104 weeks
        over_104_col = available_buckets_lower[104] if len(available_buckets_lower) > 104 else None
        if over_104_col:
            df["waiting_over_104_weeks"] = df[over_104_col].astype(int)
        else:
            df["waiting_over_104_weeks"] = 0

        # Total waiting
        if "total_all" in df.columns:
            df["total_waiting"] = pd.to_numeric(df["total_all"], errors="coerce").fillna(0).astype(int)
        elif "total" in df.columns:
            df["total_waiting"] = pd.to_numeric(df["total"], errors="coerce").fillna(0).astype(int)
        else:
            df["total_waiting"] = df[available_buckets_lower].sum(axis=1).astype(int)

        # Percentage within 18 weeks
        df["pct_within_18_weeks"] = np.where(
            df["total_waiting"] > 0,
            (df["waiting_under_18_weeks"] / df["total_waiting"] * 100).round(2),
            np.nan
        )

        # Median wait estimate
        midpoints_trimmed = BUCKET_MIDPOINTS[:len(available_buckets_lower)]
        bucket_matrix = df[available_buckets_lower].values
        totals = bucket_matrix.sum(axis=1)
        weighted_sums = (bucket_matrix * midpoints_trimmed).sum(axis=1)
        df["median_wait_weeks_est"] = np.where(
            totals > 0,
            np.round(weighted_sums / totals, 2),
            np.nan
        )

        # Drop raw bucket columns and total helper columns
        drop_cols = available_buckets_lower + [c for c in ["total", "total_all",
                     "patients_with_unknown_clock_start_date"] if c in df.columns]
        df = df.drop(columns=drop_cols)

        print(f"  Rows after metric derivation: {df.shape[0]:,}")
        frames.append(df)

    if not frames:
        print("ERROR: No files could be processed. Stopping.")
        return

    # 7. Concatenate all months
    print("\nCombining all months...")
    combined = pd.concat(frames, ignore_index=True)
    print(f"Combined shape: {combined.shape[0]:,} rows x {combined.shape[1]} columns")

    # 8. Remove duplicate rows
    before_dedup = len(combined)
    combined = combined.drop_duplicates()
    after_dedup = len(combined)
    if before_dedup != after_dedup:
        print(f"Removed {before_dedup - after_dedup:,} duplicate rows")

    # 9. Sort
    sort_cols = ["period_date", "provider_org_code", "rtt_part_type", "treatment_function_code"]
    sort_cols = [c for c in sort_cols if c in combined.columns]
    combined = combined.sort_values(sort_cols).reset_index(drop=True)

    # 10. Save
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    # 11. Summary
    print("\n── Summary ──────────────────────────────────────────────")
    print(f"  Total rows:        {len(combined):,}")
    print(f"  Columns:           {combined.shape[1]}")
    if "provider_org_code" in combined.columns:
        print(f"  Unique trusts:     {combined['provider_org_code'].nunique():,}")
    if "treatment_function_name" in combined.columns:
        print(f"  Unique specialties:{combined['treatment_function_name'].nunique():,}")
    if "rtt_part_type" in combined.columns:
        print(f"  RTT part types:    {sorted(combined['rtt_part_type'].unique())}")
    if "period_date" in combined.columns:
        date_min = combined["period_date"].min().strftime("%B %Y")
        date_max = combined["period_date"].max().strftime("%B %Y")
        print(f"  Date range:        {date_min} to {date_max}")
    if "pct_within_18_weeks" in combined.columns:
        mean_pct = combined.loc[
            combined["rtt_part_type"] == "Part_2", "pct_within_18_weeks"
        ].mean()
        print(f"  Mean % within 18 weeks (Incomplete Pathways): {mean_pct:.1f}%")
    print("─────────────────────────────────────────────────────────")
    print("RTT ingestion complete.")
    print("\nNOTE: median_wait_weeks_est is a weighted mean approximation")
    print("derived from banded data. It is not an exact median.")
    print("Always show this disclaimer alongside the metric in the dashboard.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ingest_rtt()
