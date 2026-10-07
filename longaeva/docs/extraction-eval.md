# Extraction evaluation (LON-18)

This sample evaluates the passage-only extractor independently of operating
forecasts. It contains 85 assistant-curated observation labels in 19 short,
unaltered excerpts from retained Visa, Booking, Census, United, PayPal and
Costco sources. A scheduling-only passage has an empty expected response.
The sample is deliberately selected, not a random estimate of corpus-wide
quality. Originals were retrieved after their publication dates; this is not
an assertion that the extractor was available historically.

## Files and review

- `data/fixtures/extraction_eval/passages.jsonl`: excerpts, original source URL,
  publication timestamp, original-byte SHA-256, excerpt SHA-256, page, and
  page-local character offsets. Gzip source hashes describe decompressed bytes.
- `gold.jsonl`: expected observations, excerpt-local quote and identifying
  anchor spans, category tags, rationale and explicit semantic aliases.
- `review-packet.md`: ten stratified labels covering all six organizations.
- `review.json`: AI authorship, human reviewer, selected IDs, decisions and the
  exact gold-file hash. The user approved all ten selected labels on October 7,
  2026 without corrections; status is `reviewed`. Reviewing ten labels does not
  mean that the entire corpus was human-labeled or human-reviewed.
- `cached.json`: original validated `extraction_call.parsed` payloads, raw
  response text, call IDs, provider/model, prompt hashes, original hashes,
  attempts, token counts, latency and failures. Human observation corrections
  are never substituted for provider output.
- `data/evaluation/extraction.json` and its Markdown sibling: saved results,
  denominators, coverage, disagreement examples and limitations. Before capture,
  the report shows missing outputs rather than invented predictions or 0% error.

Corrections from the reviewer must be applied to the gold labels, with their
rationale preserved in the review record and the gold hash recomputed. Disputed
labels are marked `disputed: true`; the report retains their count and excludes
them from error denominators. Their predictions are not called unsupported.
Resolve review decisions and freeze the gold labels before new provider calls.

## Labeling guide

Inspect the original source, not a model-generated answer. Label every relevant
result, outlook and qualitative business condition within the selected excerpt.
Repeated renderings of the same fact in an excerpt are one observation. Dates,
website instructions, confidence-interval margins and footnote reference numbers
are context rather than independent activity observations.

- Percent is the printed number (`8` for 8%); decreases carry negative signs.
  A stated level and its growth rate are separate observations.
- Use null for unstated geography or accounting basis. Do not infer `global`,
  `units`, or `as_reported` simply from the company's business.
- Measured results, numerical guidance and qualitative claims have distinct
  statement types. Qualitative claims have null numeric fields and unit `text`.
- Extract bounded guidance as a range, not its midpoint. Preserve approximate
  guidance's printed point/range; the schema has no separate approximation flag.
- Use the period explicitly named in the passage; otherwise use the source's
  reporting interval for undated present-tense commentary. The extractor sees
  only the passage, company, document type and source reporting interval. It does
  not see gold labels, review decisions or publication timestamps.
- Visa's lagged service-revenue volume refers to January-March even in the
  April-June earnings release. Booking Q4 outlook and FY outlook have different
  target periods. PayPal trailing-12-month activity is October-September.
- Costco's 16-week Q4 ends August 31, 2025 and starts May 12. Its 52-week fiscal
  year starts September 2, 2024. Prior-year values use the corresponding fiscal
  intervals. The earlier gate fixture's 12-week start is not reused.
- Census months and three-month windows are distinct. Retain the prior and
  revised May estimate separately, with basis `previous_estimate` and
  `revised_estimate`. Confidence-interval margins are not growth estimates.
- Geography and scope follow the stated row or qualifier. PayPal all-transaction
  decreases and ex-PSP increases can both be correct. Costco adjusted comparable
  sales exclude both gasoline-price and foreign-exchange effects; they are not
  merely a constant-currency series.
- `contradiction` covers revisions, opposing movements and apparently conflicting
  figures resolved by scope, currency basis or period. These are retained source
  statements, not fabricated contradictions inserted into passages.

Activity labels are short semantic identifiers, with growth vs level distinguished
by unit and evidence anchor. Each label's `accepted` map freezes its permitted
aliases before capture. Aliases do not change values, signs, units or dates.
Visa `constant_dollar` and PayPal `currency_neutral` may represent the extractor's
`constant_currency` basis; this does not equate their business model definitions.

