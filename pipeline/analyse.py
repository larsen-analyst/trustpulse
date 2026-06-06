"""
pipeline/analyse.py
TrustPulse -- Trust profile and risk scoring engine

Input:  data/processed/trust_master.csv
Output: data/processed/trust_profiles.csv   (per-trust snapshot with trends)
        data/processed/trust_risk_scores.csv (per-trust scoring, RAG, narrative)

Column names verified against trust_master.csv (170 columns, 221 trusts).

Scoring methodology
-------------------
Five NHS oversight domains, each scored 0-100 (higher = worse risk):

  Domain 1: Urgent and emergency care     weight 25%
    - Type 1 4hr performance  (ae_type1_4hr_performance, derived)
    - 12hr breach rate        (ae_12hr_breach_rate, derived)
    - Ambulance over-60 pct   (amb_over60_pct, where available)

  Domain 2: Elective care                 weight 20%
    - 18-week RTT performance (pct_within_18_weeks)
    - 52-week waiters         (waiting_over_52_weeks)

  Domain 3: Workforce                     weight 20%
    - Sickness rate           (sickness_rate_overall)
    - Nursing FTE trend       (workforce_nursing_fte, MoM direction)
    - Vacancy benchmark       (vac_benchmark_rate_all_pct, where available)

  Domain 4: Finance and productivity      weight 20%
    - Oversight segment       (overall_adjusted_segment)
    - Financial deficit       (in_financial_deficit / fin_in_deficit)
    - Finance variance        (fin_var_pct_turnover)
    - Productivity growth     (productivity_growth_estimate)

  Domain 5: Quality and safety            weight 15%
    - CQC overall rating      (rating_overall)
    - Bed occupancy           (beds_occupancy_rate)
    - Delayed discharge       (discharge_total_delayed_bed_days per 100 beds)
    - Cancelled ops rate      (num_cancelled / total_waiting)
    - C.diff infection rate   (cdiff_infection_rate)

Composite >= 60 --> Red   Composite >= 35 --> Amber   Composite < 35 --> Green
Financial override: deficit trusts cannot score below 50.

Financial unit costs (NHS England published rates):
  Delayed discharge: £345 per delayed bed day
  Cancelled operations: £3,000 per cancelled op
  Sickness absence: £200 per FTE day lost
"""

import numpy as np
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR      = Path(__file__).resolve().parents[1]
PROCESSED     = BASE_DIR / "data" / "processed"
MASTER_PATH   = PROCESSED / "trust_master.csv"
PROFILES_PATH = PROCESSED / "trust_profiles.csv"
SCORES_PATH   = PROCESSED / "trust_risk_scores.csv"

# ---------------------------------------------------------------------------
# Financial rates
# ---------------------------------------------------------------------------
DELAYED_DISCHARGE_RATE = 345    # £ per delayed bed day  (NHS England Sep 2025)
CANCELLED_OPS_RATE     = 3000   # £ per cancelled op     (conservative average)
SICKNESS_DAILY_RATE    = 200    # £ per FTE day lost     (approximate average)

# ---------------------------------------------------------------------------
# CQC rating --> numeric (higher = worse, consistent with scoring direction)
# ---------------------------------------------------------------------------
CQC_NUMERIC = {
    "Outstanding": 1,
    "Good":        2,
    "Requires improvement": 3,
    "Inadequate":  4,
}

