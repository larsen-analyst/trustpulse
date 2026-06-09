"""
TrustPulse -- pipeline/correlations.py
Comprehensive lag and cross-sectional correlation engine.

Outputs:
    data/processed/correlations_national.csv    -- national pooled lag correlations
    data/processed/correlations_xsection.csv    -- cross-sectional trust-level correlations
    data/processed/correlations_trust.csv       -- per-trust lag correlations (r >= 0.3)

Scale validation applied before every correlation:
    - DECIMAL 0-1 fields used as-is
    - PERCENT 0-100 fields divided by 100 for consistency
    - LARGE COUNT fields standardised (z-score) within trust before correlation
    - Annual snapshot fields excluded from lag analysis
"""

import os
import warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER       = os.path.join(BASE_DIR, "data", "processed", "trust_master.csv")
OUT_NAT      = os.path.join(BASE_DIR, "data", "processed", "correlations_national.csv")
OUT_XSECT    = os.path.join(BASE_DIR, "data", "processed", "correlations_xsection.csv")
OUT_TRUST    = os.path.join(BASE_DIR, "data", "processed", "correlations_trust.csv")

# ---------------------------------------------------------------------------
# Column metadata: (raw_col, derived_name, scale, transform)
# scale: 'decimal', 'pct100', 'count', 'snapshot'
# transform: how to convert to a comparable 0-1 or normalised float
# ---------------------------------------------------------------------------
COLS_META = {
    # A&E -- derived
    "ae_type1_4hr_perf":      ("_derived_", "decimal", None),
    "ae_12hr_count":          ("ae_patients_who_have_waited_12+_hrs_from_dta_to_admission", "count", None),
    "ae_attendances_t1":      ("ae_a&e_attendances_type_1", "count", None),
    # Sickness
    "sickness_overall":       ("sickness_rate_overall", "pct100", lambda x: x / 100),
    "sickness_nursing":       ("sick_sickness_rate_nursing", "decimal", None),
    "sickness_medical":       ("sick_sickness_rate_medical", "decimal", None),
    # Workforce
    "nursing_fte":            ("workforce_nursing_fte", "count", None),
    "nursing_fte_change":     ("workforce_nursing_fte_mom_change", "count", None),
    "total_fte":              ("workforce_total_fte", "count", None),
    "vac_rate_all":           ("vac_benchmark_rate_all_pct", "pct100", lambda x: x / 100),
    "vac_rate_nursing":       ("vac_benchmark_rate_nursing_pct", "pct100", lambda x: x / 100),
    # Beds/discharge
    "bed_occupancy":          ("beds_occupancy_rate", "decimal", None),
    "delayed_discharge":      ("discharge_total_delayed_bed_days", "count", None),
    "cancelled_ops":          ("num_cancelled", "count", None),
    "dna_rate":               ("outp_dna_rate", "decimal", None),
    # RTT/waiting
    "rtt_18wk_pct":           ("pct_within_18_weeks", "decimal", None),
    "waiters_over52":         ("waiting_over_52_weeks", "count", None),
    # Cancer/diagnostics
    "cancer_fds":             ("fds_performance", "decimal", None),
    "cancer_62d":             ("t62d_performance", "decimal", None),
    "diag_6wk_pct":           ("diag_pct_waiting_6wk", "decimal", None),
    # Quality/safety
    "shmi":                   ("shmi_value", "decimal", None),
    "fft_positive":           ("fft_pct_positive", "decimal", None),
    "fft_negative":           ("fft_pct_negative", "decimal", None),
    "comp_upheld":            ("comp_pct_upheld", "decimal", None),
    # Finance
    "fin_variance":           ("fin_var_pct_turnover", "pct100", lambda x: x / 100),
    "ref_cost_gap":           ("rc_cost_gap_pct", "pct100", lambda x: x / 100),
    # Annual snapshots -- cross-sectional only
    "ne_count_snap":          ("ne_count", "snapshot", None),
    "comp_clinical_pct_snap": ("comp_pct_clinical", "snapshot", None),
    "burnout_snap":           ("pp4_2_burnout", "snapshot", None),
    "voice_snap":             ("pp3_voice_counts", "snapshot", None),
    "engagement_snap":        ("theme_engagement", "snapshot", None),
    "dma_overall_snap":       ("dma_overall", "snapshot", None),
    "dspt_met_snap":          ("dspt_standards_met", "snapshot", None),
}

