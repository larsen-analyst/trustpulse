"""
pipeline/ingest/oversight.py
TrustPulse — NHS Oversight Framework ingest script

Sources (all in data/raw/oversight/):
  - nhs-oversight-framework-acute-trust-data-q3-25-26-v2.csv
  - nhs-oversight-framework-ambulance-trust-data-q3-25-26-v2.csv
  - nhs-oversight-framework-mental-health-and-community-trust-data-q3-25-26-v2.csv
  - nhs-oversight-framework-acute-trust-league-table-q3-25-26-v2.csv
  - nhs-oversight-framework-ambulance-trust-league-table-q3-25-26-v2.csv
  - nhs-oversight-framework-mental-health-and-community-trust-league-table-q3-25-26-v2.csv
  - NHS_Oversight_Framework_Supplementary_info_-_Productivity_Growth_Statistics.xlsx

Output: data/processed/oversight_clean.csv

Design decisions:
  - Q3 2025/26 only (most recent quarter)
  - Metrics kept are genuinely new data not already in the TrustPulse pipeline
  - Redundant metrics (A&E, RTT, sickness, discharge) are dropped — already ingested
  - OF1xxx individual metric score versions dropped — domain-level scores kept instead
  - OF0048 and OF0088 filtered to 'rate' unit to avoid count/rate duplicates
  - Output is wide format: one row per trust, one column per metric value
  - Ambulance and mental health trusts included — metrics not applicable to them are NaN
  - Productivity data is acute only — NaN for other trust types
"""

import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR  = Path(__file__).resolve().parents[2]
RAW_DIR   = BASE_DIR / "data" / "raw" / "oversight"
OUT_PATH  = BASE_DIR / "data" / "processed" / "oversight_clean.csv"

DATA_FILES = [
    "nhs-oversight-framework-acute-trust-data-q3-25-26-v2.csv",
    "nhs-oversight-framework-ambulance-trust-data-q3-25-26-v2.csv",
    "nhs-oversight-framework-mental-health-and-community-trust-data-q3-25-26-v2.csv",
]

LEAGUE_FILES = [
    "nhs-oversight-framework-acute-trust-league-table-q3-25-26-v2.csv",
    "nhs-oversight-framework-ambulance-trust-league-table-q3-25-26-v2.csv",
    "nhs-oversight-framework-mental-health-and-community-trust-league-table-q3-25-26-v2.csv",
]

PRODUCTIVITY_FILE = (
    "NHS_Oversight_Framework_Supplementary_info_-_Productivity_Growth_Statistics.xlsx"
)

PRODUCTIVITY_SKIPROWS = 14  # Confirmed by inspection: header at row 14


# ---------------------------------------------------------------------------
# Metrics to keep — genuinely new data not in existing TrustPulse pipeline
# ---------------------------------------------------------------------------

# % value metrics (raw performance values)
KEEP_PCT_METRICS = {
    "OF0010": "cancer_28day_pct",
    "OF0011": "cancer_62day_pct",
    "OF0020": "mrsa_cases_count",
    "OF0048": "ecoli_bacteraemia_rate",
    "OF0088": "cdiff_infection_rate",
    "OF0061": "staff_raising_concerns_score",
    "OF0084": "staff_engagement_score",
    "OF0063": "inpatients_60day_los_pct",
    "OF0079": "planned_surplus_deficit_pct",
    "OF0081": "variance_to_financial_plan_pct",
    "OF0085": "implied_productivity_pct",
}

# Domain scores (composite NHS England scores per domain)
KEEP_DOMAIN_SCORES = {
    "OF4000": "domain_score_access",
    "OF4002": "domain_score_patient_safety",
    "OF4003": "domain_score_finance_productivity",
    "OF4004": "domain_score_people_workforce",
    "OF4005": "domain_score_effectiveness_experience",
}

# Domain segments (1-4 segmentation per domain)
KEEP_DOMAIN_SEGMENTS = {
    "OF4100": "domain_segment_access",
    "OF4102": "domain_segment_patient_safety",
    "OF4103": "domain_segment_finance_productivity",
    "OF4104": "domain_segment_people_workforce",
    "OF4105": "domain_segment_effectiveness_experience",
}

# Summary metrics
KEEP_SUMMARY = {
    "OF5000": "overall_adjusted_segment",
    "OF5002": "overall_avg_metric_score",
}

ALL_KEEP_METRICS = {
    **KEEP_PCT_METRICS,
    **KEEP_DOMAIN_SCORES,
    **KEEP_DOMAIN_SEGMENTS,
    **KEEP_SUMMARY,
}

# For OF0048 and OF0088: both have rate and count rows — keep rate only
RATE_ONLY_METRICS = {"OF0048", "OF0088"}

