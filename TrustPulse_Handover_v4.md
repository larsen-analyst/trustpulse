# TrustPulse — Project Handover Document v4
**Prepared for:** Larsen Peter Anandh
**Date:** June 2026
**Purpose:** Complete context document for continuing TrustPulse development in a new chat session
**Previous handover:** TrustPulse_Handover_v3.md (superseded by this document)

---

## Who I Am

- **Name:** Larsen Peter Anandh
- **Course:** MSc Sport and Exercise Science, Performance Analysis, University of Essex
- **Course ends:** August 2026
- **Current visa:** Student Visa, leave to remain expires January 2027
- **GitHub:** github.com/larsen-analyst
- **Previous project:** CricIQ (Python Flask, Claude API, React, natural language cricket analytics)
- **Email:** plarsen796@gmail.com

---

## What TrustPulse Is

TrustPulse is an independent NHS performance and operational efficiency analytics platform built entirely on publicly available NHS data. It is being built for two purposes:

1. As a portfolio project to support NHS Band 5 analyst job applications
2. As a commercial product to be sold to NHS trusts, with the Innovator Founder Visa as the route to establishing a company in the UK

**One-line pitch:**
TrustPulse connects NHS workforce sickness data to A&E performance outcomes, operational efficiency signals, and cost intelligence to surface early warning signals for NHS trust directors, helping them identify deterioration before it appears in headline figures and quantify the financial cost of inefficiency using only public data.

---

## GitHub Repository

**URL:** github.com/larsen-analyst/trustpulse

**Current state of repo (all committed and pushed):**
- All pipeline ingest scripts complete
- join.py and analyse.py complete
- Full Flask app (app/, templates/, run.py) committed
- vacancies.py and staff_survey.py committed
- Latest commit: Phase 8 Flask app

---

## Local Project Location

