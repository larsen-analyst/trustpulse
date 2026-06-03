"""
pipeline/ingest/staff_survey.py
TrustPulse — NHS Staff Survey ingest script

Source : data/raw/staff_survey/NSS-Benchmark-report-excel-data-for-2021-2025-v2.xlsx
Output : data/processed/staff_survey_clean.csv

The NHS Staff Survey is conducted annually. This file covers 2021 to 2025.
Each row is one trust. Columns follow the pattern: PP1_2025, PP2_2024 etc.

This script:
  1. Reads all trust-type sheets (excludes ICBs and social enterprises)
  2. Extracts the key People Promise scores, sub-scores and themes for each year
  3. Melts to long format: one row per trust per year
  4. Saves to data/processed/staff_survey_clean.csv

Key metrics extracted per trust per year:
  PP1  — Compassionate and inclusive (score /10)
  PP2  — Recognised and rewarded
  PP3  — Voice that counts
  PP3_2 — Raising concerns sub-score (regulatory risk signal)
  PP4  — Safe and healthy
  PP4_2 — Burnout sub-score (workforce crisis signal)
  PP4_3 — Negative experiences sub-score
  PP5  — Always learning
  PP6  — Work flexibly
  PP7  — We are a team
  theme_engagement — Staff engagement (summary)
  theme_morale     — Morale (summary)

All scores are out of 10. Higher is better.
Source: NHS Staff Survey, nhsstaffsurveys.com
"""

import pandas as pd
import numpy as np
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_PATH = BASE_DIR / "data" / "raw" / "staff_survey" / \
           "NSS-Benchmark-report-excel-data-for-2021-2025-v2.xlsx"
OUT_PATH = BASE_DIR / "data" / "processed" / "staff_survey_clean.csv"

# Sheets to include — NHS trusts only, not ICBs or social enterprises
TRUST_SHEETS = [
    "Acute&Acute Community Trusts",
    "Acute Specialist Trusts",
    "MH&LD, MH, LD&Community Trusts",
    "Community Trusts",
    "Ambulance Trusts",
]

# Years in the file
YEARS = [2021, 2022, 2023, 2024, 2025]

# Metrics to extract — variable prefix mapped to clean label
METRICS = {
    "PP1":              "pp1_compassionate_inclusive",
    "PP2":              "pp2_recognised_rewarded",
    "PP3":              "pp3_voice_counts",
    "PP3_2":            "pp3_2_raising_concerns",
    "PP4":              "pp4_safe_healthy",
    "PP4_1":            "pp4_1_health_safety_climate",
    "PP4_2":            "pp4_2_burnout",
    "PP4_3":            "pp4_3_negative_experiences",
    "PP5":              "pp5_always_learning",
    "PP6":              "pp6_work_flexibly",
    "PP7":              "pp7_team",
    "theme_engagement": "theme_engagement",
    "theme_morale":     "theme_morale",
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print(f"[staff_survey] Reading: {RAW_PATH}")

    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Source file not found: {RAW_PATH}\n"
            "Download from: nhsstaffsurveys.com/results/local-results"
        )

    all_frames = []

    for sheet in TRUST_SHEETS:
        print(f"[staff_survey] Processing: {sheet}")

        df = pd.read_excel(RAW_PATH, sheet_name=sheet, dtype=str)

        # Keep only identifier cols and the metric cols we want
        id_cols = ["org_id", "org_name", "org_type_reporting_name"]
        id_cols = [c for c in id_cols if c in df.columns]

        # For each metric and year, extract the value
        rows = []
        for _, row in df.iterrows():
            org_id   = str(row.get("org_id", "")).strip()
            org_name = str(row.get("org_name", "")).strip()
            org_type = str(row.get("org_type_reporting_name", "")).strip()

            if not org_id or org_id == "nan":
                continue

            for year in YEARS:
                record = {
                    "org_code":  org_id,
                    "org_name":  org_name,
                    "org_type":  org_type,
                    "year":      year,
                    "survey_date": pd.Timestamp(f"{year}-12-01"),  # Survey published ~Dec
                }

                for metric_prefix, clean_name in METRICS.items():
                    col = f"{metric_prefix}_{year}"
                    if col in df.columns:
                        val = row.get(col, np.nan)
                        try:
                            record[clean_name] = float(val)
                        except (ValueError, TypeError):
                            record[clean_name] = np.nan
                    else:
                        record[clean_name] = np.nan

                rows.append(record)

        sheet_df = pd.DataFrame(rows)
        all_frames.append(sheet_df)
        print(f"  Rows: {len(sheet_df)} | Trusts: {sheet_df['org_code'].nunique()}")

    # Combine all sheets
    result = pd.concat(all_frames, ignore_index=True)

    # Drop rows where all metric columns are null
    metric_cols = list(METRICS.values())
    result = result.dropna(subset=metric_cols, how="all")

    # Sort
    result = result.sort_values(["org_code", "year"]).reset_index(drop=True)

    print(f"\n[staff_survey] Output shape: {result.shape}")
    print(f"[staff_survey] Trusts: {result['org_code'].nunique()}")
    print(f"[staff_survey] Years: {sorted(result['year'].unique().tolist())}")
    print(f"[staff_survey] Org types: {result['org_type'].unique().tolist()}")
    print(f"\n[staff_survey] Sample (2025, first 5 trusts):")
    sample_cols = ["org_code", "org_name", "year",
                   "theme_engagement", "theme_morale",
                   "pp3_2_raising_concerns", "pp4_2_burnout"]
    print(result[result["year"] == 2025][sample_cols].head(5).to_string())

    # National average per year for peer comparison
    print(f"\n[staff_survey] National averages by year:")
    for col in ["theme_engagement", "theme_morale", "pp3_2_raising_concerns", "pp4_2_burnout"]:
        avgs = result.groupby("year")[col].mean().round(2)
        print(f"  {col}: {avgs.to_dict()}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_PATH, index=False)
    print(f"\n[staff_survey] Saved to: {OUT_PATH}")
    print("[staff_survey] Done.")


if __name__ == "__main__":
    run()
