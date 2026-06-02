"""
pipeline/ingest/cqc.py
TrustPulse — CQC ratings ingest script

Source file : data/raw/cqc/05_May_2026_Latest_ratings.ods
Output file : data/processed/cqc_clean.csv

Verified column names (from XML inspection of source file):
  location_id, location_ods_code, location_name, care_home,
  location_type, location_primary_inspection_category,
  location_street_address, location_address_line_2, location_city,
  location_post_code, location_local_authority, location_region,
  location_nhs_region, location_onspd_ccg_code, location_onspd_ccg,
  location_commissioning_ccg_code, location_commissioning_ccg_name,
  service_population_group, domain, latest_rating, publication_date,
  report_type, inherited_rating_y_n, url, provider_id, provider_name,
  brand_id, brand_name

NOTE: The ODS preamble contains table:number-rows-repeated="1048557" padding.
This makes skiprows unreliable. Header row is found programmatically instead.
"""

import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_PATH = BASE_DIR / "data" / "raw" / "cqc" / "05_May_2026_Latest_ratings.ods"
OUT_PATH = BASE_DIR / "data" / "processed" / "cqc_clean.csv"


# ---------------------------------------------------------------------------
# Constants — verified against source file XML
# ---------------------------------------------------------------------------

SHEET_NAME = "Locations"
DOMAINS = ["Overall", "Safe", "Effective", "Caring", "Responsive", "Well-led"]

# Exact normalised column names after normalise_columns()
SPG_COL        = "service_population_group"
DOMAIN_COL     = "domain"
RATING_COL     = "latest_rating"
PROVIDER_COL   = "provider_name"
INHERITED_COL  = "inherited_rating_y_n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalise_columns(df):
    import re
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"[/\s]+", "_", regex=True)
        .str.replace(r"[^a-z0-9_]", "", regex=True)
    )
    return df


def standardise_rating(series):
    mapping = {
        "outstanding":             "Outstanding",
        "good":                    "Good",
        "requires improvement":    "Requires improvement",
        "inadequate":              "Inadequate",
        "not rated":               "Not rated",
        "inspected but not rated": "Not rated",
        "no published rating":     "Not rated",
    }
    return series.str.strip().str.lower().map(mapping).fillna("Not rated")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print(f"[cqc] Reading: {RAW_PATH}")

    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Source file not found: {RAW_PATH}\n"
            "Download from: https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
        )

    # ------------------------------------------------------------------
    # 1. Load with header=None — find header row programmatically
    # ------------------------------------------------------------------
    df_raw = pd.read_excel(
        RAW_PATH,
        sheet_name=SHEET_NAME,
        engine="odf",
        header=None,
        dtype=str,
    )
    print(f"[cqc] Raw shape after load: {df_raw.shape}")

    # ------------------------------------------------------------------
    # 2. Find the row containing 'Location ID' and use it as header
    # ------------------------------------------------------------------
    header_row_idx = None
    for idx, row in df_raw.iterrows():
        if row.astype(str).str.strip().eq("Location ID").any():
            header_row_idx = idx
            break

    if header_row_idx is None:
        raise ValueError("[cqc] Could not find header row with 'Location ID'.")

    print(f"[cqc] Header row found at index: {header_row_idx}")

    df = df_raw.iloc[header_row_idx:].copy()
    df.columns = df.iloc[0].astype(str).str.strip()
    df = df.iloc[1:].reset_index(drop=True)

    # Drop fully empty rows and blank-named columns
    df = df.loc[:, [c for c in df.columns if str(c).strip() != '']]
    df = df.loc[:, [c for c in df.columns if str(c).strip().lower() != 'nan']]
    df = df.dropna(how="all")

    print(f"[cqc] Shape after header fix: {df.shape}")

    # ------------------------------------------------------------------
    # 3. Normalise column names
    # ------------------------------------------------------------------
    df = normalise_columns(df)

    # ------------------------------------------------------------------
    # 4. Filter: Service / Population Group == 'Overall'
    # ------------------------------------------------------------------
    before = len(df)
    df = df[df[SPG_COL].str.strip().str.lower() == "overall"].copy()
    print(f"[cqc] After SPG='Overall' filter: {len(df)} rows (from {before})")

    # ------------------------------------------------------------------
    # 5. Filter: NHS trusts only
    # ------------------------------------------------------------------
    nhs_mask = (
        df[PROVIDER_COL].str.contains("NHS", na=False, case=False) |
        df[PROVIDER_COL].str.contains("Foundation Trust", na=False, case=False)
    )
    before = len(df)
    df = df[nhs_mask].copy()
    print(f"[cqc] After NHS filter: {len(df)} rows (from {before})")
    print(f"[cqc] Unique providers: {df[PROVIDER_COL].nunique()}")

    # ------------------------------------------------------------------
    # 6. Standardise domain and rating values
    # ------------------------------------------------------------------
    df[DOMAIN_COL] = df[DOMAIN_COL].str.strip()
    df[RATING_COL] = standardise_rating(df[RATING_COL])
    df = df[df[DOMAIN_COL].isin(DOMAINS)].copy()
    print(f"[cqc] After domain filter: {len(df)} rows")
    print(f"[cqc] Domain counts:\n{df[DOMAIN_COL].value_counts().to_string()}")

    # ------------------------------------------------------------------
    # 7. Pivot to wide format: one row per location, one col per domain
    # ------------------------------------------------------------------
    pivot = df.pivot_table(
        index="location_id",
        columns=DOMAIN_COL,
        values=RATING_COL,
        aggfunc="first",
    )
    pivot.columns = [
        f"rating_{c.lower().replace(' ', '_')}" for c in pivot.columns
    ]
    pivot = pivot.reset_index()

    # ------------------------------------------------------------------
    # 8. Join metadata from Overall domain rows
    # ------------------------------------------------------------------
    meta_cols = [
        "location_id", "location_ods_code", "location_name",
        "location_type", "location_primary_inspection_category",
        "location_nhs_region", "location_region",
        "provider_id", PROVIDER_COL,
        INHERITED_COL, "publication_date", "url",
    ]
    meta = (
        df[df[DOMAIN_COL] == "Overall"][meta_cols]
        .drop_duplicates(subset=["location_id"])
        .copy()
    )
    result = meta.merge(pivot, on="location_id", how="left")
    result = result.rename(columns={INHERITED_COL: "inherited_rating"})

    # ------------------------------------------------------------------
    # 9. Final column order
    # ------------------------------------------------------------------
    rating_cols = sorted([c for c in result.columns if c.startswith("rating_")])
    final_cols = [
        "location_id", "location_ods_code", "location_name",
        "location_type", "location_primary_inspection_category",
        "location_nhs_region", "location_region",
        "provider_id", "provider_name",
        "inherited_rating", "publication_date", "url",
    ] + rating_cols
    final_cols = [c for c in final_cols if c in result.columns]
    result = result[final_cols]

    # ------------------------------------------------------------------
    # 10. Save
    # ------------------------------------------------------------------
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_PATH, index=False)

    print(f"[cqc] Output shape: {result.shape}")
    print(f"[cqc] Rating columns: {rating_cols}")
    print(f"[cqc] Sample:")
    print(result.head(3).to_string())
    print(f"[cqc] Saved to: {OUT_PATH}")
    print("[cqc] Done.")


if __name__ == "__main__":
    run()
