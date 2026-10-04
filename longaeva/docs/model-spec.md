# Visa model specification

LON-19 / LON-20 · planning v1 · engine core settled October 3, 2026; calibration
settled October 3, 2026.

This document describes the Visa quarterly operating model implemented in
`backend/longaeva_app/companies/visa/` and the company-agnostic Monte Carlo engine in
`backend/longaeva_app/engine/`. Field names follow [`docs/definitions.md`](definitions.md).
Interventions (LON-22) remain out of scope here.

## 1. Overview

Each simulation starts from a dated starting state (LON-3 fixtures today; LON-14 parser
later), draws correlated factor shocks from a seeded generator, and advances four fiscal
quarters. Company code never generates random numbers. All randomness arrives through
factor draws so paired runs (LON-22) can share them exactly.

**Decisions locked in LON-19:**

1. **Six factors.** Demand, travel and FX are correlated (MR-08). Pricing, incentives and
   costs are independent factors with their own volatilities.
2. **Cross-border as a share of payments volume.** The origin share is an explicit
   analyst-assumption parameter (`cross_border_share_at_origin`). Domestic + cross-border
   equals total payments volume by construction (MR-05).

Defaults are **uncalibrated placeholders**. A run on defaults is not a forecast.

## 2. State variables

Carried path-wise between quarters. Built from a starting-state map by
`companies/visa/state.py`.

| name | unit | description |
| --- | --- | --- |
| `payments_volume_nominal_us` | usd_billions | Nominal payments volume (USD bn) |
| `payments_volume_index_constant` | index | Constant-dollar PV index (100 at origin) |
| `cross_border_share` | ratio | Cross-border ex-intra-Europe share of PV |
| `processed_transactions_count` | transactions_millions | Processed transactions (millions) |
| `effective_yield_service` | ratio | Lag-basis service yield: SR(t)/PV(t-1) in million-USD units |
| `effective_yield_service_current` | ratio | Current-basis service yield: SR(t)/PV(t); used when service_lag=False |
| `effective_yield_data_processing` | ratio | Data-processing yield: DPR / transactions |
| `effective_yield_international` | ratio | International yield on cross-border volume (million-USD units) |
| `incentive_intensity` | ratio | Client incentives / gross category revenue |
| `other_revenue` | usd_millions | Other-revenue run-rate |
| `operating_expenses_ex_special_items` | usd_millions | Recurring opex baseline (ex special items) |

Yield *levels* come from the starting state (or are derived from it using the share
assumption). There is no yield-level or fee parameter (MR-06). Teaching-fee constants from
the Stage 1 proposal are not inputs anywhere.

## 3. Sampler contract

Module: `engine/sampler.py`.

- Generator: `numpy.random.Generator(PCG64(seed))`.
- Raw draws: iid standard normals with shape `(n_paths, n_quarters, n_factors)` in
  **path-major** order. Path `i` is identical for any `n_paths > i` under the same seed.
- Correlation: Cholesky root of the company's factor correlation matrix. A singular but
  positive-semidefinite matrix uses a symmetric eigendecomposition root. Non-PSD matrices
  are rejected.
- Raw draws never depend on parameter values (paired-run safety for LON-22).

Visa factors (order): `demand`, `travel`, `fx`, `pricing`, `incentives`, `costs`.

The 3×3 macro block among demand/travel/FX is parameterized by
`corr_demand_travel`, `corr_demand_fx`, `corr_travel_fx`. Pricing, incentives and costs
are independent (identity block).

## 4. Transition rules

Module: `companies/visa/transitions.py`. Numbered list mirrored by the hand-walked unit
test (MR-02). Annual rates convert to quarterly via `(1+r)^(1/4) − 1`. Seasonal ratio sets
are geo-mean normalized to 1 at use time so annual growth comes only from growth
parameters.

1. **Read factor draws** for the quarter. Company code never generates randomness.
2. **Update activity**
   - Constant-dollar growth = quarterly trend × activity seasonal + `demand_vol` × demand.
   - Nominal payments volume also takes `fx_vol` × FX (translation).
   - Transactions take constant-dollar growth plus `transactions_growth_premium` (no FX).
   - Cross-border share updates multiplicatively so cross-border grows
     `cross_border_growth_premium` faster than total (exact to first order), applied in
     logit space to stay in (0, 1). Travel shock and cross-border seasonal enter here.
   - Domestic volume = total − cross-border.
