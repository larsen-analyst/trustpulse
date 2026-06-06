"""
TrustPulse -- pipeline/ingest/outpatients.py
Ingests NHS Hospital Outpatient Activity Provider Level Analysis files.
Three annual files: 2022-23, 2023-24, 2024-25.

Output:
    data/processed/outpatients_clean.csv

Metrics extracted per trust per year:
    - total_attended
    - total_dna
    - total_patient_cancelled
    - total_hospital_cancelled
    - dna_rate (dna / (attended + dna))
    - hospital_cancellation_rate (hospital_cancelled / total_appointments)
    - patient_cancellation_rate (patient_cancelled / total_appointments)

Source:
    https://digital.nhs.uk/data-and-information/publications/statistical/hospital-outpatient-activity
    Provider Level Analysis CSV files, financial years 2022-23 to 2024-25.

Notes:
    - '*' values are suppressed (small numbers) -- treated as null
    - Provider codes do not always match NHS trust org codes exactly
    - Joined to oversight file on org code to filter to NHS trusts only
    - Annual data only -- no monthly breakdown available
"""

import os
import glob
import pandas as pd

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR      = os.path.join(BASE_DIR, "data", "raw", "outpatients")
PROCESSED    = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE  = os.path.join(PROCESSED, "outpatients_clean.csv")

# Measures -- new format (2024-25) with numeric prefix
ATTENDED_MEASURES = [
    "01.Attended-Female", "02.Attended-Male", "03.Attended-Unknown Gender",
    "Attended-Female", "Attended-Male", "Attended-Unknown Gender",
]
DNA_MEASURES = [
    "04.DNA-Female", "05.DNA-Male", "06.DNA-Unknown Gender",
    "DNA-Female", "DNA-Male", "DNA-Unknown Gender",
]
PATIENT_CANCELLED_MEASURES = [
    "07.Patient Cancelled-Female", "08.Patient Cancelled-Male", "09.Patient Cancelled-Unknown Gender",
    "Patient Cancelled-Female", "Patient Cancelled-Male", "Patient Cancelled-Unknown Gender",
]
HOSPITAL_CANCELLED_MEASURES = [
    "10.Hospital Cancelled-Female", "11.Hospital Cancelled-Male", "12.Hospital Cancelled-Unknown Gender",
    "Hospital Cancelled-Female", "Hospital Cancelled-Male", "Hospital Cancelled-Unknown Gender",
]

# Map filename pattern to financial year label and period date
YEAR_MAP = {
    "2022-23": "2023-03-31",
    "2023-24": "2024-03-31",
    "2024-25": "2025-03-31",
}


def safe_numeric(series):
    """Convert series to numeric, treating '*' as null."""
    return pd.to_numeric(series.replace("*", None), errors="coerce")


def sum_measures(df, measures):
    """Sum a list of measures for each provider, treating * as 0."""
    result = pd.Series(0.0, index=df.index)
    for m in measures:
        mask = df["MEASURE"] == m
        vals = safe_numeric(df.loc[mask, "MEASURE_VALUE"].reindex(df.index))
        result = result.add(vals.fillna(0), fill_value=0)
    return result


