# TrustPulse — Project Handover v9
**Prepared for:** Larsen Peter Anandh
**Date:** 4 June 2026
**GitHub:** github.com/larsen-analyst/trustpulse
**Status:** Phase 8 complete. Flask app live and running. Full pipeline operational.

---

## Who This Is For

**Larsen Peter Anandh**
- MSc Sport and Exercise Science (Performance Analysis), University of Essex, graduating August 2026
- Student visa, leave to remain expires January 2027
- GitHub: github.com/larsen-analyst
- Email: plarsen796@gmail.com
- Previous project: CricIQ (Python Flask, Claude API, React, natural language cricket analytics)

---

## What TrustPulse Is

TrustPulse is an independent NHS performance and operational efficiency analytics platform built entirely on publicly available NHS data. Built for two purposes:

1. **Portfolio project** to support NHS Band 5 analyst and health data job applications
2. **Commercial product** to be sold to NHS trusts, with the Innovator Founder Visa as the route to establishing a company in the UK after course completion

**One-line pitch:**
TrustPulse connects NHS workforce, operational, financial, and quality data to surface early warning risk signals for NHS trust directors — helping them identify deteriorating performance before it appears in headline figures and quantify the financial cost of inefficiency using only public data.

**Commercial model:**
- POC pilot: 3 months free, one trust
- Single trust licence: £8,000–12,000/year
- ICB bundle (5–10 trusts): £30,000–50,000/year
- Regional (20–30 trusts): £80,000–120,000/year
- Route to market: G-Cloud Digital Marketplace, Health Systems Support Framework, direct approach to Directors of Finance/Performance

**Innovator Founder Visa:**
TrustPulse is intended to support an Innovator Founder Visa application. Window: August–December 2026. Endorsing body: Innovate UK (recommended). Requires consultation with a UK immigration solicitor specialising in this route before August 2026.

---

## Project Origin and Build History

### Before TrustPulse (early 2026)
- Larsen began with an NHS A&E waiting times analysis project at `E:\GitHUB\nhs-ae-analysis`
- Built a Python analysis script producing 5 charts: attendance trends, 4hr performance, seasonal patterns, Type 1 vs Type 2 split, year-on-year comparison
- This standalone analysis became the conceptual seed for TrustPulse

### TrustPulse concept (March–April 2026)
- Concept developed from the question: what if sickness rates are a leading indicator of A&E performance collapse?
- Expanded scope: connect workforce, sickness, beds, discharge, RTT, cancelled ops, CQC, oversight, finance into one analytical platform
- Target user identified: NHS Director of Finance or Head of Performance, not the CIO
- Commercial route scoped: G-Cloud, POC approach, Innovator Founder Visa pathway