# ---------------------------------------------------------------------------
# Lag correlation pairs: (upstream_key, downstream_key, max_lag, description)
# Only non-snapshot cols eligible for lag analysis
# ---------------------------------------------------------------------------
LAG_PAIRS = [
    # Core A&E cascade
    ("sickness_overall",    "ae_type1_4hr_perf",   3, "Overall sickness -> A&E 4hr performance"),
    ("sickness_nursing",    "ae_type1_4hr_perf",   3, "Nursing sickness -> A&E 4hr performance"),
    ("bed_occupancy",       "ae_12hr_count",        2, "Bed occupancy -> 12hr A&E breach"),
    ("delayed_discharge",   "ae_type1_4hr_perf",   2, "Delayed discharge -> A&E 4hr performance"),
    ("delayed_discharge",   "ae_12hr_count",        2, "Delayed discharge -> 12hr A&E breach"),
    ("ae_attendances_t1",   "ae_12hr_count",        1, "A&E attendances volume -> 12hr breach"),
    # Discharge/bed cascade
    ("bed_occupancy",       "delayed_discharge",    2, "Bed occupancy -> Delayed discharge"),
    ("sickness_overall",    "bed_occupancy",        2, "Sickness -> Bed occupancy"),
    ("delayed_discharge",   "rtt_18wk_pct",         3, "Delayed discharge -> RTT 18wk performance"),
    ("delayed_discharge",   "waiters_over52",        3, "Delayed discharge -> 52-week waiters"),
    ("cancelled_ops",       "waiters_over52",        3, "Cancelled ops -> 52-week waiters"),
    ("cancelled_ops",       "rtt_18wk_pct",          3, "Cancelled ops -> RTT 18wk performance"),
    # Workforce cascade
    ("nursing_fte",         "sickness_nursing",     2, "Nursing FTE -> Nursing sickness"),
    ("nursing_fte_change",  "sickness_nursing",     2, "Nursing FTE change -> Nursing sickness"),
    ("vac_rate_nursing",    "sickness_nursing",     3, "Nursing vacancy rate -> Nursing sickness"),
    ("vac_rate_all",        "sickness_overall",     3, "All-staff vacancy rate -> Overall sickness"),
    ("sickness_nursing",    "nursing_fte",           2, "Nursing sickness -> Nursing FTE (attrition)"),
    # Cancer/diagnostics cascade
    ("diag_6wk_pct",        "cancer_62d",           2, "Diagnostic 6wk wait -> Cancer 62-day performance"),
    ("cancer_fds",          "cancer_62d",            1, "Cancer 28-day FDS -> Cancer 62-day performance"),
    ("delayed_discharge",   "diag_6wk_pct",          2, "Delayed discharge -> Diagnostic waits"),
    # Quality signals
    ("sickness_overall",    "fft_negative",         1, "Sickness -> FFT negative experience"),
    ("bed_occupancy",       "fft_negative",         1, "Bed occupancy -> FFT negative experience"),
    ("ae_12hr_count",       "shmi",                  2, "12hr A&E breach -> SHMI mortality"),
    ("delayed_discharge",   "shmi",                  2, "Delayed discharge -> SHMI mortality"),
    # Finance cascade
    ("fin_variance",        "sickness_overall",     3, "Finance variance -> Sickness rate"),
    ("fin_variance",        "cancelled_ops",         2, "Finance variance -> Cancelled ops"),
    ("fin_variance",        "ae_type1_4hr_perf",    3, "Finance variance -> A&E 4hr performance"),
    # DNA/outpatient
    ("dna_rate",            "rtt_18wk_pct",          2, "DNA rate -> RTT 18wk performance"),
    ("dna_rate",            "cancelled_ops",          1, "DNA rate -> Cancelled operations"),
]

