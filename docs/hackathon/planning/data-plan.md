# Longaeva data plan — planning v1

October 1, 2026 · Phase 2 draft for review · Requirements: [requirements.md](requirements.md) (DR-*, ER-*). Approach context: [approach.md](approach.md) "Candidate sources and selection gates".

All checks below were run on October 1, 2026 from this machine using read-only HTTP requests with a declared User-Agent. "Verified" means the specific stated fact was observed today; it does not establish complete history, automation permission beyond what is stated, or predictive usefulness. No bulk ingestion, API-key registration or paid access occurred. Scripts used for the checks lived in `/tmp` and are not part of the repository.

## 1. Summary of findings

| Topic | Finding | Effect on plan |
| --- | --- | --- |
| Visa publication vintages | EDGAR `submissions` JSON lists 46 Item 2.02 earnings 8-Ks for Visa (CIK 1403161) from 2015-04-30 to 2026-07-28 with acceptance timestamps (typically 20:05Z = 16:05 ET, after the close). 10-Qs are accepted the same evening (e.g. 2024-07-23T22:12Z) or next morning; 10-Ks 2–6 weeks after the Q4 release. | Exact, externally verifiable cutoff timestamps exist for every candidate origin. Cutoff convention decided in §2.3. |
| Visa release content | The fiscal Q3 2024 release (filed 2024-07-23) states service revenue "is recognized based on payments volume in the prior quarter. All other revenue categories are recognized based on current quarter activity"; gives payments volume for both the prior quarter (March) and current quarter (June); provides a Key Business Drivers table with constant-dollar and nominal YoY growth for payments volume, cross-border volume ex-intra-Europe, total cross-border and processed transactions; gives category revenue, client incentives, net revenue, total operating expenses and special items; and says the financial outlook "is contained in the earnings presentation" on investor.visa.com. | Confirms MR-03 timing and MR-07 bases. Drivers are growth rates, not levels (MR-01). Guidance requires the IR presentation, not the 8-K (§3.1). |
| Visa XBRL | `data.sec.gov/api/xbrl/companyfacts/CIK0001403161.json` works without a key and carries `filed` dates and `frame` tags per value for standard tags (`Revenues`, `OperatingIncomeLoss`, `CostsAndExpenses`, `IncomeTaxExpenseBenefit`, `NonoperatingIncomeExpense`, `EffectiveIncomeTaxRateContinuingOperations`, …). Taxonomies present: dei, us-gaap, srt, invest, ffd. No Visa custom tags, so revenue categories, client incentives and operating KPIs are not in companyfacts. | Use XBRL for vintage-dated standard financials and cross-checks; parse release/10-Q HTML tables for categories, incentives and drivers (DRAFT-15). |
| Booking Holdings vintages | 49 Item 2.02 8-Ks (CIK 1075531) from 2014-11-04 to 2026-08-04 with acceptance timestamps (~20:03Z). Q1 releases late April/early May, Q2 early August, Q3 late Oct/early Nov, Q4 late February. | For every Visa origin the freshest Booking release is 10–12 weeks old and describes the quarter before the one Visa just reported, plus forward commentary. Timing mismatch is a named hypothesis risk (§3.2). |
| Census MARTS vintages | `census.gov/retail/marts/historic_releases.html` returned 272 links, including archived advance-release PDFs `www2.census.gov/retail/releases/historical/marts/advYYMM.pdf` (observed from `adv1512` onward; page references years 2000–2026). `marts_current.pdf` and the revised series `mrtssales92-present.xlsx` download without a key. | Vintage reconstruction is feasible via archived PDFs (DRAFT-16). The XLSX is a revised series and must not be used as a vintage (DR-04). API keys are not needed for the files. |
| Benchmarks and prices | FRED `fredgraph.csv?id=SP500` downloads without a key (daily price index, 10-year window from 2016-10). Ken French daily factors ZIP downloads. Shiller `ie_data.xls` downloads (monthly S&P composite price and dividends). Stooq returns a JavaScript challenge page for automated CSV requests. S&P DJI site returns 403. SSGA page loads but a guessed distribution-history file URL was 404. `api.nasdaq.com` timed out. Alpha Vantage and Tiingo documentation pages load; terms and limits not reviewed. `investor.visa.com` quarterly-earnings and dividend-history pages load (legacy Q4 Inc. site). | No verified free, redistributable daily S&P 500 total-return or Visa total-return series yet. Decision gate DRAFT-06 with the options in §4. |
| Reserve sources | TSA passenger-volumes page returned 403 to the scripted request; BTS TranStats TLS handshake timed out; I-94 program page loads (documentation; data files not checked). | TSA/BTS unavailable for automation as checked; I-94 remains reserve (SR-02). |
| Catalog correctness | Catalog p. 13 "BEA PCE" link points to the PCE price index page, not expenditure tables. | BEA is a reserve alternative to Census, not an extra feed. |
| Organizer constraints | Certification requires 100% public sources with documentation and references, and treats look-ahead bias as disqualifying. Rules require showing which signals moved outputs and a repeatable, scalable pipeline. | Reinforces DR-01, DR-04, ER-04, FR-11. |