### Phase 1–4: Notebooks and exploration (April–May 2026)
- Project moved to `D:\Projects\TrustPulse\`
- Jupyter notebooks built for A&E, sickness, beds, RTT, discharge, cancelled ops
- Data downloaded from NHS England and NHS Digital sources
- Core finding established: sickness rates, bed occupancy, and delayed discharge are correlated with A&E performance degradation

### Phase 5–6: Additional datasets (May 2026)
- RTT waiting times added (1.1GB, all specialties)
- Operational efficiency datasets added: beds sitrep, KH03, discharge delays, cancelled operations
- CQC ratings and NHS Oversight Framework scores added
- All data verified against NHS published sources

### Phase 7: Pipeline scripts (May–June 2026)
- All Jupyter notebooks converted to standalone Python ingest scripts
- `pipeline/ingest/` directory created with one script per dataset
- `pipeline/run_pipeline.py` master runner built (supports `--only` and `--skip` flags)
- `pipeline/validate.py` data quality validation script built
- `pipeline/join.py` built to merge all datasets into `trust_master.csv`
- `pipeline/analyse.py` first version built (later rewritten in this session)

### Phase 8: Additional data sources (June 2026)
- Staff survey ingest: `pipeline/ingest/staff_survey.py` — NHS Staff Survey 2021–2025, 206 trusts
- Vacancy benchmarks: `pipeline/ingest/vacancies.py` — regional rates by sector and staff group
- Finance ingest: `pipeline/ingest/finance.py` — Q3 2025/26 financial position, OCR from PDF using Tesseract
- Ambulance handover delays: `pipeline/ingest/ambulance.py` — Nov 2025 to Mar 2026, 148 trusts (Task 4a)

### This session (4 June 2026)
- `pipeline/join.py` rebuilt from scratch with correct column names verified against actual CSVs
- `pipeline/analyse.py` fully rewritten with real column names, 5 domain scores, composite RAG, narratives
- `app.py` Flask application written (dashboard, trust profiles, compare)
- All three pages verified working in browser

---

## Current State — What Is Built and Working

### Git log (last 10 commits)
```
54ce5d8 Phase 8: Flask app complete -- dashboard, trust profiles, compare page
b3f23f0 analyse.py: full risk scoring engine with correct column names, domain scores, composite RAG, narratives, peer comparisons
dc1328c join: fix column names, add finance fuzzy match, vacancy region bridge, ambulance merge
48c6d18 Phase 9c: handover v5 - finance, survey, vacancy complete, ambulance next
f69f2ca Phase 9c: add handover v4, project tracker v8, validate.py
7a6a45b Phase 9b: join.py updated - staff survey, vacancy benchmarks, finance data - 107 cols
8044d93 Phase 9a: finance.py ingest - 266 providers, 89 in deficit, 7 regions, 35 ICS
4512ebd Add staff_survey.py -- NHS Staff Survey 2021-2025, 206 trusts, 13 metrics
9ef3b68 Add vacancies.py -- regional NHS vacancy benchmarks, 6720 rows
bb9d30c Phase 8: Flask app -- homepage, trust profile, compare pages
```

### Data pipeline — all scripts verified and committed

| Script | Output | Coverage |
|---|---|---|
| `pipeline/ingest/ae.py` | `ae_clean.csv` 1.5MB | A&E attendances, Apr 2022–Mar 2026, 221 trusts |
| `pipeline/ingest/sickness.py` | `sickness_trust_clean.csv` 1.4MB | Staff sickness by trust, reason, staff group |
| `pipeline/ingest/workforce.py` | `workforce_clean.csv` 20MB | FTE by staff group, Apr 2019 onwards |
| `pipeline/ingest/beds.py` | `beds_sitrep_clean.csv` 1MB, `beds_kh03_clean.csv` 752KB | Daily sitrep + quarterly KH03 |
| `pipeline/ingest/discharge.py` | `discharge_clean.csv` 1.9MB | Delayed discharge bed days |
| `pipeline/ingest/cancelled_ops.py` | `cancelled_ops_monthly_clean.csv` 294KB | Cancelled operations |
| `pipeline/ingest/rtt.py` | `rtt_clean.csv` 1.1GB | RTT waiting times, all specialties |
| `pipeline/ingest/cqc.py` | `cqc_clean.csv` 126KB | CQC ratings by provider |
| `pipeline/ingest/oversight.py` | `oversight_clean.csv` 53KB | NHS Oversight Framework scores |
| `pipeline/ingest/staff_survey.py` | `staff_survey_clean.csv` 321KB | NHS Staff Survey 2021–2025, 206 trusts |
| `pipeline/ingest/vacancies.py` | `vacancies_clean.csv` 649KB | Regional vacancy rates by sector/staff group |
| `pipeline/ingest/finance.py` | `finance_clean.csv` 37KB | Q3 2025/26 financial position, OCR from PDF |
| `pipeline/ingest/ambulance.py` | `ambulance_clean.csv` 113KB | Ambulance handover delays, Nov 2025–Mar 2026 |

### Join layer — `pipeline/join.py`

Produces:
- `trust_master.csv` — 9,624 rows, 221 trusts, 170 columns, Apr 2022–Mar 2026
- `trust_profiles.csv` — 221 trusts, 315 columns, latest snapshot with 3m rolling averages

Key join details:
- Spine built from AE data (most complete time series, 221 trusts)
- All time series joined on `org_code + month` (left join)
- Ambulance: 93% null expected and correct — 5 months out of 48
- Finance: rapidfuzz fuzzy match on trust names vs oversight reference (193/266 matched, 138 low-confidence)
- Vacancies: joined via oversight region bridge (`org_code → Region → vacancy benchmark`)
- Snapshot joins (CQC, oversight, staff survey, finance) on `org_code` only

### Scoring engine — `pipeline/analyse.py`

Produces:
- `trust_profiles.csv` — rebuilt with correct column names and 3m rolling averages
- `trust_risk_scores.csv` — 221 trusts, 384 columns

**Five NHS oversight domains (0–100, higher = worse):**

| Domain | Weight | Key inputs |
|---|---|---|
| D1 Urgent & Emergency Care | 25% | ae_type1_4hr_performance, ae_12hr_breach_rate, amb_over60_pct |
| D2 Elective Care | 20% | pct_within_18_weeks, waiters_over52_per1000 |
| D3 Workforce | 20% | sickness_rate_overall, nursing_fte_trend, vac_benchmark_rate_all_pct |
| D4 Finance & Productivity | 20% | overall_adjusted_segment, fin_var_pct_turnover, productivity_growth_estimate, deficit_penalty |
| D5 Quality & Safety | 15% | cqc_overall_numeric, beds_occupancy_rate, delayed_days_per_100_beds, cancelled_ops_rate, cdiff_infection_rate |

- Composite >= 60 = Red, >= 35 = Amber, < 35 = Green
- Financial override: deficit trusts cannot score below 50
- **Current distribution: 27 Red, 180 Amber, 14 Green**, 16 financial overrides
- **Total estimated annual inefficiency: £6.85bn** (NHS published unit rates)
- Financial unit costs: delayed discharge £345/day, sickness £200/FTE day, cancelled ops £3,000/op

### Flask app — `app.py`

Run with `python app.py` → `http://localhost:5000`

