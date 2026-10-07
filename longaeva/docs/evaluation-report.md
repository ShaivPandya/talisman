# Evaluation report

The prospective registration section is complete for LON-32. The consolidated
historical evaluation, model discussion and failure case remain pending LON-33.
Historical results are available under `data/evaluation/` and in the Evaluation
page; this document does not yet constitute the final evaluation report.

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
