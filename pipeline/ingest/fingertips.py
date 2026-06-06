"""
TrustPulse -- pipeline/ingest/fingertips.py
Downloads prevention indicators from the PHE Fingertips public API.

Output:
    data/processed/fingertips_clean.csv

Indicators downloaded (local authority level):
    90585 -- Preventable mortality rate (per 100,000)
    93088 -- Adults with excess weight (%)
    338   -- Diabetes: QOF prevalence aged 17+ (%)
    273   -- Physically inactive adults (%)
    41001 -- Emergency hospital admissions for ambulatory care sensitive conditions
    92488 -- Cardiovascular disease: preventable admissions

Source:
    PHE Fingertips public API -- https://fingertips.phe.org.uk/api
    No authentication required. Public data.

Notes:
    - Area type 202 = upper tier local authority (England)
    - Latest value only per indicator per LA
    - Joined to TrustPulse via LA to ICS region mapping
"""

import os
import time
import requests
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "fingertips_clean.csv")

FINGERTIPS_API = "https://fingertips.phe.org.uk/api"

# Indicators to download
# Format: {indicator_id: column_name}
INDICATORS = {
    90585: "preventable_mortality_rate",
    93088: "excess_weight_pct",
    338:   "diabetes_prevalence_pct",
    273:   "physically_inactive_pct",
    41001: "ambulatory_care_admissions_rate",
    92488: "cvd_preventable_admissions_rate",
}

# Area type 202 = Upper tier local authority
AREA_TYPE = 202


def get_indicator_data(indicator_id, area_type=202):
    """Download latest values for one indicator across all areas."""
    url = f"{FINGERTIPS_API}/data/by_indicator_id"
    params = {
        "indicator_ids": indicator_id,
        "area_type_id": area_type,
        "latest_only": "true",
    }
    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return pd.DataFrame()
        rows = []
        for item in data:
            rows.append({
                "area_code":   item.get("AreaCode"),
                "area_name":   item.get("AreaName"),
                "value":       item.get("Value"),
                "time_period": item.get("TimePeriod"),
                "indicator_id": indicator_id,
            })
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"  ERROR fetching indicator {indicator_id}: {e}")
        return pd.DataFrame()


def ingest_fingertips():
    print("=" * 60)
    print("TrustPulse | PHE Fingertips Prevention Data Ingestion")
    print("=" * 60)
    print(f"Downloading {len(INDICATORS)} indicators from Fingertips API...")
    print(f"Area type: {AREA_TYPE} (Upper tier local authority)\n")

    all_frames = []

    for indicator_id, col_name in INDICATORS.items():
        print(f"  Fetching indicator {indicator_id} ({col_name})...")
        df = get_indicator_data(indicator_id, AREA_TYPE)
        if df.empty:
            print(f"    No data returned")
            continue
        # Filter to England LAs (area codes starting with E)
        df = df[df["area_code"].astype(str).str.startswith("E")].copy()
        df = df.rename(columns={"value": col_name})
        df = df[["area_code", "area_name", col_name, "time_period"]].copy()
        df = df.rename(columns={"time_period": f"{col_name}_period"})
        print(f"    {len(df)} areas | period: {df[f'{col_name}_period'].iloc[0] if len(df) > 0 else 'N/A'}")
        all_frames.append(df)
        time.sleep(0.5)  # be polite to the API

    if not all_frames:
        print("ERROR: No data downloaded.")
        return

    # Merge all indicators on area_code + area_name
    combined = all_frames[0][["area_code", "area_name"]].copy()
    for df in all_frames:
        val_cols = [c for c in df.columns if c not in ("area_code", "area_name")]
        combined = combined.merge(df[["area_code"] + val_cols], on="area_code", how="left")

    combined = combined.drop_duplicates(subset=["area_code"])
    combined = combined.sort_values("area_code").reset_index(drop=True)

    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Local authorities : {len(combined)}")
    print(f"  Columns           : {list(combined.columns)}")

    # Show top 10 by preventable mortality
    if "preventable_mortality_rate" in combined.columns:
        top10 = combined.nlargest(10, "preventable_mortality_rate")
        print(f"\n  Top 10 LAs by preventable mortality rate:")
        print(top10[["area_code", "area_name", "preventable_mortality_rate",
                      "physically_inactive_pct"]].to_string(index=False))

    print("\nFingertips ingestion complete.")


if __name__ == "__main__":
    ingest_fingertips()
