# Visa model specification

Methods documented on October 7, 2026. Engine and calibration definitions
remain those used by the retained evaluation runs.

This document describes the Visa quarterly operating model implemented in
`backend/longaeva_app/companies/visa/` and the company-agnostic Monte Carlo engine in
`backend/longaeva_app/engine/`. Field names follow [`docs/definitions.md`](definitions.md).
Interventions are specified in [`docs/scenarios.md`](scenarios.md) and applied after
the activity step below; with none active, this arithmetic is unchanged.

## 1. Overview

Each simulation starts from a dated starting state built by the Visa parser from
cutoff-filtered observations, draws seeded correlated factor shocks, and advances four fiscal
quarters. Company code never generates random numbers. All randomness arrives through
factor draws so paired runs can share them exactly.

**Decisions locked in **

1. **Six factors.** Demand, travel and FX are correlated. Pricing, incentives and
   costs are independent factors with their own volatilities.
2. **Cross-border as a share of payments volume.** The origin share is an explicit
   analyst-assumption parameter (`cross_border_share_at_origin`). Domestic + cross-border
   equals total payments volume by construction.

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
assumption). There is no yield-level or fee parameter. The model uses disclosed revenue and activity levels rather than assumed
contract fees.

## 3. Sampler contract

Module: `engine/sampler.py`.

- Generator: `numpy.random.Generator(PCG64(seed))`.
- Raw draws: iid standard normals with shape `(n_paths, n_quarters, n_factors)` in
  **path-major** order. Path `i` is identical for any `n_paths > i` under the same seed.
- Correlation: Cholesky root of the company's factor correlation matrix. A singular but
  positive-semidefinite matrix uses a symmetric eigendecomposition root. Non-PSD matrices
  are rejected.
- Raw draws never depend on parameter values (shared draws for paired runs).

Visa factors (order): `demand`, `travel`, `fx`, `pricing`, `incentives`, `costs`.

The 3×3 macro block among demand/travel/FX is parameterized by
`corr_demand_travel`, `corr_demand_fx`, `corr_travel_fx`. Pricing, incentives and costs
are independent (identity block).

## 4. Transition rules

Module: `companies/visa/transitions.py`. Numbered list mirrored by the hand-walked unit
test. Annual rates convert to quarterly via `(1+r)^(1/4) − 1`. Seasonal ratio sets
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

### Revenue

| Category | Driver | Timing |
| --- | --- | --- |
| Service | lag-basis yield × prior-quarter PV (million-USD units) | prior quarter; or same-quarter PV when `service_lag=False` |
| Data processing | yield × processed transactions | current quarter |
| International | yield × (share × current PV) | current quarter |
| Other | other-revenue run-rate | current quarter |

### Identities (relative tolerance ≤ 1e-9 on every path/quarter)

1. `service + data_processing + international + other − client_incentives = net_revenue`
2. `net_revenue − operating_expenses_ex_special_items = operating_profit_ex_special_items`
3. `domestic_payments_volume + cross_border_ex_intra_europe_volume = payments_volume_nominal_us`

Only the **ex-special-items** operating-profit basis is simulated. GAAP operating profit
remains a reporting field on fixtures, not a path metric.

### Switches

| Switch | Default | Effect |
| --- | --- | --- |
| `service_lag` | `true` | When `false`, service revenue uses current-basis yield × same-quarter PV. A spend reduction then moves service revenue in the start quarter instead of one quarter later. |
| `pool_mix` | `false` | When `true`, freeze the cross-border share so domestic and cross-border share one growth driver. Travel draws are still consumed so paired runs stay aligned. |

### Interventions

Applied only when the quarter's list is non-empty, after the activity update and
before pricing. See [`docs/scenarios.md`](scenarios.md).

