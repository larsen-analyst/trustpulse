"""
TrustPulse -- pipeline/ingest/dspt.py
Ingests NHS Data Security and Protection Toolkit (DSPT) scores.

Output:
    data/processed/dspt_clean.csv

Metrics per trust:
    dspt_status         : latest DSPT assessment status (text)
    dspt_year           : financial year of latest assessment
    dspt_standards_met  : 1 if standards met or exceeded, 0 otherwise
    dspt_approaching    : 1 if approaching standards
    dspt_not_met        : 1 if standards not met or not published

Source:
    data/raw/dspt/DSPT search results *.csv
    Downloaded from dsptoolkit.nhs.uk -- all organisations, filtered to R-codes.

Notes:
    - DSPT is an annual self-assessment against NHS data security standards
    - Standards met = good cyber hygiene baseline
    - Approaching standards = some gaps remain
    - Standards not met = significant cyber security risk
    - Not published = trust has not submitted (itself a risk signal)
    - Used as contextual signal in D4 (finance and productivity / governance)
"""

import os
import glob
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "dspt")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED, "dspt_clean.csv")


def ingest_dspt():
    print("=" * 60)
    print("TrustPulse | DSPT Cyber Scores Ingest")
    print("=" * 60)

    files = glob.glob(os.path.join(RAW_DIR, "*.csv"))
    if not files:
        print("ERROR: No CSV found in data/raw/dspt/")
        return

    filepath = files[0]
    print(f"Loading: {os.path.basename(filepath)}")

    df = pd.read_csv(filepath)
    df.columns = [c.strip() for c in df.columns]
    df['Code'] = df['Code'].astype(str).str.strip()
    df['Status'] = df['Status'].astype(str).str.strip()

    # Filter to NHS trust R-codes only
    df = df[df['Code'].str.match(r'^R[A-Z0-9]{2,3}$', na=False)].copy()
    print(f"  NHS trust R-codes: {len(df)}")

    # Extract year from status string
    def extract_year(s):
        import re
        m = re.search(r'(\d{4}-\d{2})', s)
        return m.group(1) if m else None

    def classify_status(s):
        s_lower = s.lower()
        if 'not met' in s_lower:
            return 'not_met'
        if 'not published' in s_lower:
            return 'not_published'
        if 'approaching' in s_lower:
            return 'approaching'
        if 'exceeded' in s_lower or 'met' in s_lower:
            return 'met'
        return 'unknown'

    out = pd.DataFrame()
    out['org_code']          = df['Code']
    out['org_name']          = df['Organisation Name'].astype(str).str.strip()
    out['dspt_status']       = df['Status']
    out['dspt_year']         = df['Status'].apply(extract_year)
    out['dspt_classification'] = df['Status'].apply(classify_status)
    out['dspt_standards_met']  = (out['dspt_classification'] == 'met').astype(int)
    out['dspt_approaching']    = (out['dspt_classification'] == 'approaching').astype(int)
    out['dspt_not_met']        = out['dspt_classification'].isin(['not_met', 'not_published']).astype(int)

    out = out.dropna(subset=['org_code'])

    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print("\n-- Summary --")
    print(f"  Trusts        : {len(out)}")
    print(f"  Columns       : {out.shape[1]}")
    print(f"\n  Classification distribution:")
    print(out['dspt_classification'].value_counts().to_string())
    print(f"\n  Year distribution:")
    print(out['dspt_year'].value_counts().sort_index().to_string())

    not_met = out[out['dspt_not_met'] == 1]
    if not not_met.empty:
        print(f"\n  Trusts NOT meeting standards ({len(not_met)}):")
        print(not_met[['org_code', 'org_name', 'dspt_status']].to_string(index=False))

    print("\nDSPT ingest complete.")


if __name__ == "__main__":
    ingest_dspt()
