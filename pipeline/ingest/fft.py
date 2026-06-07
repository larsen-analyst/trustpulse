"""
TrustPulse -- pipeline/ingest/fft.py
Ingests NHS Friends and Family Test inpatient data from xlsm files.

Output:
    data/processed/fft_clean.csv

Metrics per trust per month:
    fft_total_responses     : total FFT responses submitted
    fft_pct_positive        : % recommending the service (target > 95%)
    fft_pct_negative        : % not recommending the service

Source:
    data/raw/fft/
    Monthly inpatient xlsm files, April 2022 to March 2026.

Notes:
    - Filenames are inconsistent -- period date extracted from file title cell
    - Trusts sheet, header at row 9
    - Key columns: Trust Code, Total Responses, Percentage Positive, Percentage Negative
    - National average positive recommendation rate approximately 95-96%
    - Low positive rate (<90%) is a significant patient experience signal
"""

import os
import re
import glob
import pandas as pd
import numpy as np

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "fft")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "fft_clean.csv")

MONTHS = {
    "january":"01","february":"02","march":"03","april":"04",
    "may":"05","june":"06","july":"07","august":"08",
    "september":"09","october":"10","november":"11","december":"12",
    "jan":"01","feb":"02","mar":"03","apr":"04",
    "jun":"06","jul":"07","aug":"08","sept":"09","sep":"09",
    "oct":"10","nov":"11","dec":"12"
}


def extract_period_from_title(filepath):
    """
    Read the title cell from the file to extract the period date.
    Falls back to parsing the filename.
    """
    try:
        df = pd.read_excel(filepath, sheet_name="Trusts", header=None,
                           nrows=5, engine="openpyxl")
        # Title is usually in row 0
        for i in range(5):
            cell = str(df.iloc[i, 0]) if not pd.isna(df.iloc[i, 0]) else ""
            if any(m in cell.lower() for m in MONTHS.keys()) and any(
                str(y) in cell for y in range(2020, 2027)
            ):
                # Try to parse month and year from title
                for month_name, month_num in sorted(MONTHS.items(), key=lambda x: -len(x[0])):
                    pattern = rf"{month_name}\s+(\d{{4}})"
                    m = re.search(pattern, cell.lower())
                    if m:
                        year = m.group(1)
                        return pd.Timestamp(f"{year}-{month_num}-01")
    except Exception:
        pass

    # Fallback: parse filename
    basename = os.path.basename(filepath).lower()
    # Try full month name + year
    for month_name, month_num in sorted(MONTHS.items(), key=lambda x: -len(x[0])):
        pattern = rf"{month_name}[\s\-_]*(\d{{2,4}})"
        m = re.search(pattern, basename)
        if m:
            yr = m.group(1)
            if len(yr) == 2:
                yr = "20" + yr
            return pd.Timestamp(f"{yr}-{month_num}-01")
    return None


def process_file(filepath):
    """Process one FFT inpatient xlsm file."""
    period_date = extract_period_from_title(filepath)
    if not period_date:
        print(f"  WARNING: Could not parse period from {os.path.basename(filepath)}")
        return pd.DataFrame()

    try:
        df = pd.read_excel(filepath, sheet_name="Trusts", header=None, engine="openpyxl")
    except Exception as e:
        print(f"  ERROR reading {os.path.basename(filepath)}: {e}")
        return pd.DataFrame()

    # Find header row
    header_row = None
    for i in range(5, 20):
        row_vals = [str(v) for v in df.iloc[i].tolist()]
        if any("Trust Code" in v or "Organisation Code" in v for v in row_vals):
            header_row = i
            break

    if header_row is None:
        print(f"  WARNING: No header row found in {os.path.basename(filepath)}")
        return pd.DataFrame()

    df2 = pd.read_excel(filepath, sheet_name="Trusts", header=header_row, engine="openpyxl")
    df2.columns = [str(c).strip() for c in df2.columns]

    # Find columns
    def find_col(candidates):
        for c in candidates:
            if c in df2.columns:
                return c
        # Partial match
        for c in df2.columns:
            for cand in candidates:
                if cand.lower() in c.lower():
                    return c
        return None

    col_code  = find_col(["Trust Code", "Organisation Code", "Org Code"])
    col_name  = find_col(["Trust Name", "Organisation Name", "Org Name"])
    col_total = find_col(["Total Responses", "Total responses"])
    col_pos   = find_col(["Percentage Positive", "% Positive", "Pct Positive"])
    col_neg   = find_col(["Percentage Negative", "% Negative", "Pct Negative"])

    if not col_code:
        print(f"  WARNING: No trust code column in {os.path.basename(filepath)}")
        return pd.DataFrame()

    df2 = df2[df2[col_code].notna()].copy()
    df2 = df2[~df2[col_code].astype(str).str.contains("Total|England|Region|nan",
                                                        case=False, na=True)].copy()
    df2 = df2[df2[col_code].astype(str).str.len() <= 5].copy()

    out = pd.DataFrame()
    out["org_code"] = df2[col_code].astype(str).str.strip()
    if col_name:
        out["org_name"] = df2[col_name].astype(str).str.strip()
    out["period_date"] = period_date

    for src, dst in [
        (col_total, "fft_total_responses"),
        (col_pos,   "fft_pct_positive"),
        (col_neg,   "fft_pct_negative"),
    ]:
        if src:
            out[dst] = pd.to_numeric(df2[src].values, errors="coerce")

    # Normalise percentage -- some files use 0-100, others 0-1
    for col in ["fft_pct_positive", "fft_pct_negative"]:
        if col in out.columns:
            # If max > 1, it's already 0-100 scale, convert to 0-1
            if out[col].dropna().max() > 1.5:
                out[col] = out[col] / 100

    return out.dropna(subset=["org_code"])


def ingest_fft():
    print("=" * 60)
    print("TrustPulse | FFT Inpatient Ingestion")
    print("=" * 60)

    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.xlsm")))
    print(f"Found {len(files)} xlsm files")

    frames = []
    failed = []
    for i, filepath in enumerate(files, 1):
        basename = os.path.basename(filepath)
        df = process_file(filepath)
        if df.empty:
            failed.append(basename)
            continue
        print(f"[{i}/{len(files)}] {basename[:60]:<60} {df['period_date'].iloc[0].strftime('%b %Y')} | {df['org_code'].nunique()} trusts")
        frames.append(df)

    if not frames:
        print("ERROR: No data extracted.")
        return

    combined = pd.concat(frames, ignore_index=True)
    # Deduplicate -- keep first occurrence per org per month
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

    if failed:
        print(f"\n  Failed files ({len(failed)}):")
        for f in failed:
            print(f"    {f}")

    if "fft_pct_positive" in combined.columns:
        latest = combined[combined["period_date"] == combined["period_date"].max()]
        nhs = latest[latest["org_code"].str.match(r'^[RG]', na=False)]
        print(f"\n  Latest month NHS trusts: {len(nhs)}")
        print(f"  National avg positive %: {nhs['fft_pct_positive'].mean():.1%}")
        print(f"\n  Lowest positive % (bottom 10):")
        worst = nhs.nsmallest(10, "fft_pct_positive")
        print(worst[["org_code", "org_name", "fft_pct_positive",
                      "fft_total_responses"]].to_string(index=False))

    print("\nFFT inpatient ingestion complete.")


if __name__ == "__main__":
    ingest_fft()