# ---------------------------------------------------------------------------
# Snapshot columns -- same value every month, no time series trend meaningful
# ---------------------------------------------------------------------------
SNAPSHOT_COLS = {
    "rating_caring", "rating_effective", "rating_overall",
    "rating_responsive", "rating_safe", "rating_well-led",
    "Trust_type", "Trust_subtype", "Region",
    "league_segment", "league_rank", "league_avg_score",
    "overall_adjusted_segment", "overall_avg_metric_score",
    "in_financial_deficit",
    "domain_score_access", "domain_score_effectiveness_experience",
    "domain_score_finance_productivity", "domain_score_patient_safety",
    "domain_score_people_workforce",
    "domain_segment_access", "domain_segment_effectiveness_experience",
    "domain_segment_finance_productivity", "domain_segment_patient_safety",
    "domain_segment_people_workforce",
    "cancer_28day_pct", "cancer_62day_pct", "cdiff_infection_rate",
    "ecoli_bacteraemia_rate", "implied_productivity_pct",
    "inpatients_60day_los_pct", "mrsa_cases_count",
    "planned_surplus_deficit_pct", "staff_engagement_score",
    "staff_raising_concerns_score", "variance_to_financial_plan_pct",
    "productivity_activity_growth", "productivity_resource_growth",
    "productivity_growth_estimate",
    "fin_ics_name", "fin_region", "fin_year", "fin_quarter",
    "fin_ytd_plan_inc_dsf_m", "fin_ytd_actual_inc_dsf_m", "fin_ytd_var_m",
    "fin_var_pct_turnover", "fin_full_year_plan_exc_dsf_m",
    "fin_forecast_outturn_exc_dsf_m", "fin_forecasting_receipt_dsf",
    "fin_in_deficit",
    "vac_region", "vac_benchmark_rate_all_pct", "vac_benchmark_rate_nursing_pct",
    "survey_date",
    "pp1_compassionate_inclusive", "pp2_recognised_rewarded",
    "pp3_voice_counts", "pp3_2_raising_concerns", "pp4_safe_healthy",
    "pp4_1_health_safety_climate", "pp4_2_burnout", "pp4_3_negative_experiences",
    "pp5_always_learning", "pp6_work_flexibly", "pp7_team",
    "theme_engagement", "theme_morale",
    "location_id", "location_primary_inspection_category",
    "location_nhs_region", "location_region", "provider_name",
    "inherited_rating", "publication_date", "url",
}