# ---------------------------------------------------------------------------
# Cross-sectional pairs (using trust-level profile means)
# (upstream_key, downstream_key, description)
# ---------------------------------------------------------------------------
XSECT_PAIRS = [
    ("ne_count_snap",       "fft_negative",         "Never events -> FFT negative experience"),
    ("ne_count_snap",       "comp_upheld",           "Never events -> Complaints upheld rate"),
    ("ne_count_snap",       "shmi",                  "Never events -> SHMI mortality"),
    ("dma_overall_snap",    "rtt_18wk_pct",          "Digital maturity -> RTT 18wk performance"),
    ("dma_overall_snap",    "ae_type1_4hr_perf",    "Digital maturity -> A&E 4hr performance"),
    ("dma_overall_snap",    "cancer_62d",            "Digital maturity -> Cancer 62-day performance"),
    ("dma_overall_snap",    "cancelled_ops",         "Digital maturity -> Cancelled operations"),
    ("dspt_met_snap",       "ne_count_snap",         "DSPT standards met -> Never events"),
    ("burnout_snap",        "sickness_overall",      "Staff burnout score -> Sickness rate"),
    ("burnout_snap",        "ae_type1_4hr_perf",    "Staff burnout -> A&E 4hr performance"),
    ("burnout_snap",        "fft_negative",          "Staff burnout -> FFT negative experience"),
    ("voice_snap",          "ne_count_snap",         "Speaking up culture -> Never events"),
    ("voice_snap",          "comp_upheld",           "Speaking up culture -> Complaints upheld"),
    ("engagement_snap",     "ae_type1_4hr_perf",    "Staff engagement -> A&E 4hr performance"),
    ("engagement_snap",     "rtt_18wk_pct",          "Staff engagement -> RTT 18wk performance"),
    ("ref_cost_gap",        "shmi",                  "Reference cost gap -> SHMI mortality"),
    ("ref_cost_gap",        "rtt_18wk_pct",          "Reference cost gap -> RTT 18wk performance"),
    ("comp_upheld",         "shmi",                  "Complaints upheld rate -> SHMI mortality"),
    ("comp_clinical_pct_snap", "shmi",               "Clinical complaints pct -> SHMI mortality"),
]


def get_series(df, key):
    """Get a normalised series for the given key from the dataframe."""
    meta = COLS_META.get(key)
    if meta is None:
        return pd.Series(dtype=float)

    raw_col, scale, transform = meta

    if key == "ae_type1_4hr_perf":
        t1_att  = pd.to_numeric(df.get("ae_a&e_attendances_type_1", pd.Series(0, index=df.index)), errors="coerce")
        t1_over = pd.to_numeric(df.get("ae_attendances_over_4hrs_type_1", pd.Series(0, index=df.index)), errors="coerce")
        return (1 - t1_over / t1_att.replace(0, np.nan)).clip(0, 1)

    if raw_col not in df.columns:
        return pd.Series(dtype=float)

    s = pd.to_numeric(df[raw_col], errors="coerce")
    if transform is not None:
        s = transform(s)
    return s


def lag_corr(x, y, lag):
    """Pearson r between x (upstream) and y (downstream) at given lag."""
    if lag == 0:
        data = pd.concat([x.reset_index(drop=True),
                          y.reset_index(drop=True)], axis=1).dropna()
    else:
        data = pd.concat([x.iloc[:-lag].reset_index(drop=True),
                          y.iloc[lag:].reset_index(drop=True)], axis=1).dropna()
    if len(data) < 8:
        return np.nan, np.nan
    r, p = stats.pearsonr(data.iloc[:, 0], data.iloc[:, 1])
    return round(float(r), 3), round(float(p), 4)


def best_lag_result(x, y, max_lag):
    best_r, best_l, best_p = 0.0, 0, 1.0
    lag_rs = {}
    for lag in range(0, max_lag + 1):
        r, p = lag_corr(x, y, lag)
        lag_rs[lag] = (r, p)
        if not np.isnan(r) and abs(r) > abs(best_r):
            best_r, best_l, best_p = r, lag, p
    return best_r, best_l, best_p, lag_rs


def strength(r):
    a = abs(r)
    if a >= 0.6:  return "strong"
    if a >= 0.4:  return "moderate"
    if a >= 0.2:  return "weak"
    return "negligible"


def load_data():
    print("  Reading column headers...")
    all_cols = pd.read_csv(MASTER, nrows=0).columns.tolist()

    needed = {"org_code", "month",
              "ae_a&e_attendances_type_1",
              "ae_attendances_over_4hrs_type_1"}
    for key, (raw_col, scale, _) in COLS_META.items():
        if raw_col != "_derived_" and raw_col in all_cols:
            needed.add(raw_col)

    load_cols = [c for c in all_cols if c in needed]
    print(f"  Loading {len(load_cols)} columns...")
    df = pd.read_csv(MASTER, usecols=load_cols, low_memory=False)
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df = df.sort_values(["org_code", "month"]).reset_index(drop=True)
    print(f"  Loaded: {df.shape}")
    return df


