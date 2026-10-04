# Paired scenarios, interventions and attribution

LON-22 / FR-10, FR-11, MR-11.

Two Visa runs that share a seed share the raw factor draws. An intervention is a
persistent level shift applied once inside the transition. Comparison reads the
saved path files. Attribution re-simulates from the pinned inputs, checks the
saved hashes, and reports model-conditional contributions, a sensitivity ranking,
and provenance. Charts stay in LON-34; these endpoints do not draw them.

## Interventions

Both interventions are persistent level shifts. `start_quarter` is 1-based within
the simulated horizon (default 1, at most 8, and not past `n_quarters`). The
shift runs once, after the activity step of that quarter, and later quarters
inherit it through state. An empty list skips the hook, so a run with no
interventions is the same arithmetic as before LON-22.

| Type | Fields | What changes |
| --- | --- | --- |
| `mix_shift_conserving_total` | `cross_border_change` (greater than −1, at most 3), `start_quarter` | Cross-border share is multiplied by `1 + change` on every path. Payments volume is not touched, so domestic volume absorbs the difference. A path whose share would leave (0, 1) is rejected. |
| `total_spend_reduction` | `reduction` (greater than 0, less than 1), `start_quarter` | Nominal payments volume and the constant-dollar index are scaled by `1 − reduction`. Processed transactions are unchanged. |

Growth does not depend on the level, so from the start quarter on, reduced
payments volume is `(1 − reduction)` times the unshifted path (float noise only).
Service revenue uses prior-quarter volume, so with `service_lag` on it is
unchanged in the start quarter and lower afterward. International revenue uses
the current quarter's cross-border volume, so it moves in the start quarter.
With `service_lag` off, service revenue moves in the start quarter too. Growth
metrics in the start quarter use the realized levels; transaction growth stays
the modeled rate.

The two shifts commute on levels. They are applied in list order. A run that
omits interventions and a run that passes an empty list produce the same paths.
That outputs hash is pinned separately for the host BLAS and for the API image's
OpenBLAS; the two digests differ, and replay treats that gap as numerically
equivalent.

## Creating a scenario and a pair

`POST /scenarios` takes a company (`visa`), a name, a parameter set, optional
`pair_group_id`, a typed `interventions` list, and optional `parameter_overrides`
of `{name: {value, rationale}}`.

An override writes a child parameter set:

- `parent_id` is the base set and `cutoff_ts` is the base cutoff.
- Overridden values are stored with `assumption=true` and the given rationale.
  Base observation links and ranges are kept.
- One `parameter_update` row is written per override, with `rule_id` null.
- A set that already has the same content hash is reused, and a duplicate
  update for that parameter is not written again.

`POST /scenarios/pair-runs` submits one baseline and one or more variants:

- Every scenario must belong to the same company and the same non-null
  `pair_group_id`.
- The baseline run is created first. Variants copy its seed, `n_paths`,
  `n_quarters`, cutoff and switches, and store `baseline_run_id`.
- Variant interventions must extend the baseline list as a prefix. Draws do not
  depend on parameters or interventions, so the baseline paths match a variant's
  unshifted paths.

Migration `0006_scenario_pairs` adds `run.interventions`, `run.interventions_hash`,
and nullable `run.baseline_run_id` (`ON DELETE SET NULL`). Existing rows are
backfilled with `[]` and the hash of `[]`. Submit pins the parsed list and its
hash. Replay reports `inputs_changed` (difference `interventions_hash`) when the
scenario's list no longer matches. The forecast archive still refuses any run
whose scenario or pinned list is non-empty.

## Comparison

`GET /scenarios/comparison?run_id=&baseline_run_id=`

`baseline_run_id` defaults to the variant's `baseline_run_id`. Both runs must
have succeeded, and they must share seed, `n_paths`, `n_quarters`, cutoff,
origin and switches. A mismatch is 422.

The difference is variant minus baseline, path by path, from the saved
`paths.npz` files only. Each metric and quarter reuses the run summary
(mean, standard error, quantiles) and also reports the baseline and variant
means. Nothing is written.

A mix shift's payments-volume difference is exactly zero on every path and
quarter. A spend reduction's service-revenue difference is zero in the start
quarter when `service_lag` is on, and negative afterward.

## Attribution

`GET /scenarios/attribution?run_id=&baseline_run_id=&metric=`

`metric` is `net_revenue`, `operating_profit_ex_special_items`, or omitted for
both. Before attributing, both runs are recomputed from their pinned inputs
with the shared seed and checked against `outputs_hash` at the replay tolerance
(1e-9). A hash that does not match is 409. The response is not stored.

Changes are parameter differences (before, after, size) and the interventions
that the variant adds. Contributions, for each metric:

- **One-at-a-time.** Each change alone against the baseline.
- **Sequential.** Parameters by name, then interventions in listed order. These
  sum to the total difference.
