# Evaluation report

This report consolidates retained results for reviewers of the standalone Visa
simulation. It evaluates the implemented model and curated evidence, with no
claim of investment alpha or prospective forecast superiority. **Consensus unavailable**:
company guidance is a separately labeled comparison.

The generated tables below retain metric-specific sample counts and exact source
references. Direct model comparisons use matched origins. Read the
[model specification](model-spec.md), [definitions](definitions.md), and
[limitations](limitations.md) alongside them.

Regenerate from the standalone package with `make evaluation-report`; validate
without writing with `make evaluation-report ARGS=--check`. Both commands work
offline without a database or provider credentials. Only the delimited generated
section changes; this interpretation and the prospective procedure are authored
sections. Generation fails on missing evidence, hash mismatches or inconsistent
score aggregates. Historical code fingerprints describe the saved executions,
not the current documentation build.

<!-- BEGIN GENERATED EVALUATION -->

## Retained evidence and origin inventory

The full model scores **16 historical origins**, with **2 exclusions**. This is an origin count, not a count of independent targets or Monte Carlo paths. Source: `visa_full_model.json` (`n_scored`, `n_excluded`, `origins`, `exclusions`) and `data/fixtures/origins.csv`. Prospective origins remain separate and unscored.

| Origin / cutoff UTC | Window | Origin quarter | Target quarter | Disposition |
| --- | --- | --- | --- | --- |
| 2022-01-27T21:08:07Z | extension | FY2022Q1 | FY2022Q2 | Scored |
| 2022-04-26T20:05:54Z | extension | FY2022Q2 | FY2022Q3 | Scored |
| 2022-07-26T20:05:57Z | extension | FY2022Q3 | FY2022Q4 | FY2021Q3 payments-volume level is not in the parsed observations (FY2020/FY2021 10-K 12-month tables not extracted); starting state cannot be built |
| 2022-10-25T20:05:34Z | extension | FY2022Q4 | FY2023Q1 | FY2021Q3 payments-volume level is not in the parsed observations (FY2020/FY2021 10-K 12-month tables not extracted); starting state cannot be built |
| 2023-01-26T21:05:49Z | extension | FY2023Q1 | FY2023Q2 | Scored |
| 2023-04-25T20:05:31Z | extension | FY2023Q2 | FY2023Q3 | Scored |
| 2023-07-25T20:05:51Z | extension | FY2023Q3 | FY2023Q4 | Scored |
| 2023-10-24T20:05:35Z | extension | FY2023Q4 | FY2024Q1 | Scored |
| 2024-01-25T21:05:41Z | primary | FY2024Q1 | FY2024Q2 | Scored |
| 2024-04-23T20:05:39Z | primary | FY2024Q2 | FY2024Q3 | Scored |
| 2024-07-23T20:05:38Z | primary | FY2024Q3 | FY2024Q4 | Scored |
| 2024-10-29T20:06:08Z | primary | FY2024Q4 | FY2025Q1 | Scored |
| 2025-01-30T21:05:52Z | primary | FY2025Q1 | FY2025Q2 | Scored |
| 2025-04-29T20:05:41Z | primary | FY2025Q2 | FY2025Q3 | Scored |
| 2025-07-29T20:06:16Z | primary | FY2025Q3 | FY2025Q4 | Scored |
| 2025-10-28T20:06:03Z | primary | FY2025Q4 | FY2026Q1 | Scored |
| 2026-01-29T21:05:49Z | primary | FY2026Q1 | FY2026Q2 | Scored |
| 2026-04-28T20:05:56Z | primary | FY2026Q2 | FY2026Q3 | Scored |
| 2026-07-28T20:05:26Z | prospective | FY2026Q3 | FY2026Q4 | Prospective — not scored |

### Missing targets and origin errors

| Variant | Origin | Target / status | Reason |
| --- | --- | --- | --- |
| full_model | 2022-04-26 | payments_volume_growth_constant | missing PV levels for FY2021Q3/FY2021Q2 at cutoff |
| financial_only | 2022-04-26 | payments_volume_growth_constant | missing PV levels for FY2021Q3/FY2021Q2 at cutoff |
| guidance | 2022-01-27 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2022-01-27 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2022-01-27 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2022-04-26 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2022-04-26 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2022-04-26 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2023-01-26 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2023-01-26 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2023-01-26 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2023-04-25 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2023-04-25 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2023-04-25 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2023-07-25 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2023-07-25 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2023-07-25 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2023-10-24 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2023-10-24 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2023-10-24 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2024-01-25 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2024-01-25 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2024-01-25 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2024-04-23 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2024-04-23 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2024-04-23 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2024-07-23 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2024-07-23 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2024-07-23 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2024-10-29 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2024-10-29 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2024-10-29 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2025-01-30 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2025-01-30 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2025-01-30 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2025-04-29 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2025-04-29 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2025-04-29 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2025-07-29 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2025-07-29 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2025-07-29 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2025-10-28 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2025-10-28 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2025-10-28 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2026-01-29 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2026-01-29 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2026-01-29 | processed_transactions_growth | no numeric driver guidance |
| guidance | 2026-04-28 | cross_border_ex_intra_europe_growth_constant | no numeric driver guidance |
| guidance | 2026-04-28 | payments_volume_growth_constant | no numeric driver guidance |
| guidance | 2026-04-28 | processed_transactions_growth | no numeric driver guidance |
| no_external_commentary | 2022-04-26 | payments_volume_growth_constant | missing PV levels for FY2021Q3/FY2021Q2 at cutoff |
| pooled_spending | 2022-04-26 | payments_volume_growth_constant | missing PV levels for FY2021Q3/FY2021Q2 at cutoff |
| no_service_lag | 2022-04-26 | payments_volume_growth_constant | missing PV levels for FY2021Q3/FY2021Q2 at cutoff |

## Forecast scores

Levels and their CRPS/WIS are USD millions; driver errors and scores are percentage points. MAPE is percent. Coverage is the saved central 80% interval. `Unavailable` is not zero. Source: each `data/evaluation/visa_<variant>.json`, `aggregates.<window>.<target>` or `four_quarter.<target>`. Configurations and file hashes are in the source ledger.

Four-quarter level targets are sums; four-quarter driver targets are the fourth quarter's YoY growth. The model's driver path units are annualized QoQ before the evaluation transform. WIS uses the repository weighting documented in the [model specification](model-spec.md).

### Cached LLM baseline

Provider `openai`, model `gpt-5.4`, prompt `lon30-v1`. Source: `visa_llm_baseline.json`, `config.baseline` and `n_scored`. Historical publication cutoffs restrict supplied evidence, but cannot remove historical outcomes from pretrained-model knowledge. This is an exploratory retrospective comparison, not proof of an ex-ante forecast or causal improvement. Inputs are evidence excerpts rather than full documents.

| Capture status | Count |
| --- | --- |
| succeeded | 16 |

### Next quarter — overall