| Route | Template | Content |
|---|---|---|
| `/` | `templates/index.html` | Summary cards, top 10 risk cards, filterable/sortable trust table |
| `/trust/<org_code>` | `templates/trust.html` | Domain scores, Plotly time series charts, cost block, RAG breakdown |
| `/compare` | `templates/compare.html` | Trust search, side-by-side metric table for up to 5 trusts |
| `/api/trusts` | JSON | All trusts, key columns |
| `/api/trust/<org_code>` | JSON | Single trust full profile |
| `/api/timeseries/<org_code>` | JSON | Last 48 months key metrics |

Design: dark theme, DM Mono + DM Sans, RAG colour coding, Plotly inline charts.

---

## How to Run the Full Pipeline

```bash
venv\Scripts\activate

# Individual ingest (if source data updated)
python pipeline\ingest\ambulance.py
python pipeline\ingest\ae.py
# etc.

# Rebuild everything
python pipeline\join.py
python pipeline\analyse.py

# Run the app
python app.py
```

---

## Known Issues and Technical Debt

### 1. Finance fuzzy match quality (medium priority)
- 138/193 matched rows scored below 75 (low confidence) due to OCR-corrupted trust names
- Fix: diagnostic script printing `(finance_name, matched_org_code, score)` for low-confidence pairs, then manual override CSV `pipeline/ingest/finance_name_overrides.csv`

### 2. Junk AE columns (low priority)
- `ae_unnamed:_22` through `ae_unnamed:_26` and `ae_a` are 100% null
- Artefacts from trailing empty columns in source Excel
- Fix: add drop list in `pipeline/ingest/ae.py` before saving

### 3. Sickness date warning (cosmetic)
- `UserWarning: Parsing dates in %d/%m/%Y format when dayfirst=False`
- Fix: add `dayfirst=True` to `pd.read_csv` in `join.py` line 84

### 4. Ambulance coverage gap
- Only Nov 2025–Mar 2026 (5 winter months)
- Re-run when NHS England publishes full 2025/26 annual file
- Source: https://www.england.nhs.uk/statistics/statistical-work-areas/uec-sitrep/

### 5. Low Red count (27 vs historical ~66)
- Oversight segment and finance variance are ~25% null
- Null defaults to Amber (score 50), not Red — correct behaviour
- Red count will rise as more data is populated or if thresholds are tuned

---

## Next Steps (priority order)

1. Finance name override table — fix 138 low-confidence fuzzy matches
2. Drop junk AE columns — one-line fix in `ingest/ae.py`
3. Sickness dayfirst warning — one-line fix in `join.py`
4. Trust profile charts — consider adding date range selector
5. Ambulance data refresh when full annual file published
6. Deploy to Render or Railway for public demo URL (needed for Innovator Founder Visa evidence)
7. PL-300 certification prep — Power BI dashboard using `trust_risk_scores.csv`
8. Company registration at Companies House (£50)
9. Cyber Essentials Basic certification (~£300–500)
10. G-Cloud Digital Marketplace registration

---

## Data Sources