## 2. Visa primary sources

### 2.1 Source records

| Field | Earnings release (8-K Ex. 99.1) | 10-Q / 10-K | XBRL companyfacts | IR earnings presentation / operational data |
| --- | --- | --- | --- | --- |
| Provider / dataset | SEC EDGAR, CIK 1403161, form 8-K Item 2.02, primary document `qN20YYearningsrelease.htm` (2020+); older naming `form8-kearningsrelease*.htm`, `earningsrelease*.htm` | SEC EDGAR 10-Q/10-K HTML + Financial_Report.xlsx | `data.sec.gov/api/xbrl/companyfacts/CIK0001403161.json` | investor.visa.com quarterly earnings pages (PDF) |
| Supported drivers | Category revenue, client incentives, net revenue, opex, special items, EPS, diluted basis; YoY growth (constant and nominal) for payments volume, cross-border ex-intra-Europe, total cross-border, processed transactions; prior-quarter PV growth; dividends declared | Nominal payments volume levels (MD&A), definitions and glossary, geography splits, tax rate, net interest, diluted shares, special items detail | Standard financial tags with `filed` dates | Financial outlook (guidance); operational performance data with absolute volumes by region, cards, transactions (availability of historical PDFs unverified) |
| Coverage / frequency | Quarterly, FY2008+ (46 in recent window since 2015; older in `submissions-001.json`) | Quarterly / annual | Per filing | Quarterly |
| Publication lag | Same day as results, after the close | Same evening or next morning (10-Q); 2–6 weeks (10-K) | Hours to days after filing | Same day as results |
| Revisions / vintage | Immutable filings; corrections appear as new filings (none for earnings 8-Ks observed in the amendment list) | Immutable | Values carry their filing accession | Unknown; PDFs may be replaced |
| Access | HTTPS, no key; SEC fair access: declared User-Agent, ≤ 10 req/s | Same | Same | HTTPS; automated-access terms unverified |
| Cost / restrictions | Free, public domain | Free | Free | Free to view |
| Verification | Verified: list, timestamps, Q3 FY2024 content | Verified: list and timestamps; content tables not parsed today | Verified: endpoint, tags, `filed` fields | Verified: pages load; PDFs and history not checked |
| Integration effort | Medium: HTML table parsing across format eras (2015–2019 vs 2020+) | Medium–high: MD&A table parsing | Low | Medium; manual download fallback |
| Limitations | Drivers as growth rates; constant-dollar vs nominal both present; absolute volumes absent | Lagged volume table (prior quarter) | No custom tags; quarterly values for Q4 must be derived from FY − 9M | Guidance language varies; vintage proof weaker than EDGAR |
| Fallback | 10-Q tables | Financial_Report.xlsx (R-files) | HTML tables | Earnings call transcript on IR site (if posted); otherwise guidance omitted for that origin with the exclusion reported |

### 2.2 Definitions to settle in DRAFT-02 (verified against the 10-K glossary before use)

- Payments volume vs total volume (cash volume) vs processed transactions coverage.
- Cross-border volume total vs excluding intra-Europe; which one drives international transaction revenue (release language: ex-intra-Europe).
- Constant-dollar vs nominal growth; which basis the model's activity indices use (planning assumption: nominal indices for revenue identities, constant-dollar growth retained as evidence and for FX attribution).
- GAAP operating expenses vs identified special items (litigation provision, acquisition items); declared operating-profit basis for scoring (planning assumption: GAAP net revenue; operating profit excluding identified special items as primary, GAAP also reported).
- Fiscal calendar: FY ends September 30; Q1 = October–December.
- Newer growth disclosures (consumer payments, new flows, value-added services growth) — when they begin and whether they are comparable across origins.

### 2.3 Cutoff convention (decision D-03 in README)

Cutoff for origin q = EDGAR acceptance timestamp of Visa's quarter-q earnings 8-K. Documents enter on their own acceptance timestamps, so the same-quarter 10-Q usually enters hours later and the 10-K weeks later; a document is eligible for an origin only if its timestamp ≤ cutoff. The first eligible market session is the next trading day after the cutoff. This keeps all origins on the same convention and uses levels from the previously filed 10-Q together with growth from the release. Alternative (post-filing cutoff = max(release, 10-Q)) is recorded as an option if DRAFT-03 shows release-only inputs are insufficient for the starting state.

