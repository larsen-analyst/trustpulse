"""
TrustPulse -- pipeline/ingest/estates.py
Ingests NHS ERIC (Estates Returns Information Collection) trust-level data.
Uses Site data CSV (aggregated to trust level) for backlog maintenance figures.

Output:
    data/processed/estates_clean.csv

Metrics per trust per year:
    estates_backlog_high_risk_m      : cost to eradicate high risk backlog (GBP millions)
    estates_backlog_significant_m    : cost to eradicate significant risk backlog
    estates_backlog_moderate_m       : cost to eradicate moderate risk backlog
    estates_backlog_total_m          : total backlog (all risk levels)
    estates_maintenance_cost_m       : annual estates and property maintenance cost
    estates_total_sites              : total number of sites
    estates_capital_lifecycle_m      : capital for maintaining existing buildings
    estates_fires_count              : fires recorded in year

Source:
    data/raw/estates/ -- Site data CSVs and Trust data CSVs
    Annual ERIC publications 2022-23 to 2024-25. Source: NHS Digital.

Notes:
    - Site data is aggregated to trust level for backlog figures
    - High risk backlog = risk of catastrophic failure or major disruption to services
    - Low lifecycle investment + high backlog = compound risk signal
"""

import os
import glob
import re
import pandas as pd
import numpy as np

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "estates")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "estates_clean.csv")

PERIOD_MAP = {
    "2022-23": pd.Timestamp("2023-03-31"),
    "2023-24": pd.Timestamp("2024-03-31"),
    "2024-25": pd.Timestamp("2025-03-31"),
}


def detect_year(filepath):
    basename = os.path.basename(filepath)
    # Match explicit year pairs in filename
    if "2022_23" in basename or "202223" in basename:
        return "2022-23"
    if "2023_24" in basename or "202324" in basename:
        return "2023-24"
    if "2024_25" in basename or "202425" in basename:
        return "2024-25"
    return None


def safe_m(series):
    return (pd.to_numeric(series, errors="coerce").fillna(0) / 1e6).round(3)


def process_site_file(filepath, year):
    """Process site data CSV -- aggregate backlog figures to trust level."""
    try:
        df = pd.read_csv(filepath, encoding="latin1", dtype=str, low_memory=False)
    except Exception as e:
        print(f"  ERROR reading site file: {e}")
        return pd.DataFrame()

    # Find key columns
    def find_col(keyword):
        for c in df.columns:
            if keyword.lower() in c.lower():
                return c
        return None

    code_col     = find_col("Trust Code")
    name_col     = find_col("Trust Name")
    high_col     = find_col("high risk backlog")
    sig_col      = find_col("significant risk backlog")
    mod_col      = find_col("moderate risk backlog")
    low_col      = find_col("low risk backlog")
    maint_col    = find_col("Estates and property maintenance")

    if not code_col:
        print(f"  WARNING: No Trust Code column found")
        return pd.DataFrame()

    # Convert to numeric
    for col in [high_col, sig_col, mod_col, low_col, maint_col]:
        if col:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Aggregate to trust level
    agg = {code_col: "first"}
    if name_col:
        agg[name_col] = "first"
    for col, alias in [
        (high_col, "estates_backlog_high_risk_m"),
        (sig_col,  "estates_backlog_significant_m"),
        (mod_col,  "estates_backlog_moderate_m"),
        (low_col,  "estates_backlog_low_risk_m"),
        (maint_col,"estates_maintenance_cost_m"),
    ]:
        if col:
            agg[col] = "sum"

    grouped = df.groupby(code_col).agg(agg).reset_index(drop=True)

    out = pd.DataFrame()
    out["org_code"]     = grouped[code_col].astype(str).str.strip()
    if name_col:
        out["org_name"] = grouped[name_col].astype(str).str.strip()
    out["period_date"]  = PERIOD_MAP[year]
    out["financial_year"] = year

    for col, alias in [
        (high_col, "estates_backlog_high_risk_m"),
        (sig_col,  "estates_backlog_significant_m"),
        (mod_col,  "estates_backlog_moderate_m"),
        (low_col,  "estates_backlog_low_risk_m"),
        (maint_col,"estates_maintenance_cost_m"),
    ]:
        if col and col in grouped.columns:
            out[alias] = (grouped[col] / 1e6).round(3)

    # Total backlog
    bl_cols = [c for c in ["estates_backlog_high_risk_m",
                            "estates_backlog_significant_m",
                            "estates_backlog_moderate_m",
                            "estates_backlog_low_risk_m"] if c in out.columns]
    if bl_cols:
        out["estates_backlog_total_m"] = out[bl_cols].sum(axis=1).round(3)

    # Filter to NHS trust codes
    out = out[out["org_code"].str.match(r'^[A-Z][A-Z0-9]{2,4}$', na=False)].copy()
    return out.dropna(subset=["org_code"])


