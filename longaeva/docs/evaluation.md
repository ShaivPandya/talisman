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
# Full suite (Compose api container; writes under data/evaluation via /out)
make evaluate ARGS='--output /out/visa_full_model.json'

# Subset
make evaluate ARGS='--origin 2024-07-23 --origin 2025-10-28 --n-paths 256 --json'
```

Each origin: build starting state → calibrate (cached under
`ARTIFACT_DIR/evaluation/calibration/`) → persist parameter set + scenario →
`submit_run` with the job claimed by `evaluation` before commit → inline execute →
score → write rows. Ensemble members and weights are stored in each row's `details`.

## Results file

`data/evaluation/visa_full_model.json` holds the config and hash, per-origin scores,
aggregate tables (overall / primary / extension), the four-quarter table, exclusions
with reasons, and `n` per metric. Floats are rounded to 10 significant digits.
