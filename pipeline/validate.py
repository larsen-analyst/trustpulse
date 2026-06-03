"""
pipeline/validate.py
TrustPulse — Data quality validation script

Runs after all ingest scripts complete (called automatically by run_pipeline.py).
Checks every processed CSV for:
  - File exists and is non-empty
  - Row count is within expected range
  - No fully empty rows
  - Key identifier columns have no nulls
  - Date range is as expected
  - No duplicate rows on primary key

Can also be run standalone:
    python pipeline/validate.py
"""

import pandas as pd
from pathlib import Path
import sys


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR   = Path(__file__).resolve().parents[1]
PROCESSED  = BASE_DIR / "data" / "processed"


# ---------------------------------------------------------------------------
# Validation registry
# Each entry defines expectations for one processed file
# ---------------------------------------------------------------------------

CHECKS = [
    {
        "file":        "ae_clean.csv",
        "min_rows":    9000,
        "max_rows":    15000,
        "pk":          ["org_code", "period"],
        "notnull":     ["org_code", "period"],
        "date_col":    None,   # period column is not a standard date format
    },
    {
        "file":        "sickness_trust_clean.csv",
        "min_rows":    5000,
        "max_rows":    15000,
        "pk":          ["org_code", "period_date"],
        "notnull":     ["org_code", "period_date"],
        "date_col":    "period_date",
        "date_min":    "2024-01-01",
        "date_max":    "2027-01-01",
    },
    {
        "file":        "rtt_clean.csv",
        "min_rows":    5000000,
        "max_rows":    15000000,
        "pk":          None,
        "notnull":     ["provider_org_code", "period_date"],
        "date_col":    "period_date",
        "date_min":    "2022-01-01",
        "date_max":    "2027-01-01",
    },
    {
        "file":        "workforce_clean.csv",
        "min_rows":    100000,
        "max_rows":    250000,
        "pk":          None,
        "notnull":     ["org_code", "period_date"],
        "date_col":    "period_date",
        "date_min":    "2022-01-01",
        "date_max":    "2027-01-01",
    },
    {
        "file":        "beds_sitrep_clean.csv",
        "min_rows":    5000,
        "max_rows":    15000,
        "pk":          None,   # Multiple rows per org per date (bed types) - no simple PK
        "notnull":     ["period_date"],
        "date_col":    "period_date",
        "date_min":    "2022-01-01",
        "date_max":    "2027-01-01",
    },
    {
        "file":        "beds_kh03_clean.csv",
        "min_rows":    2000,
        "max_rows":    8000,
        "pk":          None,   # Multiple rows per org per year (sectors) - no simple PK
        "notnull":     ["org_code"],
        "date_col":    None,   # Date stored as nhs_year (e.g. 2022/23) - not parseable
    },
    {
        "file":        "discharge_clean.csv",
        "min_rows":    3000,
        "max_rows":    10000,
        "pk":          ["org_code", "period_date"],
        "notnull":     ["org_code", "period_date"],
        "date_col":    "period_date",
        "date_min":    "2023-01-01",
        "date_max":    "2027-01-01",
    },
    {
        "file":        "cancelled_ops_quarterly_clean.csv",
        "min_rows":    1500,
        "max_rows":    5000,
        "pk":          ["org_code", "period_date"],
        "notnull":     ["org_code", "period_date"],
        "date_col":    "period_date",
        "date_min":    "2022-01-01",
        "date_max":    "2027-01-01",
    },
    {
        "file":        "cancelled_ops_monthly_clean.csv",
        "min_rows":    1500,
        "max_rows":    5000,
        "pk":          ["org_code", "period_date"],
        "notnull":     ["org_code", "period_date"],
        "date_col":    "period_date",
        "date_min":    "2022-01-01",
        "date_max":    "2027-01-01",
    },
    {
        "file":        "cqc_clean.csv",
        "min_rows":    300,
        "max_rows":    2000,
        "pk":          ["location_id"],
        "notnull":     ["location_id", "provider_name"],
        "date_col":    None,
    },
    {
        "file":        "oversight_clean.csv",
        "min_rows":    100,
        "max_rows":    500,
        "pk":          ["Trust_code"],
        "notnull":     ["Trust_code", "Trust_name"],
        "date_col":    None,
    },
]