| Target | Variant | n | MAE | MAPE % | Covered / n | CRPS | WIS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Net revenue (GAAP, USD m) | full_model | 16 | 196.339 | 2.105 | 9 of 16 | 149.038 | 134.994 |
| Net revenue (GAAP, USD m) | seasonal_trend | 14 | 137.648 | 1.389 | 7 of 14 | 112.139 | 102.456 |
| Net revenue (GAAP, USD m) | financial_only | 16 | 196.315 | 2.102 | 8 of 16 | 151.578 | 137.488 |
| Net revenue (GAAP, USD m) | guidance | 12 | 216.301 | 2.140 | 5 of 12 | 161.962 | 145.489 |
| Net revenue (GAAP, USD m) | llm_baseline | 16 | 151.875 | 1.632 | 13 of 16 | Unavailable | 99.410 |
| Net revenue (GAAP, USD m) | no_external_commentary | 16 | 196.315 | 2.102 | 8 of 16 | 151.578 | 137.488 |
| Net revenue (GAAP, USD m) | pooled_spending | 16 | 202.003 | 2.159 | 7 of 16 | 150.424 | 136.097 |
| Net revenue (GAAP, USD m) | no_service_lag | 16 | 346.221 | 3.691 | 4 of 16 | 263.705 | 240.437 |
| Operating profit (ex special items, USD m) | full_model | 16 | 209.153 | 3.261 | 8 of 16 | 158.016 | 143.176 |
| Operating profit (ex special items, USD m) | seasonal_trend | 14 | 115.125 | 1.728 | 8 of 14 | 87.042 | 78.556 |
| Operating profit (ex special items, USD m) | financial_only | 16 | 212.210 | 3.309 | 8 of 16 | 159.921 | 145.410 |
| Operating profit (ex special items, USD m) | guidance | 12 | 168.416 | 2.515 | 6 of 12 | 130.528 | 120.293 |
| Operating profit (ex special items, USD m) | llm_baseline | 16 | 136.562 | 2.167 | 12 of 16 | Unavailable | 88.918 |
| Operating profit (ex special items, USD m) | no_external_commentary | 16 | 212.210 | 3.309 | 8 of 16 | 159.921 | 145.410 |
| Operating profit (ex special items, USD m) | pooled_spending | 16 | 216.345 | 3.378 | 8 of 16 | 159.240 | 144.159 |
| Operating profit (ex special items, USD m) | no_service_lag | 16 | 381.211 | 5.925 | 3 of 16 | 294.432 | 270.530 |
| Payments volume (constant-dollar YoY, pp) | full_model | 15 | 2.040 | Unavailable | 3 of 15 | 1.699 | 1.617 |
| Payments volume (constant-dollar YoY, pp) | seasonal_trend | 16 | 1.307 | Unavailable | 13 of 16 | 0.998 | 0.907 |
| Payments volume (constant-dollar YoY, pp) | financial_only | 15 | 1.996 | Unavailable | 4 of 15 | 1.665 | 1.592 |
| Payments volume (constant-dollar YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Payments volume (constant-dollar YoY, pp) | llm_baseline | 16 | 1.106 | Unavailable | 15 of 16 | Unavailable | 0.665 |
| Payments volume (constant-dollar YoY, pp) | no_external_commentary | 15 | 1.996 | Unavailable | 4 of 15 | 1.665 | 1.592 |
| Payments volume (constant-dollar YoY, pp) | pooled_spending | 15 | 2.040 | Unavailable | 3 of 15 | 1.699 | 1.617 |
| Payments volume (constant-dollar YoY, pp) | no_service_lag | 15 | 2.040 | Unavailable | 3 of 15 | 1.699 | 1.617 |
| Cross-border (constant-dollar YoY, approximate, pp) | full_model | 16 | 5.673 | Unavailable | 7 of 16 | 4.120 | 3.666 |
| Cross-border (constant-dollar YoY, approximate, pp) | seasonal_trend | 16 | 2.123 | Unavailable | 13 of 16 | 2.073 | 1.938 |
| Cross-border (constant-dollar YoY, approximate, pp) | financial_only | 16 | 5.946 | Unavailable | 6 of 16 | 4.329 | 3.866 |
| Cross-border (constant-dollar YoY, approximate, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Cross-border (constant-dollar YoY, approximate, pp) | llm_baseline | 16 | 3.562 | Unavailable | 13 of 16 | Unavailable | 2.199 |
| Cross-border (constant-dollar YoY, approximate, pp) | no_external_commentary | 16 | 5.946 | Unavailable | 6 of 16 | 4.329 | 3.866 |
| Cross-border (constant-dollar YoY, approximate, pp) | pooled_spending | 16 | 5.563 | Unavailable | 0 of 16 | 5.006 | 4.856 |
| Cross-border (constant-dollar YoY, approximate, pp) | no_service_lag | 16 | 5.673 | Unavailable | 7 of 16 | 4.120 | 3.666 |
| Transactions (count YoY, pp) | full_model | 16 | 2.456 | Unavailable | 5 of 16 | 2.197 | 2.128 |
| Transactions (count YoY, pp) | seasonal_trend | 16 | 1.205 | Unavailable | 10 of 16 | 0.916 | 0.813 |
| Transactions (count YoY, pp) | financial_only | 16 | 2.499 | Unavailable | 4 of 16 | 2.212 | 2.140 |
| Transactions (count YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Transactions (count YoY, pp) | llm_baseline | 16 | 0.806 | Unavailable | 16 of 16 | Unavailable | 0.542 |
| Transactions (count YoY, pp) | no_external_commentary | 16 | 2.499 | Unavailable | 4 of 16 | 2.212 | 2.140 |
| Transactions (count YoY, pp) | pooled_spending | 16 | 2.456 | Unavailable | 5 of 16 | 2.197 | 2.128 |
| Transactions (count YoY, pp) | no_service_lag | 16 | 2.456 | Unavailable | 5 of 16 | 2.197 | 2.128 |

### Next quarter — primary

| Target | Variant | n | MAE | MAPE % | Covered / n | CRPS | WIS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Net revenue (GAAP, USD m) | full_model | 10 | 220.890 | 2.226 | 4 of 10 | 171.695 | 157.280 |
| Net revenue (GAAP, USD m) | seasonal_trend | 10 | 152.202 | 1.466 | 6 of 10 | 122.963 | 111.288 |
| Net revenue (GAAP, USD m) | financial_only | 10 | 220.503 | 2.220 | 4 of 10 | 172.911 | 158.456 |
| Net revenue (GAAP, USD m) | guidance | 10 | 232.698 | 2.233 | 5 of 10 | 167.491 | 147.724 |
| Net revenue (GAAP, USD m) | llm_baseline | 10 | 163.300 | 1.599 | 7 of 10 | Unavailable | 112.463 |
| Net revenue (GAAP, USD m) | no_external_commentary | 10 | 220.503 | 2.220 | 4 of 10 | 172.911 | 158.456 |
| Net revenue (GAAP, USD m) | pooled_spending | 10 | 233.339 | 2.354 | 4 of 10 | 179.009 | 163.832 |
| Net revenue (GAAP, USD m) | no_service_lag | 10 | 385.783 | 3.852 | 1 of 10 | 304.129 | 281.337 |
| Operating profit (ex special items, USD m) | full_model | 10 | 245.459 | 3.597 | 4 of 10 | 188.328 | 171.761 |
| Operating profit (ex special items, USD m) | seasonal_trend | 10 | 135.295 | 1.966 | 6 of 10 | 98.657 | 88.108 |
| Operating profit (ex special items, USD m) | financial_only | 10 | 248.289 | 3.641 | 4 of 10 | 191.352 | 175.337 |
| Operating profit (ex special items, USD m) | guidance | 10 | 173.452 | 2.491 | 6 of 10 | 127.987 | 115.705 |
| Operating profit (ex special items, USD m) | llm_baseline | 10 | 164.300 | 2.443 | 6 of 10 | Unavailable | 101.619 |
| Operating profit (ex special items, USD m) | no_external_commentary | 10 | 248.289 | 3.641 | 4 of 10 | 191.352 | 175.337 |
| Operating profit (ex special items, USD m) | pooled_spending | 10 | 256.623 | 3.769 | 5 of 10 | 192.079 | 175.005 |
| Operating profit (ex special items, USD m) | no_service_lag | 10 | 446.357 | 6.537 | 1 of 10 | 359.126 | 335.778 |
| Payments volume (constant-dollar YoY, pp) | full_model | 10 | 1.517 | Unavailable | 1 of 10 | 1.324 | 1.267 |
| Payments volume (constant-dollar YoY, pp) | seasonal_trend | 10 | 0.797 | Unavailable | 10 of 10 | 0.553 | 0.484 |
| Payments volume (constant-dollar YoY, pp) | financial_only | 10 | 1.521 | Unavailable | 2 of 10 | 1.323 | 1.272 |
| Payments volume (constant-dollar YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Payments volume (constant-dollar YoY, pp) | llm_baseline | 10 | 0.740 | Unavailable | 10 of 10 | Unavailable | 0.490 |
| Payments volume (constant-dollar YoY, pp) | no_external_commentary | 10 | 1.521 | Unavailable | 2 of 10 | 1.323 | 1.272 |
| Payments volume (constant-dollar YoY, pp) | pooled_spending | 10 | 1.517 | Unavailable | 1 of 10 | 1.324 | 1.267 |
| Payments volume (constant-dollar YoY, pp) | no_service_lag | 10 | 1.517 | Unavailable | 1 of 10 | 1.324 | 1.267 |
| Cross-border (constant-dollar YoY, approximate, pp) | full_model | 10 | 3.493 | Unavailable | 6 of 10 | 2.783 | 2.580 |
| Cross-border (constant-dollar YoY, approximate, pp) | seasonal_trend | 10 | 1.217 | Unavailable | 10 of 10 | 1.635 | 1.495 |
| Cross-border (constant-dollar YoY, approximate, pp) | financial_only | 10 | 3.676 | Unavailable | 5 of 10 | 2.906 | 2.714 |
| Cross-border (constant-dollar YoY, approximate, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Cross-border (constant-dollar YoY, approximate, pp) | llm_baseline | 10 | 1.600 | Unavailable | 9 of 10 | Unavailable | 0.934 |
| Cross-border (constant-dollar YoY, approximate, pp) | no_external_commentary | 10 | 3.676 | Unavailable | 5 of 10 | 2.906 | 2.714 |
| Cross-border (constant-dollar YoY, approximate, pp) | pooled_spending | 10 | 4.100 | Unavailable | 0 of 10 | 3.854 | 3.790 |
| Cross-border (constant-dollar YoY, approximate, pp) | no_service_lag | 10 | 3.493 | Unavailable | 6 of 10 | 2.783 | 2.580 |
| Transactions (count YoY, pp) | full_model | 10 | 1.549 | Unavailable | 3 of 10 | 1.361 | 1.309 |
| Transactions (count YoY, pp) | seasonal_trend | 10 | 0.918 | Unavailable | 8 of 10 | 0.665 | 0.570 |
| Transactions (count YoY, pp) | financial_only | 10 | 1.587 | Unavailable | 2 of 10 | 1.361 | 1.297 |
| Transactions (count YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Transactions (count YoY, pp) | llm_baseline | 10 | 0.770 | Unavailable | 10 of 10 | Unavailable | 0.462 |
| Transactions (count YoY, pp) | no_external_commentary | 10 | 1.587 | Unavailable | 2 of 10 | 1.361 | 1.297 |
| Transactions (count YoY, pp) | pooled_spending | 10 | 1.549 | Unavailable | 3 of 10 | 1.361 | 1.309 |
| Transactions (count YoY, pp) | no_service_lag | 10 | 1.549 | Unavailable | 3 of 10 | 1.361 | 1.309 |

### Next quarter — extension

| Target | Variant | n | MAE | MAPE % | Covered / n | CRPS | WIS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Net revenue (GAAP, USD m) | full_model | 6 | 155.421 | 1.903 | 5 of 6 | 111.276 | 97.852 |
| Net revenue (GAAP, USD m) | seasonal_trend | 4 | 101.262 | 1.198 | 1 of 4 | 85.080 | 80.375 |
| Net revenue (GAAP, USD m) | financial_only | 6 | 156.001 | 1.907 | 4 of 6 | 116.023 | 102.540 |
| Net revenue (GAAP, USD m) | guidance | 2 | 134.315 | 1.677 | 0 of 2 | 134.315 | 134.315 |
| Net revenue (GAAP, USD m) | llm_baseline | 6 | 132.833 | 1.688 | 6 of 6 | Unavailable | 77.656 |
| Net revenue (GAAP, USD m) | no_external_commentary | 6 | 156.001 | 1.907 | 4 of 6 | 116.023 | 102.540 |
| Net revenue (GAAP, USD m) | pooled_spending | 6 | 149.777 | 1.835 | 3 of 6 | 102.782 | 89.871 |
| Net revenue (GAAP, USD m) | no_service_lag | 6 | 280.284 | 3.423 | 3 of 6 | 196.331 | 172.270 |
| Operating profit (ex special items, USD m) | full_model | 6 | 148.643 | 2.700 | 4 of 6 | 107.497 | 95.535 |
| Operating profit (ex special items, USD m) | seasonal_trend | 4 | 64.698 | 1.134 | 2 of 4 | 58.002 | 54.676 |
| Operating profit (ex special items, USD m) | financial_only | 6 | 152.078 | 2.756 | 4 of 6 | 107.536 | 95.531 |
| Operating profit (ex special items, USD m) | guidance | 2 | 143.232 | 2.635 | 0 of 2 | 143.232 | 143.232 |
| Operating profit (ex special items, USD m) | llm_baseline | 6 | 90.333 | 1.708 | 6 of 6 | Unavailable | 67.750 |
| Operating profit (ex special items, USD m) | no_external_commentary | 6 | 152.078 | 2.756 | 4 of 6 | 107.536 | 95.531 |
| Operating profit (ex special items, USD m) | pooled_spending | 6 | 149.215 | 2.728 | 3 of 6 | 104.509 | 92.747 |
| Operating profit (ex special items, USD m) | no_service_lag | 6 | 272.636 | 4.906 | 2 of 6 | 186.609 | 161.784 |
| Payments volume (constant-dollar YoY, pp) | full_model | 5 | 3.087 | Unavailable | 2 of 5 | 2.449 | 2.318 |
| Payments volume (constant-dollar YoY, pp) | seasonal_trend | 6 | 2.156 | Unavailable | 3 of 6 | 1.741 | 1.611 |
| Payments volume (constant-dollar YoY, pp) | financial_only | 5 | 2.948 | Unavailable | 2 of 5 | 2.351 | 2.232 |
| Payments volume (constant-dollar YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Payments volume (constant-dollar YoY, pp) | llm_baseline | 6 | 1.717 | Unavailable | 5 of 6 | Unavailable | 0.956 |
| Payments volume (constant-dollar YoY, pp) | no_external_commentary | 5 | 2.948 | Unavailable | 2 of 5 | 2.351 | 2.232 |
| Payments volume (constant-dollar YoY, pp) | pooled_spending | 5 | 3.087 | Unavailable | 2 of 5 | 2.449 | 2.318 |
| Payments volume (constant-dollar YoY, pp) | no_service_lag | 5 | 3.087 | Unavailable | 2 of 5 | 2.449 | 2.318 |
| Cross-border (constant-dollar YoY, approximate, pp) | full_model | 6 | 9.307 | Unavailable | 1 of 6 | 6.347 | 5.476 |
| Cross-border (constant-dollar YoY, approximate, pp) | seasonal_trend | 6 | 3.634 | Unavailable | 3 of 6 | 2.802 | 2.676 |
| Cross-border (constant-dollar YoY, approximate, pp) | financial_only | 6 | 9.730 | Unavailable | 1 of 6 | 6.699 | 5.787 |
| Cross-border (constant-dollar YoY, approximate, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Cross-border (constant-dollar YoY, approximate, pp) | llm_baseline | 6 | 6.833 | Unavailable | 4 of 6 | Unavailable | 4.307 |
| Cross-border (constant-dollar YoY, approximate, pp) | no_external_commentary | 6 | 9.730 | Unavailable | 1 of 6 | 6.699 | 5.787 |
| Cross-border (constant-dollar YoY, approximate, pp) | pooled_spending | 6 | 8.001 | Unavailable | 0 of 6 | 6.925 | 6.633 |
| Cross-border (constant-dollar YoY, approximate, pp) | no_service_lag | 6 | 9.307 | Unavailable | 1 of 6 | 6.347 | 5.476 |
| Transactions (count YoY, pp) | full_model | 6 | 3.969 | Unavailable | 2 of 6 | 3.590 | 3.494 |
| Transactions (count YoY, pp) | seasonal_trend | 6 | 1.682 | Unavailable | 2 of 6 | 1.334 | 1.218 |
| Transactions (count YoY, pp) | financial_only | 6 | 4.017 | Unavailable | 2 of 6 | 3.630 | 3.543 |
| Transactions (count YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Transactions (count YoY, pp) | llm_baseline | 6 | 0.867 | Unavailable | 6 of 6 | Unavailable | 0.676 |
| Transactions (count YoY, pp) | no_external_commentary | 6 | 4.017 | Unavailable | 2 of 6 | 3.630 | 3.543 |
| Transactions (count YoY, pp) | pooled_spending | 6 | 3.969 | Unavailable | 2 of 6 | 3.590 | 3.494 |
| Transactions (count YoY, pp) | no_service_lag | 6 | 3.969 | Unavailable | 2 of 6 | 3.590 | 3.494 |

### Four quarters (separate horizon) — overall

| Target | Variant | n | MAE | MAPE % | Covered / n | CRPS | WIS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Net revenue (GAAP, USD m) | full_model | 13 | 848.278 | 2.295 | 9 of 13 | 566.976 | 496.536 |
| Net revenue (GAAP, USD m) | seasonal_trend | 11 | 623.457 | 1.584 | 1 of 11 | 556.254 | 537.486 |
| Net revenue (GAAP, USD m) | financial_only | 13 | 900.787 | 2.469 | 8 of 13 | 629.515 | 550.067 |
| Net revenue (GAAP, USD m) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Net revenue (GAAP, USD m) | llm_baseline | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Net revenue (GAAP, USD m) | no_external_commentary | 13 | 900.787 | 2.469 | 8 of 13 | 629.515 | 550.067 |
| Net revenue (GAAP, USD m) | pooled_spending | 13 | 652.818 | 1.684 | 9 of 13 | 501.516 | 448.669 |
| Net revenue (GAAP, USD m) | no_service_lag | 13 | 919.838 | 2.467 | 9 of 13 | 629.750 | 551.637 |
| Operating profit (ex special items, USD m) | full_model | 13 | 764.576 | 3.101 | 10 of 13 | 527.702 | 463.423 |
| Operating profit (ex special items, USD m) | seasonal_trend | 11 | 413.734 | 1.537 | 1 of 11 | 351.999 | 334.380 |
| Operating profit (ex special items, USD m) | financial_only | 13 | 766.714 | 3.084 | 10 of 13 | 547.724 | 489.860 |
| Operating profit (ex special items, USD m) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Operating profit (ex special items, USD m) | llm_baseline | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Operating profit (ex special items, USD m) | no_external_commentary | 13 | 766.714 | 3.084 | 10 of 13 | 547.724 | 489.860 |
| Operating profit (ex special items, USD m) | pooled_spending | 13 | 608.618 | 2.406 | 9 of 13 | 464.350 | 415.078 |
| Operating profit (ex special items, USD m) | no_service_lag | 13 | 922.097 | 3.741 | 8 of 13 | 647.290 | 559.948 |
| Payments volume (constant-dollar YoY, pp) | full_model | 13 | 2.141 | Unavailable | 7 of 13 | 1.695 | 1.584 |
| Payments volume (constant-dollar YoY, pp) | seasonal_trend | 13 | 2.547 | Unavailable | 10 of 13 | 2.075 | 1.960 |
| Payments volume (constant-dollar YoY, pp) | financial_only | 13 | 1.021 | Unavailable | 10 of 13 | 0.863 | 0.783 |
| Payments volume (constant-dollar YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Payments volume (constant-dollar YoY, pp) | llm_baseline | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Payments volume (constant-dollar YoY, pp) | no_external_commentary | 13 | 1.021 | Unavailable | 10 of 13 | 0.863 | 0.783 |
| Payments volume (constant-dollar YoY, pp) | pooled_spending | 13 | 2.141 | Unavailable | 7 of 13 | 1.695 | 1.584 |
| Payments volume (constant-dollar YoY, pp) | no_service_lag | 13 | 2.141 | Unavailable | 7 of 13 | 1.695 | 1.584 |
| Cross-border (constant-dollar YoY, approximate, pp) | full_model | 13 | 12.563 | Unavailable | 3 of 13 | 8.342 | 7.075 |
| Cross-border (constant-dollar YoY, approximate, pp) | seasonal_trend | 13 | 7.328 | Unavailable | 10 of 13 | 6.290 | 6.019 |
| Cross-border (constant-dollar YoY, approximate, pp) | financial_only | 13 | 13.821 | Unavailable | 3 of 13 | 9.451 | 8.110 |
| Cross-border (constant-dollar YoY, approximate, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Cross-border (constant-dollar YoY, approximate, pp) | llm_baseline | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Cross-border (constant-dollar YoY, approximate, pp) | no_external_commentary | 13 | 13.821 | Unavailable | 3 of 13 | 9.451 | 8.110 |
| Cross-border (constant-dollar YoY, approximate, pp) | pooled_spending | 13 | 7.436 | Unavailable | 2 of 13 | 6.557 | 6.360 |
| Cross-border (constant-dollar YoY, approximate, pp) | no_service_lag | 13 | 12.563 | Unavailable | 3 of 13 | 8.342 | 7.075 |
| Transactions (count YoY, pp) | full_model | 13 | 1.549 | Unavailable | 8 of 13 | 1.258 | 1.155 |
| Transactions (count YoY, pp) | seasonal_trend | 13 | 2.008 | Unavailable | 8 of 13 | 1.866 | 1.763 |
| Transactions (count YoY, pp) | financial_only | 13 | 0.821 | Unavailable | 10 of 13 | 0.728 | 0.652 |
| Transactions (count YoY, pp) | guidance | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Transactions (count YoY, pp) | llm_baseline | 0 | Unavailable | Unavailable | 0 of 0 | Unavailable | Unavailable |
| Transactions (count YoY, pp) | no_external_commentary | 13 | 0.821 | Unavailable | 10 of 13 | 0.728 | 0.652 |
| Transactions (count YoY, pp) | pooled_spending | 13 | 1.549 | Unavailable | 8 of 13 | 1.258 | 1.155 |
| Transactions (count YoY, pp) | no_service_lag | 13 | 1.549 | Unavailable | 8 of 13 | 1.258 | 1.155 |

## Matched-origin baseline comparisons

Positive delta = baseline error minus full-model error: positive favors the full model. Each row uses the intersection of origins with a scored target, independently for its horizon/window. No superiority claim is inferred from unmatched aggregate tables. Coverage is shown as percent on the same n. Source: both variants' `origins[origin_date].scores.<horizon>.<target>.*`; the exact date intersections appear below each table.

### Matched q1 — overall

| Baseline | Target | n | Full MAE | Baseline MAE | Δ MAE | Δ CRPS | Δ WIS | Full coverage % | Baseline coverage % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seasonal_trend | Net revenue (GAAP, USD m) | 14 | 210.898 | 137.648 | -73.250 | -49.934 | -44.773 | 50.000 | 50.000 |
| seasonal_trend | Operating profit (ex special items, USD m) | 14 | 221.146 | 115.125 | -106.021 | -80.389 | -73.168 | 50.000 | 57.143 |
| seasonal_trend | Payments volume (constant-dollar YoY, pp) | 15 | 2.040 | 1.061 | -0.979 | -0.919 | -0.922 | 20.000 | 86.667 |
| seasonal_trend | Cross-border (constant-dollar YoY, approximate, pp) | 16 | 5.673 | 2.123 | -3.550 | -2.047 | -1.729 | 43.750 | 81.250 |
| seasonal_trend | Transactions (count YoY, pp) | 16 | 2.456 | 1.205 | -1.252 | -1.281 | -1.315 | 31.250 | 62.500 |
| financial_only | Net revenue (GAAP, USD m) | 16 | 196.339 | 196.315 | -0.024 | 2.540 | 2.493 | 56.250 | 50.000 |
| financial_only | Operating profit (ex special items, USD m) | 16 | 209.153 | 212.210 | 3.057 | 1.905 | 2.234 | 50.000 | 50.000 |
| financial_only | Payments volume (constant-dollar YoY, pp) | 15 | 2.040 | 1.996 | -0.044 | -0.034 | -0.025 | 20.000 | 26.667 |
| financial_only | Cross-border (constant-dollar YoY, approximate, pp) | 16 | 5.673 | 5.946 | 0.273 | 0.209 | 0.200 | 43.750 | 37.500 |
| financial_only | Transactions (count YoY, pp) | 16 | 2.456 | 2.499 | 0.042 | 0.015 | 0.011 | 31.250 | 25.000 |
| guidance | Net revenue (GAAP, USD m) | 12 | 205.887 | 216.301 | 10.414 | 1.052 | -1.063 | 50.000 | 41.667 |
| guidance | Operating profit (ex special items, USD m) | 12 | 222.008 | 168.416 | -53.592 | -40.682 | -35.782 | 50.000 | 50.000 |
| guidance | Payments volume (constant-dollar YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Cross-border (constant-dollar YoY, approximate, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Transactions (count YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Net revenue (GAAP, USD m) | 16 | 196.339 | 151.875 | -44.464 | Unavailable | -35.584 | 56.250 | 81.250 |
| llm_baseline | Operating profit (ex special items, USD m) | 16 | 209.153 | 136.562 | -72.591 | Unavailable | -54.258 | 50.000 | 75.000 |
| llm_baseline | Payments volume (constant-dollar YoY, pp) | 15 | 2.040 | 1.013 | -1.027 | Unavailable | -0.990 | 20.000 | 93.333 |
| llm_baseline | Cross-border (constant-dollar YoY, approximate, pp) | 16 | 5.673 | 3.562 | -2.111 | Unavailable | -1.468 | 43.750 | 81.250 |
| llm_baseline | Transactions (count YoY, pp) | 16 | 2.456 | 0.806 | -1.650 | Unavailable | -1.586 | 31.250 | 100.000 |

- `seasonal_trend/net_revenue`: 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/operating_profit_ex_special_items`: 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/payments_volume_growth_constant`: 2022-01-27, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/net_revenue`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/operating_profit_ex_special_items`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/payments_volume_growth_constant`: 2022-01-27, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `guidance/net_revenue`: 2023-01-26, 2023-04-25, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `guidance/operating_profit_ex_special_items`: 2023-01-26, 2023-04-25, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `guidance/payments_volume_growth_constant`: none
- `guidance/cross_border_ex_intra_europe_growth_constant`: none
- `guidance/processed_transactions_growth`: none
- `llm_baseline/net_revenue`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/operating_profit_ex_special_items`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/payments_volume_growth_constant`: 2022-01-27, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28

### Matched q1 — primary

| Baseline | Target | n | Full MAE | Baseline MAE | Δ MAE | Δ CRPS | Δ WIS | Full coverage % | Baseline coverage % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seasonal_trend | Net revenue (GAAP, USD m) | 10 | 220.890 | 152.202 | -68.687 | -48.733 | -45.991 | 40.000 | 60.000 |
| seasonal_trend | Operating profit (ex special items, USD m) | 10 | 245.459 | 135.295 | -110.164 | -89.670 | -83.653 | 40.000 | 60.000 |
| seasonal_trend | Payments volume (constant-dollar YoY, pp) | 10 | 1.517 | 0.797 | -0.720 | -0.771 | -0.782 | 10.000 | 100.000 |
| seasonal_trend | Cross-border (constant-dollar YoY, approximate, pp) | 10 | 3.493 | 1.217 | -2.276 | -1.148 | -1.086 | 60.000 | 100.000 |
| seasonal_trend | Transactions (count YoY, pp) | 10 | 1.549 | 0.918 | -0.631 | -0.696 | -0.739 | 30.000 | 80.000 |
| financial_only | Net revenue (GAAP, USD m) | 10 | 220.890 | 220.503 | -0.386 | 1.216 | 1.177 | 40.000 | 40.000 |
| financial_only | Operating profit (ex special items, USD m) | 10 | 245.459 | 248.289 | 2.830 | 3.024 | 3.576 | 40.000 | 40.000 |
| financial_only | Payments volume (constant-dollar YoY, pp) | 10 | 1.517 | 1.521 | 0.004 | -0.002 | 0.005 | 10.000 | 20.000 |
| financial_only | Cross-border (constant-dollar YoY, approximate, pp) | 10 | 3.493 | 3.676 | 0.183 | 0.123 | 0.133 | 60.000 | 50.000 |
| financial_only | Transactions (count YoY, pp) | 10 | 1.549 | 1.587 | 0.038 | -0.000 | -0.012 | 30.000 | 20.000 |
| guidance | Net revenue (GAAP, USD m) | 10 | 220.890 | 232.698 | 11.809 | -4.204 | -9.556 | 40.000 | 50.000 |
| guidance | Operating profit (ex special items, USD m) | 10 | 245.459 | 173.452 | -72.007 | -60.341 | -56.056 | 40.000 | 60.000 |
| guidance | Payments volume (constant-dollar YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Cross-border (constant-dollar YoY, approximate, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Transactions (count YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Net revenue (GAAP, USD m) | 10 | 220.890 | 163.300 | -57.590 | Unavailable | -44.817 | 40.000 | 70.000 |
| llm_baseline | Operating profit (ex special items, USD m) | 10 | 245.459 | 164.300 | -81.159 | Unavailable | -70.142 | 40.000 | 60.000 |
| llm_baseline | Payments volume (constant-dollar YoY, pp) | 10 | 1.517 | 0.740 | -0.777 | Unavailable | -0.776 | 10.000 | 100.000 |
| llm_baseline | Cross-border (constant-dollar YoY, approximate, pp) | 10 | 3.493 | 1.600 | -1.893 | Unavailable | -1.647 | 60.000 | 90.000 |
| llm_baseline | Transactions (count YoY, pp) | 10 | 1.549 | 0.770 | -0.779 | Unavailable | -0.848 | 30.000 | 100.000 |

- `seasonal_trend/net_revenue`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/operating_profit_ex_special_items`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/payments_volume_growth_constant`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/cross_border_ex_intra_europe_growth_constant`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `seasonal_trend/processed_transactions_growth`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/net_revenue`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/operating_profit_ex_special_items`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/payments_volume_growth_constant`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/cross_border_ex_intra_europe_growth_constant`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `financial_only/processed_transactions_growth`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `guidance/net_revenue`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `guidance/operating_profit_ex_special_items`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `guidance/payments_volume_growth_constant`: none
- `guidance/cross_border_ex_intra_europe_growth_constant`: none
- `guidance/processed_transactions_growth`: none
- `llm_baseline/net_revenue`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/operating_profit_ex_special_items`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/payments_volume_growth_constant`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/cross_border_ex_intra_europe_growth_constant`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28
- `llm_baseline/processed_transactions_growth`: 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29, 2025-10-28, 2026-01-29, 2026-04-28

### Matched q1 — extension

| Baseline | Target | n | Full MAE | Baseline MAE | Δ MAE | Δ CRPS | Δ WIS | Full coverage % | Baseline coverage % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seasonal_trend | Net revenue (GAAP, USD m) | 4 | 185.918 | 101.262 | -84.656 | -52.937 | -41.728 | 75.000 | 25.000 |
| seasonal_trend | Operating profit (ex special items, USD m) | 4 | 160.363 | 64.698 | -95.665 | -57.187 | -46.954 | 75.000 | 50.000 |
| seasonal_trend | Payments volume (constant-dollar YoY, pp) | 5 | 3.087 | 1.589 | -1.498 | -1.214 | -1.202 | 40.000 | 60.000 |
| seasonal_trend | Cross-border (constant-dollar YoY, approximate, pp) | 6 | 9.307 | 3.634 | -5.673 | -3.545 | -2.800 | 16.667 | 50.000 |
| seasonal_trend | Transactions (count YoY, pp) | 6 | 3.969 | 1.682 | -2.286 | -2.257 | -2.275 | 33.333 | 33.333 |
| financial_only | Net revenue (GAAP, USD m) | 6 | 155.421 | 156.001 | 0.580 | 4.747 | 4.688 | 83.333 | 66.667 |
| financial_only | Operating profit (ex special items, USD m) | 6 | 148.643 | 152.078 | 3.435 | 0.039 | -0.004 | 66.667 | 66.667 |
| financial_only | Payments volume (constant-dollar YoY, pp) | 5 | 3.087 | 2.948 | -0.139 | -0.098 | -0.086 | 40.000 | 40.000 |
| financial_only | Cross-border (constant-dollar YoY, approximate, pp) | 6 | 9.307 | 9.730 | 0.423 | 0.352 | 0.311 | 16.667 | 16.667 |
| financial_only | Transactions (count YoY, pp) | 6 | 3.969 | 4.017 | 0.048 | 0.040 | 0.050 | 33.333 | 33.333 |
| guidance | Net revenue (GAAP, USD m) | 2 | 130.874 | 134.315 | 3.441 | 27.335 | 41.398 | 100.000 | 0.000 |
| guidance | Operating profit (ex special items, USD m) | 2 | 104.753 | 143.232 | 38.478 | 57.611 | 65.584 | 100.000 | 0.000 |
| guidance | Payments volume (constant-dollar YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Cross-border (constant-dollar YoY, approximate, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Transactions (count YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Net revenue (GAAP, USD m) | 6 | 155.421 | 132.833 | -22.588 | Unavailable | -20.196 | 83.333 | 100.000 |
| llm_baseline | Operating profit (ex special items, USD m) | 6 | 148.643 | 90.333 | -58.310 | Unavailable | -27.785 | 66.667 | 100.000 |
| llm_baseline | Payments volume (constant-dollar YoY, pp) | 5 | 3.087 | 1.560 | -1.527 | Unavailable | -1.418 | 40.000 | 80.000 |
| llm_baseline | Cross-border (constant-dollar YoY, approximate, pp) | 6 | 9.307 | 6.833 | -2.473 | Unavailable | -1.169 | 16.667 | 66.667 |
| llm_baseline | Transactions (count YoY, pp) | 6 | 3.969 | 0.867 | -3.102 | Unavailable | -2.817 | 33.333 | 100.000 |

- `seasonal_trend/net_revenue`: 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `seasonal_trend/operating_profit_ex_special_items`: 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `seasonal_trend/payments_volume_growth_constant`: 2022-01-27, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `seasonal_trend/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `seasonal_trend/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `financial_only/net_revenue`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `financial_only/operating_profit_ex_special_items`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `financial_only/payments_volume_growth_constant`: 2022-01-27, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `financial_only/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `financial_only/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `guidance/net_revenue`: 2023-01-26, 2023-04-25
- `guidance/operating_profit_ex_special_items`: 2023-01-26, 2023-04-25
- `guidance/payments_volume_growth_constant`: none
- `guidance/cross_border_ex_intra_europe_growth_constant`: none
- `guidance/processed_transactions_growth`: none
- `llm_baseline/net_revenue`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `llm_baseline/operating_profit_ex_special_items`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `llm_baseline/payments_volume_growth_constant`: 2022-01-27, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `llm_baseline/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24
- `llm_baseline/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24

### Matched 4q — overall

| Baseline | Target | n | Full MAE | Baseline MAE | Δ MAE | Δ CRPS | Δ WIS | Full coverage % | Baseline coverage % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seasonal_trend | Net revenue (GAAP, USD m) | 11 | 926.112 | 623.457 | -302.655 | -60.900 | -1.477 | 63.636 | 9.091 |
| seasonal_trend | Operating profit (ex special items, USD m) | 11 | 782.130 | 413.734 | -368.395 | -183.309 | -137.111 | 81.818 | 9.091 |
| seasonal_trend | Payments volume (constant-dollar YoY, pp) | 13 | 2.141 | 2.547 | 0.407 | 0.381 | 0.375 | 53.846 | 76.923 |
| seasonal_trend | Cross-border (constant-dollar YoY, approximate, pp) | 13 | 12.563 | 7.328 | -5.235 | -2.051 | -1.056 | 23.077 | 76.923 |
| seasonal_trend | Transactions (count YoY, pp) | 13 | 1.549 | 2.008 | 0.459 | 0.609 | 0.608 | 61.538 | 61.538 |
| financial_only | Net revenue (GAAP, USD m) | 13 | 848.278 | 900.787 | 52.510 | 62.539 | 53.531 | 69.231 | 61.538 |
| financial_only | Operating profit (ex special items, USD m) | 13 | 764.576 | 766.714 | 2.138 | 20.022 | 26.437 | 76.923 | 76.923 |
| financial_only | Payments volume (constant-dollar YoY, pp) | 13 | 2.141 | 1.021 | -1.120 | -0.831 | -0.801 | 53.846 | 76.923 |
| financial_only | Cross-border (constant-dollar YoY, approximate, pp) | 13 | 12.563 | 13.821 | 1.258 | 1.109 | 1.035 | 23.077 | 23.077 |
| financial_only | Transactions (count YoY, pp) | 13 | 1.549 | 0.821 | -0.728 | -0.530 | -0.503 | 61.538 | 76.923 |
| guidance | Net revenue (GAAP, USD m) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Operating profit (ex special items, USD m) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Payments volume (constant-dollar YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Cross-border (constant-dollar YoY, approximate, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| guidance | Transactions (count YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Net revenue (GAAP, USD m) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Operating profit (ex special items, USD m) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Payments volume (constant-dollar YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Cross-border (constant-dollar YoY, approximate, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |
| llm_baseline | Transactions (count YoY, pp) | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |

- `seasonal_trend/net_revenue_sum`: 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `seasonal_trend/operating_profit_ex_special_items_sum`: 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `seasonal_trend/payments_volume_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `seasonal_trend/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `seasonal_trend/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `financial_only/net_revenue_sum`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `financial_only/operating_profit_ex_special_items_sum`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `financial_only/payments_volume_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `financial_only/cross_border_ex_intra_europe_growth_constant`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `financial_only/processed_transactions_growth`: 2022-01-27, 2022-04-26, 2023-01-26, 2023-04-25, 2023-07-25, 2023-10-24, 2024-01-25, 2024-04-23, 2024-07-23, 2024-10-29, 2025-01-30, 2025-04-29, 2025-07-29
- `guidance/net_revenue_sum`: none
- `guidance/operating_profit_ex_special_items_sum`: none
- `guidance/payments_volume_growth_constant`: none
- `guidance/cross_border_ex_intra_europe_growth_constant`: none
- `guidance/processed_transactions_growth`: none
- `llm_baseline/net_revenue_sum`: none
- `llm_baseline/operating_profit_ex_special_items_sum`: none
- `llm_baseline/payments_volume_growth_constant`: none
- `llm_baseline/cross_border_ex_intra_europe_growth_constant`: none
- `llm_baseline/processed_transactions_growth`: none

## Ablations and persistence

central plus one-at-a-time calibrated low/high before external updates; no retuning. ablated minus full; positive means lower error for full model

Source: `visa_ablation_persistence.json`, `profiles.central.summary` and `robustness`, keys `<variant>.overall.<horizon>.<target>.<score>`. Profile direction counts are sensitivity cases, not additional independent forecasts. Detailed per-origin and per-window comparisons remain in the [ablation persistence document](../data/evaluation/ablation_persistence.md).

| Ablation | Horizon | Target | n | Full / ablated wins / ties | Δ MAE | Full coverage | Ablated coverage | Profiles favor full / ablated / tied |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_external_commentary | q1 | Net revenue (GAAP, USD m) | 16 | 6/10/0 | -0.024 | 9/16 | 8/16 | 12/1/0 |
| no_external_commentary | q1 | Operating profit (ex special items, USD m) | 16 | 8/8/0 | 3.057 | 8/16 | 8/16 | 10/3/0 |
| no_external_commentary | q1 | Payments volume (constant-dollar YoY, pp) | 15 | 8/7/0 | -0.044 | 3/15 | 4/15 | 1/12/0 |
| no_external_commentary | q1 | Cross-border (constant-dollar YoY, approximate, pp) | 16 | 12/4/0 | 0.273 | 7/16 | 6/16 | 13/0/0 |
| no_external_commentary | q1 | Transactions (count YoY, pp) | 16 | 9/7/0 | 0.042 | 5/16 | 4/16 | 12/1/0 |
| no_external_commentary | 4q | Net revenue (GAAP, USD m) | 13 | 7/6/0 | 52.510 | 9/13 | 8/13 | 13/0/0 |
| no_external_commentary | 4q | Operating profit (ex special items, USD m) | 13 | 7/6/0 | 2.138 | 10/13 | 10/13 | 10/3/0 |
| no_external_commentary | 4q | Payments volume (constant-dollar YoY, pp) | 13 | 1/12/0 | -1.120 | 7/13 | 10/13 | 1/12/0 |
| no_external_commentary | 4q | Cross-border (constant-dollar YoY, approximate, pp) | 13 | 11/2/0 | 1.258 | 3/13 | 3/13 | 12/1/0 |
| no_external_commentary | 4q | Transactions (count YoY, pp) | 13 | 4/9/0 | -0.728 | 8/13 | 10/13 | 1/12/0 |
| pooled_spending | q1 | Net revenue (GAAP, USD m) | 16 | 9/7/0 | 5.665 | 9/16 | 7/16 | 8/5/0 |
| pooled_spending | q1 | Operating profit (ex special items, USD m) | 16 | 9/7/0 | 7.192 | 8/16 | 8/16 | 10/3/0 |
| pooled_spending | q1 | Payments volume (constant-dollar YoY, pp) | 15 | 0/0/15 | 0.000 | 3/15 | 3/15 | 0/0/13 |
| pooled_spending | q1 | Cross-border (constant-dollar YoY, approximate, pp) | 16 | 9/7/0 | -0.110 | 7/16 | 0/16 | 1/12/0 |
| pooled_spending | q1 | Transactions (count YoY, pp) | 16 | 0/0/16 | 0.000 | 5/16 | 5/16 | 0/0/13 |
| pooled_spending | 4q | Net revenue (GAAP, USD m) | 13 | 5/8/0 | -195.459 | 9/13 | 9/13 | 5/8/0 |
| pooled_spending | 4q | Operating profit (ex special items, USD m) | 13 | 5/8/0 | -155.958 | 10/13 | 9/13 | 5/8/0 |
| pooled_spending | 4q | Payments volume (constant-dollar YoY, pp) | 13 | 0/0/13 | 0.000 | 7/13 | 7/13 | 0/0/13 |
| pooled_spending | 4q | Cross-border (constant-dollar YoY, approximate, pp) | 13 | 3/10/0 | -5.127 | 3/13 | 2/13 | 2/11/0 |
| pooled_spending | 4q | Transactions (count YoY, pp) | 13 | 0/0/13 | 0.000 | 8/13 | 8/13 | 0/0/13 |
| no_service_lag | q1 | Net revenue (GAAP, USD m) | 16 | 15/1/0 | 149.882 | 9/16 | 4/16 | 13/0/0 |
| no_service_lag | q1 | Operating profit (ex special items, USD m) | 16 | 15/1/0 | 172.058 | 8/16 | 3/16 | 13/0/0 |
| no_service_lag | q1 | Payments volume (constant-dollar YoY, pp) | 15 | 0/0/15 | 0.000 | 3/15 | 3/15 | 0/0/13 |
| no_service_lag | q1 | Cross-border (constant-dollar YoY, approximate, pp) | 16 | 0/0/16 | 0.000 | 7/16 | 7/16 | 0/0/13 |
| no_service_lag | q1 | Transactions (count YoY, pp) | 16 | 0/0/16 | 0.000 | 5/16 | 5/16 | 0/0/13 |
| no_service_lag | 4q | Net revenue (GAAP, USD m) | 13 | 7/6/0 | 71.560 | 9/13 | 9/13 | 12/1/0 |
| no_service_lag | 4q | Operating profit (ex special items, USD m) | 13 | 7/6/0 | 157.521 | 10/13 | 8/13 | 13/0/0 |
| no_service_lag | 4q | Payments volume (constant-dollar YoY, pp) | 13 | 0/0/13 | 0.000 | 7/13 | 7/13 | 0/0/13 |
| no_service_lag | 4q | Cross-border (constant-dollar YoY, approximate, pp) | 13 | 0/0/13 | 0.000 | 3/13 | 3/13 | 0/0/13 |
| no_service_lag | 4q | Transactions (count YoY, pp) | 13 | 0/0/13 | 0.000 | 8/13 | 8/13 | 0/0/13 |

## Extraction errors

Provider `openai`, model `gpt-5.4`, prompt `lon16-v1`. Source: `extraction.json`, `coverage`, `errors`, `review`, `failures`. These are extraction labels, not forecast origins.

| Coverage field | Count |
| --- | --- |
| correct_labels | 23 |
| disputed_labels | 0 |
| failed_passages | 1 |
| matched_labels | 71 |
| missing_passages | 0 |
| predictions | 74 |
| scored_labels | 80 |
| succeeded_passages | 18 |
| total_labels | 85 |
| total_passages | 19 |
| unavailable_labels | 5 |

| Error category | Errors | Denominator | Rate % |
| --- | --- | --- | --- |
| activity_scope | 32 | 71 | 45.070 |
| duplicate | 0 | 74 | 0.000 |
| geography | 26 | 71 | 36.620 |
| invalid_quote | 0 | 74 | 0.000 |
| omission | 9 | 80 | 11.250 |
| period | 4 | 71 | 5.634 |
| statement_type | 1 | 71 | 1.408 |
| unit_basis | 30 | 71 | 42.254 |
| unsupported | 3 | 74 | 4.054 |
| value_range | 2 | 71 | 2.817 |

Review status: **reviewed**; reviewed labels: **10**. Assistant-curated sample; human review covers the selected ten labels, not the entire corpus. Short purposively selected passages are not a random sample of filing extraction quality. Contradictions include revisions and opposing or apparently conflicting figures resolved by scope or period. Rates for semantic fields use matched labels; omissions use labels in successful passages. Unavailable labels remain in coverage. Prediction errors by category inherit all tags of the passage; categories overlap and must not be summed. Fiscal-period defaults, uncertainty margins, and semantic aliases follow the documented labeling guide. These extraction errors are separate from forecast errors and do not establish predictive performance.

| Failed passage | Status | Reason |
| --- | --- | --- |
| united-revenue-mix | invalid_response | Response did not match the extraction schema |

Detailed labels and category/family tables: [extraction error sample](../data/evaluation/extraction.md). Labeling and denominator policy: [extraction evaluation guide](extraction-eval.md).

## Benchmarks and portfolio availability

Source: `visa_portfolio.json`, `labels`, `aggregates`, `overlap`, `visa_strategy`, `visa_buy_and_hold`. Window returns overlap; their mean is not a stitched portfolio return or an alpha estimate.

S&P 500 total return (approximation: FRED S&P 500 price index + Shiller monthly dividends, accrued daily)

Not the official S&P 500 Total Return index. Prices: S&P Dow Jones Indices via FRED (SP500). Dividends: Shiller ie_data.xls (four-quarter S&P totals interpolated monthly), spread evenly across trading days. Fetched by script; not redistributed.

US total-market total return (Ken French Mkt-RF + RF, CRSP value-weighted) - not the S&P 500

Visa buy-and-hold total return: not run (no license-compliant free daily Visa price source)

| Benchmark key | Scored n | Estimated n | Unavailable n | Mean window return % | Worst window drawdown % |
| --- | --- | --- | --- | --- | --- |
| sp500_tr_approx | 16 | 1 | 0 | 4.219 | -18.752 |
| us_total_market_tr | 16 | 0 | 0 | 4.230 | -19.558 |

Overlapping pairs: 9; windows with overlap: 14.

| Comparison | Status | Scored n | Reason |
| --- | --- | --- | --- |
| visa_strategy | not_run | 0 | No license-compliant free daily Visa price source |
| visa_buy_and_hold | not_run | 0 | No license-compliant free daily Visa price source |

## Failure case — largest next-quarter revenue error

Selection rule: maximum full-model `q1.net_revenue.abs_error`, earliest origin breaking ties. Selected origin **2024-10-29**, target **FY2025Q1**. First-print GAAP revenue was **9,510.000 USD million**. Source: `data/fixtures/visa_releases/observations.csv`, period `FY2025Q1`, field `net_revenue`, source `0001403161-25-000016/q12025earningsrelease.htm`, location `primary`. The target release was accepted at `2025-01-30T21:05:52Z`. Forecast and error cells below come from each variant's saved origin score keys, not a new simulation.

| Variant | Median (USD m) | Absolute error (USD m) | Error % | Inside 80% interval | WIS (USD m) |
| --- | --- | --- | --- | --- | --- |
| full_model | 10,020.364 | 510.364 | 5.367 | No | 402.798 |
| seasonal_trend | 9,493.869 | 16.131 | 0.170 | Yes | 27.058 |
| financial_only | 10,049.725 | 539.725 | 5.675 | No | 431.824 |
| guidance | 9,320.859 | 189.141 | 1.989 | Yes | 97.079 |
| llm_baseline | 9,450.000 | 60.000 | 0.631 | Yes | 53.125 |

## Frozen prospective registration

Target **FY2026Q4**; evidence cutoff `2026-07-28T20:05:26+00:00`; actual registration `2026-10-07T19:24:14.444045+00:00`; run `fbbad1df-6531-4a41-86e0-32dda8a482c2`; content hash `f779edc7233dc6afc991f73d19e91bc643940d64df46880c0d832a7935da9954`. **Not yet scored.** Registration occurred after the fiscal quarter ended, using the July evidence cutoff before results publication. It is not a July registration or a pre-quarter forecast. No prospective row enters the tables above. The preserved procedure below describes later scoring without changing this artifact.

## Source ledger

All paths are relative to the standalone package. SHA-256 identifies exact input bytes. Configuration/content hashes identify retained runs or suites; they are not replaced with current code hashes. Forecast JSONs export persisted evaluation rows rounded to ten significant digits. Generation validates counts, coverage and exported score means with rounding tolerance; it does not reconstruct missing path distributions or claim to replay old executions. Source files remain unchanged.

| File | SHA-256 | Configuration / content hash |
| --- | --- | --- |
| `data/demo/forecasts/prospective_fy2026q4.json` | `e7b102c2df81f507440690ff38c789d47973ad0871da199d8a8751a211fcf26b` | `—` |
| `data/demo/forecasts/prospective_fy2026q4.paths.npz` | `eb80d4b296b05fee366e5fe50450cbfa57edcf3011de2ba384c6ebbb314885d1` | `—` |
| `data/evaluation/extraction.json` | `47588e5a99369c63989e126dfd448b3a55413bf2f0e7be0a6b552b1be9793b99` | `55360cd8d41f4db9b9f3974a744db87b86e0014d16f68c0f22743a64d7d953d5` |
| `data/evaluation/visa_ablation_persistence.json` | `d83521bc535acc419a974ef56af46851016906b4720d49057ac3f48fda2bac0e` | `beb508658d7fe645c80e95b215702b5d6ad0a553149b080403fc1be4733bd463` |
| `data/evaluation/visa_financial_only.json` | `40f093a9d84742e9abefd664dd34cb6aea01e368e7dfd7210aa92791123feaaa` | `21b0880dd67399a10495f8041f4119c02e8ad9d6e2cb68f270d8f40cfe2896a1` |
| `data/evaluation/visa_full_model.json` | `12c0d6345bdf21f6ae023b85fb571685e333ae2073610999b0f989a32ef514c1` | `b601835dbea92d5fa1ca902d5e36bf686c6a045a3767efd60545f37c7a494410` |
| `data/evaluation/visa_guidance.json` | `5586480a42aac894de29ff494923e23023ea189195f1aaf43fac81b24e05d320` | `5043706a05322a129e8652953eead19933d67d27ccfaf11563baede5bca9c16d` |
| `data/evaluation/visa_llm_baseline.json` | `3d6f084e703e0ae938e67fd3e6abe1c9644f1d9aeb1b831108a8dc2441d470f0` | `c742d75dc8f26bb7c568535087b1be50275d36f06abd2836ef8280862b91607d` |
| `data/evaluation/visa_no_external_commentary.json` | `aecf762bbd7d1bb5dc3d0d489416a5d1db718340570d6addb97265f4397d9f99` | `903cafc36fdd28c3e04f1419565ff2fef4ad9e63de32e7f9791eb4f52a76cb79` |
| `data/evaluation/visa_no_service_lag.json` | `fe144560881f5d3e896bc05071925e5ad0b6c8b8207e5a17465a9be9f4ab2f83` | `1ec1440cb19286110964b8376125fed243c7d24e934e91ea3b015e1d21272ab1` |
| `data/evaluation/visa_pooled_spending.json` | `bc9308d76b6d5f3ff50afb29c318fcc530b89a838e563e84616cc2f491ee5432` | `acd79c296c9f52c94b882e2afdb662129b24fd52b0ea2f6f8f35e10ff7c2e6d2` |
| `data/evaluation/visa_portfolio.json` | `627c823e6d89fb94e3bf296706cee8d5d1b0a554569bba350581c930e141c281` | `44cb1928c2159fca06dfd124e8c04a6091829e4f8cfa39734f162fbaa1fb3639` |
| `data/evaluation/visa_seasonal_trend.json` | `2384d456ce1f0a5e9d2a7b0a04bd1ca893f18577b80fbbd5013f02d72b6833fb` | `c01522905ce5715cf8ed6c57d7d9f8be1f8843969f8320699ee23f9a3253a30a` |
| `data/fixtures/origins.csv` | `0397f08bf6471a0baef91b3586dbceb66a97dc3a1832e50a0968760fa1adc09d` | `—` |
| `data/fixtures/visa_releases/observations.csv` | `2e343e3ed87b5b75039c53a303b0aea6c113b9249f74381f5a853d3407624be8` | `—` |
| `data/fixtures/visa_releases/sources/manifest.json` | `f8bb867fb01eddd95c85571a04026cd5ac76e40301772214a26386bacb7699b8` | `—` |
| `data/manifest/benchmarks.yaml` | `f1d49aff9081ba7fea967bc2eb6f03f565b3a2ee29c5536a74da6e6f8ce8111b` | `—` |

### Retained code fingerprints

| Variant | Engine version | Evaluation code hash |
| --- | --- | --- |
| full_model | 0.1.0+cf93263a1d638ffa | `1182ed2a1f9f635dc08751555ef91bd5c1db4c926fd496429654063d2c9c1e6b` |
| seasonal_trend | 0.1.0+cf93263a1d638ffa | `1182ed2a1f9f635dc08751555ef91bd5c1db4c926fd496429654063d2c9c1e6b` |
| financial_only | 0.1.0+cf93263a1d638ffa | `1182ed2a1f9f635dc08751555ef91bd5c1db4c926fd496429654063d2c9c1e6b` |
| guidance | 0.1.0+cf93263a1d638ffa | `1182ed2a1f9f635dc08751555ef91bd5c1db4c926fd496429654063d2c9c1e6b` |
| llm_baseline | 0.1.0+cf93263a1d638ffa | `ca8d5806e58a7a12bcbf6dc6e9b7edfb7504e759bbf0d164b75acfae93817c5f` |
| no_external_commentary | 0.1.0+cf93263a1d638ffa | `1182ed2a1f9f635dc08751555ef91bd5c1db4c926fd496429654063d2c9c1e6b` |
| pooled_spending | 0.1.0+cf93263a1d638ffa | `1182ed2a1f9f635dc08751555ef91bd5c1db4c926fd496429654063d2c9c1e6b` |
| no_service_lag | 0.1.0+cf93263a1d638ffa | `1182ed2a1f9f635dc08751555ef91bd5c1db4c926fd496429654063d2c9c1e6b` |

<!-- END GENERATED EVALUATION -->

## Interpretation and limits

The results do not establish that added model complexity consistently improves
forecasts. Use the matched-origin baseline tables to assess each target and
horizon separately; the seasonal/trend and company-guidance baselines do not
have a score for every level target. Company guidance uses adjusted constant-dollar
outlooks against GAAP nominal actuals, and its operating-profit forecast is derived
from revenue and opex guidance. This basis mismatch remains a limitation. LLM CRPS and four-quarter forecasts are
unavailable. They must not be filled with zero or compared as if measured.

External commentary changes reviewed parameter values, but its effect on errors
is mixed across origins and horizons. The ablations describe consequences of
this model, evidence selection and parameter ranges. Neither a sensitivity
profile nor a second metric creates another independent forecast origin.
Intervals frequently miss actuals; a nominal coverage level is a target, not
an empirical guarantee. Extraction scope and unit/basis errors further constrain
automation, and the reviewed sample does not establish general extraction quality.

Historical inputs are selected by publication cutoff, while model development,
source retrieval and observation review were retrospective. The LLM received
same-source evidence excerpts rather than complete filings. Its pretrained
knowledge may contain outcomes regardless of the supplied cutoff. These are
exploratory retrospective comparisons, not a reconstruction of a workflow that
was actually operated at every historical origin.

### Failure-case diagnosis and invalidating conditions

The selected failure is an observed revenue overprediction outside the saved
central interval. Baselines for that same origin show the miss is not merely a
consequence of comparing different samples. The retained scores establish the
miss; they do **not** identify which model rule caused it. Plausible explanations
include seasonal activity, changing effective yields, and incentive intensity.
Those explanations require a separate decomposition before making a causal claim.

Observable conditions that invalidate continued use of the frozen assumptions:

- **Activity:** newly reported constant-dollar volume, processed transactions or
  cross-border growth contradicts the origin's growth or mix assumptions. Check
  each on its declared basis; annualized quarter-over-quarter model outputs are
  not reported year-over-year growth.
- **Yields and timing:** reported service revenue relative to prior-quarter
  volume, data-processing revenue per transaction, or international revenue
  relative to the modeled cross-border activity departs from the assumed drift
  range. Cross-border levels remain inferred, so the last ratio cannot by itself
  identify a fee change.
- **Incentives:** reported incentives as a share of gross category revenue leave
  the frozen assumed range. A new contract or mix change would invalidate the
  old intensity path; it would not justify revising an already scored forecast.
- **Definitions:** a changed reporting perimeter, restatement, or newly identified
  special item makes actuals non-comparable with the forecast basis. Flag the
  comparison rather than substituting a later vintage or a different profit basis.

Any follow-up should retain the original forecast and record new evidence and
parameter changes as a separate run. No thresholds or parameters were tuned to
erase this failure. Benchmark windows describe market returns independently;
Visa strategy, buy-and-hold and excess-return comparisons remain unavailable
without the documented daily price source.

## Prospective Q4 FY2026 registration

The frozen artifact is `data/demo/forecasts/prospective_fy2026q4.json`, with its
compressed paths in the sibling `prospective_fy2026q4.paths.npz`. The JSON retains
the immutable archive entries, actual registration timestamp, starting state,
calibrated parameters, reviewed evidence and mapping decisions, source manifest,
frozen driver history, seed, code/runtime fingerprints and output hashes.

The evidence origin is July 28, 2026 at **20:05:26 UTC** (Visa FY2026Q3).
The headline target is **FY2026Q4, July 1–September 30, 2026**. The registration
is created in October, after the fiscal quarter ended and before its earnings
release. It is a forecast of unpublished results using the July evidence cutoff;
its creation time must never be presented as July 28 or as a pre-quarter forecast.
Read the exact registration time and run ID from the artifact and the Prospective
section of the Evaluation page.

The run uses 5,000 paths, four quarterly transitions, the existing origin-derived
seed with base seed 27000, service lag enabled, pooled spending disabled, and no
interventions. Calibration excludes pandemic periods by default and uses only
evidence available at the origin. The five archived metrics span FY2026Q4 through
FY2027Q3. Supporting horizons are not additional independent forecast origins.

**Not yet scored.** This registration does not contribute to retrospective sample
counts, error aggregates or coverage denominators. No actuals are loaded or scored
by the registration command or the saved-report page. Historical model development
and retrospective choices still limit any eventual interpretation of this single
prospective result.

### Registration and verification procedure

Visa's official [quarterly-results table](https://investor.visa.com/financial-information/quarterly-earnings/default.aspx)
is populated by JavaScript. Inspect its complete earnings-release row in a browser,
including the FY2026 Q4 column. A 403, empty page, truncated result or stale cached
inventory cannot establish that results are unpublished.

For a new registration, capture a JSON publication check with `source_url` set to
that exact URL, `checked_at` set to the actual UTC check time, `method` set to
`rendered_official_quarterly_table`, and `release_links` containing **all** FY2026
earnings-release links in the rendered row. The command requires Q1, Q2 and Q3,
rejects Q4 or incomplete evidence, and requires a check less than an hour old.
This is an operator-attested browser capture, not an automatic live publication
monitor. Retain the exact links and timestamp; do not infer absence from a failed
request. The check is retained inside the frozen registration.

From `longaeva/`, with Postgres running and the backend virtualenv installed:

```bash
make register-prospective ARGS='--publication-check /tmp/visa-publication-check.json'
make replay-prospective
```

The first command executes and archives the calibrated reviewed baseline with
LLM access disabled. It requires an exact replay hash in the registration runtime.
Repeating it verifies and reuses the same run and archive entries. A PostgreSQL
lock prevents concurrent duplicate registrations; an interrupted export resumes
the recorded run. Existing registrations, timestamps and path artifacts are never
replaced. A changed artifact or failed/running run is reported for investigation.

The second command replays the packaged state and parameter values directly,
without Postgres, calibration, evidence collection or an LLM. Across platforms it
reports the existing engine's `numerically_equivalent` category when differences
are within its 1e-9 tolerance, retaining both hashes. This does not rewrite the
registration's original exact replay proof.

### Score later without changing the registration

1. Preserve the registration JSON, NPZ bytes, content hash, original archive rows
   and creation timestamps. Validate them with `make replay-prospective` first.
2. After Visa publishes Q4 FY2026 results, collect the original earnings release,
   retain its bytes and hash, record its exact EDGAR acceptance timestamp and parse
   first-print actuals with the existing Visa parser. Record actual-source metadata
   separately, proving publication occurred after registration.
3. Load samples from the frozen NPZ. Score net revenue in USD millions on the GAAP
   basis and operating profit on the ex-special-items basis used by the model.
   Document any unavailable or non-comparable actual instead of silently changing
   the definition.
4. The archived driver rates are **annualized quarter-over-quarter ratios**:
   `(1 + quarterly_growth)^4 - 1`. The UI multiplies these ratios by 100 for display.
   They are not Visa's reported year-over-year growth. Use
   `annualized_to_quarterly` and `forecast_driver_yoy` from the existing evaluation
   harness with the registration's frozen `evidence.driver_history` and saved paths
   before scoring published constant-dollar PV/cross-border growth or transaction
   count growth. Preserve skip reasons for missing history; do not fit missing
   history from later releases.
5. Apply `score_samples` to comparable samples and actuals. Save a separate dated
   prospective score report referencing the registration content/output hashes and
   actual-source hashes. Keep its scores and denominators separate from the
   retrospective report. Do not recalibrate, rerun the forecast with new inputs,
   update/delete archive rows, or score supporting quarters before their results
   become available.