### 2.4 Preliminary origin inventory (from EDGAR acceptance timestamps; eligibility not yet audited)

| Origin (release) | Fiscal quarter reported | Target quarter | Target realized (release) | Status |
| --- | --- | --- | --- | --- |
| 2024-01-25 | Q1 FY2024 | Q2 FY2024 | 2024-04-23 | candidate |
| 2024-04-23 | Q2 FY2024 | Q3 FY2024 | 2024-07-23 | candidate |
| 2024-07-23 | Q3 FY2024 | Q4 FY2024 | 2024-10-29 | candidate |
| 2024-10-29 | Q4 FY2024 | Q1 FY2025 | 2025-01-30 | candidate |
| 2025-01-30 | Q1 FY2025 | Q2 FY2025 | 2025-04-29 | candidate |
| 2025-04-29 | Q2 FY2025 | Q3 FY2025 | 2025-07-29 | candidate |
| 2025-07-29 | Q3 FY2025 | Q4 FY2025 | 2025-10-28 | candidate |
| 2025-10-28 | Q4 FY2025 | Q1 FY2026 | 2026-01-29 | candidate |
| 2026-01-29 | Q1 FY2026 | Q2 FY2026 | 2026-04-28 | candidate |
| 2026-04-28 | Q2 FY2026 | Q3 FY2026 | 2026-07-28 | candidate |
| 2026-07-28 | Q3 FY2026 | Q4 FY2026 | not yet (expected late October 2026) | **prospective** |

Ten retrospective candidates exist in the FY2024–FY2026 window; eight more exist in FY2022–FY2023 (releases 2022-01-27 … 2023-10-24) as an extension if some FY2024+ origins fail eligibility. Eligibility requires, per origin: reconstructable starting state (DRAFT-03), at least one external observation with publication ≤ cutoff (Booking and Census both publish quarterly/monthly since before 2015, so availability is likely; usefulness is a separate test), and stable driver definitions. The eligible count is reported after DRAFT-01/03; eight remains a target.

Calibration history (DR-06): FY2017–FY2023 (28 quarters) proposed, with FY2019–FY2023 as the minimum if pre-2020 release formats resist parsing. FY2020–FY2021 pandemic quarters are flagged; the treatment (down-weighting, dummy, or exclusion from residual estimation) is decided in DRAFT-21 and recorded in the model specification.

Prospective forecast (ER-10): origin 2026-07-28 → Q4 FY2026, registered in the archive before Visa's late-October 2026 release.

## 3. External evidence families

### 3.1 Family records

| Field | Booking Holdings (travel platform) | Census MARTS advance release (retail) | Airline / retailer / payment processor (gate) | Visa guidance (IR presentation) |
| --- | --- | --- | --- | --- |
| Provider / series | SEC EDGAR CIK 1075531, 8-K Item 2.02 Ex. 99.1: room nights, gross bookings, currency distinctions, forward commentary | Census Bureau Advance Monthly Retail Trade Report, archived PDFs `advYYMM.pdf`; nominal, seasonally adjusted and not adjusted; total and kind-of-business lines | EDGAR 8-K Item 2.02 of one airline (e.g. Delta), one retailer (e.g. Walmart or Target), one processor/acquirer (e.g. PayPal, Fiserv, Global Payments) — chosen in DRAFT-08 | investor.visa.com earnings presentation PDF ("financial outlook" slide); possibly prepared remarks/transcript |
| Driver supported | Travel demand direction for the cross-border ex-intra-Europe growth prior; qualitative context on international vs domestic travel | US consumption growth and category mix for the domestic payments-volume prior; e-commerce share (stretch) | Airline: international passenger revenue/capacity trend (cross-border prior); retailer: US comp sales and ticket/frequency (PV, transactions prior); processor: US card volume growth (PV cross-check) | Baseline comparison (ER-07); never a model input for the full model's historical runs unless labeled |
| Coverage / frequency | Quarterly, global, 2014+ | Monthly, US only, archived vintages observed 2015-12+ | Quarterly | Quarterly |
| Publication lag relative to Visa origins | 10–12 weeks stale at each Visa origin; covers the quarter before Visa's reported quarter plus forward commentary | ~2 weeks after month end; at a late-July Visa origin the June advance estimate (published mid-July) is eligible | Varies; Delta reports ~2 weeks before Visa; Walmart mid-quarter; PayPal/Fiserv around Visa's dates | Same day as the Visa release |
| Revisions / vintage | Immutable filings | Each month revises the prior two months; archived PDFs preserve the vintage; later series revisions excluded by DR-04 | Immutable filings | PDFs may be replaced; capture and hash at retrieval |
| Access | HTTPS, no key, SEC fair access | HTTPS, no key for files; API requires a free key (not needed) | HTTPS, no key | HTTPS; automated access terms unverified |
| Verification | Verified: list and timestamps; Q2 2026 content read in Phase 1 | Verified: archive index, file pattern, current PDF and XLSX | Not checked today | Pages load; PDF availability/history unverified |
| Integration effort | Low–medium (HTML tables + passages) | Medium (PDF table extraction per vintage; column continuity) | Low–medium per company (shared collector) | Low–medium (PDF text) |
| Limitations | Bookings ≠ completed trips ≠ Visa spending; global mix differs from Visa's; forward commentary is management expectation | US only; nominal retail ≠ card volume; excludes most services | Single-company idiosyncrasies; US-centric | Guidance ranges/wording vary; not consensus |
| Fallback | Keep as context only; Census becomes the required external family | Keep as context; Booking becomes the required family | Drop the family and report the exclusion | Omit guidance baseline for origins without a captured outlook; report the gap |