# Optional files — warn but do not fail if missing
OPTIONAL_FILES = {"outpatients_clean.csv"}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_file(check):
    name    = check["file"]
    fpath   = PROCESSED / name
    issues  = []
    warns   = []

    # 1. File exists
    if not fpath.exists():
        if name in OPTIONAL_FILES:
            return name, "SKIPPED", [], [f"Optional file not found: {fpath}"]
        issues.append(f"File not found: {fpath}")
        return name, "FAILED", issues, warns

    # 2. Load
    try:
        # For large files skip full load — use chunked row count
        if check.get("min_rows", 0) > 500000:
            row_count = sum(1 for _ in open(fpath, encoding="utf-8")) - 1
            df = pd.read_csv(fpath, nrows=1000, dtype=str)
            df_sample = True
        else:
            df = pd.read_csv(fpath, dtype=str)
            row_count = len(df)
            df_sample = False
    except Exception as e:
        issues.append(f"Could not load file: {e}")
        return name, "FAILED", issues, warns

    # 3. Row count
    min_rows = check.get("min_rows")
    max_rows = check.get("max_rows")
    if min_rows and row_count < min_rows:
        issues.append(f"Row count {row_count:,} is below minimum {min_rows:,}")
    elif max_rows and row_count > max_rows:
        warns.append(f"Row count {row_count:,} exceeds expected maximum {max_rows:,}")

    # 4. No fully empty rows (sample only for large files)
    empty_rows = df.isnull().all(axis=1).sum()
    if empty_rows > 0:
        warns.append(f"{empty_rows} fully empty rows found")

    # 5. Not-null checks
    for col in check.get("notnull", []):
        if col in df.columns:
            null_count = df[col].isnull().sum()
            if null_count > 0:
                issues.append(f"Column '{col}' has {null_count} null values")
        else:
            warns.append(f"Expected column '{col}' not found in file")

    # 6. Date range check (skip for large files using sample)
    date_col = check.get("date_col")
    if date_col and date_col in df.columns and not df_sample:
        try:
            dates = pd.to_datetime(df[date_col], errors="coerce")
            valid_dates = dates.dropna()
            if len(valid_dates) == 0:
                warns.append(f"Date column '{date_col}' has no parseable dates")
            else:
                actual_min = valid_dates.min()
                actual_max = valid_dates.max()
                date_min = pd.Timestamp(check["date_min"])
                date_max = pd.Timestamp(check["date_max"])
                if actual_min < date_min:
                    warns.append(
                        f"Earliest date {actual_min.date()} is before expected {check['date_min']}"
                    )
                if actual_max > date_max:
                    warns.append(
                        f"Latest date {actual_max.date()} is after expected {check['date_max']}"
                    )
        except Exception as e:
            warns.append(f"Could not parse date column '{date_col}': {e}")

    # 7. Duplicate primary key check (skip for large files)
    pk = check.get("pk")
    if pk and not df_sample:
        pk_cols = [c for c in pk if c in df.columns]
        if len(pk_cols) == len(pk):
            dup_count = df.duplicated(subset=pk_cols).sum()
            if dup_count > 0:
                issues.append(
                    f"Found {dup_count} duplicate rows on primary key {pk_cols}"
                )
        else:
            missing_pk = [c for c in pk if c not in df.columns]
            warns.append(f"Primary key columns not found: {missing_pk}")

    status = "FAILED" if issues else ("WARNED" if warns else "OK")
    return name, status, issues, warns


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print("[validate] Running data quality checks...")
    print("=" * 60)

    all_results = []
    for check in CHECKS:
        name, status, issues, warns = validate_file(check)
        all_results.append((name, status, issues, warns))

        status_label = {
            "OK":      "[OK]     ",
            "WARNED":  "[WARN]   ",
            "FAILED":  "[FAILED] ",
            "SKIPPED": "[SKIPPED]",
        }.get(status, status)

        print(f"{status_label} {name}")
        for issue in issues:
            print(f"           ERROR: {issue}")
        for warn in warns:
            print(f"           WARN:  {warn}")

    print("=" * 60)

    passed  = [n for n, s, _, _ in all_results if s == "OK"]
    warned  = [n for n, s, _, _ in all_results if s == "WARNED"]
    failed  = [n for n, s, _, _ in all_results if s == "FAILED"]
    skipped = [n for n, s, _, _ in all_results if s == "SKIPPED"]

    print(f"  OK:      {len(passed)}")
    print(f"  Warned:  {len(warned)}")
    print(f"  Failed:  {len(failed)}")
    print(f"  Skipped: {len(skipped)}")
    print("=" * 60)

    if failed:
        print(f"[validate] Validation FAILED: {failed}")
        sys.exit(1)
    else:
        print("[validate] All checks passed.")


if __name__ == "__main__":
    run()
