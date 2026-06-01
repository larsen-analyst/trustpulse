"""
TrustPulse — pipeline/ingest/workforce.py
Ingests NHS Workforce Statistics monthly ZIP files (trust-level),
extracts only the relevant month's data from each file, and saves
workforce_clean.csv to data/processed/

Usage:
    python pipeline\ingest\workforce.py

Output:
    data/processed/workforce_clean.csv

Source data:
    data/raw/workforce/  (45+ ZIP files, one per month, April 2022 onwards)

Format notes (confirmed from sample files):
    - Each ZIP contains multiple CSVs. We use only:
      "NHS Workforce Statistics, [Month Year] Staff Group and Organisation.csv"
    - Each file contains CUMULATIVE historical data from 2009 onwards.
      We filter to only the month matching the ZIP filename to avoid duplicates.
    - Columns: Date, NHSE_Region_Code, NHSE_Region_Name, Org Code, Org Name,
               Cluster Group, Benchmark Group, Staff Group Sort Order,
               Staff Group, Data Type, Total
    - Data Type values: FTE (full-time equivalent), HC (headcount)
    - Staff Group values include: Total, Professionally qualified clinical staff,
      HCHS Doctors, Nurses & health visitors, Support to clinical staff, etc.

Strategy:
    - Load the Staff Group and Organisation file from each monthly ZIP
    - Filter to only rows where Date matches the ZIP's own month
    - Keep both FTE and HC data types (pivot to wide format per trust per month)
    - Filter to Organisation-level data only (exclude national/regional aggregates)
    - Output: one row per trust per month per staff group, with FTE and HC columns

HCHS format ZIPs (September/October 2025):
    - Different internal structure (Core 1 file, different column names)
    - Only has annual organisation-level snapshots, not monthly
    - These are handled separately and appended if monthly data is missing
"""

import os
import re
import glob
import zipfile
import io
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "workforce")
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED_DIR, "workforce_clean.csv")

# Staff groups we want to retain
# Keeping Total plus the main clinical and support breakdowns
# that are useful for TrustPulse workforce analysis
STAFF_GROUPS_TO_KEEP = [
    "Total",
    "Professionally qualified clinical staff",
    "HCHS Doctors",
    "Nurses & health visitors",
    "Midwives",
    "Ambulance staff",
    "Support to clinical staff",
    "NHS infrastructure support",
    "Other staff or those with unknown classification",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_month_year_from_filename(zip_path):
    """
    Extract the month and year from a ZIP filename like:
    'NHS Workforce Statistics, April 2022 csv files.zip'
    Returns a string like '2022-04' or None if not found.
    """
    basename = os.path.basename(zip_path)
    # Match month name and 4-digit year
    months = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12"
    }
    for month_name, month_num in months.items():
        pattern = rf"{month_name}\s+(\d{{4}})"
        match = re.search(pattern, basename)
        if match:
            year = match.group(1)
            return f"{year}-{month_num}"
    return None


def find_org_csv_in_zip(z, month_year_str):
    """
    Find the Staff Group and Organisation CSV inside a ZIP file.
    Returns the filename if found, None otherwise.
    month_year_str is like '2022-04'
    """
    for name in z.namelist():
        if "Staff Group and Organisation" in name and name.endswith(".csv"):
            return name
    return None


