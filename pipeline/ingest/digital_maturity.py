"""
TrustPulse -- pipeline/ingest/digital_maturity.py
Ingests NHS Digital Maturity Assessment (DMA) 2025 trust-level scores.

Output:
    data/processed/digital_maturity_clean.csv

Metrics per trust (2025 assessment):
    dma_well_led            : Well Led pillar score (1-5)
    dma_smart_foundations   : Ensure Smart Foundations pillar score
    dma_safe_practice       : Safe Practice pillar score
    dma_support_workforce   : Support Workforce pillar score
    dma_empower_people      : Empower People pillar score
    dma_improve_care        : Improve Care pillar score
    dma_healthy_populations : Healthy Populations pillar score
    dma_overall             : mean of all 7 pillar scores

Source:
    data/raw/digital_maturity/Digital+Maturity+Assessment+Results+Data+File+v2.xlsx
    Sheet: SC - 2025 Pillar Summary. Acute trusts only.
    Source: NHS England Digital Maturity Assessment 2025.

Notes:
    - Self-assessment against NHS What Good Looks Like (WGLL) framework
    - Scores range 1-5. Higher = more digitally mature.
    - National median approximately 2.4-2.8 across pillars
    - No org_code in source -- fuzzy matched to TrustPulse spine on provider name
    - 134 acute trusts in 2025 assessment
"""

import os
import glob
import pandas as pd
import numpy as np

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw", "digital_maturity")
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
MASTER_PATH = os.path.join(PROCESSED, "trust_master.csv")
OUTPUT_FILE = os.path.join(PROCESSED, "digital_maturity_clean.csv")


def build_name_lookup():
    """Build lookup from trust name to org_code using spine."""
    if not os.path.exists(MASTER_PATH):
        return {}
    master = pd.read_csv(MASTER_PATH, usecols=["org_code", "org_name"], dtype=str)
    master = master.drop_duplicates(subset=["org_code"])
    lookup = {}
    for _, row in master.iterrows():
        name = str(row["org_name"]).strip().upper()
        lookup[name] = row["org_code"]
    return lookup


def fuzzy_match(dma_name, lookup):
    """Match DMA provider name to org_code."""
    norm = dma_name.strip().upper()
    if norm in lookup:
        return lookup[norm]
    # Remove common suffixes
    for suffix in [" NHS FOUNDATION TRUST", " NHS TRUST", " FOUNDATION TRUST",
                   " TEACHING HOSPITALS", " UNIVERSITY HOSPITALS"]:
        short = norm.replace(suffix, "").strip()
        for spine_name, code in lookup.items():
            spine_short = spine_name
            for s in [" NHS FOUNDATION TRUST", " NHS TRUST", " FOUNDATION TRUST"]:
                spine_short = spine_short.replace(s, "").strip()
            if short == spine_short:
                return code
    # Partial word match
    ne_words = set(norm.split()) - {"NHS", "AND", "THE", "OF", "TRUST",
                                     "FOUNDATION", "UNIVERSITY", "TEACHING"}
    best_code, best_score = None, 0
    for spine_name, code in lookup.items():
        spine_words = set(spine_name.split()) - {"NHS", "AND", "THE", "OF", "TRUST",
                                                   "FOUNDATION", "UNIVERSITY", "TEACHING"}
        if not ne_words:
            continue
        score = len(ne_words & spine_words) / len(ne_words)
        if score > best_score and score >= 0.75:
            best_score = score
            best_code = code
    return best_code


def ingest_digital_maturity():
    print("=" * 60)
    print("TrustPulse | Digital Maturity Assessment Ingest")
    print("=" * 60)

    files = glob.glob(os.path.join(RAW_DIR, "*.xlsx"))
    if not files:
        print("ERROR: No xlsx file found")
        return

    filepath = files[0]
    print(f"Loading: {os.path.basename(filepath)}")

    raw = pd.read_excel(filepath, sheet_name='SC - 2025 Pillar Summary', header=10)
    raw.columns = ['blank', 'Region', 'ICS', 'Provider', 'Care_Setting',
                   'Well_Led', 'Smart_Foundations', 'Safe_Practice',
                   'Support_Workforce', 'Empower_People', 'Improve_Care',
                   'Healthy_Populations']

    # Filter to acute trusts only, remove blank/header rows
    df = raw[raw['Provider'].notna() & (raw['Provider'].astype(str).str.strip() != '')].copy()
    df = df[~df['Provider'].astype(str).str.contains('Provider|England', na=True)].copy()
    df = df[df['Care_Setting'].astype(str).str.contains('Acute', case=False, na=False)].copy()
    print(f"  Acute trusts in file: {len(df)}")

    # Fuzzy match to org_code
    lookup = build_name_lookup()
    print(f"  Spine lookup: {len(lookup)} trust names")

    rows = []
    unmatched = []
    for _, row in df.iterrows():
        name = str(row['Provider']).strip()
        code = fuzzy_match(name, lookup)
        if code:
            rows.append({
                'org_code': code,
                'org_name_source': name,
                'dma_well_led':            pd.to_numeric(row['Well_Led'], errors='coerce'),
                'dma_smart_foundations':   pd.to_numeric(row['Smart_Foundations'], errors='coerce'),
                'dma_safe_practice':       pd.to_numeric(row['Safe_Practice'], errors='coerce'),
                'dma_support_workforce':   pd.to_numeric(row['Support_Workforce'], errors='coerce'),
                'dma_empower_people':      pd.to_numeric(row['Empower_People'], errors='coerce'),
                'dma_improve_care':        pd.to_numeric(row['Improve_Care'], errors='coerce'),
                'dma_healthy_populations': pd.to_numeric(row['Healthy_Populations'], errors='coerce'),
            })
        else:
            unmatched.append(name)

    out = pd.DataFrame(rows)
    if not out.empty:
        pillar_cols = [c for c in out.columns if c.startswith('dma_')]
        out['dma_overall'] = out[pillar_cols].mean(axis=1).round(2)

    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")

    print(f"\n-- Summary --")
    print(f"  Matched       : {len(out)} trusts")
    print(f"  Unmatched     : {len(unmatched)}")
    if unmatched:
        print(f"  Unmatched names:")
        for n in unmatched:
            print(f"    {n}")

    if not out.empty:
        print(f"\n  Score ranges (overall):")
        for col in ['dma_well_led','dma_smart_foundations','dma_safe_practice',
                    'dma_support_workforce','dma_empower_people','dma_improve_care',
                    'dma_healthy_populations','dma_overall']:
            vals = out[col].dropna()
            print(f"    {col:<30} median={vals.median():.2f}  max={vals.max():.2f}")

        print(f"\n  Top 10 most digitally mature (by overall score):")
        top10 = out.nlargest(10, 'dma_overall')[['org_code','org_name_source','dma_overall']]
        print(top10.to_string(index=False))

    print("\nDigital maturity ingest complete.")


if __name__ == "__main__":
    ingest_digital_maturity()
