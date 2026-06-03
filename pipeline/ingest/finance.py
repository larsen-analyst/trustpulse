"""
finance.py -- NHS Financial Performance Report ingest script for TrustPulse
Source: Financial performance report 2025/26 Quarter 3 (NHS England)
Output: data/processed/finance_clean.csv

Extraction approach: OCR (tesseract 5) with bounding-box column detection.
This PDF has NO text layer (printed-to-PDF from browser); pdfplumber returns empty.
Column x-coordinates were calibrated from bounding-box inspection of page 5 at 150 DPI.

Output columns:
  trust_name                  -- cleaned trust/ICB name (pre-fuzzy-match to org_code)
  ics_name                    -- ICS from section heading
  region                      -- NHS England region from page heading
  year                        -- "2025/26"
  quarter                     -- "Q3"
  ytd_plan_inc_dsf_m          -- YTD Plan Inc DSF (£m)
  ytd_actual_inc_dsf_m        -- YTD Actual Inc DSF (£m)
  ytd_var_m                   -- YTD Variance (£m)
  var_pct_turnover            -- Variance % of turnover (float, e.g. -3.4)
  full_year_plan_exc_dsf_m    -- Full Year Plan Exc DSF (£m)
  forecast_outturn_exc_dsf_m  -- Forecast Outturn Exc DSF (£m)
  forecasting_receipt_dsf     -- "Y" if trust forecasts receiving DSF, else "N"
  in_deficit                  -- 1 if forecast_outturn < 0, else 0 (None if missing)
  row_type                    -- "provider", "icb", or "total"
"""

import os
import re
import logging
import pandas as pd
import pytesseract
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("finance_ingest")
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(_SCRIPT_DIR, "..", "..", "data", "raw", "finance",
                        "Financial_performance_report_2025-26Q3.pdf")
OUTPUT_PATH = os.path.join(_SCRIPT_DIR, "..", "..", "data", "processed", "finance_clean.csv")
YEAR = "2025/26"
QUARTER = "Q3"
OCR_DPI = 150

# ---------------------------------------------------------------------------
# Column x-center boundaries (pixels at 150 DPI on 612pt letter-size page)
# Calibrated from bounding-box inspection of page 5.
# ---------------------------------------------------------------------------
COL_NAME_MAX_X = 230  # Trust/ICB name column: x_center < 230
COL_DEFS = [
    # (column_name, x_center_min, x_center_max)
    ("ytd_plan_inc_dsf_m",          240, 320),
    ("ytd_actual_inc_dsf_m",        350, 430),
    ("ytd_var_m",                   460, 540),
    ("var_pct_turnover",            570, 650),
    ("allocation_ytd_icb_only_m",   690, 770),
    ("full_year_plan_exc_dsf_m",    800, 875),
    ("forecast_outturn_exc_dsf_m",  910, 990),
    ("forecasting_receipt_dsf",    1030, 1120),
]

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
RE_REGION = re.compile(
    r"Provider and ICB (?:Financial|financial) [Pp]osition.*?(?:--|—|-)\s*(.+Region)",
    re.IGNORECASE)
RE_ICS = re.compile(
    r"Surplus\s*/\s*\(Deficit\)\s+[Pp]osition.*?(?:--|—|-)\s*(.+(?:ICS|Collaborative|Partnership|Alliance))",
    re.IGNORECASE)
RE_NUMBER = re.compile(r"^\(?-?\d[\d,]*\.?\d*\)?%?$")
RE_YES = re.compile(r"^[Yy]es$")
RE_FOOTER = re.compile(r"https?://|/100$|\d{1,3}/100$|6/3/26|PM$|NHS England")
RE_HEADER_WORD = re.compile(
    r"^(YTD|Plan|Actual|Inc|DSF|Var|of|turno|ver|Alloca|tion|Full|Year|Forec|ast|Outtur|Exc|asting|receip|Only|ICB|Provi|der|Name|Provider|Surplus|Deficit|Position|Total|Combined|Against|Expenditure|Basis|Capital|specialised|Non-delegated|employee|non-pay|costs|summary)$",
    re.IGNORECASE)
RE_PUNCTUATION_ONLY = re.compile(r"^[|£\-—–/\\.,\s]+$")

