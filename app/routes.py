"""
app/routes.py
TrustPulse URL routes
"""

from flask import Blueprint, render_template, jsonify, abort
from app.data import (
    load_profiles, get_trust_list, get_trust,
    get_summary_stats, get_top_risk_trusts, get_region_averages
)
import pandas as pd
import numpy as np
import json

main = Blueprint("main", __name__)


def clean_for_json(obj):
    """Replace NaN/Inf with None for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_for_json(i) for i in obj]
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


@main.route("/")
def index():
    stats    = get_summary_stats()
    top10    = get_top_risk_trusts(10)
    top10    = clean_for_json(top10)
    return render_template("index.html", stats=stats, top10=top10)


@main.route("/trust/<org_code>")
def trust_profile(org_code):
    trust = get_trust(org_code.upper())
    if trust is None:
        abort(404)
    trust = clean_for_json(trust)
    return render_template("trust.html", trust=trust)


@main.route("/compare")
def compare():
    trust_list = get_trust_list()
    return render_template("compare.html", trust_list=trust_list)


# ---------------------------------------------------------------------------
# API endpoints (JSON — for Plotly charts)
# ---------------------------------------------------------------------------

@main.route("/api/trusts")
def api_trusts():
    """Trust list for search autocomplete."""
    return jsonify(clean_for_json(get_trust_list()))


@main.route("/api/trust/<org_code>")
def api_trust(org_code):
    """Full trust profile as JSON."""
    trust = get_trust(org_code.upper())
    if trust is None:
        return jsonify({"error": "Trust not found"}), 404
    return jsonify(clean_for_json(trust))


@main.route("/api/risk-distribution")
def api_risk_distribution():
    """Risk distribution for homepage pie/donut chart."""
    stats = get_summary_stats()
    data = {
        "labels": ["Red", "Amber", "Green"],
        "values": [stats["red_count"], stats["amber_count"], stats["green_count"]],
        "colors": ["#f85149", "#d29922", "#3fb950"],
    }
    return jsonify(data)


@main.route("/api/top-risks")
def api_top_risks():
    """Top 10 risk trusts for homepage bar chart."""
    top10 = get_top_risk_trusts(10)
    return jsonify(clean_for_json(top10))


@main.route("/api/region-averages")
def api_region_averages():
    """Regional averages for peer comparison."""
    return jsonify(clean_for_json(get_region_averages()))