3. **Update pricing, incentives and costs**
   - The three category yields drift with their annual drifts and one shared pricing shock.
   - International yield also takes `international_fx_sensitivity` × FX.
   - Incentive intensity moves in logit space with its drift and incentive shock.
   - Other revenue grows at `other_revenue_growth`.
   - Recurring opex follows `opex_growth`, opex seasonal and the cost shock.
4. **Category revenue** (see §5).
5. **Client incentives** = intensity × Σ category revenue.
6. **Net revenue** = Σ categories − incentives.
7. **Operating profit (ex special items)** = net revenue − recurring opex.

The first simulated period is the quarter *after* the origin fiscal period.

## 5. Revenue rules, identities and switches

### Revenue (MR-03)

| Category | Driver | Timing |
| --- | --- | --- |
| Service | lag-basis yield × prior-quarter PV (million-USD units) | prior quarter; or same-quarter PV when `service_lag=False` |
| Data processing | yield × processed transactions | current quarter |
| International | yield × (share × current PV) | current quarter |
| Other | other-revenue run-rate | current quarter |

### Identities (MR-04, relative tolerance ≤ 1e-9 on every path/quarter)

1. `service + data_processing + international + other − client_incentives = net_revenue`
2. `net_revenue − operating_expenses_ex_special_items = operating_profit_ex_special_items`
3. `domestic_payments_volume + cross_border_ex_intra_europe_volume = payments_volume_nominal_us`

Only the **ex-special-items** operating-profit basis is simulated. GAAP operating profit
remains a reporting field on fixtures, not a path metric.

### Switches (MR-11)

| Switch | Default | Effect |
| --- | --- | --- |
| `service_lag` | `true` | When `false`, service revenue uses current-basis yield × same-quarter PV. |
| `pool_mix` | `false` | When `true`, freeze the cross-border share so domestic and cross-border share one growth driver. Travel draws are still consumed so paired runs stay aligned. |

## 6. Parameters

32 parameters: 8 free (MR-09), 22 estimated, 2 assumption. Defaults are uncalibrated.

| name | role | unit | lower | upper | default | description |
| --- | --- | --- | --- | --- | --- | --- |
| `payments_volume_growth` | free | ratio | -0.4 | 0.4 | 0.08 | Constant-dollar YoY payments-volume growth trend (annual). |
| `cross_border_growth_premium` | free | ratio | -0.2 | 0.4 | 0.02 | Annual constant-dollar growth premium of cross-border ex-intra-Europe over total PV. |
| `transactions_growth_premium` | free | ratio | -0.2 | 0.4 | 0.0 | Annual growth premium of processed transactions over constant-dollar PV. |
| `service_yield_drift` | free | ratio | -0.2 | 0.2 | 0.0 | Annual drift of the lag-basis and current-basis service yields. |
| `data_processing_yield_drift` | free | ratio | -0.2 | 0.2 | 0.0 | Annual drift of the data-processing yield. |
| `international_yield_drift` | free | ratio | -0.2 | 0.2 | 0.0 | Annual drift of the international (cross-border) yield. |
| `incentive_intensity_drift` | free | ratio | -0.2 | 0.2 | 0.0 | Annual drift of incentive intensity in ratio points (applied via logit). |
| `opex_growth` | free | ratio | -0.2 | 0.4 | 0.05 | Annual growth of recurring operating expenses (ex special items). |
| `activity_seasonal_q1` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q1 seasonal ratio for constant-dollar PV (geo-mean 1). |
| `activity_seasonal_q2` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q2 seasonal ratio for constant-dollar PV (geo-mean 1). |
| `activity_seasonal_q3` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q3 seasonal ratio for constant-dollar PV (geo-mean 1). |
| `activity_seasonal_q4` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q4 seasonal ratio for constant-dollar PV (geo-mean 1). |
| `cross_border_seasonal_q1` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q1 seasonal ratio for cross-border premium (geo-mean 1). |
| `cross_border_seasonal_q2` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q2 seasonal ratio for cross-border premium (geo-mean 1). |
| `cross_border_seasonal_q3` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q3 seasonal ratio for cross-border premium (geo-mean 1). |
| `cross_border_seasonal_q4` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q4 seasonal ratio for cross-border premium (geo-mean 1). |
| `opex_seasonal_q1` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q1 seasonal ratio for recurring opex (geo-mean 1). |
| `opex_seasonal_q2` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q2 seasonal ratio for recurring opex (geo-mean 1). |
| `opex_seasonal_q3` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q3 seasonal ratio for recurring opex (geo-mean 1). |
| `opex_seasonal_q4` | estimated | ratio | 0.5 | 1.5 | 1.0 | Q4 seasonal ratio for recurring opex (geo-mean 1). |
| `other_revenue_growth` | estimated | ratio | -0.4 | 0.6 | 0.12 | Annual growth of other-revenue run-rate. |
| `demand_vol` | estimated | ratio | 0.0 | 0.5 | 0.04 | Std of demand shock contribution to constant-dollar PV growth (quarterly). |
| `travel_vol` | estimated | ratio | 0.0 | 0.5 | 0.05 | Std of travel shock contribution to cross-border growth premium (quarterly). |
| `fx_vol` | estimated | ratio | 0.0 | 0.5 | 0.02 | Std of FX translation shock on nominal PV (quarterly). |
| `pricing_vol` | estimated | ratio | 0.0 | 0.5 | 0.02 | Std of shared pricing shock on category yields (quarterly). |
| `incentive_vol` | estimated | ratio | 0.0 | 0.5 | 0.02 | Std of incentive-intensity shock in logit space (quarterly). |
| `cost_vol` | estimated | ratio | 0.0 | 0.5 | 0.02 | Std of cost shock on recurring opex growth (quarterly). |
| `corr_demand_travel` | estimated | correlation | -1.0 | 1.0 | 0.4 | Correlation of demand and travel factors. |
| `corr_demand_fx` | estimated | correlation | -1.0 | 1.0 | 0.2 | Correlation of demand and FX factors. |
| `corr_travel_fx` | estimated | correlation | -1.0 | 1.0 | 0.15 | Correlation of travel and FX factors. |
| `cross_border_share_at_origin` | assumption | ratio | 0.05 | 0.35 | 0.2 | Analyst-assumption share of payments volume that is cross-border ex-intra-Europe at the origin quarter. Midpoint of the allowed range; not an estimate (LON-3: no disclosed CB level). |
| `international_fx_sensitivity` | assumption | ratio | -1.0 | 1.0 | 0.0 | Additional FX sensitivity on the international yield (0 = pricing shock only). |

