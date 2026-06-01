"""
TrustPulse — pipeline/ingest/sickness.py
Ingests raw NHS sickness absence CSV files (trust-level only),
cleans them, and saves sickness_trust_clean.csv to data/processed/

Usage:
    python pipeline\ingest\sickness.py

Output:
    data/processed/sickness_trust_clean.csv

Source data:
    data/raw/sickness/trust/  (25 CSV files, January 2024 to January 2026)

Notes on raw data format (documented in src/ingest.ipynb):
    - Each file contains 24 reason rows per trust per month
    - All 24 rows repeat the same FTE_DAYS_LOST and FTE_DAYS_AVAILABLE values
    - Fix: take the first row per trust per month using .groupby().first()
    - Files from this folder have ORG_CODE (trust-level breakdown)
    - National-level files (data/raw/sickness/national/) are NOT loaded here
      because they have no ORG_CODE and cannot be linked to individual trusts
"""

import os
import glob
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "sickness", "trust")
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED_DIR, "sickness_trust_clean.csv")


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_single_file(filepath):
    """
    Load one raw sickness CSV file and return a DataFrame.
    Returns None if the file cannot be read.
    """
    try:
        df = pd.read_csv(filepath, dtype=str)
        return df
    except Exception as e:
        print(f"  WARNING: Could not read {os.path.basename(filepath)}: {e}")
        return None


def parse_date(date_str):
    """
    Parse the date column from sickness files.
    NHS sickness files typically use a DATE column in format like '2024-01-01'
    or a YEAR/MONTH combination. Returns NaT if unparseable.
    We try multiple formats to be safe.
    """
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%B %Y", "%b %Y"]:
        try:
            return pd.to_datetime(date_str, format=fmt)
        except Exception:
            continue
    # Last resort: let pandas infer
    try:
        return pd.to_datetime(date_str, infer_datetime_format=True)
    except Exception:
        return pd.NaT


# ── Main ingestion logic ──────────────────────────────────────────────────────

def ingest_sickness():
    print("=" * 60)
    print("TrustPulse | Sickness Absence Ingestion (Trust-Level)")
    print("=" * 60)

    # 1. Find all CSV files in the trust-level sickness folder
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
    raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]

    print("Columns found:")
    print(list(raw.columns))

    # 4. Confirm ORG_CODE is present
    # This is the key column that distinguishes trust-level from national files.
    if "org_code" not in raw.columns:
        print("ERROR: 'org_code' column not found.")
        print("This may mean national-level files have been mixed in.")
        print("Check the contents of data/raw/sickness/trust/ and try again.")
        return

    # 5. Identify the date column
    # NHS sickness files may use DATE, YEAR, or a combination of YEAR + MONTH.
    # We check for common patterns.
    date_col = None
    for candidate in ["date", "absence_date", "month_date", "data_source_date"]:
        if candidate in raw.columns:
            date_col = candidate
            break

    # If no single date column, check for YEAR + MONTH combination
    has_year_month = "year" in raw.columns and "month" in raw.columns

    if date_col is None and not has_year_month:
        print("WARNING: No date column identified.")
        print("Columns present:", list(raw.columns))
        print("Script will continue but period_date will not be set.")
        print("Please check column names and update the script if needed.")

    # 6. Parse the date into a proper datetime column
    if date_col:
        print(f"Parsing date from column: '{date_col}'")
        raw["period_date"] = raw[date_col].apply(parse_date)
        unparsed = raw["period_date"].isna().sum()
        if unparsed > 0:
            print(f"  WARNING: {unparsed:,} rows had dates that could not be parsed.")
            print("  Sample unparsed values:")
            print(raw.loc[raw["period_date"].isna(), date_col].unique()[:10])
            raw = raw[raw["period_date"].notna()].copy()
            print(f"  Rows after dropping unparsed: {len(raw):,}")

    elif has_year_month:
        print("Parsing date from YEAR + MONTH columns...")
        try:
            raw["period_date"] = pd.to_datetime(
                raw["year"].astype(str) + "-" + raw["month"].astype(str) + "-01",
                format="%Y-%m-%d"
            )
        except Exception as e:
            print(f"  WARNING: Could not parse YEAR + MONTH: {e}")

    # 7. KEY STEP: De-duplicate reason rows
    # Each trust+month combination appears 24 times (once per absence reason)
    # but FTE_DAYS_LOST and FTE_DAYS_AVAILABLE are identical on every row.
    # We keep only the first row per trust per month.
    print("De-duplicating reason rows (keeping first row per trust per month)...")
    before = len(raw)

    group_cols = ["org_code"]
    if "period_date" in raw.columns:
        group_cols.append("period_date")
    elif date_col:
        group_cols.append(date_col)

    raw = raw.groupby(group_cols, as_index=False).first()
    after = len(raw)
    print(f"  Rows before: {before:,}")
    print(f"  Rows after:  {after:,}")
    print(f"  Removed:     {before - after:,} duplicate reason rows")

    # 8. Calculate sickness rate if not already present
    # Sickness rate = FTE_DAYS_LOST / FTE_DAYS_AVAILABLE * 100
    fte_lost_col = None
    fte_avail_col = None
    for candidate in ["fte_days_lost", "fte_days_lost_due_to_sickness"]:
        if candidate in raw.columns:
            fte_lost_col = candidate
            break
    for candidate in ["fte_days_available", "total_fte_days_available"]:
        if candidate in raw.columns:
            fte_avail_col = candidate
            break

    if fte_lost_col and fte_avail_col:
        raw[fte_lost_col] = pd.to_numeric(raw[fte_lost_col], errors="coerce")
        raw[fte_avail_col] = pd.to_numeric(raw[fte_avail_col], errors="coerce")

        if "sickness_absence_rate_percent" not in raw.columns:
            print(f"Calculating sickness rate from {fte_lost_col} / {fte_avail_col}")
            raw["sickness_absence_rate_percent"] = (
                raw[fte_lost_col] / raw[fte_avail_col] * 100
            ).round(4)
        else:
            # Convert existing rate column to numeric
            raw["sickness_absence_rate_percent"] = pd.to_numeric(
                raw["sickness_absence_rate_percent"], errors="coerce"
            )

    # 9. Drop duplicate rows
    before_dedup = len(raw)
    raw = raw.drop_duplicates()
    after_dedup = len(raw)
    if before_dedup != after_dedup:
        print(f"Removed {before_dedup - after_dedup:,} fully duplicate rows")

    # 10. Sort by date and org
    sort_cols = ["org_code"]
    if "period_date" in raw.columns:
        sort_cols = ["period_date", "org_code"]
    raw = raw.sort_values(sort_cols).reset_index(drop=True)

    # 11. Ensure processed directory exists
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    # 12. Save output
    raw.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    # 13. Summary
    print("\n── Summary ──────────────────────────────────────────────")
    print(f"  Total rows:    {len(raw):,}")
    print(f"  Columns:       {raw.shape[1]}")
    print(f"  Unique trusts: {raw['org_code'].nunique():,}")
    if "period_date" in raw.columns:
        date_min = raw["period_date"].min().strftime("%B %Y")
        date_max = raw["period_date"].max().strftime("%B %Y")
        print(f"  Date range:    {date_min} to {date_max}")
    if "sickness_absence_rate_percent" in raw.columns:
        mean_rate = raw["sickness_absence_rate_percent"].mean()
        print(f"  Mean sickness rate: {mean_rate:.2f}%")
    print("─────────────────────────────────────────────────────────")
    print("Sickness ingestion complete.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ingest_sickness()