| Type | Effect |
| --- | --- |
| `mix_shift_conserving_total` | Multiply cross-border share by `1 + cross_border_change`. Payments volume is unchanged, so the payments-volume identity still holds and the mix-shift total equals the baseline on every path. |
| `total_spend_reduction` | Scale nominal payments volume and the constant-dollar index by `1 − reduction`. Transactions are unchanged. Service revenue (prior-quarter volume) reacts one quarter later; international revenue reacts in the start quarter. |

## 6. Parameters

32 parameters: 8 free, 22 estimated, 2 assumption. Defaults are uncalibrated.

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
| `cross_border_share_at_origin` | assumption | ratio | 0.05 | 0.35 | 0.2 | Analyst-assumption share of payments volume that is cross-border ex-intra-Europe at the origin quarter. Midpoint of the allowed range; not an estimate (no disclosed CB level). |
| `international_fx_sensitivity` | assumption | ratio | -1.0 | 1.0 | 0.0 | Additional FX sensitivity on the international yield (0 = pricing shock only). |

### 6.1 Calibration

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
the pooled set; each evaluation row also records ensemble members and weights.

**Evidence.** Each parameter links to deterministic observation UUIDs
(`observation_uuid_for` in `extract/visa_tables.py`) or `assumption=true` with a
rationale. Artifacts carry an `evidence_index`; demo seeding loads rows under the same IDs.

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

- Mean, sample standard deviation, Monte Carlo SE of the mean (`std / √n`)
- Quantiles keyed `"0.05"`, `"0.1"`, `"0.25"`, `"0.5"`, `"0.75"`, `"0.9"`, `"0.95"`
  (same style as `RunResultSummary` / forecast rows)
- Batch-means SE per quantile

Default `n_paths` is 5,000.

## 8. Performance

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

## 9. Evidence and rule provenance

The [definitions](definitions.md) cite retained SEC originals for accounting and
activity definitions; [Visa parser](visa-parser.md) documents extraction and
first-print selection. The model implements effective revenue relationships,
not published contractual fee schedules. Each simulation rule below is either
supported by those disclosures or explicitly a modeling assumption.

| Rule / input | Evidence and implementation | Status / limitation |
| --- | --- | --- |
| Starting levels and recurring opex | Parsed release/10-Q observations, source IDs, spans and publication timestamps; `companies/visa/state.py`, `extract/visa_tables.py` | Accounting measurements, with identified special items removed from modeled opex; missing required fields refuse a state |
| Service revenue on prior-quarter volume | Definitions §4; reported service-revenue timing; `transitions.py` | Disclosed timing, effective lag-basis yield; no contractual fee inferred |
| Data-processing revenue on processed transactions | Definitions §2.4 and revenue definitions; `transitions.py` | Driver relationship from disclosures; effective yield absorbs business mix |
| International revenue on cross-border activity | Definitions §3 and revenue definitions; `transitions.py` | Disclosed growth basis; absolute share/level is an analyst assumption |
| Other revenue, incentives, net revenue, profit | Retained category amounts and accounting identities; definitions and `transitions.py` | Effective drifts and incentive intensity are modeled; ex-special-items profit differs from GAAP |
| Activity, seasonal effects, yields, opex and shock scales | Chronological calibration §6.1, `data/calibration/visa_<date>.json` evidence index | Fits and ranges use cutoff-known observations; cross-border seasonality and sparse-history fallbacks are assumptions |
| Correlated shocks | Seeded sampler §3 and calibrated macro residual correlations | Gaussian factor model is assumed; PSD projection is numerical regularization, not economic evidence |
| Booking room nights / guidance → cross-border premium | `booking_room_nights_to_cross_border_premium` v1 and `booking_guidance_to_cross_border_premium` v1; retained Booking observations | Sparse aligned history uses an analyst-range fallback; geography and business coverage differ |
| Census retail growth → payments-volume growth | `census_retail_yoy_to_payments_volume_growth` v2; verified trailing-three-month SA quarter-end releases | Fit uses eligible aligned history when sufficient, otherwise an explicit fallback; US share scaling remains assumed |
| Airline, retailer and processor statements | `airline_context`, `retailer_context`, `processor_context` v1 | Context only; no adopted numerical parameter transform |
| Intervention and attribution rules | [Scenarios](scenarios.md), saved baseline/intervention paths | User-specified model interventions; sequential and one-at-a-time attribution are model-conditional |
| Earnings/multiple bridge and action rule | [Valuation](valuation.md), [actions](actions.md), `config/decision_rule.yaml` | Illustrative assumptions; buyback average is not a market close; separate earnings and multiple spreads |