### 3.2 Observation-to-parameter mapping and how each family is tested

Mapping rules (FR-07) are of two kinds: estimated (a coefficient fitted on history ≤ cutoff, with uncertainty) and analyst-ranged (a direction and range labeled as an assumption). Each rule names the target parameter, the observation type it consumes, and the test that decides whether it stays.

| Family | Observation examples | Target parameter | Rule type (initial) | Test of value |
| --- | --- | --- | --- | --- |
| Visa release/10-Q (financial-only) | Category revenue, incentives, opex, driver growth, prior-quarter PV growth | Starting state; yield priors; incentive intensity; opex baseline; seasonal factors | Estimated | Forms the financial-only baseline (ER-07b); errors by origin |
| Booking | Measured: room nights growth, gross bookings growth, international vs domestic mix comment; Guidance: next-quarter bookings growth expectation | Travel factor → cross-border ex-intra-Europe growth prior (mean shift and/or range widening) | Analyst-ranged first; estimated if ≥ 12 aligned quarters support a coefficient | Ablation (a) vs full model across origins; incremental information over Visa-only inputs (does the mapped update reduce cross-border error?) |
| Census MARTS | Measured: latest monthly nominal retail growth, 3-month trend, category mix (e.g. nonstore vs stores) | Domestic consumption factor → US payments-volume growth prior; frequency proxy for processed transactions (weak, ranged) | Estimated for total growth where aligned; ranged for mix | Same ablation (a) structure; stale-vintage check that revised series would have changed the mapped input |
| Airline / retailer / processor (gate) | Measured segment growth; qualitative commentary | Corroborators for the travel and domestic factors; processor volume as PV cross-check | Context first; promoted to ranged rule only with a documented rationale | Reported as context unless a rule is adopted; exclusion reasons recorded |
| Visa guidance | Outlook statements for net revenue growth and expenses | Not a model parameter in the full model's historical tests | n/a | Baseline (ER-07) with a prior-data residual distribution |

Qualitative statements with no adopted rule remain context in the evidence view (MR-12). Rules that repeatedly worsen out-of-sample error lose weight or are removed through a documented model revision, never silently.

### 3.3 Known gaps in the hypothesis test

- Booking's 10–12 week staleness at Visa origins means the "external commentary" ablation mostly tests forward commentary and prior-quarter travel trends, not contemporaneous travel. Report this plainly.
- Census is US-only; Visa's international payments volume is outside its coverage. Attribute Census-driven updates to the US component only (10-Q geography split).
- Correlated proxies may add no signal; the ablation design (ER-08) and incremental-information test exist to detect that.

## 4. Benchmark and price data (DR-07, decision gate DRAFT-06)

Candidate chain, in order of preference; the gate picks the first that is verified license-compliant and documents the label text:

| Option | Series | Source and access | Verification today | Label if used | Concern |
| --- | --- | --- | --- | --- | --- |
| A | S&P 500 total return index (daily) | Free-registration EOD API (e.g. Tiingo/Alpha Vantage: SPY dividend-adjusted close), or S&P DJI download | Docs pages load; terms, limits, adjusted-series availability on free tier, redistribution rights unverified; spglobal 403 to scripts | "S&P 500 total return (SPY dividend-adjusted proxy, expense ratio noted)" if SPY used | Redistribution in the ZIP likely prohibited → fetch script, not bundled data |
| B | S&P 500 price index (FRED `SP500`) + monthly dividend accrual from Shiller `ie_data.xls` | FRED CSV without key (10-year window); Shiller XLS | Both verified downloadable | "S&P 500 total return (approximation: FRED price index + Shiller dividend series; monthly dividend accrual)" | Approximation error in dividend timing; FRED terms restrict redistribution of S&P data → fetch script |
| C | Ken French daily `Mkt-RF` + `RF` | Dartmouth data library ZIP | Verified downloadable; monthly update lag | "US total-market total return (CRSP value-weighted; Ken French) — not the S&P 500" | Not the committed benchmark; shown alongside, never relabeled |
| Visa | Daily prices + dividends | Prices: free-registration EOD API or manual CSV from investor.visa.com/Nasdaq; dividends: 8-K declarations, 10-Q/10-K (public domain) | IR pages load; price source terms unverified; Nasdaq API timed out; Stooq blocked | "Visa buy-and-hold total return (price source: …; dividends from SEC filings)" | Same redistribution question for prices |

Decision rule for the gate: use A if verified by the timebox; otherwise B as the labeled approximation with C shown as a secondary reference. Visa dividends always from SEC filings. yfinance-style unofficial access is not used in the package; if used for a local convenience check it is noted and not redistributed.

## 5. Exclusions and reserve

| Source | Status | Reason |
| --- | --- | --- |
| Historical analyst consensus | Blocked | No free licensed historical source; guidance kept under its own label (C20). |
| Longaeva data | Excluded | Unavailable; not required by the proposal for the core demonstration. |
| Stooq | Unavailable for automation | JS challenge; not bypassed (DR-09). |
| TSA checkpoint numbers | Reserve, unavailable as checked | 403 to scripted request; airline demand proxy only; US coverage. |
| BTS TranStats | Deferred | Timeout; needs a named international-passenger series and lag check. |
| I-94 arrivals | Reserve (SR-02) | US inbound only; revisions up to 36 months; downloadable series unverified. |
| BEA PCE expenditure tables | Reserve alternative to Census | Series/vintage availability unverified; catalog link pointed to a price index. |
| Catalog items outside Visa drivers (healthcare, industrials, TMT, etc.) | Out of scope | No named Visa driver. |

## 6. Licensing and redistribution policy for the package

- SEC EDGAR content: public domain; original files bundled as demo inputs.
- Census PDFs/tables: US government work; bundled.
- Ken French data: free for research with citation; bundle only derived returns needed for the demo with attribution, or fetch by script (decide in DRAFT-06).
- FRED S&P 500, Shiller, EOD-API prices: fetch by script with the user's own free key where required; do not bundle raw vendor data; bundle only the evaluation results derived from them, with the method documented.
- Every source gets a row in the package's `docs/data-licenses.md` with URL, retrieval date, terms summary and the bundle/fetch decision (DR-01).

## 7. Collection rules (DR-09)

Curated manifest (`data/manifest/*.yaml`) listing each document's URL, expected content hash after first retrieval, publication timestamp source, and license note. Collector: HTTPX with declared User-Agent, SEC rate limit ≤ 10 req/s (planned 2 req/s), exponential backoff, on-disk cache of originals, retrieval timestamps, content hashes, no retries against 403/JS challenges. No crawler.

## 8. Feasibility gates feeding the backlog

| Gate | Question | Timebox | Decision artifact | Draft |
| --- | --- | --- | --- | --- |
| G1 | How many origins are eligible under §2.3 and §2.4 rules, and why are others excluded? | 6 h | `origins.csv` + inventory note | DRAFT-01 |
| G2 | Which Visa definitions and bases does the model use; are they stable across the window? | 6 h | `definitions.md` | DRAFT-02 |
| G3 | Can two historical starting states be reconstructed from original exhibits and reconciled? | 6 h | two reconciled state fixtures + report | DRAFT-03 |
| G4 | Does Booking provide a measured fact and a qualitative passage at two cutoffs with usable timing? | 4 h | family gate note | DRAFT-04 |
| G5 | Can two Census vintages be parsed with stable categories and a revision example? | 5 h | family gate note + two vintage tables | DRAFT-05 |
| G6 | Which benchmark/price option in §4 is license-compliant and obtainable? | 4 h | benchmark decision note with label text | DRAFT-06 |
| G7 | Are historical Visa outlook statements recoverable with dates; is consensus confirmed unavailable? | 3 h | guidance gate note | DRAFT-07 |
| G8 | Which airline, retailer and processor disclosures qualify, each tied to a driver? | 5 h | selection note | DRAFT-08 |
