"""
TrustPulse -- pipeline/ingest/league_tables.py
Ingests NHS Oversight Framework league table and detailed metrics data.

Output:
    data/processed/league_tables_clean.csv

Metrics per trust (Q3 2025/26 snapshot):
    lt_segment          : oversight framework adjusted segment (1-4, 1=best)
    lt_rank             : rank within trust type
    lt_avg_score        : average metric score
    lt_in_deficit       : 1 if in financial deficit or deficit support

Source:
    data/raw/oversight/league_tables/
    nhs-oversight-framework-acute-trust-league-table-q3-25-26-v2.csv
    Source: NHS England NHS Oversight Framework Q3 2025/26

Notes:
    - Segment 1 = narrowest range of challenges
    - Segment 4 = broadest range of challenges
    - Segment 5 = Recovery Support Programme (not in public data)
    - Trusts in financial deficit cannot be higher than segment 3
    - 134 acute trusts in Q3 2025/26 publication
"""

import os
import glob
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "oversight", "league_tables")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "league_tables_clean.csv")


def ingest_league_tables():
    print("=" * 60)
    print("TrustPulse | NHS Oversight League Tables Ingest")
    print("=" * 60)

    # Find the league table file
    lt_files = glob.glob(os.path.join(RAW_DIR, "*league-table*.csv"))
    if not lt_files:
        print("ERROR: No league table CSV found")
        return

    filepath = lt_files[0]
    print(f"Loading: {os.path.basename(filepath)}")

    df = pd.read_csv(filepath, dtype=str)
    print(f"  Rows: {len(df)} | Columns: {df.shape[1]}")

    out = pd.DataFrame()
    out["org_code"]      = df["Trust_code"].astype(str).str.strip()
    out["org_name"]      = df["Trust_name"].astype(str).str.strip()
    out["quarter"]       = df["Quarter"].astype(str).str.strip()
    out["lt_segment"]    = pd.to_numeric(df["Segment"], errors="coerce")
    out["lt_rank"]       = pd.to_numeric(df["Rank"], errors="coerce")
    out["lt_avg_score"]  = pd.to_numeric(df["Average_score"], errors="coerce")
    out["lt_in_deficit"] = (df["Trust_in_financial_deficit"].str.strip().str.upper() == "YES").astype(int)
    out["lt_trust_type"] = df["Trust_type"].astype(str).str.strip()
    out["lt_region"]     = df["Region"].astype(str).str.strip()

    out = out[out["org_code"].str.match(r'^[A-Z][A-Z0-9]{2,4}$', na=False)].copy()
    out = out.dropna(subset=["org_code"])

    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Trusts        : {len(out)}")
    print(f"  Columns       : {out.shape[1]}")
    print(f"  Quarter       : {out['quarter'].iloc[0]}")
    print(f"\n  Segment distribution:")
    print(out['lt_segment'].value_counts().sort_index().to_string())
    print(f"\n  In deficit    : {out['lt_in_deficit'].sum()} of {len(out)}")

    print(f"\n  Top 10 by rank (best performing):")
    top10 = out.nsmallest(10, 'lt_rank')[['org_code','org_name','lt_segment','lt_rank','lt_avg_score']]
    print(top10.to_string(index=False))

    print(f"\n  Bottom 10 by rank (most challenged):")
    bot10 = out.nlargest(10, 'lt_rank')[['org_code','org_name','lt_segment','lt_rank','lt_avg_score']]
    print(bot10.to_string(index=False))

    print("\nLeague tables ingest complete.")


if __name__ == "__main__":
    ingest_league_tables()
