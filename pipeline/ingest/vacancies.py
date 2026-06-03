"""
pipeline/ingest/vacancies.py
TrustPulse — NHS Vacancy Statistics ingest script

Source : data/raw/vacancies/nhs-vac-stats-apr15-mar26-eng-tables.xlsx
Output : data/processed/vacancies_clean.csv

NOTE: This data is regional and sector level only — not trust level.
NHS England does not publish trust-level vacancy rates publicly.
This file is used as a regional benchmark layer: each trust is assigned
the vacancy rate for its region and sector, providing contextual comparison.

Sheets used:
  - Total 2018 onwards    — all staff groups combined
  - Nursing 2018 onwards  — nursing and midwifery
  - Medical 2018 onwards  — medical and dental

Output is long format: one row per region, sector, staff group, quarter.
Columns: region, sector, staff_group, quarter_label, quarter_date,
         vacancy_fte, vacancy_rate_pct (where available)
"""

import pandas as pd
import numpy as np
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_PATH = BASE_DIR / "data" / "raw" / "vacancies" / "nhs-vac-stats-apr15-mar26-eng-tables.xlsx"
OUT_PATH = BASE_DIR / "data" / "processed" / "vacancies_clean.csv"

HEADER_ROW = 20  # Confirmed by inspection

# Sheets and their staff group labels
SHEETS = {
    "Total 2018 onwards":   "All staff",
    "Nursing 2018 onwards": "Nursing and midwifery",
    "Medical 2018 onwards": "Medical and dental",
}

# Rows to exclude — summary/total rows and rate rows
EXCLUDE_REGION_PATTERNS = [
    "total", "grand total", "% vacancy rate", "region"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_quarter_date(label):
    """
    Convert quarter label like '2025/26 Q4 (Mar-26)' to a date.
    Returns the last month of the quarter as a timestamp.
    """
    match = re.search(r'\((\w{3}-\d{2})\)', str(label))
    if match:
        try:
            return pd.to_datetime(match.group(1), format="%b-%y")
        except Exception:
            pass
    return pd.NaT


def is_exclude_row(region_val):
    """Return True if this row is a summary/total/rate row to exclude."""
    if pd.isna(region_val):
        return True
    val = str(region_val).lower().strip()
    return any(pat in val for pat in EXCLUDE_REGION_PATTERNS)


def clean_region(val):
    """Normalise region name."""
    return str(val).strip()


def forward_fill_region(df):
    """
    Region column only appears on the first row of each group.
    Forward fill to populate subsequent sector rows.
    """
    df["Region"] = df["Region"].replace("", np.nan)
    df["Region"] = df["Region"].ffill()
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print(f"[vacancies] Reading: {RAW_PATH}")

    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Source file not found: {RAW_PATH}\n"
            "Download from: digital.nhs.uk/data-and-information/publications/statistical/nhs-vacancies-survey"
        )

    all_frames = []

    for sheet_name, staff_group in SHEETS.items():
        print(f"[vacancies] Processing sheet: {sheet_name}")

        df = pd.read_excel(
            RAW_PATH,
            sheet_name=sheet_name,
            header=HEADER_ROW,
            dtype=str,
        )

        # Drop fully empty rows and columns
        df = df.dropna(how="all")
        df = df.loc[:, df.columns.notna()]

        # Forward fill region column
        df = forward_fill_region(df)

        # Get date columns (everything except Region and Sector)
        date_cols = [c for c in df.columns if c not in ["Region", "Sector"]]

        # Filter out summary/total/rate rows
        df = df[~df["Region"].apply(is_exclude_row)].copy()
        df = df[~df["Sector"].apply(
            lambda x: any(pat in str(x).lower() for pat in ["total", "sector", "nan"])
        )].copy()

        # Melt to long format
        df_long = df.melt(
            id_vars=["Region", "Sector"],
            value_vars=date_cols,
            var_name="quarter_label",
            value_name="vacancy_fte_raw",
        )

        # Parse quarter date
        df_long["quarter_date"] = df_long["quarter_label"].apply(parse_quarter_date)

        # Clean vacancy value
        df_long["value_raw"] = pd.to_numeric(
            df_long["vacancy_fte_raw"].str.replace(",", "").str.strip().replace("-", np.nan),
            errors="coerce"
        )

        # Detect data type: values < 1 are rates (e.g. 0.055 = 5.5%)
        # Values >= 1 are FTE counts
        df_long["data_type"] = np.where(
            df_long["value_raw"] < 1, "vacancy_rate_pct", "vacancy_fte"
        )
        # Convert rate to percentage (0.055 -> 5.5)
        df_long["value"] = np.where(
            df_long["data_type"] == "vacancy_rate_pct",
            df_long["value_raw"] * 100,
            df_long["value_raw"]
        )

        # Add staff group
        df_long["staff_group"] = staff_group

        # Clean up
        df_long["region"] = df_long["Region"].str.strip()
        df_long["sector"] = df_long["Sector"].str.strip()

        keep_cols = ["region", "sector", "staff_group", "data_type",
                     "quarter_label", "quarter_date", "value"]
        all_frames.append(df_long[keep_cols])

        print(f"  Rows: {len(df_long)}")

    # Combine all staff groups
    result = pd.concat(all_frames, ignore_index=True)
    result = result.dropna(subset=["quarter_date"])
    result = result.sort_values(["region", "sector", "staff_group", "data_type", "quarter_date"])
    result = result.reset_index(drop=True)

    # Add a computed vacancy rate using Grand Total FTE as denominator proxy
    # We cannot compute exact rates without total establishment figures
    # but we preserve the raw FTE counts for benchmarking

    print(f"\n[vacancies] Output shape: {result.shape}")
    print(f"[vacancies] Regions: {result['region'].nunique()}")
    print(f"[vacancies] Sectors: {sorted(result['sector'].unique().tolist())}")
    print(f"[vacancies] Staff groups: {sorted(result['staff_group'].unique().tolist())}")
    print(f"[vacancies] Date range: {result['quarter_date'].min().date()} to {result['quarter_date'].max().date()}")
    print(f"\n[vacancies] Sample:")
    print(result.head(6).to_string())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_PATH, index=False)
    print(f"\n[vacancies] Saved to: {OUT_PATH}")
    print("[vacancies] Done.")


if __name__ == "__main__":
    run()
