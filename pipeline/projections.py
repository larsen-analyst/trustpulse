"""
TrustPulse -- pipeline/projections.py
Linear trend projection engine. Projects key metrics 90 days forward per trust.

Output:
    data/processed/projections.csv

For each trust and metric:
    - trend_slope       : monthly change (linear regression over last 6 months)
    - trend_r2          : R-squared of the trend fit
    - current_value     : latest observed value
    - projected_3m      : projected value in 3 months
    - breach_flag       : 1 if projected value crosses threshold
    - breach_direction  : 'worsening' or 'improving'
    - confidence        : 'high' (r2>=0.5), 'medium' (r2>=0.25), 'low'

Metrics projected:
    1. A&E 4hr type1 performance (threshold: 0.76)
    2. Sickness rate overall (threshold: 0.065 = 6.5%)
    3. Bed occupancy rate (threshold: 0.95)
    4. 12hr A&E breach count (threshold: trust-specific 75th percentile)
    5. Delayed discharge bed days (threshold: trust 75th percentile)
    6. RTT 18wk performance (threshold: 0.65)
    7. Nursing FTE (threshold: -3% trend = risk signal)
    8. Nursing sickness rate (threshold: 0.07 = 7%)
"""

import os
import warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER    = os.path.join(BASE_DIR, "data", "processed", "trust_master.csv")
OUT       = os.path.join(BASE_DIR, "data", "processed", "projections.csv")

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

# Metric definitions:
# (name, col_or_derived, threshold, breach_when, display_label, is_pct)
# breach_when: 'below' = breach if projected < threshold
#              'above' = breach if projected > threshold
METRICS = [
    ("ae_4hr_perf",       "_derived_ae4hr_",    0.76,   "below",  "A&E 4hr performance",         True),
    ("sickness_overall",  "sickness_rate_overall", 6.5, "above",  "Overall sickness rate (%)",   False),
    ("bed_occupancy",     "beds_occupancy_rate", 0.95,   "above",  "Bed occupancy rate",          True),
    ("ae_12hr_breach",    "ae_patients_who_have_waited_12+_hrs_from_dta_to_admission",
                                                  None,   "above",  "12hr A&E breach count",       False),
    ("delayed_discharge", "discharge_total_delayed_bed_days",
                                                  None,   "above",  "Delayed discharge bed days",  False),
    ("rtt_18wk",          "pct_within_18_weeks", 0.65,   "below",  "RTT 18wk performance",        True),
    ("nursing_fte",       "workforce_nursing_fte", None,  "below",  "Nursing FTE",                 False),
    ("sickness_nursing",  "sick_sickness_rate_nursing", 0.07, "above", "Nursing sickness rate",   True),
]

TREND_WINDOW = 6   # months of data to use for trend
PROJECT_MONTHS = 3 # months to project forward


def derive_ae4hr(df):
    t1_att  = pd.to_numeric(df.get("ae_a&e_attendances_type_1",   pd.Series(0, index=df.index)), errors="coerce")
    t1_over = pd.to_numeric(df.get("ae_attendances_over_4hrs_type_1", pd.Series(0, index=df.index)), errors="coerce")
    return (1 - t1_over / t1_att.replace(0, np.nan)).clip(0, 1)


def get_series(tdf, col):
    if col == "_derived_ae4hr_":
        return derive_ae4hr(tdf)
    return pd.to_numeric(tdf[col], errors="coerce") if col in tdf.columns else pd.Series(dtype=float)


def linear_trend(values):
    """Fit linear trend to values series. Returns (slope, r2, intercept)."""
    clean = values.dropna()
    if len(clean) < 4:
        return np.nan, np.nan, np.nan
    x = np.arange(len(clean))
    slope, intercept, r, p, se = stats.linregress(x, clean.values)
    return round(float(slope), 6), round(float(r**2), 3), round(float(intercept), 6)


def confidence_label(r2):
    if np.isnan(r2): return "insufficient"
    if r2 >= 0.5:   return "high"
    if r2 >= 0.25:  return "medium"
    return "low"


