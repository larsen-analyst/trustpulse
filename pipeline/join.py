"""
pipeline/join.py
TrustPulse -- Master join script
Builds trust_master.csv (time series) and trust_profiles.csv (latest snapshot)
"""

import os
import re
import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR       = Path(__file__).resolve().parent.parent
PROCESSED_DIR  = BASE_DIR / "data" / "processed"
DATA_DIR       = PROCESSED_DIR   # alias used by build functions

AE_PATH              = DATA_DIR / "ae_clean.csv"
SICKNESS_PATH        = DATA_DIR / "sickness_trust_clean.csv"
RTT_PATH             = DATA_DIR / "rtt_clean.csv"
WORKFORCE_PATH       = DATA_DIR / "workforce_clean.csv"
BEDS_SITREP_PATH     = DATA_DIR / "beds_sitrep_clean.csv"
DISCHARGE_PATH       = DATA_DIR / "discharge_clean.csv"
CANCELLED_OPS_PATH   = DATA_DIR / "cancelled_ops_monthly_clean.csv"
CQC_PATH             = DATA_DIR / "cqc_clean.csv"
OVERSIGHT_PATH       = DATA_DIR / "oversight_clean.csv"
VACANCIES_PATH       = DATA_DIR / "vacancies_clean.csv"
STAFF_SURVEY_PATH    = DATA_DIR / "staff_survey_clean.csv"
FINANCE_PATH         = DATA_DIR / "finance_clean.csv"
AMBULANCE_PATH       = DATA_DIR / "ambulance_clean.csv"

MASTER_OUT   = DATA_DIR / "trust_master.csv"
PROFILES_OUT = DATA_DIR / "trust_profiles.csv"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_divide(num, den):
    return num / den.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Build functions -- time series
# ---------------------------------------------------------------------------

def build_spine():
    """Build the trust-month spine from A&E data (the most complete time series)."""
    ae = pd.read_csv(AE_PATH, parse_dates=["period_date"])
    ae = ae.rename(columns={"period_date": "month"})
    ae["month"] = ae["month"].dt.to_period("M").dt.to_timestamp()
    spine = ae[["org_code", "month"]].drop_duplicates().copy()
    spine = spine.sort_values(["org_code", "month"]).reset_index(drop=True)
    print(f"  Spine       : {len(spine):,} rows | "
          f"{spine['org_code'].nunique()} trusts | "
          f"{spine['month'].min().date()} to {spine['month'].max().date()}")
    return spine, ae


def build_ae_metrics(ae):
    ae = ae.copy()
    ae["month"] = pd.to_datetime(ae["month"]).dt.to_period("M").dt.to_timestamp()

    # Rename columns to ae_ prefix where needed
    col_map = {c: f"ae_{c}" for c in ae.columns if c not in ("org_code", "month", "org_name")}
    ae = ae.rename(columns=col_map)

    # Core performance metrics
    if "ae_type1_att" in ae.columns and "ae_type1_4hr_breaches" in ae.columns:
        ae["ae_type1_4hr_performance"] = 1 - safe_divide(
            ae["ae_type1_4hr_breaches"], ae["ae_type1_att"])

    if "ae_total_att" in ae.columns and "ae_total_4hr_breaches" in ae.columns:
        ae["ae_total_4hr_performance"] = 1 - safe_divide(
            ae["ae_total_4hr_breaches"], ae["ae_total_att"])

    if "ae_type1_att" in ae.columns and "ae_total_att" in ae.columns:
        ae["ae_type1_share"] = safe_divide(ae["ae_type1_att"], ae["ae_total_att"])

    print(f"  A&E metrics : {ae.shape}")
    return ae