def process_trust_file(filepath, year):
    """Process trust data CSV -- get site count and capital investment."""
    try:
        df = pd.read_csv(filepath, encoding="latin1", dtype=str)
    except Exception as e:
        print(f"  ERROR reading trust file: {e}")
        return pd.DataFrame()

    code_col  = df.columns[0]
    sites_col = next((c for c in df.columns if "Total number of sites" in c), None)
    lc_col    = next((c for c in df.columns if "maintaining (lifecycle)" in c), None)
    fires_col = next((c for c in df.columns if "Fires recorded" in c), None)

    out = pd.DataFrame()
    out["org_code"] = df[code_col].astype(str).str.strip()
    if sites_col:
        out["estates_total_sites"] = pd.to_numeric(df[sites_col], errors="coerce").fillna(0).astype(int)
    if lc_col:
        out["estates_capital_lifecycle_m"] = (pd.to_numeric(df[lc_col], errors="coerce").fillna(0) / 1e6).round(3)
    if fires_col:
        out["estates_fires_count"] = pd.to_numeric(df[fires_col], errors="coerce").fillna(0).astype(int)

    out = out[out["org_code"].str.match(r'^[A-Z][A-Z0-9]{2,4}$', na=False)].copy()
    return out.dropna(subset=["org_code"])


def ingest_estates():
    print("=" * 60)
    print("TrustPulse | ERIC Estates Ingestion")
    print("=" * 60)

    site_files  = sorted(glob.glob(os.path.join(RAW_DIR, "*Site data*.csv")))
    trust_files = sorted(glob.glob(os.path.join(RAW_DIR, "*Trust data*.csv")))

    print(f"Found {len(site_files)} site files, {len(trust_files)} trust files")

    frames = []
    for site_fp in site_files:
        year = detect_year(site_fp)
        if not year:
            print(f"  WARNING: Could not detect year from {os.path.basename(site_fp)}")
            continue
        print(f"\nProcessing site data: {os.path.basename(site_fp)} [{year}]")
        site_df = process_site_file(site_fp, year)
        if site_df.empty:
            continue
        print(f"  Trusts: {site_df['org_code'].nunique()}")

        # Merge with trust file for same year
        trust_fp = next((f for f in trust_files if year.replace("-","_") in f or year.replace("-","") in f), None)
        if trust_fp:
            trust_df = process_trust_file(trust_fp, year)
            if not trust_df.empty:
                site_df = site_df.merge(trust_df, on="org_code", how="left")

        frames.append(site_df)

    if not frames:
        print("ERROR: No data extracted.")
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
    print(f"  Unique trusts : {combined['org_code'].nunique()}")
    print(f"  Years         : {sorted(combined['financial_year'].unique())}")

    latest = combined[combined["period_date"] == combined["period_date"].max()]
    nhs = latest[latest["org_code"].str.match(r'^R', na=False)]
    print(f"\n  NHS trusts (R-codes) in 2024-25: {len(nhs)}")

    if "estates_backlog_high_risk_m" in nhs.columns:
        total_hr = nhs["estates_backlog_high_risk_m"].sum()
        total_bl = nhs["estates_backlog_total_m"].sum() if "estates_backlog_total_m" in nhs.columns else 0
        print(f"  Total high risk backlog (NHS R-code trusts): £{total_hr:.0f}m")
        print(f"  Total backlog (all risk levels): £{total_bl:.0f}m")
        print(f"\n  Trusts with highest high-risk backlog:")
        top10 = nhs.nlargest(10, "estates_backlog_high_risk_m")[
            ["org_code","org_name","estates_backlog_high_risk_m","estates_backlog_total_m"]]
        print(top10.to_string(index=False))

    print("\nEstates ingestion complete.")


if __name__ == "__main__":
    ingest_estates()
