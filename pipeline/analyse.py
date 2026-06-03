"""
pipeline/analyse.py
TrustPulse — Trust profile and risk scoring engine

Input:  data/processed/trust_master.csv
Output: data/processed/trust_profiles.csv

For each trust produces:
  - Latest month values for all metrics
  - 3-month rolling average for all metrics
  - Trend direction (Improving / Stable / Deteriorating) per metric
  - RAG flags per domain based on NHS thresholds
  - Financial cost estimates (delayed discharge, cancelled ops, sickness)
  - Peer comparison vs regional average
  - Composite risk score (0-100)

Run:
    python pipeline/analyse.py
"""

import pandas as pd
import numpy as np
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR  = Path(__file__).resolve().parents[1]
PROCESSED = BASE_DIR / "data" / "processed"
IN_PATH   = PROCESSED / "trust_master.csv"
OUT_PATH  = PROCESSED / "trust_profiles.csv"


# ---------------------------------------------------------------------------
# NHS thresholds for RAG flags
# All thresholds from NHS England published standards
# ---------------------------------------------------------------------------

THRESHOLDS = {
    # A&E
    "ae_pct_within_4hrs_type1": {
        "red_below": 76.0, "amber_below": 95.0,
        "direction": "higher_better",
        "label": "A&E 4-hour performance (Type 1)"
    },
    "ae_pct_within_4hrs_all": {
        "red_below": 76.0, "amber_below": 95.0,
        "direction": "higher_better",
        "label": "A&E 4-hour performance (All)"
    },
    "ae_over_12hr_rate": {
        "red_above": 5.0, "amber_above": 1.0,
        "direction": "lower_better",
        "label": "A&E 12-hour breach rate"
    },
    # Sickness
    "sickness_rate_pct": {
        "red_above": 6.0, "amber_above": 4.0,
        "direction": "lower_better",
        "label": "Sickness absence rate"
    },
    "sickness_rate_anxiety": {
        "red_above": 2.0, "amber_above": 1.0,
        "direction": "lower_better",
        "label": "Anxiety/stress sickness rate"
    },
    # Beds
    "beds_ganda_occupancy_rate": {
        "red_above": 95.0, "amber_above": 85.0,
        "direction": "lower_better",
        "label": "G&A bed occupancy rate"
    },
    "beds_cc_occupancy_rate": {
        "red_above": 85.0, "amber_above": 75.0,
        "direction": "lower_better",
        "label": "Critical care occupancy rate"
    },
    "beds_los7plus_pct": {
        "red_above": 20.0, "amber_above": 12.0,
        "direction": "lower_better",
        "label": "Patients with LOS 7+ days (%)"
    },
    # RTT
    "rtt_pct_within_18_weeks": {
        "red_below": 85.0, "amber_below": 92.0,
        "direction": "higher_better",
        "label": "RTT 18-week performance"
    },
    # Discharge
    "discharge_total_delayed_bed_days": {
        "direction": "lower_better",
        "label": "Delayed discharge bed days",
        "use_percentile": True  # Flag using regional percentile
    },
    # Cancelled ops
    "cancelled_ops_count": {
        "direction": "lower_better",
        "label": "Cancelled operations",
        "use_percentile": True
    },
    # CQC
    "rating_overall_numeric": {
        "red_below": 2.0, "amber_below": 3.0,
        "direction": "higher_better",
        "label": "CQC overall rating"
    },
    "cqc_well_led_numeric": {
        "red_below": 2.0, "amber_below": 3.0,
        "direction": "higher_better",
        "label": "CQC well-led rating"
    },
    # Oversight
    "oversight_segment_numeric": {
        "red_above": 3.0, "amber_above": 2.0,
        "direction": "lower_better",
        "label": "NHS Oversight segment"
    },
}

# Metric weights for composite risk score (must sum to 1.0)
WEIGHTS = {
    "ae_pct_within_4hrs_type1":    0.20,
    "sickness_rate_pct":           0.15,
    "beds_ganda_occupancy_rate":   0.15,
    "rtt_pct_within_18_weeks":     0.15,
    "discharge_total_delayed_bed_days": 0.10,
    "ae_over_12hr_rate":           0.08,
    "cancelled_ops_count":         0.05,
    "sickness_rate_anxiety":       0.05,
    "rating_overall_numeric":      0.04,
    "oversight_segment_numeric":   0.03,
}

