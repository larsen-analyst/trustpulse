"""
app.py
TrustPulse -- Flask application
Routes: / (dashboard), /trust/<org_code>, /compare, /api/trusts, /api/trust/<org_code>
"""

import json
import math
import pandas as pd
import numpy as np
from pathlib import Path
from flask import Flask, render_template, jsonify, request, abort

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
BASE_DIR   = Path(__file__).resolve().parent
DATA_DIR   = BASE_DIR / "data" / "processed"
STATIC_DIR = BASE_DIR / "static"
TMPL_DIR   = BASE_DIR / "templates"

app = Flask(__name__, template_folder=str(TMPL_DIR), static_folder=str(STATIC_DIR))
app.config["SECRET_KEY"] = "trustpulse-dev-key-change-in-production"

# ---------------------------------------------------------------------------
# Data loading (loaded once at startup, cached in module-level variables)
# ---------------------------------------------------------------------------
_scores_df   = None
_master_df   = None
_profiles_df = None


def load_data():
    global _scores_df, _master_df, _profiles_df
    scores_path   = DATA_DIR / "trust_risk_scores.csv"
    master_path   = DATA_DIR / "trust_master.csv"
    profiles_path = DATA_DIR / "trust_profiles.csv"

    if scores_path.exists():
        _scores_df = pd.read_csv(scores_path, dtype={"org_code": str})
        _scores_df = _scores_df.replace({float("nan"): None, float("inf"): None, float("-inf"): None})
        print(f"[app] Loaded trust_risk_scores.csv: {len(_scores_df)} trusts")
    else:
        print(f"[app] WARNING: trust_risk_scores.csv not found at {scores_path}")
        _scores_df = pd.DataFrame()

    if master_path.exists():
        _master_df = pd.read_csv(master_path, dtype={"org_code": str}, parse_dates=["month"])
        print(f"[app] Loaded trust_master.csv: {len(_master_df)} rows")
    else:
        print(f"[app] WARNING: trust_master.csv not found")
        _master_df = pd.DataFrame()

    if profiles_path.exists():
        _profiles_df = pd.read_csv(profiles_path, dtype={"org_code": str})
        print(f"[app] Loaded trust_profiles.csv: {len(_profiles_df)} trusts")
    else:
        _profiles_df = pd.DataFrame()


def get_scores():
    if _scores_df is None:
        load_data()
    return _scores_df


def get_master():
    if _master_df is None:
        load_data()
    return _master_df


