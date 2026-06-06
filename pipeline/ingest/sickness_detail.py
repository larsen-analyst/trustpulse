"""
TrustPulse -- pipeline/ingest/sickness_detail.py
Ingests NHS Sickness Absence by reason, staff group and organisation files.

Output:
    data/processed/sickness_detail_clean.csv

Metrics per trust per month:
    For key staff groups: nursing, medical, support, all
        - fte_days_lost
        - fte_days_available
        - sickness_rate (days lost / days available)

    For key absence reasons (all staff groups combined):
        - s10_mh_pct    : mental health / stress / depression % of total days lost
        - s11_back_pct  : back problems % of total
        - s12_msk_pct   : other musculoskeletal % of total
        - s13_cold_pct  : cold/flu % of total
        - s98_other_pct : other known causes % of total
        - mh_flag       : True if mental health % above 30% threshold

Source:
    data/raw/sickness/trust/
    NHS Sickness Absence by reason, staff group and organisation CSV, [Month Year].csv

Notes:
    - Files cover April 2024 to January 2026 (25 files)
    - Filter to org-level rows only (exclude national/regional aggregates)
    - ORG_CODE must not contain 'All' and must not be null
    - DATE column is in DD/MM/YYYY format
"""

import os
import glob
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "sickness", "trust")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "sickness_detail_clean.csv")

# Staff groups to extract individually
STAFF_GROUP_MAP = {
    "Nurses & health visitors":           "nursing",
    "HCHS doctors - All grades":          "medical",
    "Midwives":                           "midwives",
    "Ambulance staff":                    "ambulance",
    "Support to clinical staff":          "support_clinical",
    "Support to doctors, nurses & midwives": "support_dnm",
    "All staff groups":                   "all",
}

# Reason codes to extract
REASON_MAP = {
    "S10 Anxiety/stress/depression/other psychiatric illnesses": "s10_mh",
    "S11 Back Problems":                                         "s11_back",
    "S12 Other musculoskeletal problems":                        "s12_msk",
    "S13 Cold Cough Flu - Influenza":                            "s13_cold",
    "S98 Other known causes - not elsewhere classified":         "s98_other",
}

# Mental health flag threshold -- national average is approximately 28%
MH_FLAG_THRESHOLD = 0.30