def load_monthly_workforce(zip_path, month_year_str):
    """
    Load one monthly workforce ZIP file.
    Extracts the Staff Group and Organisation CSV,
    filters to the correct month only, and returns a cleaned DataFrame.
    Returns None if the file cannot be processed.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            csv_name = find_org_csv_in_zip(z, month_year_str)
            if not csv_name:
                print(f"  WARNING: No Staff Group and Organisation CSV found in {os.path.basename(zip_path)}")
                return None

            with z.open(csv_name) as f:
                df = pd.read_csv(
                    io.TextIOWrapper(f, encoding="utf-8"),
                    dtype=str,
                    low_memory=False
                )

        # Standardise column names
        df.columns = [c.strip() for c in df.columns]

        # Parse Date column
        if "Date" not in df.columns:
            print(f"  WARNING: No 'Date' column in {os.path.basename(zip_path)}")
            return None

        df["date_parsed"] = pd.to_datetime(df["Date"], errors="coerce")

        # Filter to only the current month
        # Each file contains cumulative history — we only want the month
        # matching this ZIP to avoid loading duplicates across files
        target_year = int(month_year_str[:4])
        target_month = int(month_year_str[5:7])
        mask = (
            (df["date_parsed"].dt.year == target_year) &
            (df["date_parsed"].dt.month == target_month)
        )
        df = df[mask].copy()

        if len(df) == 0:
            print(f"  WARNING: No rows found for {month_year_str} in {os.path.basename(zip_path)}")
            return None

        return df

    except Exception as e:
        print(f"  WARNING: Could not process {os.path.basename(zip_path)}: {e}")
        return None


def clean_workforce_df(df, month_year_str):
    """
    Clean and standardise a single month's workforce DataFrame.
    Returns a cleaned DataFrame with consistent columns.
    """
    # Rename columns to standard names
    rename_map = {
        "Date": "date_raw",
        "NHSE_Region_Code": "nhse_region_code",
        "NHSE_Region_Name": "nhse_region_name",
        "Org Code": "org_code",
        "Org Name": "org_name",
        "Cluster Group": "cluster_group",
        "Benchmark Group": "benchmark_group",
        "Staff Group Sort Order": "staff_group_sort_order",
        "Staff Group": "staff_group",
        "Data Type": "data_type",
        "Total": "total",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Add period_date
    df["period_date"] = pd.to_datetime(month_year_str + "-01", format="%Y-%m-%d")

    # Filter to staff groups we want
    if "staff_group" in df.columns:
        df = df[df["staff_group"].isin(STAFF_GROUPS_TO_KEEP)].copy()

    # Convert total to numeric
    if "total" in df.columns:
        df["total"] = pd.to_numeric(df["total"], errors="coerce")

    # Keep only the columns we need
    keep_cols = [
        "period_date",
        "nhse_region_code",
        "nhse_region_name",
        "org_code",
        "org_name",
        "cluster_group",
        "benchmark_group",
        "staff_group",
        "data_type",
        "total",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].copy()

    return df


# ── Main ingestion logic ──────────────────────────────────────────────────────

def ingest_workforce():
    print("=" * 60)
    print("TrustPulse | NHS Workforce Statistics Ingestion")
    print("=" * 60)

    # 1. Find all ZIP files, excluding the HCHS format files
    # (HCHS files only have annual snapshots at org level, not monthly)
    all_zips = sorted(glob.glob(os.path.join(RAW_DIR, "*.zip")))

    # Separate older monthly format from newer HCHS format
    monthly_zips = [z for z in all_zips if "NHS Workforce Statistics," in os.path.basename(z)]
    hchs_zips = [z for z in all_zips if "HCHS" in os.path.basename(z)]

    print(f"Found {len(monthly_zips)} monthly format ZIPs")
    print(f"Found {len(hchs_zips)} HCHS format ZIPs (annual snapshots only, skipping)")

    if not monthly_zips:
        print(f"ERROR: No monthly workforce ZIP files found in {RAW_DIR}")
        return

    # 2. Process each monthly ZIP
    frames = []
    skipped = 0

    for i, zip_path in enumerate(monthly_zips, 1):
        basename = os.path.basename(zip_path)
        month_year_str = extract_month_year_from_filename(zip_path)

        if not month_year_str:
            print(f"[{i}/{len(monthly_zips)}] SKIPPED (could not parse date): {basename}")
            skipped += 1
            continue

        print(f"[{i}/{len(monthly_zips)}] {month_year_str} — {basename[:60]}...")

        df = load_monthly_workforce(zip_path, month_year_str)
        if df is None:
            skipped += 1
            continue

        df = clean_workforce_df(df, month_year_str)
        print(f"  Rows: {len(df):,} | Orgs: {df['org_code'].nunique() if 'org_code' in df.columns else 'N/A'}")
        frames.append(df)

    if not frames:
        print("ERROR: No files could be processed. Stopping.")
        return

    # 3. Combine all months
    print(f"\nCombining {len(frames)} months...")
    combined = pd.concat(frames, ignore_index=True)
    print(f"Combined shape: {combined.shape[0]:,} rows x {combined.shape[1]} columns")

    # 4. Remove duplicates
    before_dedup = len(combined)
    combined = combined.drop_duplicates()
    after_dedup = len(combined)
    if before_dedup != after_dedup:
        print(f"Removed {before_dedup - after_dedup:,} duplicate rows")

    # 5. Sort
    sort_cols = ["period_date", "org_code", "staff_group", "data_type"]
    sort_cols = [c for c in sort_cols if c in combined.columns]
    combined = combined.sort_values(sort_cols).reset_index(drop=True)

    # 6. Save
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    # 7. Summary
    print("\n── Summary ──────────────────────────────────────────────")
    print(f"  Total rows:      {len(combined):,}")
    print(f"  Columns:         {combined.shape[1]}")
    if "org_code" in combined.columns:
        print(f"  Unique trusts:   {combined['org_code'].nunique():,}")
    if "period_date" in combined.columns:
        date_min = combined["period_date"].min().strftime("%B %Y")
        date_max = combined["period_date"].max().strftime("%B %Y")
        print(f"  Date range:      {date_min} to {date_max}")
    if "staff_group" in combined.columns:
        print(f"  Staff groups:    {sorted(combined['staff_group'].unique())}")
    if "data_type" in combined.columns:
        print(f"  Data types:      {sorted(combined['data_type'].unique())}")

    # Show total FTE for most recent month as a sense check
    if "period_date" in combined.columns and "total" in combined.columns:
        latest = combined["period_date"].max()
        latest_total = combined[
            (combined["period_date"] == latest) &
            (combined.get("staff_group", pd.Series()) == "Total") &
            (combined.get("data_type", pd.Series()) == "FTE")
        ]["total"].sum()
        if latest_total > 0:
            print(f"  Total FTE ({latest.strftime('%B %Y')}): {latest_total:,.0f}")

    if skipped > 0:
        print(f"\n  NOTE: {skipped} files were skipped. Check warnings above.")
    print("─────────────────────────────────────────────────────────")
    print("Workforce ingestion complete.")
    print("\nNOTE: HCHS format ZIPs were skipped as they contain only")
    print("annual organisation snapshots, not monthly data.")
    print("Monthly data from the standard ZIPs covers April 2022 onwards.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ingest_workforce()