def build_sickness_metrics():
    df = pd.read_csv(SICKNESS_PATH, parse_dates=["date"], dayfirst=True)
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()

    # Aggregate to one row per org per month
    agg = df.groupby(["org_code", "month"]).agg(
        sickness_rate_overall    = ("sickness_absence_rate_percent", "mean"),
        sickness_fte_days_lost   = ("fte_days_lost", "sum"),
        sickness_fte_days_avail  = ("fte_days_available", "sum"),
    ).reset_index()

    # Reason-specific rates (columns may not exist -- guard each one)
    for reason_col in ["sickness_rate_anxiety", "sickness_rate_back",
                       "sickness_rate_musculoskeletal", "sickness_rate_infectious"]:
        if reason_col in df.columns:
            r = df.groupby(["org_code", "month"])[reason_col].mean().reset_index()
            agg = agg.merge(r, on=["org_code", "month"], how="left")

    print(f"  Sickness    : {agg.shape}")
    return agg


def build_workforce_metrics():
    df = pd.read_csv(WORKFORCE_PATH, parse_dates=["period_date"])
    df["month"] = df["period_date"].dt.to_period("M").dt.to_timestamp()

    # Pivot to wide: total FTE, nursing FTE, medical FTE
    fte = df[df["data_type"] == "FTE"].copy()

    def agg_group(group_label, col_name):
        sub = fte[fte["staff_group"].str.contains(group_label, case=False, na=False)]
        if sub.empty:
            return pd.DataFrame(columns=["org_code", "month", col_name])
        return sub.groupby(["org_code", "month"])["total"].sum().reset_index().rename(
            columns={"total": col_name})

    total   = agg_group("Total",            "workforce_total_fte")
    nursing = agg_group("Nurses",           "workforce_nursing_fte")
    medical = agg_group("Doctors",          "workforce_medical_fte")

    out = total.merge(nursing, on=["org_code","month"], how="outer") \
               .merge(medical, on=["org_code","month"], how="outer")

    print(f"  Workforce   : {out.shape}")
    return out


def build_beds_sitrep_metrics():
    df = pd.read_csv(BEDS_SITREP_PATH, parse_dates=["period_date"])
    df["month"] = df["period_date"].dt.to_period("M").dt.to_timestamp()

    agg = df.groupby(["org_code", "month"]).agg(
        beds_ganda_available = ("G&A beds available", "mean"),
        beds_ganda_occupied  = ("G&A beds occupied",  "mean"),
    ).reset_index()

    agg["beds_occupancy_rate"] = safe_divide(
        agg["beds_ganda_occupied"], agg["beds_ganda_available"])

    print(f"  Beds sitrep : {agg.shape}")
    return agg


def build_discharge_metrics():
    df = pd.read_csv(DISCHARGE_PATH, parse_dates=["period_date"])
    df["month"] = df["period_date"].dt.to_period("M").dt.to_timestamp()

    drop = [c for c in ("period_date", "org_name", "region", "icb",
                        "data_source", "num_providers_submitting",
                        "pct_providers_submitting") if c in df.columns]
    df = df.drop(columns=drop).copy()

    num_cols = [c for c in df.columns if c not in ("org_code", "month")]
    agg = df.groupby(["org_code", "month"])[num_cols].sum().reset_index()

    # Rename to standard key used in cost estimates downstream
    if "total_bed_days_lost" in agg.columns:
        agg = agg.rename(columns={"total_bed_days_lost": "discharge_total_delayed_bed_days"})

    print(f"  Discharge   : {agg.shape}")
    return agg


def build_cancelled_ops_metrics():
    df = pd.read_csv(CANCELLED_OPS_PATH, parse_dates=["period_date"])
    df["month"] = df["period_date"].dt.to_period("M").dt.to_timestamp()

    drop = [c for c in ("period_date", "org_name", "parent_name", "parent_org_code",
                        "nhs_year", "period_name", "data_source") if c in df.columns]
    df = df.drop(columns=drop).copy()

    num_cols = [c for c in df.columns if c not in ("org_code", "month")]
    agg = df.groupby(["org_code", "month"])[num_cols].sum().reset_index()

    print(f"  Cancelled   : {agg.shape}")
    return agg