## Capture and reproduce

Use the existing backend venv, installed as described in the package README.
Postgres and existing migrations are required only for capture. Configure the
OpenAI key in a runtime environment or pass a credentials file:

```bash
make capture-extraction ARGS='--credentials-env /path/to/runtime.env'
make evaluate-extraction

# All three input files and the output destination can be replaced explicitly:
make evaluate-extraction ARGS='--gold /path/gold.jsonl --passages /path/passages.jsonl --review /path/review.json --cached /path/cached.json --output /path/report.json'
```

Capture is explicitly OpenAI `gpt-5.4`, unchanged `lon16-v1`, at most 20 unique
passages, with the existing adapter's one retry for retryable HTTP errors or
timeouts. Successful DB entries are reused only for an identical provider,
model and canonical prompt hash. Capture commits each call and checkpoints the
export after each passage. Repeating the same checkpoint makes no new calls,
including for failed passages; use a separately budgeted output file for a new
capture. There is no prompt-tuning or automatic rerun loop.

Evaluation-only calls have a null database `document_text_id`; their stable
fixture IDs and complete passage/source provenance are in the export. Capture
does not create observations, review decisions, scenarios or parameter sets.
Credentials are read at runtime and are never copied or exported. Provider
configuration in the package remains unchanged.

Scoring reads only local files. It works with `LLM_PROVIDER` unset, no API key,
and an unreachable database. The Evaluation page reads saved artifacts through
`GET /evaluation/reports/extraction` and never triggers scoring or capture.

## Matching and denominators

Locate the prediction's quote in the excerpt, tolerating whitespace only.
Candidate matches must cover the label's identifying anchor span. Find a global
one-to-one assignment that maximizes anchored matches, then prefers the stated
activity and the fewest field disagreements when a broad quote supports multiple
facts. Values or periods alone never create a candidate match. Compare all
assigned fields even if the value or period is wrong. Numerical tolerance is
absolute `1e-6`, with no relative tolerance or automatic unit conversion.

| Error | Denominator |
| --- | --- |
| Omission | Non-disputed gold labels in successfully parsed passages |
| Value/range, statement type, activity/scope, unit/basis, period, geography | Matched gold labels, including null fields |
| Unsupported, duplicate, invalid quote | Predictions in successfully parsed passages, excluding disputed-only matches |

An unmatched prediction anchored to an already represented activity is a
duplicate; other unmatched predictions are unsupported. Invalid quotes may also
count as unsupported. A matched observation can have multiple field errors.
These error types are not additive. Zero denominators produce null rates,
displayed as `Not scored`, never a false 0%.

Family tables use the source family. Gold-label category tables use each label's
tags. Prediction error categories inherit the passage's tags; tags overlap.
Failed/invalid calls and missing outputs appear separately, along with the
number of unavailable gold labels. They do not silently improve accuracy.
Coverage retains total labels, scorable labels, exact matches, unavailable
labels and disputed labels, allowing the reader to assess the complete sample.

## Validation and limitations

The October 7, 2026 capture made 19 requests with no retries: 18 passages
succeeded and one failed schema validation. The United revenue-mix response
classified a nonnumeric statement as measured, which requires a value or range.
Its original response is retained; five labels are unavailable for scoring.
The 80 scorable labels contain 71 matched labels, 23 exact matches and nine
omissions. The saved report contains 60 disagreement records, including three
unsupported predictions. These counts describe this selected sample only.

Tests check original-source hashes and offsets, malformed responses, wrong
periods/values, aliases, ranges, qualitative nulls, quote failures, duplicates,
global matching, zero denominators, review gating, bounded capture and cache
reuse without observation or parameter writes. Standard `make check` includes
backend checks, DB tests, frontend tests and production build.

The human-reviewed sample is small. Fiscal date inference, semantic labeling,
and qualitative claim granularity remain judgment calls documented above.
The existing schema requires periods and lacks dedicated estimate-status,
confidence-interval and approximation fields. Observed errors expose those
limitations without tuning the prompt against the gold set. Historical source
dates do not prevent pretrained-model knowledge. This sample evaluates
extraction fidelity, not the quality or profitability of business forecasts.
