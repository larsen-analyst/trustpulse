"""
TrustPulse -- pipeline/ingest/diagnostics.py
Ingests NHS Monthly Diagnostics Waiting Times Provider XLS files.

Output:
    data/processed/diagnostics_clean.csv

Metrics per trust per month:
    total_waiting       : total patients on diagnostic waiting list
    waiting_6wk_plus    : patients waiting more than 6 weeks
    waiting_13wk_plus   : patients waiting more than 13 weeks
    pct_waiting_6wk     : % waiting 6+ weeks (should be < 1% -- NHS standard 99% within 6 weeks)
    activity_total      : total diagnostic activity during month

Source:
    data/raw/diagnostics/
    Monthly Diagnostics -- Provider XLS files, April 2024 to March 2026.

Notes:
    - Header row is at row index 13 (0-based)
    - Provider Code is the NHS org code
    - Skip rows 14 and 15 which are national/regional totals
    - Filter to NHS trust org codes matching oversight file
    - CDC files excluded (different format)
    - NHS standard: 99% of patients seen within 6 weeks
"""

import os
import re
import glob
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "diagnostics")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "diagnostics_clean.csv")

MONTHS = {
    "January":"01","February":"02","March":"03","April":"04",
    "May":"05","June":"06","July":"07","August":"08",
    "September":"09","October":"10","November":"11","December":"12"
}

EXCLUDE_PROVIDERS = {"Total", "England", "nan", ""}


def parse_period_from_filename(filename):
    """Extract period date from filename like Monthly-Diagnostics-Web-File-Provider-March-2026_xxx.xls"""
    basename = os.path.basename(filename)
    for month, num in MONTHS.items():
        pattern = rf"{month}-(\d{{4}})"
        m = re.search(pattern, basename)
        if m:
            year = m.group(1)
            return pd.Timestamp(f"{year}-{num}-01")
    return None


def process_file(filepath):
    """Process one diagnostics provider XLS file."""
    # Skip CDC files
    if "CDC" in os.path.basename(filepath) or "Timeseries" in os.path.basename(filepath):
        return pd.DataFrame()

    period_date = parse_period_from_filename(filepath)
    if not period_date:
        print(f"  WARNING: Could not parse period from {os.path.basename(filepath)}")
        return pd.DataFrame()

    try:
        df = pd.read_excel(filepath, sheet_name="Provider", header=None,
                           engine="xlrd")
    except Exception as e:
        print(f"  ERROR reading {os.path.basename(filepath)}: {e}")
        return pd.DataFrame()

    # Find header row -- look for row containing "Provider Code"
    header_row = None
    for i in range(5, 20):
        row_vals = [str(v) for v in df.iloc[i].tolist()]
        if any("Provider Code" in v for v in row_vals):
            header_row = i
            break

    if header_row is None:
        print(f"  WARNING: Could not find header row in {os.path.basename(filepath)}")
        return pd.DataFrame()

    # Read with proper header
    df2 = pd.read_excel(filepath, sheet_name="Provider", header=header_row,
                        engine="xlrd")

    # Standardise column names
    df2.columns = [str(c).strip() for c in df2.columns]

    # Find key columns
    def find_col(candidates):
        for c in candidates:
            if c in df2.columns:
                return c
        return None

    col_code  = find_col(["Provider Code", "Provider\nCode"])
    col_name  = find_col(["Provider Name", "Provider\nName"])
    col_total = find_col(["Total Waiting List", "Total\nWaiting List"])
    col_6wk   = find_col(["Number waiting 6+ Weeks", "Number\nwaiting 6+\nWeeks"])
    col_13wk  = find_col(["Number waiting 13+ Weeks", "Number\nwaiting 13+\nWeeks"])
    col_pct6  = find_col(["Percentage waiting 6+ weeks", "Percentage\nwaiting 6+\nweeks"])
    col_act   = find_col(["Activity during month", "Total Activity"])

    if not col_code:
        print(f"  WARNING: No Provider Code column found in {os.path.basename(filepath)}")
        print(f"  Columns: {list(df2.columns[:10])}")
        return pd.DataFrame()

    # Filter out national totals and empty rows
    df2 = df2[df2[col_code].notna()].copy()
    df2 = df2[~df2[col_code].astype(str).isin(EXCLUDE_PROVIDERS)].copy()
    df2 = df2[~df2[col_code].astype(str).str.contains("Total|Region|England", case=False, na=True)].copy()

    # Build output
    out = pd.DataFrame()
    out["org_code"] = df2[col_code].astype(str).str.strip()
    if col_name:
        out["org_name"] = df2[col_name].astype(str).str.strip()
    out["period_date"] = period_date

    for src_col, dst_col in [
        (col_total, "total_waiting"),
        (col_6wk,   "waiting_6wk_plus"),
        (col_13wk,  "waiting_13wk_plus"),
        (col_pct6,  "pct_waiting_6wk"),
        (col_act,   "activity_total"),
    ]:
        if src_col:
            out[dst_col] = pd.to_numeric(df2[src_col].values, errors="coerce")

    out = out.dropna(subset=["org_code"])
    out = out[out["org_code"].str.len() > 0]

    return out


def ingest_diagnostics():
    print("=" * 60)
    print("TrustPulse | Diagnostics Waiting Times Ingestion")
    print("=" * 60)

    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.xls")))
    print(f"Found {len(files)} XLS files")

    frames = []
    for i, filepath in enumerate(files, 1):
        basename = os.path.basename(filepath)
        if "CDC" in basename or "Timeseries" in basename:
            print(f"[{i}/{len(files)}] SKIP: {basename[:60]}")
            continue
        print(f"[{i}/{len(files)}] {basename[:70]}...")
        df = process_file(filepath)
        if df.empty:
            print(f"  WARNING: No data extracted")
            continue
        print(f"  Rows: {len(df):,} | Orgs: {df['org_code'].nunique()} | {df['period_date'].iloc[0].strftime('%b %Y')}")
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
    print(f"  Unique orgs   : {combined['org_code'].nunique()}")
    print(f"  Date range    : {combined['period_date'].min().strftime('%B %Y')} to "
          f"{combined['period_date'].max().strftime('%B %Y')}")

    if "pct_waiting_6wk" in combined.columns:
        latest = combined[combined["period_date"] == combined["period_date"].max()]
        # Filter to NHS trusts (org codes starting with R or similar)
        nhs = latest[latest["org_code"].str.match(r'^[RG][A-Z0-9]', na=False)]
        print(f"\n  NHS trusts in latest month: {len(nhs)}")
        print(f"  National avg 6+ week wait %: {nhs['pct_waiting_6wk'].mean():.1%}")
        print(f"\n  Worst 10 by 6+ week wait %:")
        worst = nhs.nlargest(10, "pct_waiting_6wk")
        print(worst[["org_code", "org_name", "pct_waiting_6wk", "total_waiting"]].to_string(index=False))

    print("\nDiagnostics ingestion complete.")


if __name__ == "__main__":
    ingest_diagnostics()