def build_rtt_metrics():
    df = pd.read_csv(RTT_PATH, parse_dates=["period_date"])
    df["month"] = df["period_date"].dt.to_period("M").dt.to_timestamp()

    # RTT uses provider_org_code as the trust identifier
    if "provider_org_code" in df.columns:
        df = df.rename(columns={"provider_org_code": "org_code"})

    drop = [c for c in ("period_date", "provider_org_name", "rtt_part_description",
                        "treatment_function_name") if c in df.columns]
    df = df.drop(columns=drop).copy()

    num_cols = [c for c in df.columns if c not in ("org_code", "month",
                "rtt_part_type", "treatment_function_code")]
    agg = df.groupby(["org_code", "month"])[num_cols].sum().reset_index()

    print(f"  RTT         : {agg.shape}")
    return agg


# ---------------------------------------------------------------------------
# Build functions -- snapshot (no date dimension)
# ---------------------------------------------------------------------------

def build_cqc_metrics():
    df = pd.read_csv(CQC_PATH)
    keep_cols = ["provider_id"] + [c for c in df.columns if c not in
                 ("provider_id", "location_ods_code", "location_name",
                  "location_type", "location_status")]
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    df = df.rename(columns={"provider_id": "org_code"})
    df = df.drop_duplicates(subset=["org_code"])
    print(f"  CQC         : {df.shape}")
    return df


def build_oversight_metrics():
    df = pd.read_csv(OVERSIGHT_PATH)
    keep_cols = [c for c in df.columns if c not in
                 ("Trust_name", "ICB_name", "Region_name")]
    df = df[keep_cols].copy()
    df = df.rename(columns={"Trust_code": "org_code"})
    df = df.drop_duplicates(subset=["org_code"])
    print(f"  Oversight   : {df.shape}")
    return df


def build_staff_survey_metrics():
    """
    Load staff_survey_clean.csv and return one row per trust (most recent year).
    Join key: org_code (snapshot, no date dimension in the master join).
    """
    if not STAFF_SURVEY_PATH.exists():
        print("  [WARNING] staff_survey_clean.csv not found -- skipping")
        return pd.DataFrame(columns=["org_code"])

    df = pd.read_csv(STAFF_SURVEY_PATH)

    # Keep most recent year per trust
    if "year" in df.columns:
        df = df.sort_values("year", ascending=False)
        df = df.drop_duplicates(subset=["org_code"], keep="first")

    # Drop columns that shouldn't be in master
    drop_cols = [c for c in ("year", "org_name", "org_type", "region") if c in df.columns]
    df = df.drop(columns=drop_cols, errors="ignore")

    print(f"  Staff survey: {df.shape}")
    return df