- **Joint residual.** Total minus the sum of the one-at-a-time contributions.
  A single change has residual zero. Two changes that interact do not.

The response includes a fixed note: sequential order is part of the definition,
one-at-a-time terms need not add up when changes interact, and every effect is
conditional on the model. Labels use that wording and do not claim an
identified effect outside the model.

### Sensitivity and support

For each parameter, sensitivity is the swing in mean horizon-total net revenue
between the range low and the range high. Ranges come from the variant
parameter set, then from the spec bounds. Other parameters stay at the variant
values, and the draws are the shared ones. Swings are normalized by the largest
absolute swing and ranked. A range endpoint that the model rejects (for example
a correlation that is not positive semidefinite) falls back to the variant
horizon mean.

Support, from the variant set's evidence links and assumption flag:

| Score | Meaning |
| --- | --- |
| 1.0 | Linked observations, and the assumption flag is false |
| 0.5 | Linked observations, and the assumption flag is true |
| 0.0 | No observations, or every linked database observation is pending or rejected |

An id that is not an observation row is not treated as pending. Calibration
UUIDs that were never loaded are in that category.

A parameter is flagged `high_sensitivity_weak_support` when
`normalized sensitivity × (1 − support) ≥ 0.25`. The threshold is a heuristic.
On the default spec ranges, seasonal bounds dominate the ranking, because
geo-mean normalization rescales every quarter. `cross_border_share_at_origin`
has support 0 and a normalized sensitivity near 0.01, so it is **not** flagged.
A parameter with support 0 is flagged only when its normalized sensitivity is
at least 0.25. On the calibrated 2024-07-23 set the seasonals are still
`[0.5, 1.5]` and are observation-backed (support 1.0), so the flag list can be
empty even though those parameters rank first.

### Provenance

Each changed or ranked parameter lists:

- observation ids from `evidence_links`
- rule id, key and version from `parameter_update` joined to `mapping_rule` on
  the variant set (`rule_id` is null for an override)
- source id, passage id and character span from the observation row

When a linked id is not in the database, attribution falls back to
`data/calibration/visa_<origin>.json` `evidence_index` (document key and
character span).

## CLI

`make pair-run` loads the calibration artifact for an origin, reuses or writes
the calibrated scenario as the baseline, adds a mix-shift variant and a
spend-reduction variant in a new pair group, and submits them together.

```bash
make pair-run ARGS='--origin 2024-07-23 --n-paths 5000 --inline'
```

Defaults: seed 22, 5,000 paths, 4 quarters, mix change −0.10, reduction 0.05.
`--inline` executes in the CLI process. The printed JSON includes per-quarter
mean differences for payments volume, service revenue, international revenue
and net revenue, the hash-verification status, flags, and the top sensitivity
ranks.

## Validation (2024-07-23, API image)

`make pair-run ARGS='--origin 2024-07-23 --n-paths 5000 --inline'` on 2026-10-04.
Seed 22, mix change −0.10, spend reduction 0.05, four quarters from FY2024Q3.
Attribution verification was `exact_match` for the baseline and each variant.
No parameter was flagged.

Mix shift, maximum absolute payments-volume difference across every path and
quarter: **0**. Service-revenue difference means were 0 in all four quarters.
Mean differences (variant − baseline), USD millions:

| Quarter | International revenue | Net revenue |
| --- | ---: | ---: |
| FY2024Q4 | −334.40 | −238.45 |
| FY2025Q1 | −358.82 | −254.73 |
| FY2025Q2 | −360.01 | −254.47 |
| FY2025Q3 | −397.98 | −280.09 |

Spend reduction, payments volume was 0.95 times the baseline (ratio between
0.9499999999999996 and 0.9500000000000003). Service revenue was unchanged in
FY2024Q4 and lower after that. International revenue was lower in the start
quarter. Mean differences, USD millions:

| Quarter | Service revenue | International revenue | Net revenue |
| --- | ---: | ---: | ---: |
| FY2024Q4 | 0 | −167.20 | −119.22 |
| FY2025Q1 | −213.66 | −180.38 | −279.72 |
| FY2025Q2 | −223.78 | −182.03 | −286.84 |
| FY2025Q3 | −219.00 | −202.31 | −296.51 |

Top sensitivity ranks on the calibrated set (horizon net revenue, support 1.0,
no flag): `activity_seasonal_q3` 1.00, `activity_seasonal_q4` 0.819,
`activity_seasonal_q2` 0.319, `activity_seasonal_q1` 0.269,
`payments_volume_growth` 0.140.

## Limitations

- Shifts persist; they are not temporary pulses or path-dependent rules.
- A spend reduction does not change processed transactions.
- Overrides keep the base ranges, so sensitivity still sweeps those ranges.
- The 0.25 flag threshold is a heuristic, not a test of support quality.
- Comparison does not re-simulate. Attribution does, and it refuses a hash
  mismatch rather than returning a stale story.
