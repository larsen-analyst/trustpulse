"""
TrustPulse -- pipeline/ingest/reference_costs.py
Ingests NHS National Cost Collection 2024/25 Organisation Level MFF-adjusted data.

Output:
    data/processed/reference_costs_clean.csv

Metrics per trust:
    rc_actual_cost_total_m     : total actual cost (GBP millions, MFF adjusted)
    rc_expected_cost_total_m   : total expected cost (GBP millions, MFF adjusted)
    rc_cost_gap_m              : actual minus expected (positive = overspending)
    rc_cost_gap_pct            : gap as % of expected cost
    rc_apc_actual_m            : admitted patient care actual cost
    rc_apc_gap_pct             : APC cost gap %
    rc_op_actual_m             : outpatient actual cost
    rc_op_gap_pct              : outpatient cost gap %
    rc_ae_actual_m             : A&E actual cost
    rc_ae_gap_pct              : A&E cost gap %

Source:
    data/raw/reference_costs/NCC_FY2024-25_Org_File2.zip
    MFF-adjusted organisation level data. 206 providers, 2024/25 financial year.

Notes:
    - MFF adjustment removes regional cost differences (London wage premium etc.)
      so trusts can be fairly compared regardless of location
    - Positive gap means trust spends MORE than expected given its activity mix
    - Negative gap means trust spends LESS than expected (efficient)
    - Mapping pots: 01_EI/02_NEI = admitted patient care, 05_OP = outpatient,
      11_A&E = emergency, 08_MH = mental health, 07_COM = community
    - Source: NHS England National Cost Collection 2024/25
"""

import os
import zipfile
import io
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "reference_costs")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "reference_costs_clean.csv")

SOURCE_FILE = os.path.join(RAW_DIR, "NCC_FY2024-25_Org_File2.zip")

# Mapping pot groupings
APC_POTS  = {"01_EI", "02_NEI"}       # Admitted patient care (elective and non-elective)
OP_POTS   = {"05_OP"}                  # Outpatient
AE_POTS   = {"11_A&E"}                 # Emergency department
MH_POTS   = {"08_MH"}                  # Mental health
COM_POTS  = {"07_COM"}                 # Community


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)


def ingest_reference_costs():
    print("=" * 60)
    print("TrustPulse | NHS Reference Costs Ingestion")
    print("=" * 60)

    if not os.path.exists(SOURCE_FILE):
        print(f"ERROR: Source file not found: {SOURCE_FILE}")
        return

    print(f"Loading: {os.path.basename(SOURCE_FILE)}")
    print("Reading 1.6 million rows -- this may take 30-60 seconds...")

    with zipfile.ZipFile(SOURCE_FILE) as z:
        csv_name = [n for n in z.namelist() if n.endswith(".csv")][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(
                io.TextIOWrapper(f, encoding="utf-8"),
                dtype={"Provider Code": str, "Department Code": str,
                       "Currency code": str, "Mapping Pot": str},
                low_memory=False
            )

    print(f"Loaded: {len(df):,} rows | {df['Provider Code'].nunique()} providers")

    # Convert cost columns to numeric
    df["actual"]   = safe_numeric(df["MFFd Actual Cost"])
    df["expected"] = safe_numeric(df["MFFd Expected Cost"])
    df["activity"] = safe_numeric(df["Activity"])

    # Total per trust
    total = df.groupby("Provider Code").agg(
        actual_total=("actual", "sum"),
        expected_total=("expected", "sum"),
        activity_total=("activity", "sum"),
    ).reset_index()

    total["rc_cost_gap_m"]   = ((total["actual_total"] - total["expected_total"]) / 1e6).round(2)
    total["rc_cost_gap_pct"] = (
        (total["actual_total"] - total["expected_total"]) /
        total["expected_total"].replace(0, float("nan")) * 100
    ).round(2)
    total["rc_actual_cost_total_m"]   = (total["actual_total"] / 1e6).round(2)
    total["rc_expected_cost_total_m"] = (total["expected_total"] / 1e6).round(2)

    # APC breakdown
    apc = df[df["Mapping Pot"].isin(APC_POTS)].groupby("Provider Code").agg(
        apc_actual=("actual", "sum"), apc_expected=("expected", "sum")
    ).reset_index()
    apc["rc_apc_actual_m"]  = (apc["apc_actual"] / 1e6).round(2)
    apc["rc_apc_gap_pct"]   = (
        (apc["apc_actual"] - apc["apc_expected"]) /
        apc["apc_expected"].replace(0, float("nan")) * 100
    ).round(2)

    # Outpatient breakdown
    op = df[df["Mapping Pot"].isin(OP_POTS)].groupby("Provider Code").agg(
        op_actual=("actual", "sum"), op_expected=("expected", "sum")
    ).reset_index()
    op["rc_op_actual_m"]  = (op["op_actual"] / 1e6).round(2)
    op["rc_op_gap_pct"]   = (
        (op["op_actual"] - op["op_expected"]) /
        op["op_expected"].replace(0, float("nan")) * 100
    ).round(2)

    # A&E breakdown
    ae = df[df["Mapping Pot"].isin(AE_POTS)].groupby("Provider Code").agg(
        ae_actual=("actual", "sum"), ae_expected=("expected", "sum")
    ).reset_index()
    ae["rc_ae_actual_m"]  = (ae["ae_actual"] / 1e6).round(2)
    ae["rc_ae_gap_pct"]   = (
        (ae["ae_actual"] - ae["ae_expected"]) /
        ae["ae_expected"].replace(0, float("nan")) * 100
    ).round(2)

    # Merge all
    out = total[["Provider Code", "rc_actual_cost_total_m", "rc_expected_cost_total_m",
                 "rc_cost_gap_m", "rc_cost_gap_pct"]].copy()
    out = out.merge(
        apc[["Provider Code", "rc_apc_actual_m", "rc_apc_gap_pct"]], on="Provider Code", how="left"
    )
    out = out.merge(
        op[["Provider Code", "rc_op_actual_m", "rc_op_gap_pct"]], on="Provider Code", how="left"
    )
    out = out.merge(
        ae[["Provider Code", "rc_ae_actual_m", "rc_ae_gap_pct"]], on="Provider Code", how="left"
    )

    out = out.rename(columns={"Provider Code": "org_code"})
    out["financial_year"] = "2024-25"
    out = out.sort_values("rc_cost_gap_pct", ascending=False).reset_index(drop=True)

    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Providers     : {len(out)}")
    print(f"  Columns       : {out.shape[1]}")
    print(f"  Total NHS cost: GBP {out['rc_actual_cost_total_m'].sum()/1000:.1f}bn")
    print(f"\n  Top 10 trusts by cost gap % (overspending vs expected):")
    print(out[["org_code","rc_actual_cost_total_m","rc_expected_cost_total_m",
               "rc_cost_gap_m","rc_cost_gap_pct"]].head(10).to_string(index=False))
    print(f"\n  Top 10 most efficient trusts (underspending vs expected):")
    print(out[["org_code","rc_actual_cost_total_m","rc_expected_cost_total_m",
               "rc_cost_gap_m","rc_cost_gap_pct"]].tail(10).to_string(index=False))

    print("\nReference costs ingestion complete.")


if __name__ == "__main__":
    ingest_reference_costs()
