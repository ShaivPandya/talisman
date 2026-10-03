# Gate: reconstruct two historical Visa starting states

LON-3 · planning v1 · settled October 2, 2026.

## Question

Can release-only inputs plus the previous 10-Q produce a complete starting state under the cutoff convention (data plan §2.3)?

## Answer

**No — not for payments-volume levels of q−1 and q.** The earnings release publishes category revenue, incentives, net revenue, GAAP and non-GAAP operating expenses (with an itemized bridge), driver growth (constant and nominal), prior-quarter PV growth, processed-transaction counts, the effective tax rate, non-operating income and diluted shares. The prior 10-Q publishes the nominal payments-volume **level** only for period **q−2** (plus multi-month totals), because of the service-revenue lag inside the form.

A complete starting state **is** obtainable once every filing eligible under §2.3 is used: year-ago 10-Q/10-K totals supply PV(q−4) / residual year-ago quarters; those levels are rolled forward with the release’s **nominal** YoY growth (definitions §5.2). Derived levels are labeled `derived` and carry a ±0.5 ppt growth rounding band.

**Alternative cutoff (post-filing = max(release, same-quarter 10-Q/10-K)):** the same-quarter 10-Q adds PV(q−1) directly, but **never** PV(q), and for Q4 origins the 10-K arrives ~217 hours later. Recommendation: **keep §2.3 / D-03**.

## Origins

| | Origin A | Origin B |
| --- | --- | --- |
| Cutoff (UTC) | `2024-07-23T20:05:38Z` | `2025-10-28T20:06:03Z` |
| Fiscal quarter | FY2024Q3 | FY2025Q4 |
| Target | FY2024Q4 | FY2026Q1 |
| Release | `0001403161-24-000040` | `0001403161-25-000077` |
| Prior 10-Q | `0001403161-24-000030` | `0001403161-25-000052` |
| Fixture | [`data/fixtures/states/visa_2024-07-23.json`](../../data/fixtures/states/visa_2024-07-23.json) | [`data/fixtures/states/visa_2025-10-28.json`](../../data/fixtures/states/visa_2025-10-28.json) |

## Field tables (summary)

Units follow [`docs/definitions.md`](../definitions.md). Status: `measured` | `derived` | `unavailable_at_cutoff`.

### Origin A — FY2024Q3

| Field | Value | Period | Basis | Status | Source |
| --- | --- | --- | --- | --- | --- |
| service_revenue | 3,967 | FY2024Q3 | gaap | measured | release |
| data_processing_revenue | 4,489 | FY2024Q3 | gaap | measured | release |
| international_transaction_revenue | 3,194 | FY2024Q3 | gaap | measured | release |
| other_revenue | 780 | FY2024Q3 | gaap | measured | release |
| client_incentives | 3,530 | FY2024Q3 | gaap | measured | release |
| net_revenue | 8,900 | FY2024Q3 | gaap | measured | release |
| operating_expenses_gaap | 2,962 | FY2024Q3 | gaap | measured | release |
| operating_expenses_ex_special_items | 2,927 | FY2024Q3 | ex_special_items | measured | release |
| special_items | 35 | FY2024Q3 | gaap | derived | GAAP − ex |
| operating_profit_gaap | 5,938 | FY2024Q3 | gaap | derived | NR − opex |
| operating_profit_ex_special_items | 5,973 | FY2024Q3 | ex_special_items | derived | NR − opex_ex |
| payments_volume_nominal_us | 3,324.3 | FY2024Q3 | derived | derived | year-ago × 1.05 |
| cash_volume_nominal_us | 634 | FY2024Q1 | nominal | measured | prior 10-Q |
| total_volume_nominal_us | 3,914 | FY2024Q1 | nominal | measured | prior 10-Q |
| processed_transactions_count | 59,300 | FY2024Q3 | count | measured | release (59.3B) |
| payments_volume_growth_constant / nominal | 7 / 5 | FY2024Q3 | const / nom | measured | release KBD |
| payments_volume_prior_quarter_growth_constant | 8 | FY2024Q2 | const | measured | release prose |
| cross_border_ex_intra_europe_growth_constant / nominal | 14 / 12 | FY2024Q3 | const / nom | measured | release KBD |
| cross_border_total_growth_constant / nominal | 14 / 12 | FY2024Q3 | const / nom | measured | release KBD |
| processed_transactions_growth | 10 | FY2024Q3 | count | measured | release KBD |
| payments_volume_index_nominal | ≈101.35 | FY2024Q3 | derived | derived | 100 at q−2 |
| cross_border_ex_intra_europe_index_nominal | — | — | derived | unavailable | no CB level |
| processed_transactions_index | 100 | FY2024Q3 | derived | derived | base=100 here |
| effective_yield_service | ≈0.001254 | FY2024Q3 | derived | derived | SR / PV(q−1) |
| effective_yield_data_processing | ≈0.0757 | FY2024Q3 | derived | derived | DPR / txns |
| effective_yield_international | — | — | derived | unavailable | no CB level |
| incentive_intensity | ≈0.2840 | FY2024Q3 | derived | derived | incentives / gross |
| tax_rate | 0.186 | FY2024Q3 | gaap | measured | release |
| net_interest_other | 51 | FY2024Q3 | gaap | measured | release |
| diluted_shares | 2,029 | FY2024Q3 | gaap | measured | release |

