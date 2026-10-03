# Visa driver and accounting definitions

LON-2 · planning v1 · settled October 1, 2026.

This document fixes the definitions the model uses for FY2017–FY2026. Every definition
cites a primary SEC filing. Canonical field names live in
`backend/longaeva_app/companies/visa/definitions.py` and are listed in the
[Field table](#field-table) below. LON-14 (parser), LON-3 (starting states) and LON-19
(engine) must import those names rather than inventing synonyms.

## 1. Fiscal calendar

Visa’s fiscal year ends on **September 30**.

| Fiscal quarter | Calendar months | Period end |
| --- | --- | --- |
| Q1 | October–December | December 31 (prior calendar year) |
| Q2 | January–March | March 31 |
| Q3 | April–June | June 30 |
| Q4 | July–September | September 30 |

**Citation:** Form 10-K cover, FY2025, accession `0001403161-25-000089`,
[v-20250930.htm](https://www.sec.gov/Archives/edgar/data/1403161/000140316125000089/v-20250930.htm):
“For the fiscal year ended September 30 , 2025”. Confirmed on the FY2018 10-K cover
(`0001403161-18-000055`).

Package encoding: `VISA_FISCAL_CALENDAR = FiscalCalendar(fiscal_year_end_month=9)`.

## 2. Activity metrics: payments volume, total volume, processed transactions

### 2.1 Payments volume

**Definition:** Aggregate dollar amount of purchases made with cards and other form
factors carrying the Visa, Visa Electron, V PAY and Interlink brands. **Excludes Europe
co-badged volume.**

**Citation:** FY2025 10-K Item 7 — Payments volume and processed transactions
(`0001403161-25-000089`): “Payments volume represents the aggregate dollar amount of
purchases made with cards and other form factors carrying the Visa, Visa Electron, V PAY
and Interlink brands and excludes Europe co-badged volume.” Same wording appears in the
Q2 FY2026 10-Q MD&A (`0001403161-26-000079`).

**Role:** Primary driver of service revenue. Model state field:
`payments_volume_nominal_us` (levels) and `payments_volume_index_nominal` (derived index).

### 2.2 Nominal payments volume

**Definition:** Payments volume denominated in U.S. dollars, calculated each quarter by
applying an established USD/foreign-currency exchange rate for each local currency in
which volumes are reported.

**Citation:** FY2025 10-K Item 7: “Nominal payments volume is denominated in U.S. dollars
and is calculated each quarter by applying an established U.S. dollar/foreign currency
exchange rate for each local currency in which our volumes are reported.”

### 2.3 Cash volume and total volume

**Definition:** Cash volume generally consists of cash access transactions, balance access
transactions, balance transfers and convenience checks. **Total nominal volume** = total
nominal payments volume + cash volume.

**Citation:** FY2025 10-K Item 7 footnotes (5)–(6): “Total nominal volume is the sum of
total nominal payments volume and cash volume.”

**Role:** Context only (`cash_volume_nominal_us`, `total_volume_nominal_us`). Not a model
activity driver. Do not treat total volume as interchangeable with payments volume.

### 2.4 Processed transactions

**Definition:** Count of payments **and** cash transactions using cards and other form
factors carrying the Visa, Visa Electron, V PAY, Interlink **and PLUS** brands
**processed on Visa’s networks**.

**Citation:** FY2025 10-K Item 7: “Processed transactions include payments and cash
transactions, and represent transactions using cards and other form factors carrying the
Visa, Visa Electron, V PAY, Interlink and PLUS brands processed on Visa’s networks.”

**Role:** Primary driver of data processing revenue (`processed_transactions_count`,
`processed_transactions_index`).

### 2.5 Coverage difference (MR-05)

Payments volume and processed transactions have **different coverage**:

- Payments volume excludes cash and excludes PLUS; excludes Europe co-badged volume.
- Processed transactions include cash and PLUS; count only what Visa’s networks process.

Therefore **payments volume ÷ processed transactions is never labeled average purchase
value**. Any such ratio in analysis must be labeled as a coverage-mismatched diagnostic,
not an observed APV.

## 3. Cross-border volume

### 3.1 Two series

| Series | Model role | Availability |
| --- | --- | --- |
| Cross-border volume **excluding transactions within Europe** | Primary driver of international transaction revenue | Prose from FY2019Q3; Key Business Drivers table from FY2020Q1 |
| Cross-border volume **total** (includes intra-Europe) | Context / share of payments volume | Continuous in releases FY2017–FY2026 |

**Citations:**

- FY2026Q3 release (`0001403161-26-000103`) footnote: “Cross-border volume excluding
  transactions within Europe.”
- Same release, Financial Highlights: “Cross-border volume excluding transactions within
  Europe, which drives our international transaction revenue, …”
- FY2019Q3 release (`0001403161-19-000026`) prose: “Excluding cross- border transactions
  within Europe, which have revenue yields similar to Europe’s domestic volume, growth was
  9% in the quarter.”

### 3.2 Overlap with payments volume (MR-05)

Cross-border volume is a **share / sub-index of payments volume**, not an amount added on
top of it. Mix-shift interventions must conserve total spending (MR-11). Independently
sampling a cross-border shock that increases total spending is forbidden.

International transaction revenue is earned for “cross-border transaction processing and
currency conversion activities” (FY2025 10-K Item 1).

## 4. Revenue categories, incentives and identities

### 4.1 Four categories + incentives

| Category | Field | Timing |
| --- | --- | --- |
| Service revenue | `service_revenue` | Recognized on **prior-quarter** payments volume |
| Data processing revenue | `data_processing_revenue` | Current-quarter processed transactions |
| International transaction revenue | `international_transaction_revenue` | Current-quarter cross-border ex-intra-Europe (+ FX/conversion) |
| Other revenue | `other_revenue` | Current-quarter activity (VAS, license fees, account-holder services) |
| Client incentives (contra-revenue) | `client_incentives` | Current quarter |
| Net revenue | `net_revenue` | Identity: Σ categories − incentives |

**Citations:**

- FY2025 10-K Item 1 “Our net revenue” defines SERVICE REVENUE, DATA PROCESSING REVENUE,
  INTERNATIONAL TRANSACTION REVENUE, OTHER REVENUE and CLIENT INCENTIVES.
- FY2025 10-K Item 7 footnote 1: “Service revenue in a given quarter is primarily assessed
  based on nominal payments volume in the prior quarter.”
- FY2026Q3 and FY2018Q3 releases both state: service revenue “is recognized based on
  payments volume in the prior quarter. All other revenue categories are recognized based
  on current quarter activity.” Stable across the window.

### 4.2 Value-added services (MR-05)

Value-added services are **already recognized within the reported categories** (chiefly
other revenue and portions of service / data processing). They are **not** a fifth revenue
bucket and must not be added again as a separate activity stream. They may inform category
yields as context.

### 4.3 Identities (MR-04)

On every path and quarter (relative tolerance ≤ 1e-9):

1. `service_revenue + data_processing_revenue + international_transaction_revenue + other_revenue − client_incentives = net_revenue`
2. `net_revenue − operating_expenses = operating_profit` (on the declared basis; see §6)

## 5. Nominal versus constant-dollar (decision)

### 5.1 What each era publishes at the cutoff

| Era | Summary Key Business Drivers | Detailed KEY BUSINESS DRIVERS table |
| --- | --- | --- |
| FY2017Q1–FY2018Q1 | Constant-dollar growth | Constant-dollar emphasis; nominal columns appear inconsistently |
| FY2018Q2–FY2026Q3 | Constant-dollar growth | **Both Constant and Nominal** YoY columns for payments volume, cross-border series and (count) processed transactions |

Constant-dollar growth “excludes the impact of foreign currency fluctuations against the
U.S. dollar” (FY2025 10-K Item 7 footnote 7).

At earnings cutoff q (LON-1 convention = EDGAR acceptance of the quarter-q 8-K):

- The same-quarter 10-Q is **not** eligible (accepted hours later; see
  `docs/origins-inventory.md`).
- The prior-quarter 10-Q reports nominal payments-volume **levels** for period **q−2**
  (service-revenue lag inside the 10-Q itself).
- Release q reports growth for periods q−1 and q (constant in the summary; constant and
  usually nominal in the detailed table).

### 5.2 Decision (choice 2a)

1. **Activity indices stay nominal** (`payments_volume_index_nominal`,
   `cross_border_ex_intra_europe_index_nominal`), matching MR-01 and keeping yields in
   reported USD.
2. **Anchor** each index on the newest eligible `payments_volume_nominal_us` (or analogous)
   level from a 10-Q/10-K with `publication_ts ≤ cutoff`.
3. **Roll forward** with release growth:
   - Prefer **nominal** growth from the detailed KEY BUSINESS DRIVERS table when present
     (FY2018Q2+).
   - Otherwise apply **constant-dollar** growth plus an **explicit, labeled currency
     adjustment** (derived from the release’s reported net-revenue growth gap between
     nominal and constant-dollar, or from the Constant vs Nominal driver columns when only
     one series needs bridging). The adjustment is stored as a derived observation with
     basis `derived`, never silently folded into the growth rate.
4. **Driver-growth forecasts are scored in constant dollars**
   (`payments_volume_growth_constant`, `cross_border_ex_intra_europe_growth_constant`,
   `processed_transactions_growth`). That is the basis the next release’s summary Key
   Business Drivers always publishes, so errors are comparable across eras.

## 6. GAAP versus identified special items (decision)

### 6.1 What Visa excludes in non-GAAP reconciliations

From the FY2025 10-K Item 7 Non-GAAP Financial Measures section (and matching release
reconciliations across eras), non-GAAP operating expenses / net income exclude:

| Item | Notes |
| --- | --- |
| Litigation provision | Uncovered legal matters and U.S. interchange MDL accruals |
| Severance costs | e.g. FY2025 organizational realignment; also appears FY2026Q3 |
| Lease consolidation costs | FY2024–FY2025 |
| Amortization of acquired intangible assets | Business combinations from FY2019 onward |
| Acquisition-related costs | Transaction, integration, retention equity |
| Investment gains/losses | Non-operating; do not correlate with core operations |
| Russia-Ukraine charges | FY2022 deconsolidation / personnel (comparability note) |

Earlier eras labeled the same idea “adjusted” rather than “non-GAAP”; the economic split
(recurring vs identified items) is continuous.

### 6.2 Declared scoring basis (confirms planning D-05)

| Metric | Primary scoring basis | Also reported |
| --- | --- | --- |
| Net revenue | **GAAP** (`net_revenue`) | — |
| Operating profit | **Excluding identified special items** (`operating_profit_ex_special_items`), which also removes the amortization and acquisition-related costs Visa lists in its non-GAAP bridge | GAAP operating profit (`operating_profit_gaap`) |
| Driver growth | **Constant-dollar** (§5.2) | Nominal retained as evidence |

Rationale: GAAP net revenue is the top-line identity the release always leads with.
Operating profit excluding identified special items (plus Visa’s listed amort/acquisition
adjustments) matches how Visa presents run-rate expense and avoids scoring litigation /
severance noise as forecast error. Amortization and acquisition-related costs are included
in the “ex_special_items” operating-expense field because Visa’s own non-GAAP bridge
treats them as non-core; both fields remain labeled so a reader can recover GAAP.

## 7. Yields (MR-06)

Effective yields are **derived** quantities, not contract fees:

| Yield | Formula |
| --- | --- |
| `effective_yield_service` | `service_revenue(t) / payments_volume_nominal(t−1)` |
| `effective_yield_data_processing` | `data_processing_revenue(t) / processed_transactions_count(t)` |
| `effective_yield_international` | international revenue / cross-border ex-intra-Europe activity |
| `incentive_intensity` | `client_incentives / gross category revenue` |

They absorb customer mix, pricing and value-added services. They are never presented as
observed contract fees.

## 8. Teaching fees — not an input

The Stage 1 proposal’s simplified example that a network “earns $1 for every $100 of
domestic spending and $3 for every $100 of cross-border spending” is an **invented teaching
illustration**. Those constants are **not an input** anywhere in this package: not in
parameter defaults, not in fixtures, not in the engine, and not in evaluation. Only the
derived effective yields in §7 are used.

## 9. Observation basis vocabulary

`observation.basis` (LON-10) is free text. LON-2 fixes the vocabulary the Visa parser and
review UI must use:

| Token | Meaning |
| --- | --- |
| `nominal` | USD at Visa’s established quarterly FX rates |
| `constant_dollar` | Growth excluding FX fluctuations vs USD |
| `gaap` | As reported under U.S. GAAP |
| `ex_special_items` | GAAP less identified special items and listed non-GAAP adjustments (§6) |
| `derived` | Computed from other fields (indices, yields, currency adjustment) |
| `count` | Transaction or share count (currency-invariant) |

## 10. Disclosure change log

| Effective | Kind | Summary |
| --- | --- | --- |
| FY2017Q1 | comparability_break | First full year with Visa Europe in the perimeter (acquisition closed June 2016). |
| FY2018Q2 | format_change | Detailed KEY BUSINESS DRIVERS table reports Constant and Nominal columns. |
| FY2019Q1 | comparability_break | ASC 606 adoption changes classification/timing of some other revenue. |
| FY2019Q3 | format_change | Cross-border ex-intra-Europe appears in release prose. |
| FY2019Q4 | label_change | Non-GAAP begins excluding amortization of acquired intangibles (FY2019+ deals). |
| FY2020Q1 | new_series | Ex-intra-Europe enters Key Business Drivers; becomes the international-revenue driver. |
| FY2020Q2 | new_series | Narrative metrics (consumer payments, commercial/money movement, VAS) in commentary — context only. |
| FY2022Q2 | comparability_break | Russia operations suspended March 2022; growth rates need a Russia note; series definitions unchanged. |
| FY2026Q2 | comparability_break | Prisma / Newpay (Argentina) acquisitions may shift category mix in FY2026Q2–Q3. |

Full structured records: `CHANGES` in `definitions.py`.

## 11. Stability verdict and eligible-origin impact

**Question:** Are the definitions stable enough across FY2017–FY2026 for the LON-1
inventory to remain eligible?

**Verdict:** **Yes.** Core definitions (four revenue categories, client incentives as
contra-revenue, service-revenue lag on prior-quarter payments volume, payments volume vs
processed-transactions coverage, constant-dollar vs nominal, fiscal calendar) hold from
FY2017Q1 through FY2026Q3. Changes in §10 are label/format changes, new series
presentations, or named comparability breaks — not redefinitions that invalidate an origin.

**Exact counts (unchanged by LON-2; LON-2 does not lower the LON-1 inventory):**

| Count | Value |
| --- | --- |
| Inventory rows FY2017Q1–FY2026Q3 | **39** |
| Calibration quarters FY2017–FY2023 with timestamps | **28** |
| Candidate origins (LON-1 timestamp + prior-10-Q checks) | **18** |
| Prospective origins | **1** (`2026-07-28` → FY2026Q4) |
| Origins excluded by LON-2 definition instability | **0** |

LON-3 (starting-state reconstruction) and LON-5 (Census timing) can still lower the
eligible count. Parser status for FY2017–FY2019 formats is deferred to LON-14 (best-effort
with per-quarter status), not treated as a definition failure here.

## 12. Field table

Canonical names imported by LON-14 / LON-19. Keep in sync with `FIELDS` in
`backend/longaeva_app/companies/visa/definitions.py`.

| name | unit | basis | period_rule | source | first | last | role |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `service_revenue` | usd_millions | gaap | prior_quarter | earnings_release | FY2017Q1 | FY2026Q3 | metric |
| `data_processing_revenue` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | metric |
| `international_transaction_revenue` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | metric |
| `other_revenue` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | metric |
| `client_incentives` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | metric |
| `net_revenue` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | scoring |
| `operating_expenses_gaap` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | metric |
| `operating_expenses_ex_special_items` | usd_millions | ex_special_items | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | scoring |
| `special_items` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | context |
| `operating_profit_gaap` | usd_millions | gaap | current_quarter | derived | FY2017Q1 | FY2026Q3 | scoring |
| `operating_profit_ex_special_items` | usd_millions | ex_special_items | current_quarter | derived | FY2017Q1 | FY2026Q3 | scoring |
| `payments_volume_nominal_us` | usd_billions | nominal | prior_quarter | form_10q | FY2017Q1 | FY2026Q3 | state |
| `cash_volume_nominal_us` | usd_billions | nominal | prior_quarter | form_10q | FY2017Q1 | FY2026Q3 | context |
| `total_volume_nominal_us` | usd_billions | nominal | prior_quarter | form_10q | FY2017Q1 | FY2026Q3 | context |
| `processed_transactions_count` | transactions_millions | count | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | state |
| `payments_volume_growth_constant` | percent | constant_dollar | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | driver |
| `payments_volume_growth_nominal` | percent | nominal | current_quarter | earnings_release | FY2018Q2 | FY2026Q3 | driver |
| `payments_volume_prior_quarter_growth_constant` | percent | constant_dollar | prior_quarter | earnings_release | FY2017Q1 | FY2026Q3 | driver |
| `cross_border_ex_intra_europe_growth_constant` | percent | constant_dollar | current_quarter | earnings_release | FY2020Q1 | FY2026Q3 | driver |
| `cross_border_ex_intra_europe_growth_nominal` | percent | nominal | current_quarter | earnings_release | FY2020Q3 | FY2026Q3 | driver |
| `cross_border_total_growth_constant` | percent | constant_dollar | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | context |
| `cross_border_total_growth_nominal` | percent | nominal | current_quarter | earnings_release | FY2020Q3 | FY2026Q3 | context |
| `processed_transactions_growth` | percent | count | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | driver |
| `payments_volume_index_nominal` | index | derived | derived | derived | FY2017Q1 | FY2026Q3 | state |
| `cross_border_ex_intra_europe_index_nominal` | index | derived | derived | derived | FY2020Q1 | FY2026Q3 | state |
| `processed_transactions_index` | index | derived | derived | derived | FY2017Q1 | FY2026Q3 | state |
| `effective_yield_service` | ratio | derived | derived | derived | FY2017Q1 | FY2026Q3 | parameter_input |
| `effective_yield_data_processing` | ratio | derived | derived | derived | FY2017Q1 | FY2026Q3 | parameter_input |
| `effective_yield_international` | ratio | derived | derived | derived | FY2017Q1 | FY2026Q3 | parameter_input |
| `incentive_intensity` | ratio | derived | derived | derived | FY2017Q1 | FY2026Q3 | parameter_input |
| `tax_rate` | ratio | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | valuation |
| `net_interest_other` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | valuation |
| `diluted_shares` | shares_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | valuation |

## 13. Handoff notes

- **LON-3:** Reconstruct starting states using these field names; nominal PV levels from the
  prior-quarter 10-Q (period q−2 at cutoff q); apply §5.2 roll-forward. Done — see
  `docs/gates/starting-states.md` and `data/fixtures/states/visa_*.json`.
  `tax_rate` / `net_interest_other` source tags corrected to `earnings_release`.
- **LON-8:** Second-wave families should map into
  `cross_border_ex_intra_europe_*` or `payments_volume_*` drivers under these definitions.
- **LON-14:** Done — see [`docs/visa-parser.md`](visa-parser.md). Parser field names =
  `FIELDS` plus observation-only `REPORTED_FIELDS` in §14; unit/basis tokens = §9.
  Structured HTML/table extraction for 39 releases and prior 10-Q/10-Ks; the two
  LON-3 fixtures reproduce on measured values, spans and derived formulas.
- **LON-16:** LLM extraction for fields the structured parser cannot locate (prose-only
  operational performance data in FY2017–FY2021Q2) can consume `parse_status.csv`
  missing-field reasons.
- **LON-19:** Done — see [`docs/model-spec.md`](model-spec.md). `VisaModel` implements
  `CompanyModel` with these field names; six factors (demand/travel/FX correlated;
  pricing/incentives/costs independent); cross-border as a share of payments volume
  (`cross_border_share_at_origin` assumption); service lag on PV(t−1);
  `service_lag` / `pool_mix` switches; no teaching-fee constants.
- **LON-25:** Valuation bridge consumes `tax_rate`, `net_interest_other`, `diluted_shares`
  and `operating_profit_*` on the bases in §6.

## 14. Observation-only reported fields (LON-14)

These names live in `REPORTED_FIELDS`, not `FIELDS`, so the LON-3 starting-state
fixtures keep their original key set. The parser still emits them as typed observations.

| Field | Unit | Basis | Period | Source | First | Last | Role |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `eps_diluted_gaap` | usd_per_share | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | context |
| `eps_diluted_ex_special_items` | usd_per_share | ex_special_items | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | context |
| `special_item_operating_expense` | usd_millions | gaap | current_quarter | earnings_release | FY2017Q1 | FY2026Q3 | context |

`special_item_operating_expense` is one row per three-month operating-expense bridge
line; the item label is stored in `attributes.item`. The unit `usd_per_share` is added
to the LON-2 unit vocabulary for EPS.
