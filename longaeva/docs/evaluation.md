# Evaluation harness

Benchmark holding-period results and the explicitly unrun Visa portfolio
comparisons are documented separately in
[`portfolio-evaluation.md`](portfolio-evaluation.md).

Scores the full Visa model at each eligible origin in `data/fixtures/origins.csv`.
Results are `evaluation_result` rows under one frozen `config_hash`, plus a compact
committed file at `data/evaluation/visa_full_model.json`.

## Origin set

| Window | Origins | Scored |
| --- | --- | --- |
| primary | FY2024Q1–FY2026Q2 (10) | all 10 |
| extension | FY2022Q1–FY2023Q4 (8) | 6 (FY2022Q3 and FY2022Q4 excluded) |
| prospective | FY2026Q3 | listed, not scored (no target release) |

**Exclusions.** FY2022Q3 and FY2022Q4 cannot build a starting state: the FY2021Q3
payments-volume level is missing from parsed observations (FY2020/FY2021 10-K
12-month tables were not extracted). FY2022Q2 is scored, but its payments-volume
driver is skipped for the same data gap on the year-ago base.

## Leakage

Before calibration, simulation and scoring, every used input must be published at
or before the cutoff:

- Starting-state sources
- Calibration evidence index
- Run source manifest
- Driver-history observations

Actuals must be published **after** the cutoff. A deliberately late input raises
`LeakageError`.

## What is scored

**Next quarter (q+1)**

| Target | Basis | Errors |
| --- | --- | --- |
| `net_revenue` | GAAP, USD millions | signed, absolute, percentage |
| `operating_profit_ex_special_items` | declared non-GAAP | signed, absolute, percentage |
| `payments_volume_growth_constant` | constant-dollar YoY | signed / absolute (pp) |
| `cross_border_ex_intra_europe_growth_constant` | constant-dollar YoY | signed / absolute (pp) |
| `processed_transactions_growth` | count YoY | signed / absolute (pp) |

Point forecast = path median (mean also recorded). Coverage = actual inside
`[q0.1, q0.9]`. CRPS is the exact sample score; WIS uses the median plus the
50% / 80% / 90% central intervals.

**Driver method (history-anchored).** The engine reports annualized QoQ growth;
quarterly rates are recovered as `(1+g)^(1/4)−1`.

- Transactions: `sim_count(q+1) / disclosed_count(q−3) − 1` (exact).
- Payments volume: `(1+YoY(q)) × (1+QoQ(q+1)) / (1+QoQ(q−3)) − 1`, with QoQ(q−3)
  from 10-Q levels and a labeled one-quarter FX adjustment.
- Cross-border: same chain; QoQ(q−3) from the calibrated model (persistence
  fallback). Flagged approximate.

**Four quarters.** Separate table with its own `n`, for origins whose four
post-origin quarters are all released. Scores four-quarter sums of net revenue and
operating profit, plus quarter-4 YoY drivers from simulated levels.

Aggregates are reported overall and by window (primary / extension), each with `n`.

## Config hash

Frozen before scoring. Covers suite version, model variant, origin list, path count,
quarters, seed policy (fixed per origin from a base seed), quantiles, coverage level,
targets and bases, driver method, CRPS/WIS definitions, calibration options,
`code_version()`, and hashes of `observations.csv`, the sources manifest and
`origins.csv`.

## How to run

```bash
# Full model plus the three baselines (Compose api container; writes under data/evaluation via /out)
make evaluate ARGS='--variant all --output-dir /out'

# Full model only
make evaluate ARGS='--variant full_model --output /out/visa_full_model.json'

# Subset
make evaluate ARGS='--origin 2024-07-23 --origin 2025-10-28 --n-paths 256 --json'
```

Each origin: build starting state → calibrate (cached under
`ARTIFACT_DIR/evaluation/calibration/`) → persist parameter set + scenario →
`submit_run` with the job claimed by `evaluation` before commit → inline execute →
score → write rows. Ensemble members and weights are stored in each row's `details`.

## Results files

Each variant writes `data/evaluation/visa_<variant>.json`: config and hash,
per-origin scores, aggregate tables (overall / primary / extension), the
four-quarter table, exclusions with reasons, and `n` per metric. Floats are
rounded to 10 significant digits. Artifacts are regenerated together after implementation changes. `code_version`
fingerprints the simulation engine; `evaluation_code_hash` separately fingerprints
the evaluation, review, quarterly selector and run-input code. The full-model and
ablation configs additionally freeze the retained evidence files, reviewed
snapshots, mapping-rule hashes and parameter-range settings before scoring.

A `baseline` object is stored on the config and enters the hash only when it is
non-empty, so an empty baseline does not change the full-model hash.

## Baselines

Same 16 scored origins and the same two exclusions (FY2022Q3, FY2022Q4) as the
full model. Same actuals, base seed and scoring. Variants:
`seasonal_trend`, `financial_only`, `guidance`.

**Seasonal/trend.** A level point is the year-ago quarter times one plus the
mean YoY of the last four eligible quarters. Pandemic quarters stay out of that
mean, matching calibration. Drivers persist the last reported YoY. Draws are
normal, seeded per series, scaled by rolling-origin residuals from FY2018Q2
whose actuals were already published. Fewer than six residuals sets
`residual_n_low`. Image-era and FY2017 level rows are dropped, same as the
calibration quality gate, so FY2022Q1 and FY2022Q2 have no level point (the
year-ago quarter is image-era). Operating profit uses the derived series.

**Full model.** Chronological Visa calibration followed by the retained reviewed
external mapping rules, using only publications available by the origin cutoff.

