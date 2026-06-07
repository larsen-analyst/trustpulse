"""
TrustPulse -- pipeline/ingest/complaints.py
Ingests NHS Written Complaints (KO41a) secondary care organisation-level data.

Output:
    data/processed/complaints_clean.csv

Metrics per trust per year:
    comp_total_new              : total new written complaints
    comp_per_1000_admissions    : complaints rate per 1,000 admissions (calculated)
    comp_pct_upheld             : % of resolved complaints fully upheld
    comp_pct_comm               : % related to communications
    comp_pct_waiting            : % related to waiting times
    comp_pct_clinical           : % related to clinical treatment
    comp_pct_discharge          : % related to admissions, discharge and transfers
    comp_service_inpatient      : inpatient complaints count
    comp_service_outpatient     : outpatient complaints count
    comp_service_emergency      : emergency complaints count

Source:
    data/raw/complaints/
    Annual CSV zips 2022-23 to 2024-25. KO41a Secondary Care Org Level files.

Notes:
    - Org Level file has one row per trust per year
    - Filter to trust-level (not ICB or national aggregates)
    - Complaints rate requires activity denominator -- use A&E + admissions proxy
    - Annual data: one snapshot per year per trust
    - Subject area percentages identify where the trust has most patient dissatisfaction
"""

import os
import glob
import zipfile
import io
import re
import pandas as pd
import numpy as np

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "complaints")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "complaints_clean.csv")

YEAR_MAP = {
    "2022-23": pd.Timestamp("2023-03-31"),
    "2023-24": pd.Timestamp("2024-03-31"),
    "2024-25": pd.Timestamp("2025-03-31"),
}

# NHS trust org code prefixes (R = NHS trust, G = other NHS)
NHS_PREFIXES = tuple("RABCDEFGHJKLMNPQRSTVWXYZ")


def safe_numeric(s):
    return pd.to_numeric(s, errors="coerce").fillna(0)


def process_zip(filepath):
    """Process one complaints CSV zip file."""
    z = zipfile.ZipFile(filepath)
    # Find the secondary care org level CSV
    org_files = [n for n in z.namelist()
                 if "Secondary Care" in n and "Org Level" in n and n.endswith(".csv")]
    if not org_files:
        print(f"  WARNING: No Org Level CSV found in {os.path.basename(filepath)}")
        return pd.DataFrame()

    with z.open(org_files[0]) as f:
        df = pd.read_csv(f, dtype=str)

    # Extract year from Year column
    year_val = df["Year"].dropna().iloc[0] if "Year" in df.columns else None
    period_date = YEAR_MAP.get(year_val)
    if not period_date:
        print(f"  WARNING: Unknown year {year_val}")
        return pd.DataFrame()

    print(f"  Year: {year_val} | Rows: {len(df):,}")

    # Filter to NHS trust level only (not ICB, not national)
    df = df[df["Organisation_Code"].notna()].copy()
    df = df[~df["Organisation_Code"].astype(str).str.contains("Total|National|Region", case=False, na=True)]
    # Keep only org codes that look like NHS trust codes (3-5 chars, start with R or G etc.)
    df = df[df["Organisation_Code"].astype(str).str.match(r'^[A-Z][A-Z0-9]{2,4}$', na=False)]

    # Convert numeric columns
    num_cols = [c for c in df.columns if c not in
                ["Year", "NHS_England_Region_Code", "NHS_England_Region_Name",
                 "ICS_Code", "ICS_Name", "Organisation_Code",
                 "Organisation_Name", "Organisation_Type"]]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    total = df["Complaints_Total_New"]
    subject_total = df["Subject_Area_Sub_Total"].replace(0, np.nan)

    out = pd.DataFrame()
    out["org_code"]               = df["Organisation_Code"].astype(str).str.strip()
    out["org_name"]               = df["Organisation_Name"].astype(str).str.strip()
    out["org_type"]               = df["Organisation_Type"].astype(str).str.strip()
    out["period_date"]            = period_date
    out["financial_year"]         = year_val
    out["comp_total_new"]         = total.astype(int)
    out["comp_total_upheld"]      = df["Complaints_Number_Upheld"]
    out["comp_total_resolved"]    = df["Complaints_Total_Resolved"]
    out["comp_pct_upheld"]        = (df["Complaints_Number_Upheld"] /
                                     df["Complaints_Total_Resolved"].replace(0, np.nan)).round(4)

    # Subject area percentages -- what are patients complaining about
    out["comp_pct_comm"]          = (df["Subject_Area_Communications"] /
                                     subject_total).round(4)
    out["comp_pct_waiting"]       = (df["Subject_Area_Waiting_Times"] /
                                     subject_total).round(4)
    out["comp_pct_clinical"]      = (df["Clinical_Treatment_Sub_Total"] /
                                     subject_total).round(4)
    out["comp_pct_discharge"]     = (df["Subject_Area_Admissions_Discharge_And_Transfers"] /
                                     subject_total).round(4)
    out["comp_pct_care"]          = (df["Subject_Area_Patient_Care_Including_Nutrition_Hydration"] /
                                     subject_total).round(4)

    # Service breakdown
    out["comp_service_inpatient"]  = df["Service_Inpatient"].astype(int)
    out["comp_service_outpatient"] = df["Service_Outpatient"].astype(int)
    out["comp_service_emergency"]  = df["Service_Emergency"].astype(int)
    out["comp_service_mental"]     = df["Service_Mental_Health"].astype(int)
    out["comp_service_maternity"]  = df["Service_Maternity"].astype(int)

    return out.dropna(subset=["org_code"])


def ingest_complaints():
    print("=" * 60)
    print("TrustPulse | NHS Written Complaints Ingestion")
    print("=" * 60)

    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.zip")))
    print(f"Found {len(files)} zip files")

    frames = []
    for filepath in files:
        basename = os.path.basename(filepath)
        print(f"\nProcessing: {basename[:70]}")
        df = process_zip(filepath)
        if df.empty:
            continue
        print(f"  Trusts: {df['org_code'].nunique()}")
        frames.append(df)

    if not frames:
        print("ERROR: No data extracted.")
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
    print(f"  Years         : {sorted(combined['financial_year'].unique())}")

    latest = combined[combined["period_date"] == combined["period_date"].max()]
    nhs = latest[latest["org_code"].str.match(r'^R', na=False)]
    print(f"\n  NHS trusts in latest year (R-codes): {len(nhs)}")
    print(f"  Total complaints (latest year): {nhs['comp_total_new'].sum():,}")
    print(f"  Median complaints per trust: {nhs['comp_total_new'].median():.0f}")

    print(f"\n  Top 10 by total complaints (latest year):")
    top10 = nhs.nlargest(10, "comp_total_new")[
        ["org_code", "org_name", "comp_total_new", "comp_pct_comm",
         "comp_pct_waiting", "comp_pct_upheld"]].copy()
    print(top10.to_string(index=False))

    print(f"\n  Trusts with highest % waiting times complaints:")
    wait = nhs.nlargest(10, "comp_pct_waiting")[
        ["org_code", "org_name", "comp_total_new", "comp_pct_waiting"]].copy()
    print(wait.to_string(index=False))

    print("\nComplaints ingestion complete.")


if __name__ == "__main__":
    ingest_complaints()