QUARTER = "Q3 2025/26"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():

    # ------------------------------------------------------------------
    # 1. Load and stack all three data files, filter to Q3
    # ------------------------------------------------------------------
    print("[oversight] Loading data files...")
    data_frames = []
    for fname in DATA_FILES:
        fpath = RAW_DIR / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Missing: {fpath}")
        df = pd.read_csv(fpath, dtype=str)
        data_frames.append(df)

    data = pd.concat(data_frames, ignore_index=True)
    before = len(data)
    data = data[data["Quarter"] == QUARTER].copy()
    print(f"[oversight] After Q3 filter: {len(data)} rows (from {before})")
    print(f"[oversight] Trust types: {data['Trust_type'].unique()}")
    print(f"[oversight] Unique trusts: {data['Trust_code'].nunique()}")

    # ------------------------------------------------------------------
    # 2. Filter to selected metrics only
    # ------------------------------------------------------------------
    data = data[data["Metric_ID"].isin(ALL_KEEP_METRICS.keys())].copy()

    # For rate/count duplicates, keep rate unit only
    rate_mask = (
        ~data["Metric_ID"].isin(RATE_ONLY_METRICS) |
        (data["Metric_ID"].isin(RATE_ONLY_METRICS) & (data["Units"] == "rate"))
    )
    data = data[rate_mask].copy()
    print(f"[oversight] After metric filter: {len(data)} rows")

    # ------------------------------------------------------------------
    # 3. Rename Metric_ID to clean column names and pivot to wide
    # ------------------------------------------------------------------
    data["metric_col"] = data["Metric_ID"].map(ALL_KEEP_METRICS)

    # Convert Value to numeric
    data["Value"] = pd.to_numeric(data["Value"], errors="coerce")

    pivot = data.pivot_table(
        index="Trust_code",
        columns="metric_col",
        values="Value",
        aggfunc="first",
    )
    pivot.columns.name = None
    pivot = pivot.reset_index()
    print(f"[oversight] Pivoted shape: {pivot.shape}")

    # ------------------------------------------------------------------
    # 4. Join trust metadata (name, type, region)
    # ------------------------------------------------------------------
    meta = (
        data[["Trust_code", "Trust_name", "Trust_type", "Trust_subtype", "Region"]]
        .drop_duplicates(subset=["Trust_code"])
        .copy()
    )
    result = meta.merge(pivot, on="Trust_code", how="left")

    # ------------------------------------------------------------------
    # 5. Load and join league table data
    # ------------------------------------------------------------------
    print("[oversight] Loading league tables...")
    league_frames = []
    for fname in LEAGUE_FILES:
        fpath = RAW_DIR / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Missing: {fpath}")
        df = pd.read_csv(fpath, dtype=str)
        league_frames.append(df)

    league = pd.concat(league_frames, ignore_index=True)

    # Keep only columns useful for TrustPulse
    league = league[[
        "Trust_code", "Average_score", "Segment",
        "Trust_in_financial_deficit", "Rank"
    ]].copy()
    league = league.rename(columns={
        "Average_score":             "league_avg_score",
        "Segment":                   "league_segment",
        "Trust_in_financial_deficit": "in_financial_deficit",
        "Rank":                      "league_rank",
    })

    result = result.merge(league, on="Trust_code", how="left")
    print(f"[oversight] After league join: {result.shape}")

    # ------------------------------------------------------------------
    # 6. Load and join productivity data (acute only)
    # ------------------------------------------------------------------
    print("[oversight] Loading productivity data...")
    prod_path = RAW_DIR / PRODUCTIVITY_FILE
    if not prod_path.exists():
        raise FileNotFoundError(f"Missing: {prod_path}")

    prod = pd.read_excel(prod_path, skiprows=PRODUCTIVITY_SKIPROWS, dtype=str)

    # Drop unnamed columns
    prod = prod.loc[:, [c for c in prod.columns if "Unnamed" not in str(c)]]
    prod = prod.dropna(how="all")

    prod = prod.rename(columns={
        "Org code":                      "Trust_code",
        "Cost weighted activity growth": "productivity_activity_growth",
        "Real terms resource growth":    "productivity_resource_growth",
        "Productivity growth estimate":  "productivity_growth_estimate",
    })

    prod = prod[["Trust_code", "productivity_activity_growth",
                 "productivity_resource_growth", "productivity_growth_estimate"]].copy()

    for col in ["productivity_activity_growth", "productivity_resource_growth",
                "productivity_growth_estimate"]:
        prod[col] = pd.to_numeric(prod[col], errors="coerce")

    result = result.merge(prod, on="Trust_code", how="left")
    print(f"[oversight] After productivity join: {result.shape}")

    # ------------------------------------------------------------------
    # 7. Final column order
    # ------------------------------------------------------------------
    id_cols = [
        "Trust_code", "Trust_name", "Trust_type", "Trust_subtype", "Region",
    ]
    summary_cols = [
        "league_segment", "league_rank", "league_avg_score",
        "overall_adjusted_segment", "overall_avg_metric_score",
        "in_financial_deficit",
    ]
    domain_score_cols = sorted([c for c in result.columns if c.startswith("domain_score_")])
    domain_segment_cols = sorted([c for c in result.columns if c.startswith("domain_segment_")])
    metric_cols = sorted([
        c for c in result.columns
        if c in KEEP_PCT_METRICS.values()
    ])
    productivity_cols = [
        "productivity_activity_growth",
        "productivity_resource_growth",
        "productivity_growth_estimate",
    ]

    final_cols = (
        id_cols + summary_cols + domain_score_cols +
        domain_segment_cols + metric_cols + productivity_cols
    )
    final_cols = [c for c in final_cols if c in result.columns]
    result = result[final_cols]

    # ------------------------------------------------------------------
    # 8. Save
    # ------------------------------------------------------------------
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_PATH, index=False)

    print(f"[oversight] Output shape: {result.shape}")
    print(f"[oversight] Columns: {list(result.columns)}")
    print(f"[oversight] Sample:")
    print(result.head(3).to_string())
    print(f"[oversight] Saved to: {OUT_PATH}")
    print("[oversight] Done.")


if __name__ == "__main__":
    run()
