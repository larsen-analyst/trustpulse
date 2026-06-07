"""
TrustPulse -- pipeline/ingest/rtt_specialty.py
Ingests NHS Waiting List Minimum Dataset (WLMDS) provider-level summary.

Output:
    data/processed/rtt_specialty_clean.csv

Metrics per trust (latest snapshot -- week ending 29 March 2026):
    wlmds_total_waiting       : total incomplete RTT pathways
    wlmds_waiting_u18wks      : pathways waiting under 18 weeks
    wlmds_waiting_18to52      : pathways waiting 18-52 weeks
    wlmds_waiting_over52      : pathways waiting over 52 weeks
    wlmds_waiting_first_att   : pathways waiting for first attendance
    wlmds_pct_within_18wks    : % pathways within 18 weeks
    wlmds_pct_over52wks       : % pathways over 52 weeks

Source:
    data/raw/rtt_specialty/WLMDS-Summary-to-29-Mar-2026-v2.xlsx
    Provider sheet. Latest week snapshot March 2026.
    Source: NHS England WLMDS publication.

Notes:
    - Snapshot data -- single point in time (week ending 29 March 2026)
    - Provider x specialty breakdown not available as public download
    - WLMDS is management information, less validated than monthly RTT official stats
    - 'Waiting for first attendance' is a new metric not in monthly RTT data
      -- shows how many patients haven't even had their first appointment yet
    - Complement to monthly RTT: use monthly RTT for trend, WLMDS for latest position
"""

import os
import glob
import pandas as pd
import numpy as np

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "rtt_specialty")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "rtt_specialty_clean.csv")


def ingest_rtt_specialty():
    print("=" * 60)
    print("TrustPulse | WLMDS RTT Provider Ingest")
    print("=" * 60)

    files = glob.glob(os.path.join(RAW_DIR, "*.xlsx"))
    if not files:
        print("ERROR: No XLSX file found in data/raw/rtt_specialty/")
        return

    filepath = files[0]
    print(f"Loading: {os.path.basename(filepath)}")

    # Provider sheet -- header rows 12-13, data from row 14
    raw = pd.read_excel(filepath, sheet_name="Provider", header=None)
    print(f"  Raw shape: {raw.shape}")

    # Row 12 = section headers, row 13 = column names
    # Data starts at row 14 (index 13)
    header_row = 12  # 0-indexed
    data_start  = 14  # 0-indexed

    # Build column names from rows 12 and 13
    row12 = raw.iloc[header_row].fillna("").astype(str).tolist()
    row13 = raw.iloc[header_row + 1].fillna("").astype(str).tolist()

    # First 3 cols are org info
    col_names = []
    for i, (r12, r13) in enumerate(zip(row12, row13)):
        if r13 and r13 not in ["nan", ""]:
            col_names.append(r13.strip())
        elif r12 and r12 not in ["nan", ""]:
            col_names.append(r12.strip())
        else:
            col_names.append(f"col_{i}")

    df = raw.iloc[data_start:].copy()
    df.columns = col_names[:len(df.columns)]
    df = df.reset_index(drop=True)

    # col_0 is blank -- org code is at position 1
    org_col = df.columns[1]
    name_col = df.columns[2] if len(df.columns) > 2 else None

    # Filter to NHS trust codes
    df = df[df[org_col].notna()].copy()
    df = df[df[org_col].astype(str).str.match(r'^[A-Z][A-Z0-9]{2,4}$', na=False)].copy()

    print(f"  Providers after filter: {len(df)}")
    print(f"  Columns: {df.columns.tolist()[:8]}")

    out = pd.DataFrame()
    out["org_code"] = df[org_col].astype(str).str.strip()
    if name_col:
        out["org_name"] = df[name_col].astype(str).str.strip()
    out["snapshot_date"] = pd.Timestamp("2026-03-29")

    # Map key columns by position
    # Col 0: org code, 1: name, 2: type, 3: total waiting, 4: waiting first att, 5: new periods
    # Then waiting bands: u18, 18-26, 26-40, 40-52, 52-65, 65-78, 78-104, 104+
    numeric_cols = df.columns[4:].tolist()  # skip blank, code, name, type

    def safe_int(series):
        return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)

    # Column positions (from raw data inspection):
    # numeric_cols[0]=total, [1]=u18wks, [2]=18to26, [3]=26to40, [4]=40to52,
    # [5]=52to65, [6]=65to78, [7]=78to104, [8]=104plus, [9]=unknown,
    # [10]=pct_18wks, [11]=pct_over52, [12]=first_att_count, [13]=first_att2,
    # [14]=pct_first_att
    try:
        out["wlmds_total_waiting"]    = safe_int(df[numeric_cols[0]])
        out["wlmds_waiting_u18wks"]   = safe_int(df[numeric_cols[1]])
        out["wlmds_waiting_18to26"]   = safe_int(df[numeric_cols[2]])
        out["wlmds_waiting_26to40"]   = safe_int(df[numeric_cols[3]])
        out["wlmds_waiting_40to52"]   = safe_int(df[numeric_cols[4]])
        # 52+ weeks = sum of bands 5-8
        over52 = sum(safe_int(df[numeric_cols[i]]) for i in range(5, 9) if i < len(numeric_cols))
        out["wlmds_waiting_over52"]   = over52
        # % columns already calculated by NHS England
        out["wlmds_pct_within_18wks"] = pd.to_numeric(df[numeric_cols[10]], errors="coerce").round(4)
        out["wlmds_pct_over52wks"]    = pd.to_numeric(df[numeric_cols[11]], errors="coerce").round(4)
        out["wlmds_waiting_first_att"]= safe_int(df[numeric_cols[12]])
        out["wlmds_pct_first_att"]    = pd.to_numeric(df[numeric_cols[14]], errors="coerce").round(4)
    except Exception as e:
        print(f"  WARNING: Column mapping issue: {e}")

    out = out.dropna(subset=["org_code"])

    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Rows          : {len(out)}")
    print(f"  Columns       : {out.shape[1]}")
    print(f"  Snapshot date : 29 March 2026")

    if "wlmds_total_waiting" in out.columns:
        print(f"  Total NHS waiting list: {out['wlmds_total_waiting'].sum():,}")
        print(f"\n  Trusts with largest waiting lists:")
        top10 = out.nlargest(10, "wlmds_total_waiting")[
            ["org_code", "org_name", "wlmds_total_waiting",
             "wlmds_pct_within_18wks"]].copy()
        if "wlmds_pct_within_18wks" in top10.columns:
            top10["wlmds_pct_within_18wks"] = (top10["wlmds_pct_within_18wks"] * 100).round(1)
        print(top10.to_string(index=False))

    print("\nWLMDS ingest complete.")


if __name__ == "__main__":
    ingest_rtt_specialty()