### Origin B — FY2025Q4

| Field | Value | Period | Basis | Status |
| --- | --- | --- | --- | --- |
| service_revenue | 4,602 | FY2025Q4 | gaap | measured |
| data_processing_revenue | 5,394 | FY2025Q4 | gaap | measured |
| international_transaction_revenue | 3,800 | FY2025Q4 | gaap | measured |
| other_revenue | 1,176 | FY2025Q4 | gaap | measured |
| client_incentives | 4,248 | FY2025Q4 | gaap | measured |
| net_revenue | 10,724 | FY2025Q4 | gaap | measured |
| operating_expenses_gaap | 4,576 | FY2025Q4 | gaap | measured |
| operating_expenses_ex_special_items | 3,611 | FY2025Q4 | ex_special_items | measured |
| special_items | 965 | FY2025Q4 | gaap | derived |
| operating_profit_gaap | 6,148 | FY2025Q4 | gaap | derived |
| operating_profit_ex_special_items | 7,113 | FY2025Q4 | ex_special_items | derived |
| payments_volume_nominal_us | 3,716.9 | FY2025Q4 | derived | derived |
| cash_volume_nominal_us | 599 | FY2025Q2 | nominal | measured |
| total_volume_nominal_us | 3,943 | FY2025Q2 | nominal | measured |
| processed_transactions_count | 67,700 | FY2025Q4 | count | measured |
| payments_volume_growth_constant / nominal | 9 / 9 | FY2025Q4 | const / nom | measured |
| payments_volume_prior_quarter_growth_constant | 8 | FY2025Q3 | const | measured |
| cross_border_ex_intra_europe_growth_constant / nominal | 11 / 14 | FY2025Q4 | const / nom | measured |
| cross_border_total_growth_constant / nominal | 12 / 17 | FY2025Q4 | const / nom | measured |
| processed_transactions_growth | 10 | FY2025Q4 | count | measured |
| tax_rate | 0.182 | FY2025Q4 | gaap | measured |
| net_interest_other | 75 | FY2025Q4 | gaap | measured |
| diluted_shares | 1,945 | FY2025Q4 | gaap | measured |

Unavailable at both origins: `cross_border_ex_intra_europe_index_nominal`, `effective_yield_international` (no disclosed CB level; MR-01).

## Identity residuals

All four identities hold within ±0.5 USD millions on both fixtures:

1. Σ categories − incentives = net revenue
2. net revenue − opex_gaap = operating_profit_gaap
3. net revenue − opex_ex = operating_profit_ex_special_items
4. opex_gaap − special_items = opex_ex

## PV derivations

### Origin A

- PV(FY2023Q2) = 2,957 (FY2023Q3 10-Q, 3 months ended Mar 2023)
- PV(FY2024Q2) = 2,957 × 1.07 = **3,163.99** (nominal growth from Q2 FY2024 release KBD)
- PV(FY2023Q3) = 12,074 − 8,908 = **3,166** (FY2023 10-K TTM Jun − FY2023Q3 10-Q 9M Mar)
- PV(FY2024Q3) = 3,166 × 1.05 = **3,324.3** (nominal growth from Q3 FY2024 release KBD)

### Origin B

- PV(FY2024Q3) = 12,984 − 9,656 = **3,328**
- PV(FY2025Q3) = 3,328 × 1.09 = **3,627.52**
- PV(FY2024Q4) = 3,410 (FY2025Q1 10-Q, 3 months ended Sep 2024)
- PV(FY2025Q4) = 3,410 × 1.09 = **3,716.9**

Rounding band = year-ago × 0.005 (whole-percent growth).

## Mismatch table (derived vs later-reported)