# Words that look like numbers but aren't (OCR artefacts)
RE_PAGE_NUMBER = re.compile(r"^\d{1,3}/\d{2,3}$")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_number(s: str):
    """
    Convert OCR'd number string to float. Handles parentheses = negative.
    Returns None if unparseable.
    """
    if not s:
        return None
    s = str(s).strip()
    negative = s.startswith("(") and s.endswith(")")
    s = s.replace("(", "").replace(")", "").replace(",", "").strip()
    # Remove trailing % if present
    is_pct = s.endswith("%")
    s = s.replace("%", "").strip()
    if not s:
        return None
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def assign_col(x_center: int):
    """Return column name for a word's x_center, or None if outside all columns."""
    if x_center < COL_NAME_MAX_X:
        return "name"
    for col_name, x_min, x_max in COL_DEFS:
        if x_min <= x_center <= x_max:
            return col_name
    return None


def is_skip_word(w: str) -> bool:
    w = w.strip()
    if not w:
        return True
    if RE_FOOTER.search(w):
        return True
    if RE_HEADER_WORD.match(w):
        return True
    if RE_PUNCTUATION_ONLY.match(w):
        return True
    if RE_PAGE_NUMBER.match(w):
        return True
    if w in {"£m", "£", "|", "—", "-", "–"}:
        return True
    return False


def is_numeric_token(w: str) -> bool:
    """True if the token looks like a number from this report."""
    clean = w.replace("(", "").replace(")", "").replace(",", "").replace("%", "").replace(".", "")
    return bool(RE_NUMBER.match(w)) or (clean.isdigit() and len(clean) > 0)


def clean_trust_name(name: str) -> str:
    """
    Reconstruct a clean trust name from OCR fragments.
    OCR often inserts spaces mid-word due to narrow column rendering.
    Common suffixes are normalised: NHS FT, NHS Trust, NHST, ICB.
    """
    # Remove stray characters
    name = re.sub(r"[|£]", "", name)
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    # Normalise common suffix variants
    name = re.sub(r"\bNHSFT\b", "NHS FT", name, flags=re.IGNORECASE)
    name = re.sub(r"\bNHST\b", "NHS Trust", name, flags=re.IGNORECASE)
    name = re.sub(r"\bIcs\b", "ICS", name, flags=re.IGNORECASE)
    name = re.sub(r"\bIcb\b", "ICB", name, flags=re.IGNORECASE)
    return name


def classify_row_type(name: str) -> str:
    n = name.upper()
    if n.startswith("TOTAL"):
        return "total"
    if "ICB" in n and "NHS FT" not in n and "NHS TRUST" not in n and "NHST" not in n:
        return "icb"
    return "provider"


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def ocr_page_structured(page_num: int, pdf_path: str, dpi: int = OCR_DPI) -> pd.DataFrame:
    """
    Rasterize one PDF page using pymupdf and return pytesseract word-level bounding-box DataFrame.
    Uses pymupdf instead of pdftoppm for Windows compatibility.
    """
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]  # fitz is 0-indexed
    zoom = dpi / 72  # 72 is PDF default DPI
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    doc.close()
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    df = pytesseract.image_to_data(img, output_type=pytesseract.Output.DATAFRAME)
    df = df[df["conf"] > 25].copy()
    df["x_center"] = df["left"] + df["width"] // 2
    return df

def page_plain_text(df: pd.DataFrame) -> str:
    """Reconstruct flat text for heading detection."""
    if df.empty:
        return ""
    parts = []
    for (blk, ln), grp in df.groupby(["block_num", "line_num"]):
        parts.append(" ".join(grp.sort_values("word_num")["text"].tolist()))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parse one page
# ---------------------------------------------------------------------------

