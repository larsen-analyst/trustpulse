"""
TrustPulse -- pipeline/ingest/sport_england.py
Ingests Sport England Active Lives Adult Survey -- Table 3 Local Authority level data.

Output:
    data/processed/sport_england_clean.csv

Metrics per local authority:
    - inactivity_rate   : % adults doing < 30 mins activity per week (Nov 2024-25)
    - activity_rate     : % adults doing 150+ mins per week (Nov 2024-25)
    - fairly_active_rate: % adults doing 30-149 mins per week (Nov 2024-25)

Source:
    Sport England Active Lives Adult Survey, November 2024-25
    Table 3: Levels by Local Authority

Notes:
    - Data is at local authority level, not trust level
    - Joined to TrustPulse via local authority to ICS/region mapping
    - Inactivity rate is the primary signal for preventable NHS demand
"""

import os
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "prevention", "sport_england")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "sport_england_clean.csv")

SOURCE_FILE = os.path.join(
    RAW_DIR,
    "Active Lives Adult Survey report Nov 24-25 Tables 1-5 Levels of activity.xlsx"
)

# Column positions in Table 3 (0-indexed, header=None)
# Three time periods: 2015-16 (cols 5-16), 2023-24 (cols 19-30), 2024-25 (cols 33-44)
# For each period: Active pop, Active rate, CI lower, CI upper,
#                  Fairly active pop, FA rate, CI lower, CI upper,
#                  Inactive pop, Inactive rate, CI lower, CI upper
COL_ONS_CODE       = 0
COL_LA_NAME        = 1
COL_ACTIVE_RATE    = 35   # 2024-25 active rate (%)
COL_FA_RATE        = 39   # 2024-25 fairly active rate (%)
COL_INACTIVE_RATE  = 43   # 2024-25 inactive rate (%)

# Previous year for trend
COL_ACTIVE_RATE_PREV   = 21  # 2023-24 active rate
COL_INACTIVE_RATE_PREV = 29  # 2023-24 inactive rate


def ingest_sport_england():
    print("=" * 60)
    print("TrustPulse | Sport England Active Lives Ingestion")
    print("=" * 60)

    if not os.path.exists(SOURCE_FILE):
        print(f"ERROR: Source file not found: {SOURCE_FILE}")
        print("Expected: Active Lives Adult Survey report Nov 24-25 Tables 1-5 Levels of activity.xlsx")
        return

    print(f"Loading: {os.path.basename(SOURCE_FILE)}")

    df = pd.read_excel(SOURCE_FILE, sheet_name="Table 3 Levels Local Authority", header=None)
    print(f"Raw shape: {df.shape}")

    # Data rows start at row 10 (0-indexed)
    # Filter to rows where column 0 looks like an ONS code (starts with E)
    data = df.iloc[9:].copy()
    data = data[data[COL_ONS_CODE].astype(str).str.match(r'^E\d+', na=False)].copy()

    print(f"LA rows found: {len(data)}")

    out = pd.DataFrame()
    out["ons_code"]              = data[COL_ONS_CODE].values
    out["la_name"]               = data[COL_LA_NAME].values
    out["activity_rate_2425"]    = pd.to_numeric(data[COL_ACTIVE_RATE].values,   errors="coerce")
    out["fairly_active_rate_2425"] = pd.to_numeric(data[COL_FA_RATE].values,     errors="coerce")
    out["inactivity_rate_2425"]  = pd.to_numeric(data[COL_INACTIVE_RATE].values, errors="coerce")
    out["activity_rate_2324"]    = pd.to_numeric(data[COL_ACTIVE_RATE_PREV].values,   errors="coerce")
    out["inactivity_rate_2324"]  = pd.to_numeric(data[COL_INACTIVE_RATE_PREV].values, errors="coerce")

    # YOY change in inactivity
    out["inactivity_change_yoy"] = (
        out["inactivity_rate_2425"] - out["inactivity_rate_2324"]
    ).round(4)

    out = out.dropna(subset=["ons_code", "inactivity_rate_2425"])
    out = out.sort_values("inactivity_rate_2425", ascending=False).reset_index(drop=True)

    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Local authorities : {len(out)}")
    print(f"  Inactivity rate   : mean {out['inactivity_rate_2425'].mean():.1%} | "
          f"min {out['inactivity_rate_2425'].min():.1%} | "
          f"max {out['inactivity_rate_2425'].max():.1%}")
    print(f"\n  Top 10 most inactive local authorities (2024-25):")
    print(out[["ons_code","la_name","inactivity_rate_2425","inactivity_change_yoy"]].head(10).to_string(index=False))

    print("\nSport England ingestion complete.")


if __name__ == "__main__":
    ingest_sport_england()