def process_file(filepath):
    """Process one sickness detail file. Returns two DataFrames: staff_group_df and reason_df."""
    df = pd.read_csv(filepath, dtype=str, low_memory=False)

    # Filter to organisation level only
    mask = (
        df["ORG_CODE"].notna() &
        ~df["ORG_CODE"].str.contains("All", case=False, na=True) &
        ~df["NHSE_CODE"].str.contains("All", case=False, na=True)
    )
    df = df[mask].copy()

    if len(df) == 0:
        return pd.DataFrame(), pd.DataFrame()

    # Parse date
    df["period_date"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["period_date"])

    # Convert numeric columns
    for col in ["FTE_DAYS_AVAILABLE", "FTE_DAYS_LOST", "FTE_DAYS_LOST_REASON"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    period_date = df["period_date"].iloc[0]

    # --- Staff group breakdown ---
    sg_rows = []
    for group_label, short_name in STAFF_GROUP_MAP.items():
        sub = df[df["STAFF_GROUP"] == group_label].groupby("ORG_CODE").agg(
            fte_days_available=("FTE_DAYS_AVAILABLE", "sum"),
            fte_days_lost=("FTE_DAYS_LOST", "sum"),
        ).reset_index()
        sub["staff_group"] = short_name
        sub["period_date"] = period_date
        sub["org_name"] = df.groupby("ORG_CODE")["ORG_NAME"].first().reindex(sub["ORG_CODE"]).values
        sg_rows.append(sub)

    staff_df = pd.concat(sg_rows, ignore_index=True) if sg_rows else pd.DataFrame()
    if not staff_df.empty:
        staff_df["sickness_rate"] = (
            staff_df["fte_days_lost"] / staff_df["fte_days_available"].replace(0, float("nan"))
        ).round(4)

    # --- Reason breakdown (all staff groups combined) ---
    all_staff = df[df["STAFF_GROUP"] == "All staff groups"].copy()
    total_lost = all_staff.groupby("ORG_CODE")["FTE_DAYS_LOST"].first().reset_index()
    total_lost.columns = ["ORG_CODE", "total_fte_lost"]

    reason_rows = []
    for reason_label, short_name in REASON_MAP.items():
        sub = all_staff[all_staff["REASON"] == reason_label].groupby("ORG_CODE")["FTE_DAYS_LOST_REASON"].sum().reset_index()
        sub.columns = ["ORG_CODE", short_name + "_days"]
        reason_rows.append(sub)

    if reason_rows:
        reason_df = reason_rows[0]
        for r in reason_rows[1:]:
            reason_df = reason_df.merge(r, on="ORG_CODE", how="outer")
        reason_df = reason_df.merge(total_lost, on="ORG_CODE", how="left")
        reason_df["period_date"] = period_date

        # Calculate percentages
        for short_name in REASON_MAP.values():
            col = short_name + "_days"
            pct_col = short_name + "_pct"
            if col in reason_df.columns:
                reason_df[pct_col] = (
                    reason_df[col] / reason_df["total_fte_lost"].replace(0, float("nan"))
                ).round(4)

        # Mental health flag
        if "s10_mh_pct" in reason_df.columns:
            reason_df["mh_flag"] = reason_df["s10_mh_pct"] > MH_FLAG_THRESHOLD

        reason_df = reason_df.rename(columns={"ORG_CODE": "org_code"})
    else:
        reason_df = pd.DataFrame()

    staff_df = staff_df.rename(columns={"ORG_CODE": "org_code"}) if not staff_df.empty else staff_df

    return staff_df, reason_df


def ingest_sickness_detail():
    print("=" * 60)
    print("TrustPulse | Sickness Detail Ingestion")
    print("=" * 60)

    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))
    print(f"Found {len(files)} sickness detail files")

    if not files:
        print(f"ERROR: No files found in {RAW_DIR}")
        return

    all_staff = []
    all_reason = []

    for i, filepath in enumerate(files, 1):
        basename = os.path.basename(filepath)
        print(f"[{i}/{len(files)}] {basename[:70]}...")
        sg_df, re_df = process_file(filepath)
        if not sg_df.empty:
            all_staff.append(sg_df)
        if not re_df.empty:
            all_reason.append(re_df)

    if not all_staff:
        print("ERROR: No staff group data extracted.")
        return

    # Combine staff group data
    staff_combined = pd.concat(all_staff, ignore_index=True).drop_duplicates()

    # Pivot staff group to wide format: one row per trust per month
    staff_pivot = staff_combined.pivot_table(
        index=["org_code", "org_name", "period_date"],
        columns="staff_group",
        values=["fte_days_lost", "sickness_rate"],
        aggfunc="first"
    )
    staff_pivot.columns = [f"sick_{col[0]}_{col[1]}" for col in staff_pivot.columns]
    staff_pivot = staff_pivot.reset_index()

    # Combine reason data
    if all_reason:
        reason_combined = pd.concat(all_reason, ignore_index=True).drop_duplicates(
            subset=["org_code", "period_date"]
        )
        # Merge staff pivot with reason data
        final = staff_pivot.merge(
            reason_combined.drop(columns=[c for c in reason_combined.columns if c.endswith("_days")], errors="ignore"),
            on=["org_code", "period_date"],
            how="left"
        )
    else:
        final = staff_pivot

    final = final.sort_values(["org_code", "period_date"]).reset_index(drop=True)

    os.makedirs(PROCESSED, exist_ok=True)
    final.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Rows         : {len(final):,}")
    print(f"  Columns      : {final.shape[1]}")
    print(f"  Unique trusts: {final['org_code'].nunique()}")
    print(f"  Date range   : {final['period_date'].min().strftime('%B %Y')} to {final['period_date'].max().strftime('%B %Y')}")

    if "mh_flag" in final.columns:
        mh_trusts = final[final["mh_flag"] == True]["org_code"].nunique()
        print(f"  MH flag trusts (>30% of sickness is mental health): {mh_trusts}")

    if "sick_sickness_rate_nursing" in final.columns:
        latest = final[final["period_date"] == final["period_date"].max()]
        print(f"\n  Latest month nursing sickness rate -- top 10:")
        top10 = latest.nlargest(10, "sick_sickness_rate_nursing")[["org_code", "org_name", "sick_sickness_rate_nursing", "s10_mh_pct"]].copy()
        print(top10.to_string(index=False))

    print("\nSickness detail ingestion complete.")


if __name__ == "__main__":
    ingest_sickness_detail()
