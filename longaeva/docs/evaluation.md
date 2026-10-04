# Evaluation harness (LON-27)

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

## Leakage (ER-04 / MR-10)

Before calibration, simulation and scoring, every used input must be published at
or before the cutoff:

- starting-state sources
- calibration evidence index
- run source manifest
- driver-history observations

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

**Four quarters (ER-13).** Separate table with its own `n`, for origins whose four
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
rounded to 10 significant digits. All four files below share
`code_version` `0.1.0+cf93263a1d638ffa`. `visa_full_model.json` was regenerated
with the baselines so the comparison is one code version.

A `baseline` object is stored on the config and enters the hash only when it is
non-empty, so an empty baseline does not change the full-model hash.

## Baselines (LON-29)

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

**Financial-only.** The harness path with no external mapping rules.
`external_updates` is `[]` and the excluded families are booking, census,
airline, retailer and processor. The harness does not apply those rules yet
(that is LON-31 ablation (a), plus LON-15 Census vintages), so this variant
matches `full_model` exactly. The pair is not evidence about external data.

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
| full_model | net revenue | 16 | 196.3 | 8 of 16 | 151.6 |
| full_model | operating profit ex special items | 16 | 212.2 | 8 of 16 | 159.9 |
| seasonal_trend | net revenue | 14 | 137.6 | 7 of 14 | 112.1 |
| seasonal_trend | operating profit ex special items | 14 | 115.1 | 8 of 14 | 87.04 |
| financial_only | net revenue | 16 | 196.3 | 8 of 16 | 151.6 |
| financial_only | operating profit ex special items | 16 | 212.2 | 8 of 16 | 159.9 |
| guidance | net revenue | 12 | 216.3 | 5 of 12 | 162 |
| guidance | operating profit ex special items | 12 | 168.4 | 6 of 12 | 130.5 |

`n` is the number of origins with a scored error, not the origin-set size.
Seasonal drivers are scored at all 16 origins. Guidance has no driver or
four-quarter scores. The JSON files are the source for unrounded values.