| Origin | Period | Derived | Later-reported | Diff | Within band? | Later source |
| --- | --- | --- | --- | --- | --- | --- |
| A | FY2024Q2 (q−1) | 3,163.99 | 3,172 | −8.01 | yes (±14.8) | same-q 10-Q `…-24-000041` |
| A | FY2024Q3 (q) | 3,324.3 | 3,328 | −3.7 | yes (±15.8) | FY2024 10-K TTM − 9M |
| A | FY2023Q2 vintage | 2,957 (at cutoff) | 2,963 (restated) | −6 | note | year-ago column in `…-24-000041` |
| B | FY2025Q3 (q−1) | 3,627.52 | 3,617 | +10.52 | yes (±16.6) | FY2025 10-K TTM − prior 9M |
| B | FY2025Q4 (q) | 3,716.9 | 3,732 | −15.1 | yes (±17.1) | FY2026Q1 10-Q |

Vintage note: later 10-Qs restate year-ago PV columns by a few billions. That is expected under DR-04 (use the first print available at the cutoff; link later revisions without substituting them into earlier origins).

## Alternative cutoff assessment

| Cutoff rule | PV(q−2) | PV(q−1) | PV(q) | Latency |
| --- | --- | --- | --- | --- |
| §2.3 (earnings 8-K acceptance) | prior 10-Q | derived | derived | 0 |
| max(release, same-q 10-Q) | prior 10-Q | measured | still derived | +2 h (Q1–Q3) |
| max(release, same-q 10-K) for Q4 | prior 10-Q | measured (via 10-K tables) | still derived | **+217 h** (Origin B) |

Same-quarter forms never publish current-quarter PV levels (service-revenue lag). Derivation of PV(q) remains necessary under any cutoff that stays inside the release window. **Keep D-03.**

## Eligible-origin impact (exact)

LON-3 does **not** lower the LON-1 inventory counts. Both reconstructed origins are complete under §2.3 with eligible-family inputs:

| Count | Value |
| --- | --- |
| Inventory rows FY2017Q1–FY2026Q3 | **39** |
| Calibration FY2017–FY2023 | **28** |
| Candidate origins | **18** |
| Prospective | **1** |
| Origins excluded by LON-3 incompleteness | **0** |

Census timing (LON-5) can still lower the count.

## Definitions note (LON-2 follow-up)

`tax_rate` and `net_interest_other` field `source` tags were corrected from `form_10q` to `earnings_release` (both appear in the release at the cutoff). Field **names** are unchanged.

## LON-14 span correction (Origin B nominal growth)

In `visa_2025-10-28.json`, three FY2025Q4 entries originally cited the Key Business
Drivers **Constant** cell (`char_start` 112485, quote `9%`) for **nominal** growth:
`payments_volume_growth_nominal` and the supporting spans on derived
`payments_volume_nominal_us` and `payments_volume_index_nominal`. Values were already
9% on both columns. LON-14 repoints those spans to the **Nominal** cell at 112729
with an anchor that `locate_span` resolves there. Constant-dollar growth remains at
112485.

## Five-value reviewer checklist

Re-checked against live EDGAR HTML on October 2, 2026:

| # | Origin | Field | Value | URL | Anchor → quote |
| --- | --- | --- | --- | --- | --- |
| 1 | A | net_revenue | 8,900 | [q32024earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm) | `Net revenue</font>` → `8,900` |
| 2 | A | payments_volume_growth_nominal | 5 | same | `KEY BUSINESS DRIVERS` → `5%` |
| 3 | A | payments_volume_nominal_us (q−2) | 3,280 | [v-20240331.htm](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000030/v-20240331.htm) | `Total nominal payments volume` → `3,280` |
| 4 | B | operating_expenses_ex_special_items | 3,611 | [q42025earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1403161/000140316125000077/q42025earningsrelease.htm) | `Non-GAAP` → `3,611` |
| 5 | B | diluted_shares | 1,945 | same | `Diluted Weighted-average Shares Outstanding` → `1,945` |

## Originals

Thirteen unique filings retained under [`data/fixtures/states/sources/`](../../data/fixtures/states/sources/) as deterministic `.htm.gz` (mtime=0) with SHA-256 in `manifest.json` (~1.2 MB compressed). Fetch: `python -m longaeva_app.collect.state_sources fetch`. Locate spans: `… locate data/fixtures/states/visa_YYYY-MM-DD.json`.

## Handoff

- **LON-14:** Done — structured parser in `extract/visa_tables.py` reproduces both
  fixtures (measured values and spans; derived values via fixture formulas). See
  [`docs/visa-parser.md`](../visa-parser.md).
- **LON-19:** `to_starting_state()` returns the numeric map; service lag uses PV(t−1); no teaching-fee constants; CB index remains unavailable until a level source exists or an analyst assumption is reviewed.
- **LON-20:** use derived PV series with rounding bands; do not substitute post-cutoff restatements into earlier cutoffs.
- **LON-25:** valuation bridge consumes `tax_rate`, `net_interest_other`, `diluted_shares`, `operating_profit_*`.