**Financial-only.** The harness path with no external mapping rules.
`external_updates` is `[]` and the excluded families are booking, census,
airline, retailer and processor. It rebuilds from the original calibrated parent and matches the
`no_external_commentary` ablation. The full model now applies reviewed Booking
and quarterly Census updates. Airline, retailer and processor evidence stays
context under the existing registry. Removing external inputs changes numerical
parameters where adopted rules apply; origins with no change remain scored.

**Company guidance.** The point is the midpoint of Visa's next-quarter outlook
applied to the year-ago actual. Operating profit is derived (guided revenue
minus year-ago operating expenses grown at the opex outlook) and flagged
`derived`. FY2023Q1 and FY2023Q2 state opex only as "2 to 3 points lower than"
the prior quarter; that is the origin quarter's reported opex YoY minus 2.5
percentage points. Deck phrases are adjusted constant-dollar growth scored
against GAAP nominal actuals; those rows carry `basis_note`, and the residual
distribution absorbs the gap. Residuals are prior guidance errors once four
have actuals published at or before the cutoff; otherwise the seasonal/trend
spread, flagged `residual_source=seasonal_trend_fallback`. Drivers and the
four-quarter horizon are marked unavailable (`no numeric driver guidance`,
`guidance is next-quarter only`). Origins without a next-quarter outlook
(FY2022Q2, FY2023Q3, FY2023Q4) are marked unavailable. FY2022Q1 has a revenue
outlook but no usable year-ago level, and no opex outlook. Every row is labeled
`company guidance`. The only estimates string, on the config, is
`consensus unavailable (no licensed free historical source)`.

Next-quarter overall scores (MAE and mean CRPS in the target's units; coverage
is the 80% interval):

| Variant | Target | n | MAE | Coverage | Mean CRPS |
| --- | --- | ---: | ---: | --- | ---: |
| full_model | net revenue | 16 | 196.339 | 9 of 16 | 149.038 |
| full_model | operating profit ex special items | 16 | 209.153 | 8 of 16 | 158.016 |
| seasonal_trend | net revenue | 14 | 137.648 | 7 of 14 | 112.139 |
| seasonal_trend | operating profit ex special items | 14 | 115.125 | 8 of 14 | 87.042 |
| financial_only | net revenue | 16 | 196.315 | 8 of 16 | 151.578 |
| financial_only | operating profit ex special items | 16 | 212.210 | 8 of 16 | 159.921 |
| guidance | net revenue | 12 | 216.301 | 5 of 12 | 161.962 |
| guidance | operating profit ex special items | 12 | 168.416 | 6 of 12 | 130.528 |

`n` is the number of origins with a scored error, not the origin-set size.
Seasonal drivers are scored at all 16 origins. Guidance has no driver or
four-quarter scores. The JSON files are the source for unrounded values.

## Ablations and persistence

```bash
make evaluate ARGS='--variant ablations --output-dir /out'
make evaluate ARGS='--variant no_external_commentary --output /out/visa_no_external_commentary.json'
```

The suite runs the full model, `no_external_commentary`, `pooled_spending`
(`pool_mix=true`) and `no_service_lag` (`service_lag=false`). All share origin
sets, starting states, seeds, paths and scoring. The other engine switch remains
at its full-model default in each ablation. No recalibration to evaluation
outcomes takes place.

The central profile plus one-at-a-time calibrated low/high endpoints of payments
volume growth, cross-border growth premium and the four yield/incentive drifts
produce 13 predefined profiles. Each profile starts from the same calibrated
parent setting for all four variants, before external updates.

`visa_ablation_persistence.json` holds all profile configs and hashes, per-origin
results, paired differences and wins/ties/losses. `ablation_persistence.md` is its
readable table. Positive `ablated_minus_full` means lower error for the full model.
Next-quarter and four-quarter targets stay separate, with counts and coverage.
The suite fails if a variant lacks an origin or a matching scoring target; it
does not claim completion from the surviving subset.

Saved inputs record source dates, review status, parent hashes, numerical changes,
context, absent families and no-effect flags. The retained corpus has limited
Booking coverage, and suspect Census releases can leave an older quarter as the
latest eligible signal. Reviews are retrospective. These comparisons measure
the specified model and corpus, and do not guarantee forecast improvement.

Recorded suite: 13 profiles × four variants × 16 origins = 832 model/origin results,
using 5,000 paths, four quarters and base seed 27,000. Both documented exclusions
remain. Every profile has all four matched variants and all 16 origins.

Central net-revenue absolute-error comparisons (USD millions; wins are per origin):

| Horizon | Removed feature | n | Full wins | Ablated wins | Ties | Mean ablated − full error | Full coverage | Ablated coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| q1 | no_external_commentary | 16 | 6 | 10 | 0 | -0.024 | 9 of 16 | 8 of 16 |
| q1 | pooled_spending | 16 | 9 | 7 | 0 | 5.665 | 9 of 16 | 7 of 16 |
| q1 | no_service_lag | 16 | 15 | 1 | 0 | 149.882 | 9 of 16 | 4 of 16 |
| 4q | no_external_commentary | 13 | 7 | 6 | 0 | 52.510 | 9 of 13 | 8 of 13 |
| 4q | pooled_spending | 13 | 5 | 8 | 0 | -195.459 | 9 of 13 | 9 of 13 |
| 4q | no_service_lag | 13 | 7 | 6 | 0 | 71.560 | 9 of 13 | 9 of 13 |

CRPS, WIS, driver targets, origin-level differences and the 13-profile direction
counts appear in the persistence artifacts. The external-evidence comparison is
small and does not consistently improve error; unchanged cases are retained.