### 6.1 Calibration (LON-20)

Implementation: `companies/visa/calibration.py`. Artifacts:
`data/calibration/visa_<origin-date>.json`. CLI: `python -m longaeva_app.cli calibrate`
(prefer the host venv for `--write`; Compose mounts `data/` read-only).

**Vintage rule.** Each observation's publication time is its source's EDGAR
`acceptance_utc`. Fits use the latest vintage published at or before the origin cutoff.
Comparative quarterly levels are remapped to the year-ago period so post-cutoff
restatements cannot leak (tested: FY2023Q2 payments volume is 2,957 at the FY2024Q3
cutoff and 2,963 at the FY2024Q4 cutoff). Fiscal Q3 payments-volume levels are
`TTM − 9M` with publication time equal to the later of the two windows.

**Quality gates.** FY2017 and FY2018Q1 are unused. Image-era net revenue and
GAAP-derived opex are excluded; opex enters only when `statement_type=measured`
(modern table era). Non-positive or ±25% QoQ-jump PV levels are dropped. Cross-border
uses ex-intra-Europe growth only (disclosed from FY2021Q3).

**Pandemic treatment.** Estimation weight is zero for FY2020Q2–FY2021Q4, for YoY
comparisons against those quarters (through FY2022Q4), and for QoQ comparisons that
touch them (through FY2022Q1). Quarters remain in the panel, flagged. An
"if included" alternative is reported in each artifact's sensitivity table.

**Estimators.** Activity and opex seasonal ratios are demeaned mean log QoQ changes,
geo-mean normalized to 1. Cross-border seasonals are assumed 1.0 (not identifiable from
YoY-only disclosure). The eight free parameters plus `other_revenue_growth` are fitted
with bounded `scipy.optimize.least_squares` on YoY log residuals implied by four
zero-shock steps of `transition_quarter`. Shock scales are residual SD / 2 (travel also
`/ (1 − share)`; FX is RMS of nominal−constant gaps / 2). Macro correlations are
nearest-PSD projections (defaults when fewer than six common quarters). Ranges are 90%
intervals clipped to `ParameterSpec` bounds.

**Ensemble.** Members end at the origin: last 4 quarters, last 8 quarters, and full
history from FY2018Q2. Weights are inverse MSE of one-step pseudo-OOS errors over the
last four eligible quarters (Bates–Granger), normalized to sum to 1. The pooled set is
a weight-average (geo-mean for seasonals; PSD projection for correlations). Runs use
the pooled set; each evaluation row (LON-27) also records ensemble members and weights.

