"""
TrustPulse -- pipeline/correlations.py
Calculates lag correlations between upstream signals and downstream outcomes.
Reads trust_master.csv in chunks by trust to avoid memory issues.

Output:
    data/processed/correlations_national.csv
    data/processed/correlations_trust.csv
"""

import os
import warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER    = os.path.join(BASE_DIR, "data", "processed", "trust_master.csv")
OUT_NAT   = os.path.join(BASE_DIR, "data", "processed", "correlations_national.csv")
OUT_TRUST = os.path.join(BASE_DIR, "data", "processed", "correlations_trust.csv")

# Only load these columns
NEEDED_COLS = [
    "org_code", "month",
    "ae_a&e_attendances_type_1",
    "ae_attendances_over_4hrs_type_1",
    "ae_patients_who_have_waited_12+_hrs_from_dta_to_admission",
    "sickness_rate_overall",
    "sick_sickness_rate_nursing",
    "beds_occupancy_rate",
    "discharge_total_delayed_bed_days",
    "pct_within_18_weeks",
    "workforce_nursing_fte",
]

# Signal pairs: (upstream, downstream, max_lag, description)
SIGNAL_PAIRS = [
    ("sickness_rate_overall",              "ae_type1_4hr_perf",         3,
     "Sickness -> A&E 4hr performance"),
    ("sick_sickness_rate_nursing",         "ae_type1_4hr_perf",         3,
     "Nursing sickness -> A&E 4hr performance"),
    ("beds_occupancy_rate",                "ae_12hr_breach",             2,
     "Bed occupancy -> 12hr A&E breach"),
    ("beds_occupancy_rate",                "discharge_total_delayed_bed_days", 1,
     "Bed occupancy -> Delayed discharge"),
    ("discharge_total_delayed_bed_days",   "pct_within_18_weeks",       3,
     "Delayed discharge -> RTT 18wk performance"),
    ("workforce_nursing_fte",              "sick_sickness_rate_nursing", 2,
     "Nursing FTE -> Nursing sickness"),
    ("sickness_rate_overall",              "beds_occupancy_rate",        2,
     "Sickness -> Bed occupancy"),
    ("discharge_total_delayed_bed_days",   "ae_type1_4hr_perf",         2,
     "Delayed discharge -> A&E 4hr performance"),
]


def load_master():
    print("  Reading column list...")
    all_cols = pd.read_csv(MASTER, nrows=0).columns.tolist()
    load_cols = [c for c in NEEDED_COLS if c in all_cols]
    print(f"  Loading {len(load_cols)} columns...")
    df = pd.read_csv(MASTER, usecols=load_cols, low_memory=False)
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df = df.sort_values(["org_code", "month"]).reset_index(drop=True)

    # Derive computed columns
    t1_att  = pd.to_numeric(df.get("ae_a&e_attendances_type_1", pd.Series(0, index=df.index)), errors="coerce")
    t1_over = pd.to_numeric(df.get("ae_attendances_over_4hrs_type_1", pd.Series(0, index=df.index)), errors="coerce")
    df["ae_type1_4hr_perf"] = (1 - t1_over / t1_att.replace(0, np.nan)).clip(0, 1)

    df["ae_12hr_breach"] = pd.to_numeric(
        df.get("ae_patients_who_have_waited_12+_hrs_from_dta_to_admission", pd.Series()), errors="coerce")

    for col in ["sickness_rate_overall", "sick_sickness_rate_nursing",
                "beds_occupancy_rate", "discharge_total_delayed_bed_days",
                "pct_within_18_weeks", "workforce_nursing_fte"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print(f"  Loaded: {df.shape}")
    return df


def lag_corr(x, y, lag):
    if lag == 0:
        combined = pd.concat([x.reset_index(drop=True),
                               y.reset_index(drop=True)], axis=1).dropna()
    else:
        combined = pd.concat([x.iloc[:-lag].reset_index(drop=True),
                               y.iloc[lag:].reset_index(drop=True)], axis=1).dropna()
    if len(combined) < 6:
        return np.nan, np.nan
    r, p = stats.pearsonr(combined.iloc[:, 0], combined.iloc[:, 1])
    return round(r, 3), round(p, 4)


def best_lag(x, y, max_lag):
    best_r, best_l, best_p = 0.0, 0, 1.0
    for lag in range(0, max_lag + 1):
        r, p = lag_corr(x, y, lag)
        if not np.isnan(r) and abs(r) > abs(best_r):
            best_r, best_l, best_p = r, lag, p
    return best_r, best_l, best_p


def run():
    print("=" * 60)
    print("TrustPulse | Correlation Engine")
    print("=" * 60)

    master = load_master()
    trusts = master["org_code"].unique()
    print(f"  Trusts: {len(trusts)}\n")

    # National pooled
    print("[1] National pooled correlations...")
    nat_rows = []
    for up, dn, max_lag, desc in SIGNAL_PAIRS:
        x = master[up] if up in master.columns else pd.Series(dtype=float)
        y = master[dn] if dn in master.columns else pd.Series(dtype=float)
        r, lag, p = best_lag(x, y, max_lag)
        strength = "strong" if abs(r) >= 0.4 else "moderate" if abs(r) >= 0.2 else "weak"
        nat_rows.append({
            "upstream": up, "downstream": dn, "description": desc,
            "best_lag_months": lag, "best_r": r, "best_p": p,
            "direction": "positive" if r >= 0 else "negative",
            "strength": strength,
        })
        print(f"  {desc[:50]:<50} r={r:>6.3f} lag={lag}m {strength}")

    nat_df = pd.DataFrame(nat_rows)
    nat_df.to_csv(OUT_NAT, index=False)

    # Per trust
    print(f"\n[2] Per-trust correlations ({len(trusts)} trusts)...")
    trust_rows = []
    for org_code, tdf in master.groupby("org_code"):
        tdf = tdf.sort_values("month").reset_index(drop=True)
        if len(tdf) < 12:
            continue
        for up, dn, max_lag, desc in SIGNAL_PAIRS:
            x = tdf[up] if up in tdf.columns else pd.Series(dtype=float)
            y = tdf[dn] if dn in tdf.columns else pd.Series(dtype=float)
            if x.notna().sum() < 8 or y.notna().sum() < 8:
                continue
            r, lag, p = best_lag(x, y, max_lag)
            if abs(r) >= 0.3:
                trust_rows.append({
                    "org_code": org_code, "upstream": up, "downstream": dn,
                    "description": desc, "best_lag_months": lag,
                    "best_r": r, "best_p": p,
                    "direction": "positive" if r >= 0 else "negative",
                    "strength": "strong" if abs(r) >= 0.4 else "moderate",
                })

    trust_df = pd.DataFrame(trust_rows)
    trust_df.to_csv(OUT_TRUST, index=False)
    n_trusts = trust_df["org_code"].nunique() if not trust_df.empty else 0
    print(f"  {len(trust_df)} significant pairs across {n_trusts} trusts")
    print(f"\nSaved:\n  {OUT_NAT}\n  {OUT_TRUST}")
    print("\nCorrelation engine complete.")


if __name__ == "__main__":
    run()