| Dataset | Source | URL |
|---|---|---|
| A&E Attendances | NHS England | https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/ |
| Ambulance Handovers | NHS England UEC Sitrep | https://www.england.nhs.uk/statistics/statistical-work-areas/uec-sitrep/ |
| Beds (Sitrep + KH03) | NHS England | https://www.england.nhs.uk/statistics/statistical-work-areas/bed-availability-and-occupancy/ |
| Cancelled Operations | NHS England | https://www.england.nhs.uk/statistics/statistical-work-areas/cancelled-elective-operations/ |
| CQC Ratings | CQC | https://www.cqc.org.uk/about-us/transparency/using-cqc-data |
| Delayed Discharge | NHS England | https://www.england.nhs.uk/statistics/statistical-work-areas/discharge-delays-acute-data/ |
| Finance Q3 2025/26 | NHS England | https://www.england.nhs.uk/financial-accounting-and-reporting/nhs-financial-performance/ |
| NHS Oversight Framework | NHS England | https://www.england.nhs.uk/publication/nhs-oversight-framework/ |
| RTT Waiting Times | NHS England | https://www.england.nhs.uk/statistics/statistical-work-areas/rtt-waiting-times/ |
| Sickness Absence | NHS Digital | https://digital.nhs.uk/data-and-information/publications/statistical/nhs-sickness-absence-rates |
| Staff Survey | NHS England | https://www.nhsstaffsurveys.com/results/ |
| Vacancies | NHS Digital | https://digital.nhs.uk/data-and-information/publications/statistical/nhs-vacancies-survey |
| Workforce | NHS Digital | https://digital.nhs.uk/data-and-information/publications/statistical/nhs-workforce-statistics |

---

## Project Structure

```
D:\Projects\TrustPulse\
├── app.py                           Flask application (root level)
├── pipeline/
│   ├── __init__.py
│   ├── run_pipeline.py              Master runner (--only, --skip flags)
│   ├── join.py                      Builds trust_master.csv and trust_profiles.csv
│   ├── analyse.py                   Risk scoring engine, builds trust_risk_scores.csv
│   ├── validate.py                  Data quality checks
│   └── ingest/
│       ├── __init__.py
│       ├── ae.py
│       ├── ambulance.py             Task 4a -- added this session
│       ├── beds.py
│       ├── cancelled_ops.py
│       ├── cqc.py
│       ├── discharge.py
│       ├── finance.py               OCR-based, Tesseract required
│       ├── oversight.py
│       ├── rtt.py
│       ├── sickness.py
│       ├── staff_survey.py
│       ├── vacancies.py
│       └── workforce.py
├── templates/
│   ├── index.html                   Dashboard (standalone, no base.html dependency)
│   ├── trust.html                   Trust profile with Plotly charts
│   └── compare.html                 Side-by-side comparison, up to 5 trusts
├── static/                          Empty -- CSS is inline in templates
├── data/
│   ├── raw/                         Source files (not committed to git)
│   │   ├── ae/
│   │   ├── ambulance/
│   │   ├── beds/sitrep/ and kh03/
│   │   ├── cancelled_ops/
│   │   ├── cqc/
│   │   ├── discharge_delays/
│   │   ├── finance/
│   │   ├── oversight/
│   │   ├── rtt/
│   │   ├── sickness/trust/
│   │   ├── staff_survey/
│   │   ├── vacancies/
│   │   └── workforce/
│   └── processed/                   Generated CSVs (not committed to git)
│       ├── trust_master.csv         9,624 rows, 221 trusts, 170 cols, 10MB
│       ├── trust_profiles.csv       221 trusts, 315 cols, 526KB
│       └── trust_risk_scores.csv    221 trusts, 384 cols, 730KB
├── TrustPulse_Handover_v9.md        This document
└── TrustPulse_ProjectTracker_v8.html  Phase tracker (localStorage-based)
```

---

## Key Technical Rules

1. All data is public NHS data only. No internal trust data used or assumed.
2. Every financial estimate shows its formula, source, and disclaimer.
3. Never fabricate data or fill gaps with estimates unless clearly labelled.
4. The product is independent of any NHS employment — built on public data before any NHS job.
5. One step at a time. Confirm each step works before moving to the next.
6. Save to GitHub after completing any phase or significant milestone.
7. MeRLIN content (separate consulting work) is in US English. This project is in British English.
