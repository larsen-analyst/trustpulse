"""
TrustPulse -- pipeline/ingest/shmi.py
Ingests the SHMI Historical trust-level data from the latest NHS Digital publication.

Output:
    data/processed/shmi_clean.csv

Columns per trust per time period:
    org_code        : NHS trust code
    org_name        : trust name
    time_period     : e.g. JAN25_DEC25 (12-month rolling window label)
    period_start    : first month of the 12-month window (datetime)
    period_end      : last month of the 12-month window (datetime)
    shmi_value      : SHMI ratio (observed / expected deaths)
    shmi_banding    : 1=Higher than expected, 2=As expected, 3=Lower than expected
    shmi_banding_label : Higher/As expected/Lower than expected
    spells          : total hospital spells in period
    observed_deaths : actual deaths within 30 days
    expected_deaths : statistically expected deaths
    palliative_pct  : % of spells with palliative care coding (contextual)

Source:
    data/raw/shmi/SHMI data, Jan25-Dec25.zip
    File: SHMI data/Historical_trust_level_SHMI_data_Jan25-Dec25_csv.csv

Notes:
    - The historical file in the latest zip contains all periods from Jan 2018 onwards
    - SHMI_BANDING ** = suppressed (small numbers) -- treated as null
    - Only periods from April 2022 onwards retained to match TrustPulse pipeline start
    - 118 acute trusts per period
    - SHMI is NOT a direct measure of quality of care -- it is a smoke alarm signal
      requiring further investigation. All displays must include this disclaimer.
"""

import os
import glob
import zipfile
import io
import re
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "shmi")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "shmi_clean.csv")

# Only keep periods from April 2022 to match pipeline start
PIPELINE_START = pd.Timestamp("2022-04-01")

BANDING_MAP = {
    "1.0": "Higher than expected",
    "1":   "Higher than expected",
    "2.0": "As expected",
    "2":   "As expected",
    "3.0": "Lower than expected",
    "3":   "Lower than expected",
    "**":  None,
}

MONTH_MAP = {
    "JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06",
    "JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"
}


def parse_period(period_str):
    """
    Parse TIME_PERIOD like 'JAN25_DEC25' into start and end dates.
    Returns (period_start, period_end) as Timestamps, or (NaT, NaT) if unparseable.
    """
    try:
        parts = period_str.split("_")
        if len(parts) != 2:
            return pd.NaT, pd.NaT
        start_m = parts[0][:3].upper()
        start_y = "20" + parts[0][3:5]
        end_m   = parts[1][:3].upper()
        end_y   = "20" + parts[1][3:5]
        start = pd.Timestamp(f"{start_y}-{MONTH_MAP[start_m]}-01")
        # End date = last day of end month
        end_month_start = pd.Timestamp(f"{end_y}-{MONTH_MAP[end_m]}-01")
        end = end_month_start + pd.offsets.MonthEnd(0)
        return start, end
    except Exception:
        return pd.NaT, pd.NaT


def find_latest_zip():
    """Find the SHMI zip containing the most recent data (Jan25-Dec25)."""
    zips = glob.glob(os.path.join(RAW_DIR, "*.zip"))
    if not zips:
        return None
    # Prefer the Jan25-Dec25 file which contains full historical data
    for z in zips:
        if "Jan25-Dec25" in z or "Jan25_Dec25" in z:
            return z
    # Fallback: sort by modification time, take latest
    return max(zips, key=os.path.getmtime)


def ingest_shmi():
    print("=" * 60)
    print("TrustPulse | SHMI Ingestion")
    print("=" * 60)

    latest_zip = find_latest_zip()
    if not latest_zip:
        print(f"ERROR: No SHMI zip files found in {RAW_DIR}")
        return

    print(f"Using: {os.path.basename(latest_zip)}")

    # Find the historical trust-level file inside the zip
    with zipfile.ZipFile(latest_zip) as z:
        hist_files = [n for n in z.namelist()
                      if "Historical" in n and "trust" in n.lower() and n.endswith(".csv")]
        if not hist_files:
            print("ERROR: Historical trust-level CSV not found in zip")
            print("Files in zip:", z.namelist()[:10])
            return

        hist_file = hist_files[0]
        print(f"Reading: {hist_file}")

        with z.open(hist_file) as f:
            df = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8"), dtype=str)

    print(f"Raw shape: {df.shape}")
    print(f"Time periods: {df['TIME_PERIOD'].nunique()}")
    print(f"Trusts: {df['PROVIDER_CODE'].nunique()}")

    # Parse period dates
    df[["period_start", "period_end"]] = df["TIME_PERIOD"].apply(
        lambda x: pd.Series(parse_period(x))
    )

    # Filter to pipeline start date
    df = df[df["period_start"] >= PIPELINE_START].copy()
    print(f"After filtering to Apr 2022+: {len(df):,} rows | {df['TIME_PERIOD'].nunique()} periods")

    # Map banding
    df["shmi_banding_label"] = df["SHMI_BANDING"].map(BANDING_MAP)

    # Convert numerics
    for col in ["SHMI_VALUE", "SPELLS", "OBSERVED", "EXPECTED",
                "PALLIATIVE_SPELLS", "PALLIATIVE_DEATHS"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Palliative care percentage
    if "PALLIATIVE_SPELLS" in df.columns and "SPELLS" in df.columns:
        df["palliative_pct"] = (
            df["PALLIATIVE_SPELLS"] / df["SPELLS"].replace(0, float("nan"))
        ).round(4)

    # Build clean output
    keep = {
        "PROVIDER_CODE":   "org_code",
        "PROVIDER_NAME":   "org_name",
        "TIME_PERIOD":     "time_period",
        "period_start":    "period_start",
        "period_end":      "period_end",
        "SHMI_VALUE":      "shmi_value",
        "SHMI_BANDING":    "shmi_banding",
        "shmi_banding_label": "shmi_banding_label",
        "SPELLS":          "spells",
        "OBSERVED":        "observed_deaths",
        "EXPECTED":        "expected_deaths",
    }
    if "palliative_pct" in df.columns:
        keep["palliative_pct"] = "palliative_pct"

    out = df[[c for c in keep.keys() if c in df.columns]].rename(columns=keep)
    out = out.dropna(subset=["org_code", "period_start"])
    out = out.sort_values(["org_code", "period_start"]).reset_index(drop=True)

    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Rows           : {len(out):,}")
    print(f"  Columns        : {out.shape[1]}")
    print(f"  Unique trusts  : {out['org_code'].nunique()}")
    print(f"  Period range   : {out['period_start'].min().strftime('%B %Y')} to {out['period_end'].max().strftime('%B %Y')}")

    latest = out[out["period_start"] == out["period_start"].max()]
    banding = latest["shmi_banding_label"].value_counts()
    print(f"\n  Latest period banding distribution:")
    for b, n in banding.items():
        print(f"    {b}: {n}")

    higher = latest[latest["shmi_banding_label"] == "Higher than expected"].sort_values("shmi_value", ascending=False)
    if not higher.empty:
        print(f"\n  Trusts with Higher than expected SHMI (latest period):")
        print(higher[["org_code", "org_name", "shmi_value", "observed_deaths", "expected_deaths"]].to_string(index=False))

    print("\n  DISCLAIMER: SHMI is not a direct measure of quality of care.")
    print("  A higher than expected SHMI is a smoke alarm requiring further investigation.")
    print("\nSHMI ingestion complete.")


if __name__ == "__main__":
    ingest_shmi()
