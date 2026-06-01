"""
TrustPulse — pipeline/ingest/ae.py
Ingests raw NHS A&E CSV files, cleans them, and saves ae_clean.csv to data/processed/

Usage:
    python pipeline/ingest/ae.py

Output:
    data/processed/ae_clean.csv

Source data:
    data/raw/ae/  (48 CSV files, April 2022 to March 2026)

Notes on raw data format (documented in src/ingest.ipynb):
    - Period column contains values like "MSitAE-APRIL-2022"
    - Some files contain "Total" and "TOTAL" rows which must be excluded
    - Strip "MSitAE-" prefix before parsing the date
"""

import os
import glob
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────────

# This script is run from the project root: D:\Projects\TrustPulse\
# Adjust BASE_DIR if you run it from a different location.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "ae")
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED_DIR, "ae_clean.csv")


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_period(period_str):
    """
    Convert a raw Period value like 'MSitAE-APRIL-2022' into a pandas Timestamp.
    Returns NaT if the value cannot be parsed.
    """
    try:
        # Remove the 'MSitAE-' prefix
        stripped = str(period_str).replace("MSitAE-", "").strip()
        return pd.to_datetime(stripped, format="%B-%Y")
    except Exception:
        return pd.NaT


def load_single_file(filepath):
    """
    Load one raw A&E CSV file and return a DataFrame.
    Returns None if the file cannot be read.
    """
    try:
        df = pd.read_csv(filepath, dtype=str)
        return df
    except Exception as e:
        print(f"  WARNING: Could not read {os.path.basename(filepath)}: {e}")
        return None


# ── Main ingestion logic ──────────────────────────────────────────────────────

def ingest_ae():
    print("=" * 60)
    print("TrustPulse | A&E Ingestion")
    print("=" * 60)

    # 1. Find all CSV files in the raw A&E folder
    pattern = os.path.join(RAW_DIR, "*.csv")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"ERROR: No CSV files found in {RAW_DIR}")
        print("Check that RAW_DIR is correct and files are present.")
        return

    print(f"Found {len(files)} CSV files in {RAW_DIR}")

    # 2. Load and concatenate all files
    frames = []
    for filepath in files:
        df = load_single_file(filepath)
        if df is not None:
            frames.append(df)

    if not frames:
        print("ERROR: No files could be loaded. Stopping.")
        return

    raw = pd.concat(frames, ignore_index=True)
    print(f"Raw combined shape: {raw.shape[0]:,} rows x {raw.shape[1]} columns")

    # 3. Standardise column names
    # Strip whitespace and convert to lowercase with underscores
    raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]

    # 4. Identify the period and org columns
    # The handover document confirms the Period column exists as-is.
    # We check for it explicitly and fail clearly if it is missing.
    if "period" not in raw.columns:
        print("ERROR: 'period' column not found. Columns present:")
        print(list(raw.columns))
        print("Check column names in the raw files and update this script.")
        return

    # 5. Remove Total/TOTAL rows (aggregate rows, not trust-level)
    # These appear in some files and must be excluded before any analysis.
    org_col = None
    for candidate in ["org_code", "code", "org", "trust_code"]:
        if candidate in raw.columns:
            org_col = candidate
            break

    # Also check the period column itself for Total rows
    total_mask = raw["period"].str.upper().str.contains("TOTAL", na=False)
    if total_mask.sum() > 0:
        print(f"Removing {total_mask.sum():,} 'Total' rows from period column")
        raw = raw[~total_mask].copy()

    if org_col:
        org_total_mask = raw[org_col].str.upper().str.contains("TOTAL", na=False)
        if org_total_mask.sum() > 0:
            print(f"Removing {org_total_mask.sum():,} 'Total' rows from {org_col} column")
            raw = raw[~org_total_mask].copy()

    # 6. Parse the Period column into a proper datetime
    print("Parsing Period column...")
    raw["period_date"] = raw["period"].apply(parse_period)

    unparsed = raw["period_date"].isna().sum()
    if unparsed > 0:
        print(f"  WARNING: {unparsed:,} rows had Period values that could not be parsed.")
        print("  Sample unparsed values:")
        print(raw.loc[raw["period_date"].isna(), "period"].unique()[:10])
        raw = raw[raw["period_date"].notna()].copy()
        print(f"  Rows after dropping unparsed: {len(raw):,}")

    # 7. Drop duplicate rows
    before_dedup = len(raw)
    raw = raw.drop_duplicates()
    after_dedup = len(raw)
    if before_dedup != after_dedup:
        print(f"Removed {before_dedup - after_dedup:,} duplicate rows")

    # 8. Sort by date and org
    sort_cols = ["period_date"]
    if org_col:
        sort_cols.append(org_col)
    raw = raw.sort_values(sort_cols).reset_index(drop=True)

    # 9. Ensure processed directory exists
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    # 10. Save output
    raw.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    # 11. Summary
    print("\n── Summary ──────────────────────────────────────────────")
    print(f"  Total rows:    {len(raw):,}")
    print(f"  Columns:       {raw.shape[1]}")
    if org_col:
        print(f"  Unique trusts: {raw[org_col].nunique():,}")
    date_min = raw["period_date"].min().strftime("%B %Y")
    date_max = raw["period_date"].max().strftime("%B %Y")
    print(f"  Date range:    {date_min} to {date_max}")
    print("─────────────────────────────────────────────────────────")
    print("A&E ingestion complete.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ingest_ae()