def process_file(filepath, year_label, period_date):
    """Process one outpatients provider level analysis file."""
    print(f"  Loading: {os.path.basename(filepath)}")

    df = pd.read_csv(filepath, dtype=str)

    # Filter to provider level -- handle both old format ('Provider') and new ('03.Provider')
    provider_mask = df["GEOGRAPHY_LEVEL"].str.contains("Provider", case=False, na=False)

    # Filter to attendance summary -- handle both old and new measure type labels
    att_mask = df["MEASURE_TYPE"].str.contains("Attendance Summary", case=False, na=False)

    df = df[provider_mask & att_mask].copy()

    print(f"  Provider rows: {len(df):,} | Unique providers: {df['ORGANISATION_CODE'].nunique()}")

    # Pivot: one row per provider, columns for each measure
    df["MEASURE_VALUE_NUM"] = safe_numeric(df["MEASURE_VALUE"])

    pivot = df.pivot_table(
        index=["ORGANISATION_CODE", "ORGANISATION_DESCRIPTION"],
        columns="MEASURE",
        values="MEASURE_VALUE_NUM",
        aggfunc="sum"
    ).reset_index()

    pivot.columns.name = None

    # Sum to totals
    def col_sum(cols):
        available = [c for c in cols if c in pivot.columns]
        if not available:
            return pd.Series(0.0, index=pivot.index)
        return pivot[available].fillna(0).sum(axis=1)

    pivot["total_attended"]          = col_sum(ATTENDED_MEASURES)
    pivot["total_dna"]               = col_sum(DNA_MEASURES)
    pivot["total_patient_cancelled"] = col_sum(PATIENT_CANCELLED_MEASURES)
    pivot["total_hospital_cancelled"]= col_sum(HOSPITAL_CANCELLED_MEASURES)

    pivot["total_appointments"] = (
        pivot["total_attended"] +
        pivot["total_dna"] +
        pivot["total_patient_cancelled"] +
        pivot["total_hospital_cancelled"]
    )

    # Rates
    pivot["dna_rate"] = (
        pivot["total_dna"] / (pivot["total_attended"] + pivot["total_dna"])
    ).round(4)

    pivot["hospital_cancellation_rate"] = (
        pivot["total_hospital_cancelled"] / pivot["total_appointments"]
    ).round(4)

    pivot["patient_cancellation_rate"] = (
        pivot["total_patient_cancelled"] / pivot["total_appointments"]
    ).round(4)

    # Add year and period date
    pivot["financial_year"] = year_label
    pivot["period_date"]    = period_date

    # Rename org columns
    pivot = pivot.rename(columns={
        "ORGANISATION_CODE":        "org_code",
        "ORGANISATION_DESCRIPTION": "org_name_outp",
    })

    # Keep only what we need
    keep = [
        "period_date", "financial_year", "org_code", "org_name_outp",
        "total_attended", "total_dna", "total_patient_cancelled",
        "total_hospital_cancelled", "total_appointments",
        "dna_rate", "hospital_cancellation_rate", "patient_cancellation_rate",
    ]
    keep = [c for c in keep if c in pivot.columns]
    pivot = pivot[keep].copy()

    print(f"  Output rows: {len(pivot):,}")
    return pivot


def ingest_outpatients():
    print("=" * 60)
    print("TrustPulse | Outpatient Activity Ingestion")
    print("=" * 60)

    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))
    print(f"Found {len(files)} CSV files in {RAW_DIR}")

    if not files:
        print(f"ERROR: No CSV files found in {RAW_DIR}")
        return

    frames = []

    for filepath in files:
        basename = os.path.basename(filepath)
        year_label = None
        period_date = None

        for year, pdate in YEAR_MAP.items():
            if year in basename:
                year_label = year
                period_date = pdate
                break

        if not year_label:
            print(f"  SKIPPED (could not identify year): {basename}")
            continue

        print(f"\nProcessing {year_label}:")
        try:
            df = process_file(filepath, year_label, period_date)
            frames.append(df)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

    if not frames:
        print("ERROR: No files processed.")
        return

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates()
    combined = combined.sort_values(["period_date", "org_code"]).reset_index(drop=True)

    # Summary before filtering
    print(f"\nCombined (all providers): {len(combined):,} rows | "
          f"{combined['org_code'].nunique()} unique orgs")

    # Save full version
    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Total rows    : {len(combined):,}")
    print(f"  Unique orgs   : {combined['org_code'].nunique()}")
    print(f"  Years covered : {sorted(combined['financial_year'].unique())}")

    # Show DNA rate range as sense check
    print(f"\n  DNA rate summary:")
    print(f"    Mean  : {combined['dna_rate'].mean():.1%}")
    print(f"    Median: {combined['dna_rate'].median():.1%}")
    print(f"    Max   : {combined['dna_rate'].max():.1%}")

    # Show top 10 NHS trust DNA rates for 2024-25
    latest = combined[combined["financial_year"] == "2024-25"].copy()
    oversight_path = os.path.join(PROCESSED, "oversight_clean.csv")
    if os.path.exists(oversight_path):
        oversight = pd.read_csv(oversight_path, usecols=["Trust_code", "Trust_name"])
        nhs = latest[latest["org_code"].isin(oversight["Trust_code"])].copy()
        nhs = nhs.sort_values("dna_rate", ascending=False)
        print(f"\n  NHS trusts matched in 2024-25: {len(nhs)}")
        print(f"  Top 10 by DNA rate:")
        print(nhs[["org_code", "org_name_outp", "dna_rate",
                    "total_dna", "total_attended"]].head(10).to_string(index=False))
    else:
        print("  (oversight_clean.csv not found -- skipping NHS trust filter)")

    print("\nOutpatient ingestion complete.")


if __name__ == "__main__":
    ingest_outpatients()
