"""
app/data.py
TrustPulse data loading and caching layer

Loads trust_profiles.csv once at startup.
All routes read from the in-memory cache — no disk reads per request.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from functools import lru_cache

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"


@lru_cache(maxsize=1)
def load_profiles():
    """Load trust_profiles.csv and return as DataFrame. Cached after first call."""
    path = PROCESSED / "trust_profiles.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"trust_profiles.csv not found at {path}. "
            "Run pipeline/analyse.py first."
        )
    df = pd.read_csv(path, dtype={"org_code": str})
    df["org_code"] = df["org_code"].str.strip()
    return df


def get_trust_list():
    """Return list of {org_code, org_name, risk_rag, risk_score} dicts for search."""
    df = load_profiles()
    cols = ["org_code", "org_name", "risk_rag", "risk_score",
            "red_flag_count", "amber_flag_count"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].to_dict(orient="records")


def get_trust(org_code):
    """Return a single trust's full profile as a dict."""
    df = load_profiles()
    row = df[df["org_code"] == org_code]
    if len(row) == 0:
        return None
    return row.iloc[0].to_dict()


def get_summary_stats():
    """Return headline stats for homepage."""
    df = load_profiles()
    stats = {
        "total_trusts":     int(len(df)),
        "red_count":        int((df["risk_rag"] == "Red").sum())   if "risk_rag" in df.columns else 0,
        "amber_count":      int((df["risk_rag"] == "Amber").sum()) if "risk_rag" in df.columns else 0,
        "green_count":      int((df["risk_rag"] == "Green").sum()) if "risk_rag" in df.columns else 0,
        "total_inefficiency": None,
        "avg_inefficiency":   None,
        "data_month":       None,
    }
    if "est_total_annual_inefficiency_cost_gbp" in df.columns:
        total = df["est_total_annual_inefficiency_cost_gbp"].sum()
        avg   = df["est_total_annual_inefficiency_cost_gbp"].mean()
        stats["total_inefficiency"] = f"£{total/1e9:.1f}bn"
        stats["avg_inefficiency"]   = f"£{avg/1e6:.1f}m"
    if "data_month" in df.columns:
        stats["data_month"] = df["data_month"].iloc[0]
    return stats


def get_top_risk_trusts(n=10):
    """Return top N trusts by risk score."""
    df = load_profiles()
    cols = ["org_code", "org_name", "risk_score", "risk_rag",
            "red_flag_count", "amber_flag_count",
            "ae_pct_within_4hrs_type1_3m_avg",
            "sickness_rate_pct_3m_avg",
            "beds_ganda_occupancy_rate_3m_avg",
            "est_total_annual_inefficiency_cost_gbp"]
    cols = [c for c in cols if c in df.columns]
    if "risk_score" in df.columns:
        df = df.sort_values("risk_score", ascending=False)
    return df[cols].head(n).to_dict(orient="records")


def get_region_averages():
    """Return regional average for key metrics."""
    df = load_profiles()
    if "region" not in df.columns:
        return {}
    metric_cols = [
        "ae_pct_within_4hrs_type1_3m_avg",
        "sickness_rate_pct_3m_avg",
        "beds_ganda_occupancy_rate_3m_avg",
        "rtt_pct_within_18_weeks_3m_avg",
    ]
    metric_cols = [c for c in metric_cols if c in df.columns]
    return df.groupby("region")[metric_cols].mean().round(2).to_dict(orient="index")