def parse_page(page_num: int, pdf_path: str, current_region: str, current_ics: str):
    """
    OCR one page. Extract trust rows and update region/ICS state.
    Returns: (rows: list[dict], updated_region: str, updated_ics: str)
    """
    df = ocr_page_structured(page_num, pdf_path)
    if df.empty:
        return [], current_region, current_ics

    plain = page_plain_text(df)

    m = RE_REGION.search(plain)
    if m:
        current_region = m.group(1).strip()

    m = RE_ICS.search(plain)
    if m:
        current_ics = m.group(1).strip()

    # Restrict to table area: below y=280 (header blocks end around y=260-280)
    table_df = df[df["top"] > 280].copy()
    if table_df.empty:
        return [], current_region, current_ics

    rows = []
    # Accumulate current row state
    curr = _empty_row()
    has_numeric = False

    def flush():
        nonlocal curr, has_numeric
        name = clean_trust_name(" ".join(curr["name_parts"]))
        if not name or not has_numeric or len(name) < 3:
            curr = _empty_row()
            has_numeric = False
            return None
        # Skip obvious header artefacts
        if is_skip_word(name) or RE_HEADER_WORD.match(name):
            curr = _empty_row()
            has_numeric = False
            return None

        def pick(col):
            parts = curr.get(col, [])
            if not parts:
                return None
            return parse_number("".join(parts))

        def pick_text(col):
            return " ".join(curr.get(col, [])).strip()

        var_pct_raw = pick_text("var_pct_turnover").replace("%", "")
        forecast = pick("forecast_outturn_exc_dsf_m")
        dsf_raw = pick_text("forecasting_receipt_dsf")
        forecasting_dsf = "Y" if RE_YES.search(dsf_raw) else "N"
        in_deficit = (1 if forecast is not None and forecast < 0
                      else (0 if forecast is not None else None))

        row = {
            "trust_name": name,
            "ics_name": current_ics,
            "region": current_region,
            "year": YEAR,
            "quarter": QUARTER,
            "ytd_plan_inc_dsf_m": pick("ytd_plan_inc_dsf_m"),
            "ytd_actual_inc_dsf_m": pick("ytd_actual_inc_dsf_m"),
            "ytd_var_m": pick("ytd_var_m"),
            "var_pct_turnover": parse_number(var_pct_raw) if var_pct_raw else None,
            "full_year_plan_exc_dsf_m": pick("full_year_plan_exc_dsf_m"),
            "forecast_outturn_exc_dsf_m": forecast,
            "forecasting_receipt_dsf": forecasting_dsf,
            "in_deficit": in_deficit,
            "row_type": classify_row_type(name),
        }
        curr = _empty_row()
        has_numeric = False
        return row

    prev_block = None
    for _, word_row in table_df.sort_values(["block_num", "top", "left"]).iterrows():
        w = str(word_row["text"]).strip()
        if not w:
            continue
        if is_skip_word(w):
            continue

        block = word_row["block_num"]
        x_c = word_row["x_center"]
        col = assign_col(x_c)
        if col is None:
            continue

        # New block starting in name column signals a new trust row
        if block != prev_block and col == "name" and curr["name_parts"] and has_numeric:
            r = flush()
            if r:
                rows.append(r)

        prev_block = block

        if col == "name":
            if not is_numeric_token(w) and not RE_YES.match(w):
                curr["name_parts"].append(w)
        else:
            curr[col].append(w)
            if is_numeric_token(w) or RE_YES.match(w):
                has_numeric = True

    # Flush final row on page
    r = flush()
    if r:
        rows.append(r)

    return rows, current_region, current_ics


def _empty_row():
    d = {"name_parts": []}
    for col_name, _, _ in COL_DEFS:
        d[col_name] = []
    return d


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(pdf_path: str = PDF_PATH, output_path: str = OUTPUT_PATH):
    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    log.info(f"PDF: {total_pages} pages. Starting OCR extraction (this takes ~5-8 minutes)...")

    all_rows = []
    current_region = "Unknown"
    current_ics = "Unknown"

    # Pages 1-4 are national-level summary tables, not trust rows
    for page_num in range(5, total_pages + 1):
        if page_num % 10 == 0:
            log.info(f"  Page {page_num}/{total_pages} | Region: {current_region[:30]}")
        try:
            rows, current_region, current_ics = parse_page(
                page_num, pdf_path, current_region, current_ics)
            all_rows.extend(rows)
        except Exception as e:
            log.warning(f"  Page {page_num} error: {e}")

    df = pd.DataFrame(all_rows)
    log.info(f"Raw extracted rows: {len(df)}")

    if df.empty:
        log.error("No rows extracted. Check PDF path and OCR output.")
        return df

    # Clean trust names
    df["trust_name"] = df["trust_name"].str.strip()
    df = df[df["trust_name"].str.len() > 2].copy()

    # Remove duplicate total/ICB rows that can appear when a page continues mid-table
    # Keep first occurrence of each (trust_name, year, quarter) combination
    # NOTE: Totals and ICB rows intentionally retained for reference but flagged
    df = df.drop_duplicates(subset=["trust_name", "year", "quarter", "row_type"], keep="first")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    log.info(f"Saved {len(df)} rows to {output_path}")

    # Summary statistics
    providers = df[df["row_type"] == "provider"]
    in_deficit_count = (providers["in_deficit"] == 1).sum()
    log.info(f"Provider rows: {len(providers)} | In deficit: {in_deficit_count}")
    log.info(f"Regions found: {df['region'].nunique()}")
    log.info(f"ICS found: {df['ics_name'].nunique()}")

    return df


if __name__ == "__main__":
    run()