def build_vacancy_metrics():
    """
    Load vacancies_clean.csv and return regional benchmark rates per org_code.
    Vacancy data is regional only (no trust-level data exists publicly).

    Join strategy: oversight file maps org_code -> NHS England region name.
    Vacancy file uses the same region name values. We resolve to org_code so
    the join in run() is a simple left join on org_code (no separate region bridge needed).
    """
    if not VACANCIES_PATH.exists():
        print("  [WARNING] vacancies_clean.csv not found -- skipping vacancy benchmarks")
        return pd.DataFrame(columns=["org_code"])
    if not OVERSIGHT_PATH.exists():
        print("  [WARNING] oversight_clean.csv not found -- cannot build vacancy region bridge")
        return pd.DataFrame(columns=["org_code"])

    vac = pd.read_csv(VACANCIES_PATH, parse_dates=["quarter_date"])
    oversight = pd.read_csv(OVERSIGHT_PATH)

    # Identify region and org_code columns in oversight (tolerant of name variants)
    region_col = next((c for c in oversight.columns
                       if c.lower() in ("region", "region_name", "nhse_region")), None)
    code_col   = next((c for c in oversight.columns
                       if c.lower() in ("trust_code", "org_code", "provider_code")), None)

    if region_col is None or code_col is None:
        print(f"  [WARNING] Cannot find region/code cols in oversight -- skipping vacancies")
        return pd.DataFrame(columns=["org_code"])

    org_region = (oversight[[code_col, region_col]]
                  .rename(columns={code_col: "org_code", region_col: "vac_region"})
                  .drop_duplicates(subset=["org_code"]))

    # Keep most recent quarter per region/sector/staff_group/data_type
    vac = vac.sort_values("quarter_date", ascending=False)
    vac = vac.drop_duplicates(
        subset=["region", "sector", "staff_group", "data_type"], keep="first")

    # Acute, all staff, vacancy rate
    rate_all = (
        vac[(vac["sector"] == "Acute") &
            (vac["staff_group"] == "All staff") &
            (vac["data_type"] == "vacancy_rate_pct")]
        [["region", "value"]]
        .rename(columns={"value": "vac_benchmark_rate_all_pct"})
    )

    # Acute, nursing, vacancy rate
    rate_nursing = (
        vac[(vac["sector"] == "Acute") &
            (vac["staff_group"] == "Nursing and midwifery") &
            (vac["data_type"] == "vacancy_rate_pct")]
        [["region", "value"]]
        .rename(columns={"value": "vac_benchmark_rate_nursing_pct"})
    )

    region_benchmarks = rate_all.merge(rate_nursing, on="region", how="outer")

    # Resolve to org_code level
    out = (org_region
           .merge(region_benchmarks, left_on="vac_region", right_on="region", how="left")
           .drop(columns=["region"], errors="ignore"))

    matched = out["vac_benchmark_rate_all_pct"].notna().sum()
    print(f"  Vacancies   : {len(out)} orgs | {matched} with benchmark rates")
    return out


def _clean_ocr_trust_name(name: str) -> str:
    """
    Remove spaces inserted mid-word by Tesseract OCR on the finance PDF.
    Strategy: collapse any space between two lowercase/mixed-case fragments
    that are not natural word boundaries (i.e. not preceded/followed by
    known suffix tokens).
    """
    import re as _re
    if not isinstance(name, str):
        return name
    # Remove stray pipe/currency characters
    name = _re.sub(r"[|]", "", name).strip()
    # Collapse spaces inside words: e.g. "Liverp ool" -> "Liverpool"
    # A space is spurious if the preceding fragment ends with a lowercase letter
    # and the following fragment starts with a lowercase letter
    name = _re.sub(r"(?<=[a-z])\s+(?=[a-z])", "", name)
    # Also handle: "Childr en" -> "Children" (lowercase then lowercase after space)
    # And: "Hospit al" -> "Hospital"
    # Already handled above. Now normalise multiple spaces.
    name = _re.sub(r"\s+", " ", name).strip()
    return name