def run():
    print("=" * 60)
    print("TrustPulse | Projection Engine (90-day forward)")
    print("=" * 60)

    all_cols = pd.read_csv(MASTER, nrows=0).columns.tolist()
    load_cols = [c for c in NEEDED_COLS if c in all_cols]
    print(f"  Loading {len(load_cols)} columns...")
    master = pd.read_csv(MASTER, usecols=load_cols, low_memory=False)
    master["month"] = pd.to_datetime(master["month"], errors="coerce")
    master = master.sort_values(["org_code", "month"]).reset_index(drop=True)

    latest_month = master["month"].max()
    trend_cutoff = latest_month - pd.DateOffset(months=TREND_WINDOW - 1)
    print(f"  Latest month: {latest_month.strftime('%Y-%m')}")
    print(f"  Trend window: {trend_cutoff.strftime('%Y-%m')} to {latest_month.strftime('%Y-%m')}")
    print(f"  Projection target: +{PROJECT_MONTHS} months\n")

    rows = []
    trusts_processed = 0

    for org_code, tdf in master.groupby("org_code"):
        tdf = tdf.sort_values("month").reset_index(drop=True)
        # Trend window data
        trend_data = tdf[tdf["month"] >= trend_cutoff].copy()
        if len(trend_data) < 3:
            continue

        trusts_processed += 1

        for metric_name, col, threshold, breach_dir, label, is_pct in METRICS:
            # Full series for context
            full_series = get_series(tdf, col)
            # Trend series (last 6 months)
            trend_series = get_series(trend_data, col)

            current_val = full_series.dropna().iloc[-1] if full_series.dropna().shape[0] > 0 else np.nan
            if np.isnan(current_val):
                continue

            slope, r2, intercept = linear_trend(trend_series)

            # Project 3 months forward
            if not np.isnan(slope):
                n_trend_pts = trend_series.dropna().shape[0]
                projected = intercept + slope * (n_trend_pts - 1 + PROJECT_MONTHS)
            else:
                projected = current_val

            # Determine breach
            # For metrics with None threshold, use trust's own 75th percentile
            if threshold is None:
                hist_vals = full_series.dropna()
                t_threshold = hist_vals.quantile(0.75) if len(hist_vals) >= 6 else np.nan
            else:
                t_threshold = threshold

            breach = 0
            if not np.isnan(t_threshold) and not np.isnan(projected):
                if breach_dir == "below" and projected < t_threshold:
                    breach = 1
                elif breach_dir == "above" and projected > t_threshold:
                    breach = 1

            # Direction
            if not np.isnan(slope):
                # For 'below' metrics, negative slope = worsening
                if breach_dir == "below":
                    direction = "worsening" if slope < -0.001 else "improving" if slope > 0.001 else "stable"
                else:
                    direction = "worsening" if slope > 0.001 else "improving" if slope < -0.001 else "stable"
            else:
                direction = "unknown"

            rows.append({
                "org_code":          org_code,
                "metric":            metric_name,
                "metric_label":      label,
                "current_value":     round(float(current_val), 4),
                "trend_slope":       round(float(slope), 6) if not np.isnan(slope) else None,
                "trend_r2":          round(float(r2), 3) if not np.isnan(r2) else None,
                "projected_3m":      round(float(projected), 4),
                "threshold":         t_threshold if not np.isnan(t_threshold) else None,
                "breach_flag":       breach,
                "trend_direction":   direction,
                "confidence":        confidence_label(r2),
                "is_pct_display":    int(is_pct),
            })

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT, index=False)

    print(f"  Trusts processed : {trusts_processed}")
    print(f"  Projection rows  : {len(df_out)}")
    print(f"\n  Breach flags by metric:")
    breach_summary = df_out[df_out["breach_flag"]==1].groupby("metric_label").size().sort_values(ascending=False)
    print(breach_summary.to_string())

    print(f"\n  Worsening trends by metric:")
    worsening = df_out[df_out["trend_direction"]=="worsening"].groupby("metric_label").size().sort_values(ascending=False)
    print(worsening.to_string())

    print(f"\n  High confidence projections: {(df_out['confidence']=='high').sum()}")
    print(f"  Medium confidence:           {(df_out['confidence']=='medium').sum()}")
    print(f"  Low confidence:              {(df_out['confidence']=='low').sum()}")

    print(f"\nSaved: {OUT}")
    print("\nProjection engine complete.")
    return df_out


if __name__ == "__main__":
    run()