The authoritative [mapping registry](mapping-rules.md) states constants,
alignment, priority and fallback rules. Full-model artifacts retain reviewed
source snapshots, rule hashes, parent parameter hashes, before/after values and
context/no-effect reasons in each origin's `inputs`. Qualitative statements and
LLM confidence never become probabilities. Financial-only and the
no-external-commentary ablation rebuild from the calibrated parent; the full
model applies adopted Booking/Census rules. They are no longer identical by
construction.

## 10. Evaluation definitions and retained evidence

[The evaluation report](evaluation-report.md) is the consolidated, generated
record of sample counts, exclusions, matched comparisons and source hashes.
[Evaluation methodology](evaluation.md) describes target transformations and
baselines; [LLM baseline](llm-baseline.md) documents evidence excerpts and capture.

- Point errors use the predictive median: signed error = median − actual,
  absolute error = its magnitude, and percentage error = absolute error / |actual|.
  Percentage error is unavailable at a zero actual and is not used for drivers.
- Coverage is the inclusive interval from quantile 0.1 to 0.9. CRPS for sampled
  forecasts is `mean(|X−y|) − mean(|X−X'|)/2` over empirical paths.
- The **implemented WIS variant** is `(abs(median−y) + Σ[(α/2)(u−l) +
  max(l−y,0) + max(y−u,0)]) / (K+1)`, with central intervals 50%, 80%, 90%,
  `α = 1 − coverage`, and `K = 3`. It gives the median absolute-error term
  weight 1. This is the repository's retained weighting, not the common
  median-weight-1/2, denominator-`K+1/2` normalization. It is used consistently
  across saved comparisons; this reporting change does not rescore history.
- Levels are USD millions. Driver target values are YoY ratios and their errors
  are displayed in percentage points. Engine driver paths remain annualized QoQ;
  the harness performs the documented history-anchored conversion before scoring.
- Four-quarter level targets are sums; driver targets are fourth-quarter YoY.
  They have separate eligibility and denominators and overlap adjacent origins.
- Baselines comprise seasonal/trend, financial-only, company guidance, and a
  same-source evidence-excerpt LLM forecast. Guidance is not consensus. LLM
  quantiles support median errors, coverage and WIS, but not mean or CRPS;
  guidance and the LLM baseline have no four-quarter forecast.
- Ablations remove external commentary, pool spending, or remove service lag.
  The retained persistence suite uses central and predefined one-at-a-time low/high
  settings. Those profiles do not increase the number of independent origins.

The source ledger retains the code fingerprints actually used. A later
report-only code change does not invalidate historical outputs. The generator
checks source hashes and aggregates from exported score rows without fitting,
replaying simulations, capturing provider responses or rewriting the forecast.

## 11. Prospective registration and data gaps

The frozen FY2026Q4 registration contains its actual October creation timestamp,
July evidence cutoff, inputs, hashes and paths. It forecasts unpublished results
for a quarter that had already ended. It is not scored in the retrospective
report. [The report's prospective procedure](evaluation-report.md) explains how
later actuals must be recorded and scored separately without changing the archive.

The result pages read packaged reports without running scoring. The final report,
model specification and failure case are available through the saved-document API.
Startup seeds the bundled saved runs. Export verification checks a fresh
application environment. Recovering the two excluded extension origins requires
additional FY2020/FY2021 10-K volume parsing; this report does not fill those gaps.
