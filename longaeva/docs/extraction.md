# LLM extraction and review (LON-16)

Passage-only structured extraction. A model reads one selected `document_text`
row and returns observations that match a fixed schema. Nothing here is a
forecast, and nothing is written into a parameter set.

Provider setup lives in this file. The quickstart stays runnable with
`LLM_PROVIDER` unset.

## When extraction is off

`GET /observations/extraction-status` reports `enabled: false` and a
`disabled_reason` when:

- `LLM_PROVIDER` is unset (fresh extraction returns **503**)
- the named provider is not `anthropic`, `openai`, `gemini`, or `stub`
- the named provider's API key is unset (an explicit `provider` on
  `POST /observations/extract` returns **422**; the default unset provider
  returns **503**)

An unknown provider does not crash the API. `build_provider` returns before
any HTTP client is constructed, so a disabled process makes no provider call.
Replay and calibrated runs do not need a key.

## Configure a provider

Put the values in `longaeva/.env` (gitignored). Do not commit them and do not
print them.

```bash
LLM_PROVIDER=anthropic
# Optional. Defaults: claude-sonnet-4-6, gpt-5.4, gemini-3.1-pro-preview
LLM_MODEL=
LLM_BASE_URL=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
LLM_TIMEOUT_SEC=60
LLM_MAX_OUTPUT_TOKENS=4096
EXTRACTION_MAX_PASSAGES=25
EXTRACTION_MAX_PASSAGE_CHARS=12000
```

`LLM_PROVIDER=stub` is for tests. It needs no key and does not open a socket.

Compose passes `LLM_MODEL`, `LLM_BASE_URL`, and the three keys into the `api`
and `worker` services. Recreate those containers after changing `.env`.

Adapters (httpx, no new dependencies):

| Provider | Call | Structured output |
| --- | --- | --- |
| `anthropic` | `POST /v1/messages` | Forced tool `record_observations` |
| `openai` | `POST /v1/responses` | Strict JSON schema |
| `gemini` | `generateContent` | Response schema and `thinkingLevel: LOW` (so thoughts do not truncate the JSON); key in `x-goog-api-key`, not the URL |

Each adapter times out at `LLM_TIMEOUT_SEC` and retries once on HTTP 429,
5xx, or a timeout. The API key is stripped from stored errors.

## Passage-only prompt

One call per passage. The user message contains the company, document type,
the source's reporting period when both bounds are stored, and that passage's
text. It does not include other passages or the publication timestamp.

System rules: use only the passage; quote a verbatim span that contains the
number; return an empty list when nothing is stated; do not add confidence or
probability. Percent values are the number as written (`8` for `8%`).

## Spans, cache, and failures

A quote is located in the passage, including a whitespace-tolerant match.
The observation span is page-local: `document_text.char_start` plus the
offset inside the passage. A quote that is not in the passage is recorded on
the call and is not stored as an observation. A number that does not appear
in its quote is still stored, with `attributes.number_not_in_quote` set.

`extraction_call` is both the cache and the failure log:

| `status` | Meaning |
| --- | --- |
| `succeeded` | Cache hit key. Partial unique index on `(provider, model, prompt_hash)`. |
| `invalid_response` | JSON or schema failed. `parsed` is null. Raw text is kept. |
| `provider_error` | The call failed after the retry. Not reused. |

The prompt hash is SHA-256 of the canonical `{prompt version, system prompt,
user message, schema}`. A cache hit does not call the provider and does not
insert a duplicate observation. Failed rows are never hits.

Budget: at most `EXTRACTION_MAX_PASSAGES` (25) passages, each at most
`EXTRACTION_MAX_PASSAGE_CHARS` (12,000) characters. Over the limit is **422**
before any call.

Each run writes `reports/extraction/<stamp>.json` with calls made, cache hits,
hit rate, failures by status, and observations created (NR-02).

## Review

New observations are `pending`. `POST /review-decisions` appends a decision
with the next `version` (`accept`, `reject`, or `correct`) and sets
`review_status`. A correction may change only semantic fields: statement type,
activity type, geography, period, value or range, unit, and basis. Unknown
keys, confidence, and probability are **422**. The merged values are checked
with the same rules as `ObservationCreate`.

The original observation row is not rewritten except for `review_status`.
`GET /observations/{id}/review` returns the row, the decision history, and
`effective` values (the row overlaid with the latest correction). `effective`
is null while the row is pending or rejected.

`POST /runs` refuses a parameter set whose evidence links cite a pending or
rejected observation row (**422**). Identifiers that are not observation rows
(parser evidence, for example) are ignored. Replay is not guarded, so a later
re-review does not change a saved run.

Extraction does not write `parameter_set` or `parameter_update`.

## API and CLI

| Method | Path |
| --- | --- |
| GET | `/observations/extraction-status` |
| POST | `/observations/extract` (202, or 503 / 422 / 404) |
| GET | `/observations/extraction-calls` |
| GET | `/observations/{id}/review` |
| POST | `/review-decisions` (201) |
| GET | `/review-decisions?observation_id=` |

`extract` is an internal job type. `POST /jobs` refuses it. `POST /observations/extract`
enqueues it for the worker.

```bash
make extract ARGS='--status'
make extract ARGS='--source-key booking:release:0001075531-25-000050 --contains "Room nights grew" --provider anthropic'
```

`--passage` (repeatable) selects by `document_text` id. `--inline` runs in the
CLI process. Otherwise the command enqueues and waits for the worker (default
180s). Exit 2 means extraction is disabled or the selection failed.

## Manual check

1. Keep provider keys only in `.env`.
2. `make up`, then collect a retained filing, for example Booking Q3 2025
   (`booking:release:0001075531-25-000050`).
3. Run `make extract` once per provider on a passage that contains
   `Room nights grew`, then repeat one provider. The second run should be a
   cache hit (`calls_made` 0, `cache_hits` 1).
4. Compare the pending observation with fixture `bkng_2025q3_room_nights_yoy`:
   measured, `room_nights`, value 8, unit `percent`, period 2025-07-01 to
   2025-09-30, basis `units`.
5. Restore `.env` without the keys and recreate the `api` and `worker`
   containers. Rows already written stay in the local database only.