# Financial calculation rates — NHS England published figures
DELAYED_DISCHARGE_RATE_GBP = 345   # Per delayed bed day
CANCELLED_OPS_RATE_GBP     = 3000  # Per cancelled operation (conservative average)
SICKNESS_DAILY_COST_GBP    = 200   # Approximate average daily staff cost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rag_flag(value, config):
    """Return RAG flag for a single value given threshold config."""
    if pd.isna(value):
        return "Unknown"
    direction = config.get("direction", "lower_better")
    if direction == "higher_better":
        red_below   = config.get("red_below")
        amber_below = config.get("amber_below")
        if red_below and value < red_below:
            return "Red"
        if amber_below and value < amber_below:
            return "Amber"
        return "Green"
    else:  # lower_better
        red_above   = config.get("red_above")
        amber_above = config.get("amber_above")
        if red_above and value > red_above:
            return "Red"
        if amber_above and value > amber_above:
            return "Amber"
        return "Green"


def percentile_rag(value, p75, p50):
    """RAG flag based on regional percentile (for metrics without fixed thresholds)."""
    if pd.isna(value):
        return "Unknown"
    if value > p75:
        return "Red"
    if value > p50:
        return "Amber"
    return "Green"


def trend_direction(recent_avg, prior_avg, direction, threshold_pct=3.0):
    """
    Compare recent 3-month avg vs prior 3-month avg.
    threshold_pct: minimum % change to call a trend (avoids noise).
    Returns: Improving, Deteriorating, Stable, or Insufficient Data
    """
    if pd.isna(recent_avg) or pd.isna(prior_avg) or prior_avg == 0:
        return "Insufficient Data"
    pct_change = ((recent_avg - prior_avg) / abs(prior_avg)) * 100
    if abs(pct_change) < threshold_pct:
        return "Stable"
    if direction == "higher_better":
        return "Improving" if pct_change > 0 else "Deteriorating"
    else:
        return "Improving" if pct_change < 0 else "Deteriorating"