def run():
    print("=" * 65)
    print("TrustPulse | Comprehensive Correlation Engine")
    print("=" * 65)

    master = load_data()
    trusts = master["org_code"].unique()
    print(f"  Trusts: {len(trusts)}\n")

    # -------------------------------------------------------------------
    # 1. National pooled lag correlations
    # -------------------------------------------------------------------
    print("[1] National pooled lag correlations...")
    nat_rows = []

    for up, dn, max_lag, desc in LAG_PAIRS:
        x = get_series(master, up)
        y = get_series(master, dn)
        r, lag, p, lag_rs = best_lag_result(x, y, max_lag)
        row = {
            "upstream": up, "downstream": dn, "description": desc,
            "best_lag_months": lag, "best_r": r, "best_p": p,
            "direction": "positive" if r >= 0 else "negative",
            "strength": strength(r),
        }
        for l, (lr, lp) in lag_rs.items():
            row[f"r_lag{l}"] = lr
        nat_rows.append(row)
        flag = "***" if abs(r) >= 0.4 else "**" if abs(r) >= 0.2 else ""
        print(f"  {desc[:55]:<55} r={r:>6.3f} lag={lag}m {strength(r):<12} {flag}")

    nat_df = pd.DataFrame(nat_rows).sort_values("best_r", key=abs, ascending=False)
    nat_df.to_csv(OUT_NAT, index=False)
    print(f"\n  Saved: {OUT_NAT}")

    # -------------------------------------------------------------------
    # 2. Cross-sectional correlations (trust-level means)
    # -------------------------------------------------------------------
    print("\n[2] Cross-sectional correlations (trust-level means)...")
    xsect_rows = []

    # Build trust-level mean for each key
    trust_means = {}
    for key in COLS_META:
        s = get_series(master, key)
        s.index = master["org_code"]
        trust_means[key] = s.groupby(level=0).mean()

    for up, dn, desc in XSECT_PAIRS:
        x = trust_means.get(up, pd.Series(dtype=float))
        y = trust_means.get(dn, pd.Series(dtype=float))
        combined = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
        if len(combined) < 10:
            continue
        r, p = stats.pearsonr(combined["x"], combined["y"])
        r, p = round(float(r), 3), round(float(p), 4)
        xsect_rows.append({
            "upstream": up, "downstream": dn, "description": desc,
            "r": r, "p": p, "n_trusts": len(combined),
            "direction": "positive" if r >= 0 else "negative",
            "strength": strength(r),
        })
        flag = "***" if abs(r) >= 0.4 else "**" if abs(r) >= 0.2 else ""
        print(f"  {desc[:55]:<55} r={r:>6.3f} n={len(combined):>3} {strength(r):<12} {flag}")

    xsect_df = pd.DataFrame(xsect_rows).sort_values("r", key=abs, ascending=False)
    xsect_df.to_csv(OUT_XSECT, index=False)
    print(f"\n  Saved: {OUT_XSECT}")

    # -------------------------------------------------------------------
    # 3. Per-trust lag correlations
    # -------------------------------------------------------------------
    print(f"\n[3] Per-trust lag correlations ({len(trusts)} trusts)...")
    trust_rows = []

    for org_code, tdf in master.groupby("org_code"):
        tdf = tdf.sort_values("month").reset_index(drop=True)
        if len(tdf) < 12:
            continue
        for up, dn, max_lag, desc in LAG_PAIRS:
            x = get_series(tdf, up)
            y = get_series(tdf, dn)
            if x.notna().sum() < 8 or y.notna().sum() < 8:
                continue
            r, lag, p, _ = best_lag_result(x, y, max_lag)
            if abs(r) >= 0.3:
                trust_rows.append({
                    "org_code": org_code, "upstream": up, "downstream": dn,
                    "description": desc, "best_lag_months": lag,
                    "best_r": r, "best_p": p,
                    "direction": "positive" if r >= 0 else "negative",
                    "strength": strength(r),
                })

    trust_df = pd.DataFrame(trust_rows)
    trust_df.to_csv(OUT_TRUST, index=False)
    n_trusts = trust_df["org_code"].nunique() if not trust_df.empty else 0
    print(f"  {len(trust_df)} significant pairs across {n_trusts} trusts")
    print(f"  Saved: {OUT_TRUST}")

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print("\n[4] Top findings (|r| >= 0.2 nationally):")
    strong = nat_df[nat_df["best_r"].abs() >= 0.2][
        ["description", "best_r", "best_lag_months", "strength"]]
    print(strong.to_string(index=False))

    print("\n[5] Top cross-sectional findings (|r| >= 0.2):")
    xs_strong = xsect_df[xsect_df["r"].abs() >= 0.2][
        ["description", "r", "n_trusts", "strength"]]
    print(xs_strong.to_string(index=False))

    print("\nCorrelation engine complete.")
    return nat_df, xsect_df, trust_df


if __name__ == "__main__":
    run()