def safe_val(val):
    """Convert numpy/pandas types to JSON-safe Python types."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    return val


def row_to_dict(row):
    """Convert a DataFrame row to a clean JSON-safe dict."""
    return {k: safe_val(v) for k, v in row.items()}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    df = get_scores()
    if df.empty:
        return render_template("index.html", error="No risk scores data found. Run pipeline/analyse.py first.")

    # Summary stats
    rag_counts = df["overall_rag"].value_counts().to_dict() if "overall_rag" in df.columns else {}
    n_red    = int(rag_counts.get("Red",   0))
    n_amber  = int(rag_counts.get("Amber", 0))
    n_green  = int(rag_counts.get("Green", 0))
    n_total  = len(df)

    total_cost = df["est_annual_inefficiency_gbp"].sum() if "est_annual_inefficiency_gbp" in df.columns else 0
    total_cost = 0 if (total_cost is None or (isinstance(total_cost, float) and math.isnan(total_cost))) else total_cost

    # Top 10 highest risk
    top10 = df.head(10)
    top10_list = [row_to_dict(row) for _, row in top10.iterrows()]

    # All trusts for the filterable table (summary columns only)
    table_cols = ["org_code", "org_name", "Region", "Trust_type", "overall_rag",
                  "composite_score", "d1_rag", "d2_rag", "d3_rag", "d4_rag", "d5_rag",
                  "red_flag_count", "est_annual_inefficiency_gbp"]
    table_cols = [c for c in table_cols if c in df.columns]
    table_data = [row_to_dict(row) for _, row in df[table_cols].iterrows()]

    # Regions for filter
    regions = sorted(df["Region"].dropna().unique().tolist()) if "Region" in df.columns else []

    return render_template("index.html",
        n_red=n_red, n_amber=n_amber, n_green=n_green, n_total=n_total,
        total_cost_bn=round(total_cost / 1e9, 2),
        top10=top10_list,
        table_data=json.dumps(table_data),
        regions=regions,
        data_month=df["data_month"].iloc[0] if "data_month" in df.columns else "Mar 2026",
    )


@app.route("/trust/<org_code>")
def trust_profile(org_code):
    df = get_scores()
    master = get_master()

    if df.empty:
        abort(503, "Risk scores not available. Run pipeline/analyse.py first.")

    trust_row = df[df["org_code"] == org_code]
    if trust_row.empty:
        abort(404, f"Trust {org_code} not found.")

    trust = row_to_dict(trust_row.iloc[0])

    # Time series for charts (last 24 months)
    charts = {}
    if not master.empty:
        t = master[master["org_code"] == org_code].sort_values("month")
        if not t.empty:
            t = t.tail(24)
            months = t["month"].dt.strftime("%b %Y").tolist()

            # Derive 4hr performance from raw A&E counts
            t1_att   = t["ae_a&e_attendances_type_1"].fillna(0)
            t1_over4 = t["ae_attendances_over_4hrs_type_1"].fillna(0)
            ae_perf  = (1 - t1_over4 / t1_att.replace(0, float("nan"))) * 100

            charts["ae"] = {
                "months": months,
                "perf":   [safe_val(v) for v in ae_perf.tolist()],
                "target": 76,
            }

            if "sickness_rate_overall" in t.columns:
                charts["sickness"] = {
                    "months": months,
                    "rate":   [safe_val(v) for v in t["sickness_rate_overall"].tolist()],
                    "target": 5.5,
                }

            if "beds_occupancy_rate" in t.columns:
                charts["beds"] = {
                    "months": months,
                    "rate":   [safe_val(v) for v in (t["beds_occupancy_rate"] * 100).tolist()],
                    "warn":   85,
                    "crit":   95,
                }

            if "pct_within_18_weeks" in t.columns:
                charts["rtt"] = {
                    "months": months,
                    "perf":   [safe_val(v) for v in (t["pct_within_18_weeks"] * 100).tolist()],
                    "target": 65,
                }

    # Regional peers for context
    region = trust.get("Region")
    peers = {}
    if region and "Region" in df.columns:
        region_df = df[df["Region"] == region]
        peers["count"]       = len(region_df)
        peers["avg_score"]   = safe_val(region_df["composite_score"].mean()) if "composite_score" in region_df.columns else None
        peers["n_red"]       = int((region_df["overall_rag"] == "Red").sum()) if "overall_rag" in region_df.columns else 0

    return render_template("trust.html",
        trust=trust,
        charts=json.dumps(charts),
        peers=peers,
        org_code=org_code,
    )


@app.route("/compare")
def compare():
    df = get_scores()
    org_codes = request.args.getlist("org")

    trusts = []
    if org_codes and not df.empty:
        for code in org_codes[:5]:  # max 5 trusts
            row = df[df["org_code"] == code]
            if not row.empty:
                trusts.append(row_to_dict(row.iloc[0]))

    # All trust names for the selector
    all_trusts = []
    if not df.empty:
        cols = ["org_code", "org_name", "Region", "overall_rag", "composite_score"]
        cols = [c for c in cols if c in df.columns]
        all_trusts = [row_to_dict(r) for _, r in df[cols].iterrows()]

    return render_template("compare.html",
        trusts=trusts,
        trusts_json=json.dumps(trusts),
        all_trusts=json.dumps(all_trusts),
        selected_codes=org_codes,
    )


# ---------------------------------------------------------------------------
# JSON API endpoints (used by JS on the pages)
# ---------------------------------------------------------------------------

@app.route("/api/trusts")
def api_trusts():
    df = get_scores()
    if df.empty:
        return jsonify([])
    cols = ["org_code", "org_name", "Region", "Trust_type", "overall_rag",
            "composite_score", "d1_score", "d1_rag", "d2_score", "d2_rag",
            "d3_score", "d3_rag", "d4_score", "d4_rag", "d5_score", "d5_rag",
            "red_flag_count", "est_annual_inefficiency_gbp"]
    cols = [c for c in cols if c in df.columns]
    result = [row_to_dict(r) for _, r in df[cols].iterrows()]
    return jsonify(result)


@app.route("/api/trust/<org_code>")
def api_trust(org_code):
    df = get_scores()
    if df.empty:
        return jsonify({"error": "No data"}), 503
    row = df[df["org_code"] == org_code]
    if row.empty:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_dict(row.iloc[0]))


@app.route("/api/timeseries/<org_code>")
def api_timeseries(org_code):
    master = get_master()
    if master.empty:
        return jsonify([])
    t = master[master["org_code"] == org_code].sort_values("month")
    if t.empty:
        return jsonify([])
    t = t.tail(48)
    # Return key metrics only
    keep = ["month", "ae_a&e_attendances_type_1", "ae_attendances_over_4hrs_type_1",
            "sickness_rate_overall", "beds_occupancy_rate", "pct_within_18_weeks",
            "discharge_total_delayed_bed_days", "amb_over60_pct"]
    keep = [c for c in keep if c in t.columns]
    t_sub = t[keep].copy()
    t_sub["month"] = t_sub["month"].dt.strftime("%Y-%m-%d")
    result = [row_to_dict(r) for _, r in t_sub.iterrows()]
    return jsonify(result)


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

@app.template_filter("rag_class")
def rag_class(rag_val):
    return {"Red": "rag-red", "Amber": "rag-amber", "Green": "rag-green"}.get(rag_val, "rag-unknown")


@app.template_filter("fmt_cost")
def fmt_cost(val):
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if v >= 1e9:
            return f"£{v/1e9:.1f}bn"
        if v >= 1e6:
            return f"£{v/1e6:.1f}m"
        if v >= 1e3:
            return f"£{v/1e3:.0f}k"
        return f"£{v:.0f}"
    except (TypeError, ValueError):
        return "N/A"


@app.template_filter("fmt_pct")
def fmt_pct(val, decimals=1):
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.{decimals}f}%"
    except (TypeError, ValueError):
        return "N/A"


@app.template_filter("fmt_score")
def fmt_score(val):
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.1f}"
    except (TypeError, ValueError):
        return "N/A"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    load_data()
    app.run(debug=True, port=5000)
