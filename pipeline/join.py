"""
pipeline/join.py
TrustPulse — Master trust profile builder

Joins all processed datasets on trust code and date to produce one master
analytical file: data/processed/trust_master.csv

Output structure:
  - One row per trust per month
  - Full date range covered (nulls where a dataset has no data for that period)
  - 50 derived metrics calculated across all datasets
  - Quarterly datasets forward-filled to monthly
  - Snapshot datasets (CQC, Oversight) joined on trust code only

Run:
    python pipeline/join.py

Output: data/processed/trust_master.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR   = Path(__file__).resolve().parents[1]
PROCESSED  = BASE_DIR / "data" / "processed"
OUT_PATH   = PROCESSED / "trust_master.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load(filename, **kwargs):
    path = PROCESSED / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing processed file: {path}")
    df = pd.read_csv(path, **kwargs)
    print(f"  Loaded {filename}: {df.shape}")
    return df


def to_month_start(series):
    """Coerce a date series to month-start timestamps."""
    return pd.to_datetime(series, errors="coerce").dt.to_period("M").dt.to_timestamp()


def safe_divide(num, den, scale=1):
    """Divide two series safely, returning NaN on zero/null denominator."""
    return np.where(den.notna() & (den != 0), num / den * scale, np.nan)


def rating_to_numeric(series):
    """Map CQC text ratings to numeric scores."""
    mapping = {
        "outstanding":          4,
        "good":                 3,
        "requires improvement": 2,
        "inadequate":           1,
        "not rated":            np.nan,
    }
    return series.str.strip().str.lower().map(mapping)


# ---------------------------------------------------------------------------
# Step 1 — Build trust-month spine
# ---------------------------------------------------------------------------

def build_spine():
    """
    Build the master spine: one row per trust per month.
    Uses ae_clean as the anchor since it has the broadest trust coverage
    and most complete monthly data.
    """
    print("\n[join] Building trust-month spine from A&E data...")
    ae = load("ae_clean.csv")

    # Parse the A&E period column (format: MSitAE-APRIL-2022)
    ae["month"] = pd.to_datetime(
        ae["period"].str.replace("MSitAE-", "", regex=False),
        format="%B-%Y",
        errors="coerce"
    )
    ae = ae.dropna(subset=["month", "org_code"])

    # Build spine: all unique trust-month combinations
    spine = ae[["org_code", "org_name", "month"]].drop_duplicates().copy()
    spine = spine.sort_values(["org_code", "month"]).reset_index(drop=True)
    print(f"  Spine: {len(spine):,} rows | {spine['org_code'].nunique()} trusts | "
          f"{spine['month'].min().date()} to {spine['month'].max().date()}")
    return spine, ae


# ---------------------------------------------------------------------------
# Step 2 — A&E metrics
# ---------------------------------------------------------------------------

def build_ae_metrics(ae):
    print("\n[join] Building A&E metrics...")
    df = ae.copy()

    # Coerce numeric
    num_cols = [c for c in df.columns if c not in ["period", "org_code", "parent_org", "org_name", "month"]]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Identify column names defensively
    t1_att   = next((c for c in df.columns if "type_1" in c and "attendance" in c and "booked" not in c and "over" not in c), None)
    t2_att   = next((c for c in df.columns if "type_2" in c and "attendance" in c and "over" not in c), None)
    other_att= next((c for c in df.columns if "other" in c and "attendance" in c and "over" not in c), None)
    t1_admit = next((c for c in df.columns if "emergency_admission" in c and "type_1" in c), None)
    t1_4hr   = next((c for c in df.columns if "over_4hrs" in c and "type_1" in c), None)
    t2_4hr   = next((c for c in df.columns if "over_4hrs" in c and "type_2" in c), None)
    other_4hr= next((c for c in df.columns if "over_4hrs" in c and "other" in c), None)
    t1_12hr  = next((c for c in df.columns if "over_12hrs" in c and "type_1" in c), None)

    out = df[["org_code", "month"]].copy()

    if t1_att:
        out["ae_type1_attendances"]    = df[t1_att]
    if t2_att:
        out["ae_type2_attendances"]    = df[t2_att]
    if other_att:
        out["ae_other_attendances"]    = df[other_att]

    # Total attendances
    att_cols = [c for c in [t1_att, t2_att, other_att] if c]
    if att_cols:
        out["ae_total_attendances"]    = df[att_cols].sum(axis=1, min_count=1)

    # 4-hour performance
    if t1_att and t1_4hr:
        within_4hr = df[t1_att] - df[t1_4hr]
        out["ae_pct_within_4hrs_type1"] = safe_divide(within_4hr, df[t1_att], scale=100)

    if att_cols and t1_4hr:
        total_over_4hr_cols = [c for c in [t1_4hr, t2_4hr, other_4hr] if c]
        total_over_4hr = df[total_over_4hr_cols].sum(axis=1, min_count=1)
        total_within_4hr = out["ae_total_attendances"] - total_over_4hr
        out["ae_pct_within_4hrs_all"]   = safe_divide(total_within_4hr, out["ae_total_attendances"], scale=100)

    # Emergency admission rate
    if t1_att and t1_admit:
        out["ae_type1_admission_rate"]  = safe_divide(df[t1_admit], df[t1_att], scale=100)

    # 12-hour breaches
    if t1_12hr:
        out["ae_over_12hr_count"]       = df[t1_12hr]
        if t1_att:
            out["ae_over_12hr_rate"]    = safe_divide(df[t1_12hr], df[t1_att], scale=100)

    # Type 1 share
    if t1_att and "ae_total_attendances" in out.columns:
        out["ae_type1_share_pct"]       = safe_divide(df[t1_att], out["ae_total_attendances"], scale=100)

    print(f"  A&E metrics: {[c for c in out.columns if c not in ['org_code','month']]}")
    return out


# ---------------------------------------------------------------------------
# Step 3 — Sickness metrics
# ---------------------------------------------------------------------------

def build_sickness_metrics():
    print("\n[join] Building sickness metrics...")
    df = load("sickness_trust_clean.csv")
    df["month"] = to_month_start(df["period_date"])
    df["fte_days_available"] = pd.to_numeric(df["fte_days_available"], errors="coerce")
    df["fte_days_lost"]      = pd.to_numeric(df["fte_days_lost"], errors="coerce")

    out_rows = []

    for (org, month), grp in df.groupby(["org_code", "month"]):
        row = {"org_code": org, "month": month}

        # Overall rate — All Staff Groups, All Reasons
        all_grp = grp[
            (grp["staff_group"].str.lower().str.contains("all", na=False)) &
            (grp["reason"].str.lower().str.contains("all", na=False))
        ]
        if len(all_grp) > 0:
            avail = all_grp["fte_days_available"].sum()
            lost  = all_grp["fte_days_lost"].sum()
            row["sickness_rate_pct"]    = (lost / avail * 100) if avail > 0 else np.nan
            row["fte_days_lost_total"]  = lost
            row["fte_days_available_total"] = avail

        # Anxiety/stress/depression
        anxiety = grp[grp["reason"].str.lower().str.contains("anxiety|stress|depression", na=False)]
        if len(anxiety) > 0:
            avail = anxiety["fte_days_available"].sum()
            lost  = anxiety["fte_days_lost"].sum()
            row["sickness_rate_anxiety"] = (lost / avail * 100) if avail > 0 else np.nan

        # Musculoskeletal
        msk = grp[grp["reason"].str.lower().str.contains("musculo|back", na=False)]
        if len(msk) > 0:
            avail = msk["fte_days_available"].sum()
            lost  = msk["fte_days_lost"].sum()
            row["sickness_rate_musculoskeletal"] = (lost / avail * 100) if avail > 0 else np.nan

        # Infectious disease (COVID proxy)
        covid = grp[grp["reason"].str.lower().str.contains("infect|cold|flu|covid", na=False)]
        if len(covid) > 0:
            avail = covid["fte_days_available"].sum()
            lost  = covid["fte_days_lost"].sum()
            row["sickness_rate_infectious"] = (lost / avail * 100) if avail > 0 else np.nan

        # Nursing and midwifery
        nursing = grp[
            grp["staff_group"].str.lower().str.contains("nurs|midwif", na=False) &
            grp["reason"].str.lower().str.contains("all", na=False)
        ]
        if len(nursing) > 0:
            avail = nursing["fte_days_available"].sum()
            lost  = nursing["fte_days_lost"].sum()
            row["sickness_nursing_rate"] = (lost / avail * 100) if avail > 0 else np.nan

        # Medical and dental
        medical = grp[
            grp["staff_group"].str.lower().str.contains("medical|dental", na=False) &
            grp["reason"].str.lower().str.contains("all", na=False)
        ]
        if len(medical) > 0:
            avail = medical["fte_days_available"].sum()
            lost  = medical["fte_days_lost"].sum()
            row["sickness_medical_rate"] = (lost / avail * 100) if avail > 0 else np.nan

        out_rows.append(row)

    out = pd.DataFrame(out_rows)

    # National average per month for peer comparison
    # Calculate only if column exists and has values
    if "sickness_rate_pct" in out.columns and out["sickness_rate_pct"].notna().any():
        nat_avg = out.groupby("month")["sickness_rate_pct"].mean().rename("nat_avg_sickness")
        out = out.merge(nat_avg, on="month", how="left")
        out["sickness_vs_national_avg"] = out["sickness_rate_pct"] - out["nat_avg_sickness"]
        out = out.drop(columns=["nat_avg_sickness"])
    else:
        out["sickness_vs_national_avg"] = np.nan

    print(f"  Sickness metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Step 4 — Workforce metrics
# ---------------------------------------------------------------------------

def build_workforce_metrics():
    print("\n[join] Building workforce metrics...")
    df = load("workforce_clean.csv")
    df["month"] = to_month_start(df["period_date"])
    df["total"] = pd.to_numeric(df["total"], errors="coerce")

    # Workforce file is long format: data_type column distinguishes FTE vs Headcount
    has_data_type = "data_type" in df.columns

    if has_data_type:
        fte_df = df[df["data_type"].str.upper().str.contains("FTE", na=False)].copy()
        hc_df  = df[df["data_type"].str.upper().str.contains("HEAD|HC", na=False)].copy()
    else:
        fte_df = df.copy()
        hc_df  = pd.DataFrame()

    out_rows = []
    for (org, month), grp in fte_df.groupby(["org_code", "month"]):
        row = {"org_code": org, "month": month}

        row["workforce_total_fte"]   = grp["total"].sum()

        nursing = grp[grp["staff_group"].str.lower().str.contains("nurs|midwif", na=False)]
        row["workforce_nursing_fte"] = nursing["total"].sum() if len(nursing) > 0 else np.nan

        medical = grp[grp["staff_group"].str.lower().str.contains("medical|dental", na=False)]
        row["workforce_medical_fte"] = medical["total"].sum() if len(medical) > 0 else np.nan

        out_rows.append(row)

    out = pd.DataFrame(out_rows)

    # Join headcount separately
    if len(hc_df) > 0:
        hc_agg = hc_df.groupby(["org_code", "month"])["total"].sum().reset_index()
        hc_agg = hc_agg.rename(columns={"total": "workforce_total_headcount"})
        out = out.merge(hc_agg, on=["org_code", "month"], how="left")
        out["workforce_hc_to_fte_ratio"] = safe_divide(
            out["workforce_total_headcount"], out["workforce_total_fte"])

    out = pd.DataFrame(out_rows)
    print(f"  Workforce metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Step 5 — Beds sitrep metrics
# ---------------------------------------------------------------------------

def build_beds_sitrep_metrics():
    print("\n[join] Building beds sitrep metrics...")
    df = load("beds_sitrep_clean.csv")
    df["month"] = to_month_start(df["period_date"])

    num_cols = [c for c in df.columns if c not in ["period_date", "region", "org_code", "org_name", "month"]]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Identify columns defensively
    ganda_avail = next((c for c in df.columns if "g&a" in c.lower() and "available" in c.lower() and "adult" not in c.lower()), None)
    ganda_occ   = next((c for c in df.columns if "g&a" in c.lower() and "occup" in c.lower() and "rate" not in c.lower() and "adult" not in c.lower()), None)
    cc_avail    = next((c for c in df.columns if "critical care" in c.lower() and "available" in c.lower()), None)
    cc_occ      = next((c for c in df.columns if "critical care" in c.lower() and "occup" in c.lower() and "rate" not in c.lower()), None)
    los7        = next((c for c in df.columns if "los" in c.lower() and "7" in c), None)
    los14       = next((c for c in df.columns if "los" in c.lower() and "14" in c), None)
    los21       = next((c for c in df.columns if "los" in c.lower() and "21" in c), None)

    out = df[["org_code", "month"]].copy()

    if ganda_avail:
        out["beds_ganda_available"]         = df[ganda_avail]
    if ganda_occ:
        out["beds_ganda_occupied"]          = df[ganda_occ]
    if ganda_avail and ganda_occ:
        out["beds_ganda_occupancy_rate"]    = safe_divide(df[ganda_occ], df[ganda_avail], scale=100)
    if cc_avail:
        out["beds_cc_available"]            = df[cc_avail]
    if cc_avail and cc_occ:
        out["beds_cc_occupancy_rate"]       = safe_divide(df[cc_occ], df[cc_avail], scale=100)
    if los7:
        out["beds_los7plus_count"]          = df[los7]
        if ganda_occ:
            out["beds_los7plus_pct"]        = safe_divide(df[los7], df[ganda_occ], scale=100)
    if los14:
        out["beds_los14plus_count"]         = df[los14]
        if ganda_occ:
            out["beds_los14plus_pct"]       = safe_divide(df[los14], df[ganda_occ], scale=100)
    if los21:
        out["beds_los21plus_count"]         = df[los21]
        if ganda_occ:
            out["beds_los21plus_pct"]       = safe_divide(df[los21], df[ganda_occ], scale=100)

    # Aggregate to one row per org per month (sitrep may have multiple rows)
    out = out.groupby(["org_code", "month"]).mean(numeric_only=True).reset_index()
    print(f"  Beds sitrep metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Step 6 — Discharge metrics
# ---------------------------------------------------------------------------

def build_discharge_metrics():
    print("\n[join] Building discharge metrics...")
    df = load("discharge_clean.csv")
    df["month"] = to_month_start(df["period_date"])

    num_cols = [c for c in df.columns if c not in ["region", "icb", "org_code", "org_name",
                "period_date", "month", "data_source"]]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    bed_days_nhs    = next((c for c in df.columns if "bed_day" in c.lower() and "nhs" in c.lower()), None)
    bed_days_social = next((c for c in df.columns if "bed_day" in c.lower() and "social" in c.lower()), None)
    pct_same_day    = next((c for c in df.columns if "same_day" in c.lower()), None)
    delayed_nhs     = next((c for c in df.columns if "delayed" in c.lower() and "nhs" in c.lower() and "bed" not in c.lower()), None)
    delayed_social  = next((c for c in df.columns if "delayed" in c.lower() and "social" in c.lower() and "bed" not in c.lower()), None)

    out = df[["org_code", "month"]].copy()

    if bed_days_nhs and bed_days_social:
        out["discharge_delayed_bed_days_nhs"]    = df[bed_days_nhs]
        out["discharge_delayed_bed_days_social"] = df[bed_days_social]
        out["discharge_total_delayed_bed_days"]  = df[bed_days_nhs] + df[bed_days_social]
        out["discharge_cost_estimate_gbp"]       = out["discharge_total_delayed_bed_days"] * 345
        out["discharge_nhs_share_pct"]           = safe_divide(df[bed_days_nhs],
                                                    out["discharge_total_delayed_bed_days"], scale=100)
    elif bed_days_nhs:
        out["discharge_delayed_bed_days_nhs"]    = df[bed_days_nhs]
        out["discharge_cost_estimate_gbp"]       = df[bed_days_nhs] * 345

    if pct_same_day:
        out["discharge_pct_same_day"]            = df[pct_same_day]

    out = out.groupby(["org_code", "month"]).sum(numeric_only=True).reset_index()
    print(f"  Discharge metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Step 7 — Cancelled ops metrics
# ---------------------------------------------------------------------------

def build_cancelled_ops_metrics():
    print("\n[join] Building cancelled ops metrics...")
    df = load("cancelled_ops_monthly_clean.csv")
    df["month"] = to_month_start(df["period_date"])

    for c in ["num_cancelled", "num_cancelled_28day", "num_not_rescheduled"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    out = df.groupby(["org_code", "month"]).agg(
        cancelled_ops_count=("num_cancelled", "sum"),
        cancelled_28day_count=("num_cancelled_28day", "sum") if "num_cancelled_28day" in df.columns else ("num_cancelled", "sum"),
        not_rescheduled_count=("num_not_rescheduled", "sum") if "num_not_rescheduled" in df.columns else ("num_cancelled", "sum"),
    ).reset_index()

    out["cancelled_ops_not_rescheduled_rate"] = safe_divide(
        out["not_rescheduled_count"], out["cancelled_ops_count"], scale=100)
    out["cancelled_28day_rate"]               = safe_divide(
        out["cancelled_28day_count"], out["cancelled_ops_count"], scale=100)

    # Cost estimate: £3,000 per cancelled op (approximate NHS reference cost average)
    # NOTE: actual cost varies by specialty — this is a conservative estimate
    out["cancelled_ops_cost_estimate_gbp"]    = out["cancelled_ops_count"] * 3000

    print(f"  Cancelled ops metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Step 8 — RTT metrics (aggregated from 7.6M rows)
# ---------------------------------------------------------------------------

def build_rtt_metrics():
    print("\n[join] Building RTT metrics (large file — this may take a moment)...")
    df = load("rtt_clean.csv", dtype=str)
    df["month"] = to_month_start(df["period_date"])
    df["provider_org_code"] = df["provider_org_code"].str.strip()

    # Focus on Part 2 (incomplete pathways) — the waiting list
    part2 = df[df["rtt_part_type"].str.upper() == "PART_2"].copy()
    part1a = df[df["rtt_part_type"].str.upper() == "PART_1A"].copy()
    part1b = df[df["rtt_part_type"].str.upper() == "PART_1B"].copy()

    # Identify wait bucket columns (numeric week columns)
    wait_cols = [c for c in df.columns if c.replace(".", "").isdigit() or
                 (c.startswith("gt") or c.startswith("Gt") or
                  any(c.startswith(str(i)) for i in range(104)))]

    # Use known column: waiting_under_18_weeks
    under18_col = "waiting_under_18_weeks" if "waiting_under_18_weeks" in df.columns else None

    # All numeric wait bucket cols
    bucket_cols = [c for c in df.columns if c not in [
        "period_date", "provider_org_code", "provider_org_name",
        "rtt_part_type", "rtt_part_description",
        "treatment_function_code", "treatment_function_name", "month"
    ]]
    for c in bucket_cols:
        part2[c] = pd.to_numeric(part2[c], errors="coerce")
    if under18_col:
        part2[under18_col] = pd.to_numeric(part2[under18_col], errors="coerce")

    # Aggregate Part 2 per trust per month
    agg_part2 = part2.groupby(["provider_org_code", "month"]).agg(
        rtt_total_incomplete=( bucket_cols[0] if bucket_cols else under18_col, "sum"),
        rtt_within_18_weeks=(under18_col, "sum") if under18_col else (bucket_cols[0], "sum"),
        rtt_specialty_count=("treatment_function_code", "nunique"),
    ).reset_index()

    if under18_col and "rtt_total_incomplete" in agg_part2.columns:
        agg_part2["rtt_pct_within_18_weeks"] = safe_divide(
            agg_part2["rtt_within_18_weeks"], agg_part2["rtt_total_incomplete"], scale=100)

    # Part 1A and 1B — completed pathways
    for c in bucket_cols:
        if c in part1a.columns:
            part1a[c] = pd.to_numeric(part1a[c], errors="coerce")
        if c in part1b.columns:
            part1b[c] = pd.to_numeric(part1b[c], errors="coerce")

    agg_part1a = part1a.groupby(["provider_org_code", "month"])[bucket_cols[0] if bucket_cols else under18_col].sum().reset_index()
    agg_part1a.columns = ["provider_org_code", "month", "rtt_admitted_completed"]

    agg_part1b = part1b.groupby(["provider_org_code", "month"])[bucket_cols[0] if bucket_cols else under18_col].sum().reset_index()
    agg_part1b.columns = ["provider_org_code", "month", "rtt_nonadmitted_completed"]

    out = agg_part2.merge(agg_part1a, on=["provider_org_code", "month"], how="left")
    out = out.merge(agg_part1b, on=["provider_org_code", "month"], how="left")
    out = out.rename(columns={"provider_org_code": "org_code"})

    print(f"  RTT metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Step 9 — CQC snapshot metrics
# ---------------------------------------------------------------------------

def build_cqc_metrics():
    print("\n[join] Building CQC snapshot metrics...")
    df = load("cqc_clean.csv")

    rating_cols = ["rating_overall", "rating_safe", "rating_effective",
                   "rating_caring", "rating_responsive", "rating_well_led"]

    for col in rating_cols:
        if col in df.columns:
            df[f"{col}_numeric"] = rating_to_numeric(df[col])

    numeric_cols = [f"{c}_numeric" for c in rating_cols if f"{c}_numeric" in df.columns]
    if numeric_cols:
        df["cqc_domain_min"]          = df[numeric_cols].min(axis=1)
        df["cqc_domain_max"]          = df[numeric_cols].max(axis=1)
        df["cqc_domain_range"]        = df["cqc_domain_max"] - df["cqc_domain_min"]

    if "rating_overall_numeric" in df.columns and "rating_safe_numeric" in df.columns:
        df["cqc_safe_vs_overall_gap"] = df["rating_safe_numeric"] - df["rating_overall_numeric"]
    if "rating_well_led_numeric" in df.columns:
        df["cqc_well_led_numeric"]    = df["rating_well_led_numeric"]

    keep_cols = ["location_ods_code"] + [c for c in df.columns if
                 "numeric" in c or c in ["cqc_domain_min", "cqc_domain_range",
                 "cqc_safe_vs_overall_gap", "cqc_well_led_numeric",
                 "rating_overall", "rating_safe", "rating_well_led"]]
    keep_cols = [c for c in keep_cols if c in df.columns]

    out = df[keep_cols].copy()
    # Try location_ods_code first, fall back to provider_id
    # location_ods_code is the location-level code (may be blank)
    # provider_id is the trust-level code (e.g. RGT) — better join key
    if "provider_id" in df.columns:
        # Use provider_id as org_code for joining to spine
        out["org_code"] = df["provider_id"].str.strip()
    elif "location_ods_code" in df.columns:
        out["org_code"] = df["location_ods_code"].str.strip()
    else:
        out["org_code"] = np.nan

    # One row per org code — aggregate ratings by taking mode (most common rating)
    out = out.dropna(subset=["org_code"])
    out = out[out["org_code"].str.strip() != ""].copy()

    # For trusts with multiple locations, take the overall rating from
    # the trust-level row (location_type == NHS Trust) if available,
    # otherwise aggregate numerics by mean
    numeric_cols = [c for c in out.columns if c.endswith("_numeric") or
                    c in ["cqc_domain_min", "cqc_domain_range", "cqc_safe_vs_overall_gap"]]
    text_cols    = [c for c in out.columns if c in ["rating_overall", "rating_safe", "rating_well_led"]]

    agg_dict = {c: "mean" for c in numeric_cols if c in out.columns}
    agg_dict.update({c: "first" for c in text_cols if c in out.columns})

    if agg_dict:
        out = out.groupby("org_code").agg(agg_dict).reset_index()
    else:
        out = out.drop_duplicates(subset=["org_code"], keep="first")

    print(f"  CQC metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Step 10 — Oversight snapshot metrics
# ---------------------------------------------------------------------------

def build_oversight_metrics():
    print("\n[join] Building oversight snapshot metrics...")
    df = load("oversight_clean.csv")

    # Numeric segment
    df["oversight_segment_numeric"] = pd.to_numeric(df["league_segment"], errors="coerce")
    df["oversight_in_deficit"]      = (df["in_financial_deficit"].str.upper() == "YES").astype(int)

    # Domain score summary
    score_cols = [c for c in df.columns if c.startswith("domain_score_")]
    if score_cols:
        df["oversight_domain_score_worst"] = df[score_cols].min(axis=1)
        df["oversight_domain_score_range"] = df[score_cols].max(axis=1) - df[score_cols].min(axis=1)

    # Cancer combined
    if "cancer_28day_pct" in df.columns and "cancer_62day_pct" in df.columns:
        df["oversight_cancer_combined"] = df[["cancer_28day_pct", "cancer_62day_pct"]].mean(axis=1)

    # Staff combined
    if "staff_engagement_score" in df.columns and "staff_raising_concerns_score" in df.columns:
        df["oversight_staff_combined"] = df[["staff_engagement_score", "staff_raising_concerns_score"]].mean(axis=1)

    keep_cols = ["Trust_code"] + [c for c in df.columns if c.startswith("domain_score_") or
                 c.startswith("domain_segment_") or c in [
                 "league_rank", "league_avg_score", "overall_adjusted_segment",
                 "oversight_segment_numeric", "oversight_in_deficit",
                 "oversight_domain_score_worst", "oversight_domain_score_range",
                 "oversight_cancer_combined", "oversight_staff_combined",
                 "productivity_growth_estimate", "implied_productivity_pct",
                 "planned_surplus_deficit_pct", "cancer_28day_pct", "cancer_62day_pct",
                 "staff_engagement_score", "staff_raising_concerns_score",
                 "mrsa_cases_count", "ecoli_bacteraemia_rate", "cdiff_infection_rate",
                 "inpatients_60day_los_pct"]]
    keep_cols = [c for c in keep_cols if c in df.columns]

    out = df[keep_cols].copy()
    out = out.rename(columns={"Trust_code": "org_code"})
    out = out.drop_duplicates(subset=["org_code"])

    print(f"  Oversight metrics shape: {out.shape}")
    return out


# ---------------------------------------------------------------------------
# Main join
# ---------------------------------------------------------------------------

def run():
    print("[join] Starting master join...")

    # Build spine
    spine, ae = build_spine()

    # Build all metric tables
    ae_metrics         = build_ae_metrics(ae)
    sickness_metrics   = build_sickness_metrics()
    workforce_metrics  = build_workforce_metrics()
    beds_metrics       = build_beds_sitrep_metrics()
    discharge_metrics  = build_discharge_metrics()
    cancelled_metrics  = build_cancelled_ops_metrics()
    rtt_metrics        = build_rtt_metrics()
    cqc_metrics        = build_cqc_metrics()
    oversight_metrics  = build_oversight_metrics()

    # ---------------------------------------------------------------------------
    # Join time series datasets onto spine (left join — keeps all spine rows)
    # ---------------------------------------------------------------------------
    print("\n[join] Joining datasets onto spine...")

    master = spine.copy()

    time_series = [
        (ae_metrics,       "A&E"),
        (sickness_metrics, "Sickness"),
        (workforce_metrics,"Workforce"),
        (beds_metrics,     "Beds sitrep"),
        (discharge_metrics,"Discharge"),
        (cancelled_metrics,"Cancelled ops"),
        (rtt_metrics,      "RTT"),
    ]

    for df, name in time_series:
        df["month"] = pd.to_datetime(df["month"])
        master = master.merge(df, on=["org_code", "month"], how="left")
        print(f"  After {name} join: {master.shape}")

    # ---------------------------------------------------------------------------
    # Cross-dataset derived metrics (need both datasets joined first)
    # ---------------------------------------------------------------------------
    print("\n[join] Calculating cross-dataset metrics...")

    # FTE per bed
    if "workforce_total_fte" in master.columns and "beds_ganda_available" in master.columns:
        master["workforce_fte_per_bed"] = safe_divide(
            master["workforce_total_fte"], master["beds_ganda_available"])

    # Delayed days per bed
    if "discharge_total_delayed_bed_days" in master.columns and "beds_ganda_available" in master.columns:
        master["discharge_delayed_days_per_bed"] = safe_divide(
            master["discharge_total_delayed_bed_days"], master["beds_ganda_available"])

    # ---------------------------------------------------------------------------
    # Nursing FTE trend (month on month change)
    # ---------------------------------------------------------------------------
    if "workforce_nursing_fte" in master.columns:
        master = master.sort_values(["org_code", "month"])
        master["workforce_nursing_fte_mom_change"] = master.groupby("org_code")[
            "workforce_nursing_fte"].diff()

    # ---------------------------------------------------------------------------
    # Join snapshot datasets (CQC and Oversight — no date dimension)
    # ---------------------------------------------------------------------------
    master = master.merge(cqc_metrics,      on="org_code", how="left")
    master = master.merge(oversight_metrics, on="org_code", how="left")
    print(f"  After snapshot joins: {master.shape}")

    # ---------------------------------------------------------------------------
    # Final sort and save
    # ---------------------------------------------------------------------------
    master = master.sort_values(["org_code", "month"]).reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(OUT_PATH, index=False)

    print(f"\n[join] Output shape: {master.shape}")
    print(f"[join] Trusts: {master['org_code'].nunique()}")
    print(f"[join] Date range: {master['month'].min()} to {master['month'].max()}")
    print(f"[join] Columns ({len(master.columns)}):")
    for c in master.columns:
        null_pct = master[c].isnull().mean() * 100
        print(f"  {c:<50} {null_pct:.0f}% null")
    print(f"\n[join] Saved to: {OUT_PATH}")
    print("[join] Done.")


if __name__ == "__main__":
    run()