**Path:** `D:\Projects\TrustPulse\`

**Complete folder structure:**
```
TrustPulse\
├── data\
│   ├── raw\
│   │   ├── ae\
│   │   ├── sickness\
│   │   ├── rtt\
│   │   ├── workforce\
│   │   ├── beds\
│   │   ├── discharge_delays\
│   │   ├── cancelled_ops\
│   │   ├── cqc\
│   │   ├── oversight\
│   │   ├── vacancies\         (NEW — nhs-vac-stats-apr15-mar26-eng-tables.xlsx)
│   │   ├── staff_survey\      (NEW — NSS-Benchmark-report-excel-data-for-2021-2025-v2.xlsx)
│   │   ├── finance\           (NEW — PDFs downloaded, NOT YET INGESTED)
│   │   └── outpatients\       (FOLDER MISSING — needs download)
│   └── processed\
│       ├── ae_clean.csv
│       ├── sickness_trust_clean.csv
│       ├── rtt_clean.csv
│       ├── workforce_clean.csv
│       ├── beds_sitrep_clean.csv
│       ├── beds_kh03_clean.csv
│       ├── discharge_clean.csv
│       ├── cancelled_ops_quarterly_clean.csv
│       ├── cancelled_ops_monthly_clean.csv
│       ├── cqc_clean.csv
│       ├── oversight_clean.csv
│       ├── vacancies_clean.csv        (NEW — 6,720 rows, regional benchmarks)
│       ├── staff_survey_clean.csv     (NEW — 981 rows, 206 trusts, 2021-2025)
│       ├── trust_master.csv           (9,624 rows, 221 trusts, 81 cols)
│       ├── trust_profiles.csv         (221 rows, 187 cols — analysis output)
│       └── trust_risk_scores.csv
├── src\
├── notebooks\
├── static\
├── pipeline\
│   ├── __init__.py
│   ├── run_pipeline.py
│   ├── validate.py
│   ├── join.py
│   ├── analyse.py
│   └── ingest\
│       ├── ae.py, sickness.py, rtt.py, workforce.py
│       ├── beds.py, discharge.py, cancelled_ops.py
│       ├── cqc.py, oversight.py
│       ├── vacancies.py               (NEW)
│       ├── staff_survey.py            (NEW)
│       └── outpatients.py             (MISSING — blocked)
├── app\
│   ├── __init__.py
│   ├── data.py
│   └── routes.py
├── templates\
│   ├── base.html
│   ├── index.html
│   ├── trust.html
│   └── compare.html
├── run.py
└── TrustPulse_ProjectTracker_v8.html
```

---

## Python Packages Installed

```
pandas, flask, plotly, matplotlib, python-dateutil, jupyter, numpy,
openpyxl, xlrd (2.0.2), odfpy (1.4.1)
```

---

## What Has Been Built — Complete Status

### Phases 1-7: Data pipeline (COMPLETE)
All ingest scripts running. Full pipeline passes end to end. validate.py passes 11/11 checks.

### Phase 7d: Master join and analysis engine (COMPLETE)

**trust_master.csv:** 9,624 rows, 221 trusts, 81 columns
- Full date range April 2022 to March 2026
- All 11 datasets joined on trust code and date
- 50 derived metrics across all datasets
- Cross-dataset metrics: FTE per bed, delayed days per bed, nursing FTE trend

**trust_profiles.csv:** 221 rows, 187 columns
- Latest month, 3-month rolling average, prior 3-month average per metric
- Trend directions: Improving, Stable, Deteriorating, Insufficient Data
- RAG flags based on NHS published thresholds
- Peer comparison vs regional average
- Financial estimates using published NHS rates
- Composite risk scores: 66 Red, 155 Amber, 0 Green
- Total estimated annual inefficiency: £5,598,804,948
- Average per trust: £36,834,243

**Financial rates used (all NHS published):**
- Delayed discharge: £345 per bed day
- Cancelled operations: £3,000 per cancelled op (conservative average)
- Sickness absence: £200 per FTE day lost

**Top 10 highest-risk trusts (March 2026):**
1. University Hospitals of North Midlands NHS Trust — 63.5
2. The Dudley Group NHS Foundation Trust — 63.5
3. The Queen Elizabeth Hospital King's Lynn — 62.5
4. University Hospitals Birmingham NHS FT — 61.5
5. The Rotherham NHS Foundation Trust — 61.0
6. Doncaster and Bassetlaw Teaching Hospitals NHS FT — 61.0
7. Chesterfield Royal Hospital NHS FT — 60.5
8. Liverpool University Hospitals NHS FT — 60.5
9. Mid and South Essex NHS FT — 59.5
10. University Hospitals Coventry and Warwickshire — 59.0

### Phase 8: Flask app (COMPLETE — running at localhost:5000)

**To start:** `python run.py` from `D:\Projects\TrustPulse\`

**Pages:**
- `/` — Homepage: 66 Red, 155 Amber, £5.6bn headline, risk distribution donut chart, top 10 bar chart, full risk table
- `/trust/<org_code>` — Trust profile: financial headline banner, domain RAG cards, A&E and sickness trend charts, four detail panels (workforce, operational efficiency, RTT, CQC/oversight)
- `/compare` — Three-trust side-by-side comparison via API

**API endpoints:**
- `/api/trusts` — trust list for search autocomplete
- `/api/trust/<org_code>` — full trust profile as JSON
- `/api/risk-distribution` — donut chart data
- `/api/top-risks` — top 10 bar chart data
- `/api/region-averages` — regional averages

**Tech stack:** Flask, Plotly.js, DM Sans + DM Mono fonts, system default colour scheme (dark/light mode)

---

## New Datasets Ingested This Session

### vacancies_clean.csv
- 6,720 rows
- 7 NHS England regions, 5 sectors (Acute, Ambulance, Community, Mental Health, Specialist)
- 3 staff groups (All staff, Nursing and midwifery, Medical and dental)
- Quarterly data: June 2018 to March 2026
- Data types: vacancy_fte (absolute count) and vacancy_rate_pct
- **NOTE: Regional and sector level only — trust-level vacancy data is not publicly available**
- Used as: regional benchmark layer for contextual comparison

### staff_survey_clean.csv
- 981 rows
- 206 trusts across all trust types
- 5 years: 2021, 2022, 2023, 2024, 2025
- 13 metrics per trust per year (all scored out of 10, higher is better):
  - PP1: Compassionate and inclusive
  - PP2: Recognised and rewarded
  - PP3: Voice that counts
  - PP3_2: Raising concerns (regulatory risk signal — declining 6.59→6.41)
  - PP4: Safe and healthy
  - PP4_1: Health and safety climate
  - PP4_2: Burnout (workforce crisis signal — national avg 5.01/10)
  - PP4_3: Negative experiences
  - PP5: Always learning
  - PP6: Work flexibly
  - PP7: We are a team
  - theme_engagement: Staff engagement (national avg 6.79/10)
  - theme_morale: Morale (national avg 5.93/10)
- Join key: org_code matches spine org_code
- Source: nhsstaffsurveys.com/results/local-results

---

## Next Steps — Immediate Priority (New Chat)

### Task 1 — Finance data (NEXT UP)
Larsen has downloaded NHS financial performance report PDFs. These contain trust-level surplus/deficit data.

**Files Larsen has (in data/raw/finance/):**
- Financial performance report 2024/25 Q4 (full year outturn)
- Financial performance report 2023/24 Q4 (full year outturn)
- Financial performance report 2025/26 Q3 (most recent)

**What these contain:** Trust-level Plan £m, Actual £m, Variance £m, Variance % of turnover, broken down by ICS/region. Tables for every NHS trust in England.

**What to do:** Upload the PDFs to the new chat. Inspect structure. Write `pipeline/ingest/finance.py` to extract tables from PDFs and produce `data/processed/finance_clean.csv`.

**Key columns to extract:** trust_name, ics_name, region, year, quarter, plan_gbp_m, actual_gbp_m, variance_gbp_m, variance_pct_turnover, in_deficit (Y/N)

**NOTE:** No org_code in these PDFs — trust names must be matched to org codes using a fuzzy name match against trust_master.csv org_name column.

### Task 2 — After finance.py is done
Update join.py to incorporate:
- staff_survey_clean.csv (join on org_code + year, use most recent year as snapshot)
- vacancies_clean.csv (join on region + sector as benchmark, not trust level)
- finance_clean.csv (join on org_code)

### Task 3 — After join.py updated
Re-run analyse.py to refresh trust_profiles.csv with new data.

### Task 4 — Remaining data gaps (in priority order)
After finance is done, remaining high-value datasets:
1. Ambulance handover delays (monthly CSV from NHS England UEC data)
2. Outpatient DNA rates (annual Excel from NHS Digital — currently blocked)
3. GIRFT data (trust-level readmission and LOS outliers)
4. PHE Fingertips preventable admissions (API or CSV)

### Task 5 — Deployment (Phase 9)
Deploy to Render once data is complete. Requirements file needed. Gunicorn for production server.

---

## Data Sources Status

| Dataset | Status | File location |
|---|---|---|
| A&E | Ingested | processed/ae_clean.csv |
| Sickness | Ingested | processed/sickness_trust_clean.csv |
| RTT | Ingested | processed/rtt_clean.csv |
| Workforce | Ingested | processed/workforce_clean.csv |
| Beds sitrep | Ingested | processed/beds_sitrep_clean.csv |
| Beds KH03 | Ingested | processed/beds_kh03_clean.csv |
| Discharge | Ingested | processed/discharge_clean.csv |
| Cancelled ops monthly | Ingested | processed/cancelled_ops_monthly_clean.csv |
| Cancelled ops quarterly | Ingested | processed/cancelled_ops_quarterly_clean.csv |
| CQC ratings | Ingested | processed/cqc_clean.csv |
| NHS Oversight Framework | Ingested | processed/oversight_clean.csv |
| NHS Vacancy Statistics | Ingested | processed/vacancies_clean.csv |
| NHS Staff Survey 2021-2025 | Ingested | processed/staff_survey_clean.csv |
| NHS Financial positions | Downloaded as PDFs — NOT YET INGESTED | raw/finance/ |
| Outpatients / DNA | NOT DOWNLOADED | — |
| Ambulance handover delays | NOT DOWNLOADED | — |
| GIRFT | NOT DOWNLOADED | — |

---

## Key Technical Discoveries (All Sessions)

1. NHS sickness files — only "All staff groups" exists, no breakdown by staff type
2. Sickness reason codes: S10=anxiety, S11=back, S12=MSK, S13=cold/flu
3. Sickness fte_days_lost_reason column = days lost for that specific reason
4. Workforce file is long format — data_type = FTE or HC, value column = total
5. Staff groups in workforce: HCHS Doctors, Nurses & health visitors, Midwives, Total etc.
6. A&E period format: MSitAE-APRIL-2022 — strip prefix, parse month-year
7. CQC ODS file — 1GB uncompressed XML, header found programmatically
8. CQC join key — use provider_id not location_ods_code
9. Oversight Trust_code = org_code for joins
10. run_pipeline.py uses runpy — odfpy must be installed in venv for CQC
11. CQC takes 8-10 minutes to load — normal
12. trust_profiles.csv is the Flask app input — loaded once at startup via lru_cache
13. Jinja2 does not have enumerate filter built in — register it in app/__init__.py
14. NHS vacancy data is regional only — no trust-level public data exists
15. NHS Staff Survey org_id = trust org_code (e.g. R0A, RRK)
16. Staff Survey PP3_2 (raising concerns) declining nationally year on year — important signal
17. Financial performance reports contain trust-level £m figures but as HTML/PDF tables — no downloadable CSV exists

---

## Important Rules for the New Chat

1. Larsen is separate from Pavithra. Do not mix their contexts.
2. TrustPulse uses only public NHS data. No internal trust data.
3. Every financial estimate must show formula, source, and disclaimer.
4. Never fabricate data, assume missing values, or fill gaps without clear labelling.
5. One step at a time. Confirm before moving to next task.
6. Always inspect files before writing any ingest script.
7. Commit to GitHub after every completed script.
8. run_pipeline.py uses runpy for all scripts. odfpy must be in venv.
9. CQC ODS file takes 8-10 minutes. Normal.
10. trust_profiles.csv loads via lru_cache in app/data.py.
11. Jinja2 enumerate filter must be registered in app/__init__.py.
12. Finance PDF tables have trust names but no org codes — use fuzzy matching against trust_master.csv.
13. Agency/bank spend data is NOT publicly available at trust level — confirmed via search.
14. Vacancy data is regional only — clearly label as benchmark, not trust-specific.

---

## Financial Rates (All NHS Published)

| Metric | Rate | Source |
|---|---|---|
| DNA cost | £120 per missed appointment | NHS England published rate |
| Delayed discharge | £345 per delayed bed day | NHS England September 2025 |
| Cancelled operations | £3,000 per cancelled op (conservative) | NHS England reference costs |
| Sickness cost | £200 per FTE day lost | Approximate average daily staff cost |

---

## Commercial Route to Market

1. Build product fully, deploy on Render
2. Register company at Companies House (£50, 1 day)
3. Cyber Essentials Basic (~£300-500)
4. DTAC self-assessment (free)
5. Three-part demo: risk flag, false economy, peer comparison
6. Three-month free POC pilot
7. G-Cloud registration

**Pricing:**
- Single trust: £8,000-12,000/year
- ICB bundle (5-10 trusts): £30,000-50,000/year
- Regional (20-30 trusts): £80,000-120,000/year

---

## Innovator Founder Visa Timeline

- Course ends: August 2026
- Leave to remain expires: January 2027
- Window: August to December 2026 (5 months)
- Endorsing body: Innovate UK (recommended)

---

## Key URLs

| Dataset | URL |
|---|---|
| NHS Financial performance reports | england.nhs.uk/publication/financial-performance-reports |
| NHS Staff Survey local results | nhsstaffsurveys.com/results/local-results |
| NHS Vacancy Statistics | digital.nhs.uk/data-and-information/publications/statistical/nhs-vacancies-survey |
| NHS A&E statistics | england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity |
| CQC ratings | cqc.org.uk/about-us/transparency/using-cqc-data |
| NHS Oversight Framework | england.nhs.uk/nhs-oversight-framework/segmentation-and-league-tables |
| TrustPulse GitHub | github.com/larsen-analyst/trustpulse |