**Evidence.** Each parameter links to deterministic observation UUIDs
(`observation_uuid_for` in `extract/visa_tables.py`) or `assumption=true` with a
rationale. Artifacts carry an `evidence_index`; LON-37 loads rows under the same IDs.

**Calibrated pooled values (committed artifacts).**

| origin | weights (last_4q / last_8q / full) | `payments_volume_growth` | `opex_growth` | `demand_vol` |
| --- | --- | --- | --- | --- |
| 2024-07-23 (FY2024Q3) | 0.499 / 0.364 / 0.137 | 0.0825 | 0.1086 | 0.0047 |
| 2025-10-28 (FY2025Q4) | 0.647 / 0.149 / 0.204 | 0.0852 | 0.1108 | 0.0034 |

**Sensitivity.** Each artifact includes a table of next-quarter mean net revenue,
next-quarter mean operating profit (ex special items), and four-quarter mean net
revenue under low/high yield and incentive drifts (90% ranges), assumption-parameter
bounds, and the pandemic-included alternative. Common seed, 2,000 paths.

## 7. Outputs

`engine/runner.simulate` returns path-complete metric and end-of-quarter state arrays of
shape `(n_paths, n_quarters)`, the correlated draws, the simulated fiscal periods, seed,
switches and parameters.

`engine/summary.summarize_paths` reports, per metric and quarter:

- mean, sample standard deviation, Monte Carlo SE of the mean (`std / √n`)
- quantiles keyed `"0.05"`, `"0.1"`, `"0.25"`, `"0.5"`, `"0.75"`, `"0.9"`, `"0.95"`
  (same style as `RunResultSummary` / forecast rows)
- batch-means SE per quantile

Default `n_paths` is 5,000 (MR-08).

## 8. Performance (NR-01)

Target: 5,000 paths × 4 quarters ≤ 60 s on a laptop (CPU-only NumPy).

| Field | Value |
| --- | --- |
| Measured at (UTC) | 2026-10-03T03:31:30Z |
| Fixture | `data/fixtures/states/visa_2024-07-23.json` (FY2024Q3) |
| Paths × quarters | 5,000 × 4 |
| Median / max (5 repeats) | **4.4 ms / 4.9 ms** |
| Limit | 60 s |
| Environment | Python 3.12.2, NumPy 2.5.3, macOS arm64 (Apple M1) |
| Result | **Pass** (≈12,000× under the limit) |

Re-measure:

```bash
cd backend && .venv/bin/python -m longaeva_app.cli engine-benchmark --repeats 3
```

## 9. Handoffs

- **LON-14:** parsers must reproduce LON-3 fixtures; engine consumes the same field names.
- **LON-20 (done):** chronological fit, ensemble weights, evidence UUIDs, sensitivity
  table, and pandemic exclusion are implemented; see §6.1.
- **LON-21:** mapping rules update parameter sets (including the share assumption) with
  provenance; assumption flags already declared on the two assumption parameters.
- **LON-22:** interventions (`mix_shift_conserving_total`, `total_spend_reduction`) and
  attribution; reuse shared draws from the sampler; share-based CB state is already
  conservation-ready.
- **LON-23:** persist runs with seed, `n_paths`, parameter-set hash, switches and
  output hash; see [`docs/runs-and-replay.md`](runs-and-replay.md).
- **LON-25:** valuation bridge consumes `operating_profit_ex_special_items` paths plus
  fixture `tax_rate` / `net_interest_other` / `diluted_shares`.
- **LON-27 (done):** evaluation harness calibrates at each origin, runs the full model,
  scores levels and history-anchored YoY drivers, and records ensemble members/weights
  per row. See [`docs/evaluation.md`](evaluation.md). Engine metric
  `payments_volume_growth_constant` remains annualized QoQ; scoring recovers quarterly
  rates before the YoY transform.
- **LON-29 / LON-31:** reuse the harness with a different `model_variant` (baselines;
  ablation switches); keep the same origins, actuals, seeds and metrics.
- **LON-32:** the state builder produces the FY2026Q3 prospective start; reuse the
  sensitivity harness for ablations.
- **LON-33:** cite `data/evaluation/visa_full_model.json` with its `n` and exclusions.
- **LON-36:** `GET /evaluation-results` needs `model_variant` / `config_hash` filters
  and a higher limit (~800 rows per variant).
- **LON-37:** load observations under the deterministic UUIDs so evidence links resolve.
- **Parser follow-up:** extract FY2020/FY2021 10-K 12-month PV tables to recover
  FY2022Q3 and FY2022Q4.