def rag_to_score(rag):
    """Convert RAG to numeric for composite scoring."""
    return {"Green": 0, "Amber": 1, "Red": 2, "Unknown": 1}.get(rag, 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print(f"[analyse] Loading: {IN_PATH}")
    if not IN_PATH.exists():
        raise FileNotFoundError(f"trust_master.csv not found. Run pipeline/join.py first.")

    master = pd.read_csv(IN_PATH, dtype={"org_code": str})
    master["month"] = pd.to_datetime(master["month"], errors="coerce")
    master = master.dropna(subset=["org_code", "month"])
    master = master.sort_values(["org_code", "month"])

    print(f"[analyse] Master shape: {master.shape}")
    print(f"[analyse] Trusts: {master['org_code'].nunique()}")
    print(f"[analyse] Date range: {master['month'].min().date()} to {master['month'].max().date()}")

    # Identify the latest month with data
    latest_month = master["month"].max()
    cutoff_3m    = latest_month - pd.DateOffset(months=3)
    cutoff_6m    = latest_month - pd.DateOffset(months=6)

    print(f"[analyse] Latest month: {latest_month.date()}")
    print(f"[analyse] 3-month window: {cutoff_3m.date()} to {latest_month.date()}")
    print(f"[analyse] Prior 3-month window: {cutoff_6m.date()} to {cutoff_3m.date()}")

    # Numeric metric columns (exclude identifiers and categoricals)
    exclude_cols = {
        "org_code", "org_name", "month",
        "rating_overall", "rating_safe", "rating_well_led",
    }
    metric_cols = [c for c in master.columns
                   if c not in exclude_cols
                   and master[c].dtype in [np.float64, np.int64, float, int]
                   or (c not in exclude_cols and pd.api.types.is_numeric_dtype(master[c]))]
    metric_cols = [c for c in metric_cols if c not in exclude_cols]

    # Snapshot columns — CQC and oversight (same value every month, no trend)
    snapshot_cols = [c for c in metric_cols if
                     c.startswith("rating_") or
                     c.startswith("cqc_") or
                     c.startswith("oversight_") or
                     c.startswith("domain_score_") or
                     c.startswith("domain_segment_") or
                     c.startswith("league_") or
                     c.startswith("overall_") or
                     c in ["cancer_28day_pct", "cancer_62day_pct",
                            "cdiff_infection_rate", "ecoli_bacteraemia_rate",
                            "mrsa_cases_count", "implied_productivity_pct",
                            "inpatients_60day_los_pct", "planned_surplus_deficit_pct",
                            "staff_engagement_score", "staff_raising_concerns_score",
                            "productivity_growth_estimate"]]

    time_series_cols = [c for c in metric_cols if c not in snapshot_cols]

    print(f"[analyse] Time series metrics: {len(time_series_cols)}")
    print(f"[analyse] Snapshot metrics: {len(snapshot_cols)}")

    # ------------------------------------------------------------------
    # Build trust profiles
    # ------------------------------------------------------------------
    profiles = []

    for org_code, trust_df in master.groupby("org_code"):
        trust_df = trust_df.sort_values("month")
        row = {"org_code": org_code}

        # Trust name and region
        row["org_name"]   = trust_df["org_name"].dropna().iloc[-1] if trust_df["org_name"].notna().any() else org_code
        row["data_month"] = latest_month.strftime("%Y-%m")

        # Recent and prior windows
        recent = trust_df[trust_df["month"] > cutoff_3m]
        prior  = trust_df[(trust_df["month"] > cutoff_6m) & (trust_df["month"] <= cutoff_3m)]
        latest = trust_df[trust_df["month"] == latest_month]

        # ------------------------------------------------------------------
        # Time series metrics: latest, 3m avg, trend
        # ------------------------------------------------------------------
        for col in time_series_cols:
            if col not in trust_df.columns:
                continue

            # Latest value
            latest_val = latest[col].dropna().iloc[-1] if len(latest) > 0 and latest[col].notna().any() else np.nan
            row[f"{col}_latest"] = latest_val

            # 3-month rolling average
            recent_vals = recent[col].dropna()
            recent_avg  = recent_vals.mean() if len(recent_vals) > 0 else np.nan
            row[f"{col}_3m_avg"] = recent_avg

            # Prior 3-month average
            prior_vals = prior[col].dropna()
            prior_avg  = prior_vals.mean() if len(prior_vals) > 0 else np.nan
            row[f"{col}_prior_3m_avg"] = prior_avg

            # Trend
            if col in THRESHOLDS:
                direction = THRESHOLDS[col].get("direction", "lower_better")
                row[f"{col}_trend"] = trend_direction(recent_avg, prior_avg, direction)

            # RAG flag (based on 3m avg — more stable than latest)
            if col in THRESHOLDS and not THRESHOLDS[col].get("use_percentile"):
                row[f"{col}_rag"] = rag_flag(recent_avg, THRESHOLDS[col])

        # ------------------------------------------------------------------
        # Snapshot metrics: single value (no trend)
        # ------------------------------------------------------------------
        for col in snapshot_cols:
            if col not in trust_df.columns:
                continue
            val = trust_df[col].dropna().iloc[-1] if trust_df[col].notna().any() else np.nan
            row[col] = val
            if col in THRESHOLDS and not THRESHOLDS[col].get("use_percentile"):
                row[f"{col}_rag"] = rag_flag(val, THRESHOLDS[col])

        profiles.append(row)

    profiles_df = pd.DataFrame(profiles)
    print(f"[analyse] Profiles built: {profiles_df.shape}")

    # ------------------------------------------------------------------
    # Percentile-based RAG flags (need all trusts to calculate)
    # ------------------------------------------------------------------
    for col, config in THRESHOLDS.items():
        if not config.get("use_percentile"):
            continue
        avg_col = f"{col}_3m_avg"
        if avg_col not in profiles_df.columns:
            continue
        p50 = profiles_df[avg_col].quantile(0.50)
        p75 = profiles_df[avg_col].quantile(0.75)
        profiles_df[f"{col}_rag"] = profiles_df[avg_col].apply(
            lambda v: percentile_rag(v, p75, p50)
        )

    # ------------------------------------------------------------------
    # Peer comparison — trust vs regional average
    # ------------------------------------------------------------------
    print("[analyse] Calculating peer comparisons...")

    # Get region from oversight or from master
    if "Region" in master.columns:
        region_map = master.groupby("org_code")["Region"].first().to_dict()
    else:
        region_map = {}

    profiles_df["region"] = profiles_df["org_code"].map(region_map)

    peer_metrics = [
        "ae_pct_within_4hrs_type1_3m_avg",
        "sickness_rate_pct_3m_avg",
        "beds_ganda_occupancy_rate_3m_avg",
        "rtt_pct_within_18_weeks_3m_avg",
        "discharge_total_delayed_bed_days_3m_avg",
    ]

    for metric in peer_metrics:
        if metric not in profiles_df.columns:
            continue
        regional_avg = profiles_df.groupby("region")[metric].transform("mean")
        base_name    = metric.replace("_3m_avg", "")
        profiles_df[f"{base_name}_vs_region"] = profiles_df[metric] - regional_avg

    # ------------------------------------------------------------------
    # Financial cost estimates
    # ------------------------------------------------------------------
    print("[analyse] Calculating financial estimates...")

    # Delayed discharge — monthly cost annualised
    dd_col = "discharge_total_delayed_bed_days_3m_avg"
    if dd_col in profiles_df.columns:
        profiles_df["est_annual_delayed_discharge_cost_gbp"] = (
            profiles_df[dd_col] * DELAYED_DISCHARGE_RATE_GBP * 12
        ).round(0)

    # Cancelled operations — monthly cost annualised
    co_col = "cancelled_ops_count_3m_avg"
    if co_col in profiles_df.columns:
        profiles_df["est_annual_cancelled_ops_cost_gbp"] = (
            profiles_df[co_col] * CANCELLED_OPS_RATE_GBP * 12
        ).round(0)

    # Sickness — monthly FTE days lost cost
    sick_col = "fte_days_lost_total_3m_avg"
    if sick_col in profiles_df.columns:
        profiles_df["est_monthly_sickness_cost_gbp"] = (
            profiles_df[sick_col] * SICKNESS_DAILY_COST_GBP
        ).round(0)
        profiles_df["est_annual_sickness_cost_gbp"] = (
            profiles_df["est_monthly_sickness_cost_gbp"] * 12
        ).round(0)

    # Total estimated annual inefficiency cost
    cost_cols = [c for c in [
        "est_annual_delayed_discharge_cost_gbp",
        "est_annual_cancelled_ops_cost_gbp",
        "est_annual_sickness_cost_gbp",
    ] if c in profiles_df.columns]

    if cost_cols:
        profiles_df["est_total_annual_inefficiency_cost_gbp"] = profiles_df[cost_cols].sum(
            axis=1, min_count=1
        ).round(0)

    # ------------------------------------------------------------------
    # Composite risk score (0-100, higher = more at risk)
    # ------------------------------------------------------------------
    print("[analyse] Calculating composite risk scores...")

    rag_scores = []
    for col, weight in WEIGHTS.items():
        rag_col = f"{col}_rag"
        if rag_col in profiles_df.columns:
            score = profiles_df[rag_col].apply(rag_to_score) * weight * 50
            rag_scores.append(score)

    if rag_scores:
        profiles_df["risk_score"] = sum(rag_scores).round(1)
        profiles_df["risk_rag"]   = pd.cut(
            profiles_df["risk_score"],
            bins=[-1, 20, 50, 101],
            labels=["Green", "Amber", "Red"]
        )

    # ------------------------------------------------------------------
    # Count of Red flags per trust
    # ------------------------------------------------------------------
    rag_cols = [c for c in profiles_df.columns if c.endswith("_rag") and c != "risk_rag"]
    profiles_df["red_flag_count"]   = (profiles_df[rag_cols] == "Red").sum(axis=1)
    profiles_df["amber_flag_count"] = (profiles_df[rag_cols] == "Amber").sum(axis=1)
    profiles_df["green_flag_count"] = (profiles_df[rag_cols] == "Green").sum(axis=1)

    # ------------------------------------------------------------------
    # Sort by risk score descending
    # ------------------------------------------------------------------
    if "risk_score" in profiles_df.columns:
        profiles_df = profiles_df.sort_values("risk_score", ascending=False).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    profiles_df.to_csv(OUT_PATH, index=False)

    print(f"\n[analyse] Output shape: {profiles_df.shape}")
    print(f"[analyse] Trusts: {profiles_df['org_code'].nunique()}")

    # Summary of risk distribution
    if "risk_rag" in profiles_df.columns:
        print(f"\n[analyse] Risk distribution:")
        print(profiles_df["risk_rag"].value_counts().to_string())

    # Top 10 at-risk trusts
    if "risk_score" in profiles_df.columns:
        print(f"\n[analyse] Top 10 highest-risk trusts:")
        top10_cols = ["org_code", "org_name", "risk_score", "risk_rag",
                      "red_flag_count", "amber_flag_count"]
        top10_cols = [c for c in top10_cols if c in profiles_df.columns]
        print(profiles_df[top10_cols].head(10).to_string(index=False))

    # Financial summary
    if "est_total_annual_inefficiency_cost_gbp" in profiles_df.columns:
        total = profiles_df["est_total_annual_inefficiency_cost_gbp"].sum()
        mean  = profiles_df["est_total_annual_inefficiency_cost_gbp"].mean()
        print(f"\n[analyse] Financial estimates:")
        print(f"  Total estimated annual inefficiency (all trusts): £{total:,.0f}")
        print(f"  Average per trust: £{mean:,.0f}")
        print(f"  NOTE: These are estimates using published NHS rates.")
        print(f"  Delayed discharge: £{DELAYED_DISCHARGE_RATE_GBP}/day")
        print(f"  Cancelled ops: £{CANCELLED_OPS_RATE_GBP} avg reference cost")
        print(f"  Sickness: £{SICKNESS_DAILY_COST_GBP}/FTE day")

    print(f"\n[analyse] Saved to: {OUT_PATH}")
    print("[analyse] Done.")


if __name__ == "__main__":
    run()