def build_finance_metrics():
    """
    Load finance_clean.csv, clean OCR-broken trust names, fuzzy-match to
    org_codes using the AE spine, and return one row per trust.

    The finance PDF was OCR'd with Tesseract which inserts spurious spaces
    mid-word. Names are cleaned before matching.

    Join key: org_code (resolved via fuzzy match to AE org_name).
    Snapshot join -- no date dimension.
    """
    if not FINANCE_PATH.exists():
        print("  [WARNING] finance_clean.csv not found -- skipping finance join")
        return pd.DataFrame(columns=["org_code"])
    if not AE_PATH.exists():
        print("  [WARNING] ae_clean.csv not found -- cannot build org_code lookup for finance")
        return pd.DataFrame(columns=["org_code"])

    from rapidfuzz import process as fuzz_process, fuzz

    df = pd.read_csv(FINANCE_PATH)

    # Provider rows only -- exclude ICB and total rows
    df = df[df["row_type"] == "provider"].copy()
    if df.empty:
        print("  [WARNING] No provider rows in finance_clean.csv")
        return pd.DataFrame(columns=["org_code"])

    # Clean OCR-broken names
    df["trust_name_clean"] = df["trust_name"].apply(_clean_ocr_trust_name)

    # Build org_code -> trust_name lookup from oversight (proper NHS trust names)
    oversight_ref = pd.read_csv(OVERSIGHT_PATH, usecols=["Trust_code", "Trust_name"]).drop_duplicates()
    oversight_ref = oversight_ref.dropna(subset=["Trust_name"])
    name_to_code = dict(zip(oversight_ref["Trust_name"].str.strip(), oversight_ref["Trust_code"]))
    choices = list(name_to_code.keys())

    # Fuzzy match each finance trust name to the AE reference list
    matched_codes = []
    scores = []
    for name in df["trust_name_clean"]:
        result = fuzz_process.extractOne(
            name, choices, scorer=fuzz.token_sort_ratio, score_cutoff=60)
        if result:
            matched_codes.append(name_to_code[result[0]])
            scores.append(result[1])
        else:
            matched_codes.append(None)
            scores.append(0)

    df["org_code"] = matched_codes
    df["_match_score"] = scores

    n_matched = df["org_code"].notna().sum()
    n_low = (df["_match_score"] < 75).sum()
    print(f"  Finance     : {len(df)} provider rows | "
          f"{n_matched} matched to org_code | "
          f"{n_low} low-confidence matches (<75)")

    # Drop rows with no match
    df = df.dropna(subset=["org_code"]).copy()

    # Prefix metric cols with fin_
    id_cols = {"org_code", "trust_name", "trust_name_clean", "_match_score", "row_type"}
    rename = {c: f"fin_{c}" for c in df.columns
              if c not in id_cols and not c.startswith("fin_")}
    df = df.rename(columns=rename)

    # One row per org_code -- keep highest match score if duplicates
    df = df.sort_values("_match_score", ascending=False)
    df = df.drop_duplicates(subset=["org_code"], keep="first")

    drop_cols = [c for c in ("trust_name", "trust_name_clean", "_match_score",
                             "row_type") if c in df.columns]
    df = df.drop(columns=drop_cols, errors="ignore")

    return df


def build_ambulance_metrics():
    """
    Load ambulance_clean.csv and return monthly trust-level metrics.

    Coverage: Nov 2025 to Mar 2026 (5 months, 148 trusts).
    ~80% of rows in trust_master will be null for these columns -- expected and correct.
    The columns are still used for the Flask trust profile pages and winter outlier analysis.
    Join key: org_code + date (renamed to month before merging).
    """
    if not AMBULANCE_PATH.exists():
        print("  [WARNING] ambulance_clean.csv not found -- skipping ambulance join")
        return pd.DataFrame(columns=["org_code", "date"])

    amb = pd.read_csv(AMBULANCE_PATH, parse_dates=["date"])

    keep = [
        "org_code",
        "date",
        "amb_handovers_total",
        "amb_handovers_known",
        "amb_over15_count",
        "amb_over30_count",
        "amb_over60_count",
        "amb_over15_pct",
        "amb_over30_pct",
        "amb_over60_pct",
    ]
    amb = amb[[c for c in keep if c in amb.columns]].copy()

    # Normalise date to first of month (defensive -- should already be)
    amb["date"] = amb["date"].dt.to_period("M").dt.to_timestamp()

    print(f"  Ambulance   : {len(amb):,} rows | "
          f"{amb['org_code'].nunique()} trusts | "
          f"{amb['date'].min().date()} to {amb['date'].max().date()}")
    return amb


# ---------------------------------------------------------------------------
# Main join
# ---------------------------------------------------------------------------

