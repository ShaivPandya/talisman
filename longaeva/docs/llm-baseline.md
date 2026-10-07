# LLM same-document forecast baseline (LON-30)

This retrospective baseline asks OpenAI `gpt-5.4` for next-quarter predictive
quantiles across the same 16 eligible origins as the full model. The two existing
origin exclusions remain excluded. It uses one fixed prompt (`lon30-v1`), with
no prompt selection or outcome-driven tuning.

## Matched evidence and limitations

Each origin has a frozen pack in `data/fixtures/llm_baseline/YYYY-MM-DD.json`.
Selection follows starting-state input spans, calibration-used observation
spans, driver history, and the same reviewed external evidence snapshot as the
full model. Census includes verified quarter-end fitting-history releases.
Documents published exactly at cutoff are eligible; later publications and
revisions are excluded. Original bytes are hash checked before capture.

HTML excerpts retain the containing table row, preceding row and first three
header/context rows; prose retains nearby text nodes within 500 raw characters.
Census retains the first page containing its dated three-month headline.
Overlapping rows and text nodes are deduplicated. Every excerpt records its
source, original hash, publication timestamp, location and text hash. Source
selection and the complete pack enter the request hash. Missing required
originals or hash mismatches stop capture before a provider request.

This is a **same-source, evidence-excerpt** comparison. The model receives
historical observations with their original units and contextual source text,
rather than full filings. It does not receive calibrated parameters, mapping
results, simulation forecasts, future actuals, or scoring results. Manually
reviewed observations and retrospective source retrieval are shared with the
existing model evaluation; they were not necessarily available as a workflow
at the historical date.

Publication cutoffs cannot remove historical outcomes from pretrained-model
knowledge. This is an exploratory retrospective comparison, not proof of
an ex-ante forecast or a causal improvement.

## Capture

The existing backend venv and a running Longaeva Postgres are needed to prepare
new packs. Verified Census archive originals must exist locally; use the
documented Census collector if preparing on a fresh installation. Frozen packs
and cached scoring do not require these originals or Postgres.

```bash
# Freeze and verify all 16 origins; no API calls.
make capture-llm-baseline ARGS='--prepare-only'

# Explicit live capture. Credentials are loaded at runtime, never copied/exported.
make capture-llm-baseline ARGS='--provider openai --model gpt-5.4 --credentials-env /path/to/runtime.env'

# Capture a subset or use separate evidence/checkpoint destinations.
make capture-llm-baseline ARGS='--origin 2024-07-23 --input-dir /path/to/packs --output /path/to/cached.json'
```

Without a matching provider key, capture records no attempted forecasts and
reports `not run (no provider)`. It never changes the application's default
provider selection. Supported adapters accept a forecast schema while their
extraction defaults remain unchanged. For another provider, explicitly select
both `--provider` and `--model`.

OpenAI uses the Responses API's [strict structured-output format](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

Capture is bounded to 16 unique eligible origins and one forecast request per
origin, with at most one transport retry for the existing retryable errors.
No schema repair or automatic prompt-tuning loop is performed. Responses are
validated for complete target coverage, exact fiscal quarter, finite values,
and ordered quantiles. Missing forecasts require explicit reasons. Refusal,
incomplete response, schema failure and transport failure remain distinct.

`cached.json` retains original response text, validated forecasts, attempts,
token counts, latency, request settings, evidence hash, request hash and call
integrity hash. Successful and failed attempts are checkpointed atomically.
Repeating a completed checkpoint makes no new calls. Changed model, prompt,
settings or evidence require a separate output file; failures are not silently
retried. API errors use the provider adapter's credential redaction.

The initial live request was rejected with HTTP 400 because nested schema
references had not been resolved by the shared adapter. That diagnostic attempt
is retained separately in `schema-validation-rejected.json`; it generated no
forecast or token usage. The adapter was corrected before the capture sweep,
and the request settings record `provider_schema_version: inline-refs-v1`.
The forecasting prompt and evidence policy were unchanged.

## Offline scoring and display

```bash
make evaluate-llm-baseline
# Or choose inputs explicitly:
cd backend
.venv/bin/python -m longaeva_app.cli evaluate --variant llm_baseline \
  --llm-cache /path/to/cached.json --llm-input-dir /path/to/packs --json
```

Scoring only reads retained packs, responses and the existing first-print
actuals. It needs no provider credentials, network or database. The `all`
evaluation suite includes this cached baseline and never captures fresh LLM
forecasts. The Python runner can optionally persist its normal evaluation rows
when explicitly supplied a database session factory.

Targets are GAAP nominal net revenue and operating profit excluding identified
special items in USD millions, plus the three existing driver YoY growth
targets in ratio units. Seven quantiles (5%, 10%, 25%, 50%, 75%, 90%, 95%) use
the existing median signed/absolute error, level MAPE, 80% coverage and WIS
formulas. Driver errors are displayed in percentage points. Missing targets
retain a reason and do not enter that target's denominator. Zero denominators
produce null scores. Successfully scored origins, failed calls, missing
captures and exclusions remain visible separately.

**CRPS and forecast means are unavailable.** Seven quantiles do not specify a
complete distribution; no synthetic paths or tail assumptions are invented.
The shared aggregation tolerates absent CRPS while preserving existing sampled
baseline scores. Four-quarter scores are also unavailable because this baseline
predicts only the next quarter.

`data/evaluation/visa_llm_baseline.json` is served through the existing
`GET /evaluation/reports/llm_baseline` endpoint. Evaluation → Forecasts & baselines
shows saved scores, coverage, provider/model, failure reasons and limitations.
Opening the page never scores or captures. The guide is also available through
the saved-document reader.

## Validation

Unit tests cover source hashes, cutoff equality and future publications,
contextual/deduplicated table selection, malformed/nonfinite/unordered responses,
wrong horizons, unavailable targets, missing provider, refusals, bounded retries,
checkpoint resume and invalidation, offline repeatability, and equality with
the sampled scorer's shared quantile metrics. `make check` additionally verifies
database behavior, package isolation, frontend tests and the production build.

The packaged capture was completed on 2026-10-07: all 16 origins succeeded,
with 80 target forecasts scored and two existing origin exclusions. The corrected
sweep used 16 transport attempts, 1,422,665 input tokens and 26,525 output tokens;
no transport retries were needed. The separate schema-validation rejection above
is retained in addition to these outcomes.

All 16 completed checkpoints were replayed unchanged with zero provider calls.
The CLI then scored twice with provider credentials unset, an unreachable
database URL, and provider construction, HTTP clients and socket connections
blocked. Both reports were identical, with canonical report SHA-256
`c919efc888c5dcce859ab64efc8fa78328d3d1ca01eae3d800fdaaf654fd4581`.
Each target has `n=16`; CRPS is null and four-quarter `n=0`.

`make check` passed (508 backend tests and 33 frontend tests). The subsequently
added bundled-evidence regression also passed in the 14-test LLM suite. Final
frontend lint, tests and production build passed after the display refinement;
the standalone isolation guard reported zero findings. Browser inspection
covered successful scores and unavailable four-quarter results; rendered
Evaluation-panel tests cover explicit unavailable targets and provider failures.