# Columns to drop entirely from analysis (100% null artefacts from AE ingest)
DROP_COLS = {
    "ae_unnamed:_22", "ae_unnamed:_23", "ae_unnamed:_24",
    "ae_unnamed:_25", "ae_unnamed:_26", "ae_a",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_col(df, col):
    if col in df.columns:
        return df[col]
    return pd.Series(np.nan, index=df.index)


def rag_threshold(value, direction, red_thresh, amber_thresh):
    """
    direction: 'low'  = lower is worse (e.g. 4hr performance)
               'high' = higher is worse (e.g. sickness rate)
    """
    if pd.isna(value):
        return "Unknown"
    if direction == "low":
        if value <= red_thresh:   return "Red"
        if value <= amber_thresh: return "Amber"
        return "Green"
    else:
        if value >= red_thresh:   return "Red"
        if value >= amber_thresh: return "Amber"
        return "Green"


def rag_percentile(value, p75, p50):
    """RAG for metrics with no fixed threshold -- use distribution."""
    if pd.isna(value): return "Unknown"
    if value >= p75:   return "Red"
    if value >= p50:   return "Amber"
    return "Green"


def rag_score(r):
    return {"Red": 100, "Amber": 50, "Green": 0, "Unknown": 50}.get(r, 50)


def trend_direction(recent_avg, prior_avg, direction, threshold_pct=3.0):
    if pd.isna(recent_avg) or pd.isna(prior_avg) or prior_avg == 0:
        return "Insufficient Data"
    pct = ((recent_avg - prior_avg) / abs(prior_avg)) * 100
    if abs(pct) < threshold_pct:
        return "Stable"
    if direction == "low":    # lower = better
        return "Improving" if pct < 0 else "Deteriorating"
    else:                     # higher = better
        return "Improving" if pct > 0 else "Deteriorating"


# ---------------------------------------------------------------------------
# Step 1: Build trust_profiles.csv from trust_master.csv
# ---------------------------------------------------------------------------

def build_profiles(master):
    """
    For each trust: latest value, 3m avg, prior 3m avg, trend for time series cols.
    Snapshot cols: latest value only.
    """
    master = master.copy()
    master["month"] = pd.to_datetime(master["month"], errors="coerce")
    master = master.dropna(subset=["org_code", "month"])
    master = master.sort_values(["org_code", "month"])

    # Drop 100% null junk columns
    master = master.drop(columns=[c for c in DROP_COLS if c in master.columns])

    latest_month = master["month"].max()
    cutoff_3m    = latest_month - pd.DateOffset(months=3)
    cutoff_6m    = latest_month - pd.DateOffset(months=6)

    print(f"  Latest month  : {latest_month.date()}")
    print(f"  3m window     : {cutoff_3m.date()} to {latest_month.date()}")
    print(f"  Prior 3m      : {cutoff_6m.date()} to {cutoff_3m.date()}")

    id_cols = {"org_code", "month", "ae_period", "ae_parent_org"}
    all_metric_cols = [
        c for c in master.columns
        if c not in id_cols
        and c not in DROP_COLS
        and pd.api.types.is_numeric_dtype(master[c])
    ]
    snapshot_cols = [c for c in all_metric_cols if c in SNAPSHOT_COLS]
    ts_cols       = [c for c in all_metric_cols if c not in SNAPSHOT_COLS]

    print(f"  Time series cols : {len(ts_cols)}")
    print(f"  Snapshot cols    : {len(snapshot_cols)}")

    profiles = []
    for org_code, tdf in master.groupby("org_code"):
        tdf = tdf.sort_values("month")
        row = {"org_code": org_code}

        # Identity
        row["org_name"]   = tdf["org_name"].dropna().iloc[-1] \
                            if tdf["org_name"].notna().any() else org_code
        row["data_month"] = latest_month.strftime("%Y-%m")

        # String snapshot cols (non-numeric but needed on profile)
        for col in ("Region", "Trust_type", "Trust_subtype",
                    "rating_overall", "rating_safe", "rating_effective",
                    "rating_caring", "rating_responsive", "rating_well-led",
                    "fin_ics_name", "fin_region", "vac_region"):
            if col in tdf.columns:
                val = tdf[col].dropna().iloc[-1] if tdf[col].notna().any() else np.nan
                row[col] = val

        # Time series: latest, 3m avg, prior 3m avg, trend
        recent = tdf[tdf["month"] > cutoff_3m]
        prior  = tdf[(tdf["month"] > cutoff_6m) & (tdf["month"] <= cutoff_3m)]
        latest = tdf[tdf["month"] == latest_month]

        for col in ts_cols:
            lv = latest[col].dropna().iloc[-1] \
                 if len(latest) > 0 and latest[col].notna().any() else np.nan
            row[f"{col}_latest"] = lv

            rv = recent[col].dropna()
            ra = rv.mean() if len(rv) > 0 else np.nan
            row[f"{col}_3m_avg"] = ra

            pv = prior[col].dropna()
            pa = pv.mean() if len(pv) > 0 else np.nan
            row[f"{col}_prior_3m_avg"] = pa

        # Snapshot: single latest value
        for col in snapshot_cols:
            val = tdf[col].dropna().iloc[-1] if tdf[col].notna().any() else np.nan
            row[col] = val

        profiles.append(row)

    df = pd.DataFrame(profiles)
    print(f"  Profiles built   : {df.shape}")
    return df, ts_cols, latest_month


# ---------------------------------------------------------------------------
# Step 2: Derive computed metrics on profiles
# ---------------------------------------------------------------------------

def add_derived(df):
    """Add derived metrics that scoring needs, from raw profile values."""

    # Type 1 4hr performance
    t1_att   = safe_col(df, "ae_a&e_attendances_type_1_3m_avg")
    t1_over4 = safe_col(df, "ae_attendances_over_4hrs_type_1_3m_avg")
    df["ae_type1_4hr_performance"] = np.where(
        t1_att > 0, 1 - (t1_over4 / t1_att), np.nan)

    # Total 4hr performance
    tot_att   = (safe_col(df, "ae_a&e_attendances_type_1_3m_avg") +
                 safe_col(df, "ae_a&e_attendances_type_2_3m_avg") +
                 safe_col(df, "ae_a&e_attendances_other_a&e_department_3m_avg"))
    tot_over4 = (safe_col(df, "ae_attendances_over_4hrs_type_1_3m_avg") +
                 safe_col(df, "ae_attendances_over_4hrs_type_2_3m_avg") +
                 safe_col(df, "ae_attendances_over_4hrs_other_department_3m_avg"))
    df["ae_total_4hr_performance"] = np.where(
        tot_att > 0, 1 - (tot_over4 / tot_att), np.nan)

    # 12hr breach rate
    hr12   = safe_col(df, "ae_patients_who_have_waited_12+_hrs_from_dta_to_admission_3m_avg")
    df["ae_12hr_breach_rate"] = np.where(
        t1_att > 0, hr12 / t1_att, np.nan)

    # 52-week waiters per 1,000 on waiting list
    w52    = safe_col(df, "waiting_over_52_weeks_3m_avg")
    tot_w  = safe_col(df, "total_waiting_3m_avg")
    df["waiters_over52_per1000"] = np.where(
        tot_w > 0, (w52 / tot_w) * 1000, np.nan)

    # Delayed discharge days per 100 beds
    dd     = safe_col(df, "discharge_total_delayed_bed_days_3m_avg")
    beds   = safe_col(df, "beds_ganda_available_3m_avg")
    df["delayed_days_per_100_beds"] = np.where(
        beds > 0, (dd / beds) * 100, np.nan)

    # Cancelled ops rate (as % of waiting list -- labelled as estimate)
    canc   = safe_col(df, "num_cancelled_3m_avg")
    df["cancelled_ops_rate"] = np.where(
        tot_w > 0, canc / tot_w, np.nan)

    # CQC overall rating as numeric (higher = worse)
    if "rating_overall" in df.columns:
        df["cqc_overall_numeric"] = df["rating_overall"].map(CQC_NUMERIC)
    else:
        df["cqc_overall_numeric"] = np.nan

    # Nursing FTE trend direction
    nursing_3m    = safe_col(df, "workforce_nursing_fte_3m_avg")
    nursing_prior = safe_col(df, "workforce_nursing_fte_prior_3m_avg")
    df["nursing_fte_trend"] = [
        trend_direction(r, p, "high")   # higher nursing FTE = better
        for r, p in zip(nursing_3m, nursing_prior)
    ]

    # Ambulance over-60 pct: use 3m avg where available
    df["amb_over60_pct_score"] = safe_col(df, "amb_over60_pct_3m_avg")

    # Resolve deficit: prefer in_financial_deficit, fallback fin_in_deficit
    if "in_financial_deficit" in df.columns:
        df["_deficit"] = df["in_financial_deficit"].fillna(0)
    elif "fin_in_deficit" in df.columns:
        df["_deficit"] = df["fin_in_deficit"].fillna(0)
    else:
        df["_deficit"] = 0.0
    df["_deficit"] = df["_deficit"].astype(float)

    return df


# ---------------------------------------------------------------------------
# Step 3: Individual metric RAG flags
# ---------------------------------------------------------------------------

def apply_rags(df):
    # A&E
    df["rag_4hr_type1"]  = df["ae_type1_4hr_performance"].apply(
        lambda v: rag_threshold(v, "low", 0.76, 0.85))
    df["rag_4hr_total"]  = df["ae_total_4hr_performance"].apply(
        lambda v: rag_threshold(v, "low", 0.70, 0.80))
    df["rag_12hr"]       = df["ae_12hr_breach_rate"].apply(
        lambda v: rag_threshold(v, "high", 0.05, 0.02))

    # Ambulance
    df["rag_amb_60min"]  = df["amb_over60_pct_score"].apply(
        lambda v: rag_threshold(v, "high", 0.30, 0.15))

    # RTT
    df["rag_rtt_18wk"]   = safe_col(df, "pct_within_18_weeks_3m_avg").apply(
        lambda v: rag_threshold(v, "low", 0.65, 0.80))
    df["rag_rtt_52wk"]   = df["waiters_over52_per1000"].apply(
        lambda v: rag_threshold(v, "high", 5.0, 1.0))

    # Workforce
    df["rag_sickness"]   = safe_col(df, "sickness_rate_overall_3m_avg").apply(
        lambda v: rag_threshold(v, "high", 7.0, 5.5))
    df["rag_vacancy"]    = safe_col(df, "vac_benchmark_rate_all_pct").apply(
        lambda v: rag_threshold(v, "high", 12.0, 8.0))

    def nursing_rag(trend):
        return {"Deteriorating": "Red", "Stable": "Amber",
                "Improving": "Green", "Insufficient Data": "Unknown"}.get(trend, "Unknown")
    df["rag_nursing_trend"] = df["nursing_fte_trend"].apply(nursing_rag)

    # Finance
    def seg_rag(v):
        if pd.isna(v): return "Unknown"
        if v >= 4: return "Red"
        if v >= 3: return "Amber"
        return "Green"
    df["rag_oversight_segment"] = safe_col(df, "overall_adjusted_segment").apply(seg_rag)

    df["rag_finance_variance"] = safe_col(df, "fin_var_pct_turnover").apply(
        lambda v: rag_threshold(v, "high", -5.0, -2.0)
        if not pd.isna(v) else "Unknown")

    df["rag_productivity"] = safe_col(df, "productivity_growth_estimate").apply(
        lambda v: rag_threshold(v, "low", -3.0, 0.0))

    # Quality / safety
    def cqc_rag(v):
        if pd.isna(v): return "Unknown"
        if v >= 4: return "Red"
        if v >= 3: return "Amber"
        return "Green"
    df["rag_cqc_overall"] = df["cqc_overall_numeric"].apply(cqc_rag)

    df["rag_beds_occupancy"] = safe_col(df, "beds_occupancy_rate_3m_avg").apply(
        lambda v: rag_threshold(v, "high", 0.95, 0.85))

    # Delayed discharge and cancelled ops: percentile-based (no fixed NHS threshold)
    dd_col = "delayed_days_per_100_beds"
    if dd_col in df.columns:
        p50 = df[dd_col].quantile(0.50)
        p75 = df[dd_col].quantile(0.75)
        df["rag_delayed_discharge"] = df[dd_col].apply(
            lambda v: rag_percentile(v, p75, p50))
    else:
        df["rag_delayed_discharge"] = "Unknown"

    co_col = "cancelled_ops_rate"
    if co_col in df.columns:
        p50c = df[co_col].quantile(0.50)
        p75c = df[co_col].quantile(0.75)
        df["rag_cancelled_ops"] = df[co_col].apply(
            lambda v: rag_percentile(v, p75c, p50c))
    else:
        df["rag_cancelled_ops"] = "Unknown"

    df["rag_cdiff"] = safe_col(df, "cdiff_infection_rate").apply(
        lambda v: rag_threshold(v, "high", 0.30, 0.15))

    # DNA rate -- outpatients, annual snapshot. Red > 15%, Amber > 8%
    df["rag_dna_rate"] = safe_col(df, "outp_dna_rate").apply(
        lambda v: rag_threshold(v, "high", 0.15, 0.08))

    return df


# ---------------------------------------------------------------------------
# Step 4: Domain scores (0-100, higher = worse)
# ---------------------------------------------------------------------------

def domain_scores(df):
    rs = rag_score  # shorthand

    # Domain 1: Urgent and emergency care
    d1_4hr  = df["rag_4hr_type1"].apply(rs)
    d1_12hr = df["rag_12hr"].apply(rs)
    d1_amb  = df["rag_amb_60min"].apply(rs)
    # Where ambulance data unavailable (Unknown), substitute 12hr signal
    d1_amb  = d1_amb.where(df["rag_amb_60min"] != "Unknown", d1_12hr)
    df["d1_score"] = (d1_4hr * 0.50 + d1_12hr * 0.35 + d1_amb * 0.15).clip(0, 100).round(1)

    # Domain 2: Elective care
    d2_18wk = df["rag_rtt_18wk"].apply(rs)
    d2_52wk = df["rag_rtt_52wk"].apply(rs)
    df["d2_score"] = (d2_18wk * 0.65 + d2_52wk * 0.35).clip(0, 100).round(1)

    # Domain 3: Workforce
    d3_sick    = df["rag_sickness"].apply(rs)
    d3_nursing = df["rag_nursing_trend"].apply(rs)
    d3_vac     = df["rag_vacancy"].apply(rs)
    df["d3_score"] = (d3_sick * 0.50 + d3_nursing * 0.30 + d3_vac * 0.20
                      ).clip(0, 100).round(1)

    # Domain 4: Finance and productivity
    d4_seg  = df["rag_oversight_segment"].apply(rs)
    d4_var  = df["rag_finance_variance"].apply(rs)
    d4_prod = df["rag_productivity"].apply(rs)
    deficit_penalty = df["_deficit"].fillna(0) * 30  # +30 points if in deficit
    df["d4_score"] = (
        d4_seg  * 0.40 +
        d4_var  * 0.30 +
        d4_prod * 0.30 +
        deficit_penalty
    ).clip(0, 100).round(1)

    # Domain 5: Quality and safety
    d5_cqc    = df["rag_cqc_overall"].apply(rs)
    d5_beds   = df["rag_beds_occupancy"].apply(rs)
    d5_dtoc   = df["rag_delayed_discharge"].apply(rs)
    d5_canc   = df["rag_cancelled_ops"].apply(rs)
    d5_cdiff  = df["rag_cdiff"].apply(rs)
    d5_dna    = df["rag_dna_rate"].apply(rs)
    df["d5_score"] = (
        d5_cqc   * 0.25 +
        d5_beds  * 0.20 +
        d5_dtoc  * 0.20 +
        d5_canc  * 0.15 +
        d5_cdiff * 0.10 +
        d5_dna   * 0.10
    ).clip(0, 100).round(1)

    # Domain RAG
    def drag(score):
        if score >= 60: return "Red"
        if score >= 35: return "Amber"
        return "Green"

    for d in ("d1", "d2", "d3", "d4", "d5"):
        df[f"{d}_rag"] = df[f"{d}_score"].apply(drag)

    # Composite score
    comp = (
        df["d1_score"] * 0.25 +
        df["d2_score"] * 0.20 +
        df["d3_score"] * 0.20 +
        df["d4_score"] * 0.20 +
        df["d5_score"] * 0.15
    ).clip(0, 100).round(1)

    # Financial override: deficit trusts cannot score below 50
    override = ((df["_deficit"] == 1) & (comp < 50)).astype(int)
    comp = comp.where(df["_deficit"] != 1, comp.clip(lower=50))
    df["composite_score"]             = comp
    df["financial_override_applied"]  = override

    # Overall RAG
    df["overall_rag"] = comp.apply(
        lambda s: "Red" if s >= 60 else ("Amber" if s >= 35 else "Green"))

    # Red / Amber / Green flag counts (across all rag_ columns)
    rag_cols = [c for c in df.columns if c.startswith("rag_")]
    df["red_flag_count"]   = (df[rag_cols] == "Red").sum(axis=1)
    df["amber_flag_count"] = (df[rag_cols] == "Amber").sum(axis=1)
    df["green_flag_count"] = (df[rag_cols] == "Green").sum(axis=1)

    return df


# ---------------------------------------------------------------------------
# Step 5: Peer comparisons
# ---------------------------------------------------------------------------

def add_peer_comparisons(df):
    region_col = "Region"

    metrics = [
        ("ae_type1_4hr_performance", "low"),
        ("sickness_rate_overall_3m_avg", "high"),
        ("beds_occupancy_rate_3m_avg", "high"),
        ("pct_within_18_weeks_3m_avg", "low"),
        ("discharge_total_delayed_bed_days_3m_avg", "high"),
        ("waiting_over_52_weeks_3m_avg", "high"),
        ("composite_score", "high"),
    ]

    for metric, direction in metrics:
        if metric not in df.columns:
            continue
        # National percentile (higher pct = worse)
        nat_rank = df[metric].rank(pct=True, na_option="keep") * 100
        df[f"{metric}_national_pct"] = (
            nat_rank if direction == "high" else 100 - nat_rank).round(1)

        # Regional percentile
        if region_col in df.columns:
            reg_rank = (df.groupby(region_col)[metric]
                        .rank(pct=True, na_option="keep") * 100)
            df[f"{metric}_regional_pct"] = (
                reg_rank if direction == "high" else 100 - reg_rank).round(1)

            # Also store raw vs regional mean gap
            reg_mean = df.groupby(region_col)[metric].transform("mean")
            df[f"{metric}_vs_region"] = (df[metric] - reg_mean).round(3)

    return df


# ---------------------------------------------------------------------------
# Step 6: Annual cost estimates
# ---------------------------------------------------------------------------

def add_cost_estimates(df):
    dd   = safe_col(df, "discharge_total_delayed_bed_days_3m_avg")
    canc = safe_col(df, "num_cancelled_3m_avg")
    sick = safe_col(df, "sickness_fte_days_lost_3m_avg")

    df["est_annual_delayed_discharge_gbp"] = (dd   * DELAYED_DISCHARGE_RATE * 12).round(0)
    df["est_annual_cancelled_ops_gbp"]     = (canc * CANCELLED_OPS_RATE     * 12).round(0)
    df["est_annual_sickness_gbp"]          = (sick * SICKNESS_DAILY_RATE    * 12).round(0)

    cost_cols = [c for c in [
        "est_annual_delayed_discharge_gbp",
        "est_annual_cancelled_ops_gbp",
        "est_annual_sickness_gbp",
    ] if c in df.columns]
    # DNA cost -- outpatients only, annual data. Cost per missed appointment: GBP 120
    dna_col = "outp_total_dna"
    if dna_col in df.columns:
        df["est_annual_dna_cost_gbp"] = (safe_col(df, dna_col) * 120).round(0)

    df["est_annual_inefficiency_gbp"] = df[cost_cols].sum(axis=1, min_count=1).round(0)

    return df


# ---------------------------------------------------------------------------
# Step 7: Plain English narrative
# ---------------------------------------------------------------------------

def generate_narrative(row):
    name  = row.get("org_name", row.get("org_code", "This trust"))
    rag   = row.get("overall_rag", "Amber")
    score = row.get("composite_score", 50)

    parts = [f"{name} is rated {rag} overall "
             f"(composite risk score {score:.0f}/100, higher = greater risk)."]

    red_domains, amber_domains = [], []
    domain_labels = {
        "d1": "urgent and emergency care", "d2": "elective care",
        "d3": "workforce", "d4": "finance and productivity",
        "d5": "quality and safety",
    }
    for k, label in domain_labels.items():
        r = row.get(f"{k}_rag")
        if r == "Red":   red_domains.append(label)
        elif r == "Amber": amber_domains.append(label)

    if red_domains:
        parts.append(f"Significant concerns in: {', '.join(red_domains)}.")
    if amber_domains:
        parts.append(f"Moderate risk in: {', '.join(amber_domains)}.")
    if not red_domains and not amber_domains:
        parts.append("No domain is rated Red.")

    ae = row.get("ae_type1_4hr_performance")
    if pd.notna(ae):
        parts.append(f"Type 1 A&E 4-hour performance: {ae*100:.1f}% (target 76%).")

    sick = row.get("sickness_rate_overall_3m_avg")
    if pd.notna(sick):
        parts.append(f"Sickness rate: {sick:.1f}% (national average ~5.5%).")

    beds = row.get("beds_occupancy_rate_3m_avg")
    if pd.notna(beds):
        level = "critically high" if beds >= 0.95 else ("elevated" if beds >= 0.85 else "within range")
        parts.append(f"Bed occupancy: {beds*100:.1f}% ({level}).")

    rtt = row.get("pct_within_18_weeks_3m_avg")
    if pd.notna(rtt):
        parts.append(f"RTT 18-week performance: {rtt*100:.1f}% (65% standard).")

    if row.get("_deficit", 0) == 1:
        parts.append("Trust is in financial deficit; financial override applied.")

    amb = row.get("amb_over60_pct_3m_avg")
    if pd.notna(amb):
        parts.append(f"Ambulance handover delays >60 min: {amb*100:.1f}% of known handovers (winter 2025/26).")

    cost = row.get("est_annual_inefficiency_gbp")
    if pd.notna(cost) and cost > 0:
        parts.append(
            f"Estimated annual inefficiency cost: £{cost/1e6:.1f}m "
            f"(delayed discharge £{DELAYED_DISCHARGE_RATE}/day, "
            f"sickness £{SICKNESS_DAILY_RATE}/FTE day, "
            f"cancelled ops £{CANCELLED_OPS_RATE}/op -- NHS published rates).")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print("[analyse] Starting TrustPulse risk scoring engine...")

    if not MASTER_PATH.exists():
        raise FileNotFoundError(
            f"trust_master.csv not found at {MASTER_PATH}. Run pipeline/join.py first.")

    print(f"[analyse] Loading trust_master.csv...")
    master = pd.read_csv(MASTER_PATH, dtype={"org_code": str})
    print(f"  Shape: {master.shape}")

    # ------------------------------------------------------------------
    # Phase 1: Build trust_profiles.csv
    # ------------------------------------------------------------------
    print("\n[analyse] Phase 1: Building trust profiles...")
    profiles, ts_cols, latest_month = build_profiles(master)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    profiles.to_csv(PROFILES_PATH, index=False)
    print(f"  trust_profiles.csv saved: {profiles.shape}")

    # ------------------------------------------------------------------
    # Phase 2: Scoring
    # ------------------------------------------------------------------
    print("\n[analyse] Phase 2: Scoring and RAG flagging...")
    df = profiles.copy()
    df = add_derived(df)
    df = apply_rags(df)
    df = domain_scores(df)

    print("\n[analyse] Phase 3: Peer comparisons...")
    df = add_peer_comparisons(df)

    print("[analyse] Phase 4: Cost estimates...")
    df = add_cost_estimates(df)

    print("[analyse] Phase 5: Generating narratives...")
    df["narrative"] = df.apply(generate_narrative, axis=1)

    # ------------------------------------------------------------------
    # Sort and save trust_risk_scores.csv
    # ------------------------------------------------------------------
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)

    # Put key columns first
    front = [
        "org_code", "org_name", "Region", "Trust_type",
        "overall_rag", "composite_score", "financial_override_applied",
        "d1_score", "d1_rag", "d2_score", "d2_rag",
        "d3_score", "d3_rag", "d4_score", "d4_rag",
        "d5_score", "d5_rag",
        "red_flag_count", "amber_flag_count", "green_flag_count",
        "est_annual_inefficiency_gbp",
        "narrative",
    ]
    front = [c for c in front if c in df.columns]
    rest  = [c for c in df.columns if c not in front]
    df    = df[front + rest]

    df.to_csv(SCORES_PATH, index=False)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    rag_dist = df["overall_rag"].value_counts()
    n_red    = rag_dist.get("Red",   0)
    n_amber  = rag_dist.get("Amber", 0)
    n_green  = rag_dist.get("Green", 0)
    n_ov     = int(df["financial_override_applied"].sum())
    total_cost = df["est_annual_inefficiency_gbp"].sum()

    print(f"\n[analyse] Results:")
    print(f"  Trusts scored      : {len(df)}")
    print(f"  Red                : {n_red}")
    print(f"  Amber              : {n_amber}")
    print(f"  Green              : {n_green}")
    print(f"  Financial override : {n_ov} trusts")
    print(f"  Total est. annual inefficiency: £{total_cost/1e9:.2f}bn")
    print(f"  Output             : {SCORES_PATH}")
    print(f"  Columns            : {df.shape[1]}")

    print(f"\n[analyse] Top 10 highest-risk trusts:")
    top10 = df[["org_code", "org_name", "overall_rag", "composite_score",
                "d1_rag", "d2_rag", "d3_rag", "d4_rag", "d5_rag",
                "red_flag_count"]].head(10)
    print(top10.to_string(index=False))

    print("\n[analyse] Done.")
    return df


if __name__ == "__main__":
    run()