def run():
    print("[join] Starting master join...")

    # Build spine
    spine, ae = build_spine()

    # Build all metric tables
    print("\n[join] Building metric tables...")
    ae_metrics         = build_ae_metrics(ae)
    sickness_metrics   = build_sickness_metrics()
    workforce_metrics  = build_workforce_metrics()
    beds_metrics       = build_beds_sitrep_metrics()
    discharge_metrics  = build_discharge_metrics()
    cancelled_metrics  = build_cancelled_ops_metrics()
    rtt_metrics        = build_rtt_metrics()
    cqc_metrics        = build_cqc_metrics()
    oversight_metrics  = build_oversight_metrics()
    staff_survey_metrics = build_staff_survey_metrics()
    vacancy_metrics    = build_vacancy_metrics()
    finance_metrics    = build_finance_metrics()
    ambulance_metrics  = build_ambulance_metrics()

    # ---------------------------------------------------------------------------
    # Join time series datasets onto spine (left join -- keeps all spine rows)
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

    # --- Ambulance handover delays (Nov 2025 - Mar 2026 only) ---
    if not ambulance_metrics.empty and "date" in ambulance_metrics.columns:
        ambulance_metrics = ambulance_metrics.rename(columns={"date": "month"})
        ambulance_metrics["month"] = pd.to_datetime(ambulance_metrics["month"])
        master = master.merge(ambulance_metrics, on=["org_code", "month"], how="left")
        print(f"  After Ambulance join: {master.shape}")

    # ---------------------------------------------------------------------------
    # Cross-dataset derived metrics (need both datasets joined first)
    # ---------------------------------------------------------------------------
    print("\n[join] Calculating cross-dataset metrics...")

    # FTE per bed
    if "workforce_total_fte" in master.columns and "beds_ganda_available" in master.columns:
        master["workforce_fte_per_bed"] = safe_divide(
            master["workforce_total_fte"], master["beds_ganda_available"])

    # Delayed days per bed
    if "discharge_total_delayed_bed_days" in master.columns and \
       "beds_ganda_available" in master.columns:
        master["discharge_delayed_days_per_bed"] = safe_divide(
            master["discharge_total_delayed_bed_days"], master["beds_ganda_available"])

    # Nursing FTE trend (month on month change)
    if "workforce_nursing_fte" in master.columns:
        master = master.sort_values(["org_code", "month"])
        master["workforce_nursing_fte_mom_change"] = master.groupby("org_code")[
            "workforce_nursing_fte"].diff()

    # ---------------------------------------------------------------------------
    # Join snapshot datasets
    # ---------------------------------------------------------------------------
    print("\n[join] Joining snapshot datasets...")

    master = master.merge(cqc_metrics,       on="org_code", how="left")
    master = master.merge(oversight_metrics,  on="org_code", how="left")
    master = master.merge(staff_survey_metrics, on="org_code", how="left")
    master = master.merge(finance_metrics,    on="org_code", how="left")
    print(f"  After snapshot joins: {master.shape}")

    # Join vacancy benchmarks on org_code (already resolved from region in build function)
    if not vacancy_metrics.empty and "org_code" in vacancy_metrics.columns:
        master = master.merge(vacancy_metrics, on="org_code", how="left")
    print(f"  After vacancy join: {master.shape}")

    # ---------------------------------------------------------------------------
    # Financial cost estimates
    # ---------------------------------------------------------------------------
    print("\n[join] Calculating financial cost estimates...")

    # Delayed discharge cost: £345 per delayed bed day (NHS England published rate)
    if "discharge_total_delayed_bed_days" in master.columns:
        master["fin_est_delayed_discharge_cost_gbp"] = \
            master["discharge_total_delayed_bed_days"] * 345

    # Cancelled operations cost: £3,000 per cancelled op (conservative average)
    if "num_cancelled" in master.columns:
        master["fin_est_cancelled_ops_cost_gbp"] = master["num_cancelled"] * 3000

    # Sickness cost: £200 per FTE day lost
    if "sickness_fte_days_lost" in master.columns:
        master["fin_est_sickness_cost_gbp"] = master["sickness_fte_days_lost"] * 200

    # Total estimated monthly inefficiency cost
    cost_cols = [c for c in master.columns if c.startswith("fin_est_") and
                 c.endswith("_cost_gbp")]
    if cost_cols:
        master["fin_est_total_inefficiency_cost_gbp"] = master[cost_cols].sum(axis=1, skipna=True)

    # ---------------------------------------------------------------------------
    # Final sort and save trust_master.csv
    # ---------------------------------------------------------------------------
    master = master.sort_values(["org_code", "month"]).reset_index(drop=True)

    MASTER_OUT.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(MASTER_OUT, index=False)

    print(f"\n[join] trust_master.csv saved")
    print(f"  Shape   : {master.shape}")
    print(f"  Trusts  : {master['org_code'].nunique()}")
    print(f"  Dates   : {master['month'].min().date()} to {master['month'].max().date()}")

    # ---------------------------------------------------------------------------
    # Build trust_profiles.csv -- one row per trust, latest month snapshot
    # ---------------------------------------------------------------------------
    print("\n[join] Building trust_profiles.csv...")

    profiles = master.sort_values("month").groupby("org_code").last().reset_index()

    # Rolling averages: 3-month and prior 3-month for key metrics
    key_metrics = [
        "ae_type1_4hr_performance", "ae_total_4hr_performance",
        "sickness_rate_overall", "sickness_fte_days_lost",
        "workforce_total_fte", "workforce_nursing_fte",
        "beds_occupancy_rate", "discharge_total_delayed_bed_days",
        "fin_est_total_inefficiency_cost_gbp",
    ]

    master_sorted = master.sort_values(["org_code", "month"])

    for metric in key_metrics:
        if metric not in master.columns:
            continue
        roll = master_sorted.groupby("org_code")[metric].apply(
            lambda x: x.rolling(3, min_periods=1).mean().iloc[-1]
            if len(x) >= 1 else np.nan
        ).reset_index(name=f"{metric}_3m_avg")
        profiles = profiles.merge(roll, on="org_code", how="left")

        prior = master_sorted.groupby("org_code")[metric].apply(
            lambda x: x.iloc[-6:-3].mean() if len(x) >= 4 else np.nan
        ).reset_index(name=f"{metric}_prior3m_avg")
        profiles = profiles.merge(prior, on="org_code", how="left")

    # Trend direction
    for metric in key_metrics:
        col_now   = f"{metric}_3m_avg"
        col_prior = f"{metric}_prior3m_avg"
        if col_now in profiles.columns and col_prior in profiles.columns:
            def trend(row):
                n, p = row[col_now], row[col_prior]
                if pd.isna(n) or pd.isna(p):
                    return "Insufficient Data"
                diff_pct = abs(n - p) / (abs(p) + 1e-9)
                if diff_pct < 0.02:
                    return "Stable"
                # For sickness and discharge, lower is better
                if "sickness" in metric or "discharge" in metric or "cancelled" in metric:
                    return "Improving" if n < p else "Deteriorating"
                return "Improving" if n > p else "Deteriorating"
            profiles[f"{metric}_trend"] = profiles.apply(trend, axis=1)

    PROFILES_OUT.parent.mkdir(parents=True, exist_ok=True)
    profiles.to_csv(PROFILES_OUT, index=False)

    print(f"[join] trust_profiles.csv saved")
    print(f"  Shape   : {profiles.shape}")
    print(f"  Trusts  : {profiles['org_code'].nunique()}")

    # Column null report
    print(f"\n[join] Column null summary (master):")
    for c in master.columns:
        null_pct = master[c].isnull().mean() * 100
        print(f"  {c:<55} {null_pct:.0f}% null")

    print("\n[join] Done.")


if __name__ == "__main__":
    run()
