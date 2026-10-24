# Agent prompt caching (TL-190, TL-221)

The chat router sends the contents of `system.md` and `agent_system.md` as
one system text block with an ephemeral cache breakpoint. Memory, screen
context, response preferences and domain instructions follow in a separate
block. OpenAI receives the same stable-first instruction text.

Anthropic and OpenAI normal chat calls send the full agent-exposed tool catalog
in name order (82 tools at measurement time), filtered by the provider/model's
current gateway policy. Regex and intent routing still choose workflows, ticker
context and follow-up hints; they no longer determine these providers' wire tool
lists. Discovery therefore does not change schemas mid-turn. Gemini and Talisman
keep their selected/discovered tool behavior. Execution still authorizes every
tool call; advertising a schema does not grant execution permission.

Because Anthropic orders its cache prefix as tools → system → messages, the
stable system breakpoint also covers the tools. Final synthesis and output-limit
continuations retain definitions with `tool_choice: {"type": "none"}` on Anthropic
and `tool_choice: "none"` on OpenAI. Dedicated workflow/structured synthesis paths
keep their existing prompt/tool shapes.

The catalog is rebuilt once per normal turn and on a provider fallback. Gateway
policy changes intentionally change it: private tools are excluded when private
egress is denied, local-only tools are excluded from external providers, and
explicit provider/model/sensitivity denials still apply. Gateway rules check the
actual input sensitivity and each schema sensitivity, so a higher-sensitivity
schema cannot mask a denial for another class. The usual gateway check still
runs on every actual request, including when policy changes during a turn.

Every OpenAI chat request uses a bounded, hashed `prompt_cache_key` derived from
the actual server session ID, including newly created sessions, retries, output
continuations and structured passes. Keys contain no raw session ID. No extended
retention is enabled. See OpenAI's [prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

A second breakpoint marks the last eligible content block of the latest
message, including tool results. Stored history is not annotated, so markers
do not accumulate over successive rounds. Empty text and thinking blocks are
not marked. The cache uses the default five-minute lifetime; no extended TTL
or new configuration is required.

## Observations

Each completed Anthropic/OpenAI streaming call logs `agent_chat_prompt_cache`
with the model, provider and cache token counts. The TL-179 `chat_model` event and
SSE `done.timings.models` include total input, cache reads, uncached input and
`cached_input_percent = 100 * cache_read_input_tokens / input_tokens` (rounded
to three decimal places). Anthropic additionally reports cache writes. Structured
passes attach their usage to their existing model timing. Failed/empty calls or
providers without cache usage report a null share rather than a fabricated hit.
Existing phase, round, duration and TTFT fields allow comparisons. No prompts,
tool arguments, raw session IDs or response text are added to these logs.

OpenAI's `usage.input_tokens_details.cached_tokens` is a subset of its total
`input_tokens`; it is never added to the total. Chat-Completions-style
`prompt_tokens_details.cached_tokens` is parsed the same way. Anthropic excludes
cache reads and writes from its raw input count, so those are added exactly once.

The chat usage field `input_tokens` remains total input for budgets, provenance
and the UI. Anthropic's raw input count is exposed as `uncached_input_tokens`:

```text
input_tokens = uncached_input_tokens + cache_read_input_tokens + cache_creation_input_tokens
```

For the measured `claude-sonnet-4-6` model, cache reads do not count toward
Anthropic's input-tokens-per-minute limit. Uncached input and cache writes do;
request/output limits still apply. Five-minute writes cost 1.25 times ordinary
input, and reads cost 0.1 times ordinary input for this model. See Anthropic's
[rate limits](https://platform.claude.com/docs/en/api/rate-limits) and
[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

## Stable-tool comparison (TL-221)

Run each provider serially from the issue worktree:

```bash
.venv/bin/python -m scripts.benchmark_agent_prompt_cache \
  --protocol stable-tools --provider anthropic --pairs 3 --runs 2 \
  --output outputs/TL-221-anthropic.json
.venv/bin/python -m scripts.benchmark_agent_prompt_cache \
  --protocol stable-tools --provider openai --pairs 3 --runs 2 \
  --output outputs/TL-221-openai.json
```

These are paid provider calls using committed static prompts and tool schemas,
synthetic memory/screen/preferences, and fabricated tool results. The harness
loads only the provider key/model from the worktree's `.env`; it does not execute
tools, start a server, read real conversation history or connect to production
state. Reports contain numeric observations and source/SDK/model metadata, not
request/response content or credentials.

The before arm reconstructs TL-221's prior wire behavior: per-message tool
selection, expansion after discovery, no OpenAI key, and removed OpenAI schemas
at synthesis. The after arm uses the actual current catalog and request builder.
Six fixed histories cover initial input, discovery, another tool result,
text-only synthesis, a second turn with changed dynamic context, and its tool
continuation. Both arms receive identical transcripts, output limits (64) and
reasoning settings (disabled); model output is not fed back. Cold namespaces
are inserted before cacheable instructions and into the earliest tool description.
Arms alternate within each phase, concurrency is one, and two separate batches
are retained. This measures synthetic provider streaming, not complete user turns
or tool-choice quality. Initial tool use is not forced in this replay.

On 2026-10-22, both providers completed all 72 calls (36 per arm), with six
observations per phase/arm. Models were `claude-sonnet-4-6` / `gpt-5.4`, SDKs
0.84.0 / 2.17.0. All **30/30 after-first calls per provider** read the cache;
before missed at discovery and the next turn, and OpenAI also missed at synthesis.
The following p50 and p95 values use nearest rank; six samples make tail estimates
particularly noisy. No observations were removed.

| Provider / phase | Before hits | After hits | After cached input | Before TTFT p50 / p95 ms | After TTFT p50 / p95 ms |
| --- | --- | --- | --- | --- | --- |
| anthropic / initial | 0/6 | 0/6 | 0.00% | 902.4 / 1999.4 | 1098.7 / 1766.7 |
| anthropic / discovery | 0/6 | 6/6 | 99.48% | 1016.2 / 2325.5 | 933.0 / 1834.6 |
| anthropic / tool_continuation | 6/6 | 6/6 | 99.51% | 899.2 / 1242.9 | 993.4 / 2326.2 |
| anthropic / synthesis | 6/6 | 6/6 | 99.98% | 1143.1 / 10361.9 | 1145.6 / 1745.3 |
| anthropic / next_turn | 0/6 | 6/6 | 97.75% | 896.1 / 1523.7 | 1115.9 / 4970.9 |
| anthropic / next_turn_continuation | 6/6 | 6/6 | 99.51% | 792.8 / 856.8 | 936.9 / 1238.4 |
| openai / initial | 0/6 | 0/6 | 0.00% | 731.4 / 4404.1 | 1072.9 / 1356.8 |
| openai / discovery | 0/6 | 6/6 | 93.75% | 685.4 / 1343.3 | 979.1 / 1436.6 |
| openai / tool_continuation | 6/6 | 6/6 | 93.30% | 1239.5 / 6758.1 | 1058.6 / 1381.6 |
| openai / synthesis | 0/6 | 6/6 | 92.19% | 659.6 / 735.8 | 954.8 / 1107.5 |
| openai / next_turn | 0/6 | 6/6 | 93.97% | 718.7 / 896.5 | 1154.0 / 1406.5 |
| openai / next_turn_continuation | 6/6 | 6/6 | 93.49% | 666.6 / 877.2 | 1002.3 / 1312.1 |

The full catalog increases cold input substantially. Totals across 36 calls per
arm show the resulting tradeoff:

| Provider / arm | Total input | Cache reads | Cache writes | Ordinary input |
| --- | --- | --- | --- | --- |
| anthropic / before | 293,448 | 146,826 | 146,514 | 108 |
| anthropic / after | 618,312 | 511,950 | 106,254 | 108 |
| openai / before | 226,298 | 67,584 | 0 | 158,714 |
| openai / after | 413,208 | 321,792 | 0 | 91,416 |

Anthropic's cache-write volume falls, and OpenAI's ordinary input falls. Total
input rises on both providers. These runs establish reliable cache reuse, **not
a latency improvement**: several median TTFTs regress with the larger catalog.
Benefits depend on conversation length, workload and provider pricing; short or
cold sessions can cost more. Provider/network variance and concurrent agents on
the host also affect timings. Raw reports retain batch, pair, phase and host load
for inspection. Production timing collection is still needed before claiming
faster user turns or overall savings.

The legacy TL-190 replay remains available as the default `--protocol legacy`.
The experiments below predate TL-221 and describe that earlier request shape.

## Repeatable comparison

From the issue worktree with its dependencies installed:

```bash
.venv/bin/python -m scripts.benchmark_agent_prompt_cache \
  --pairs 10 --rounds 3 --output outputs/agent-prompt-cache.json
```

This makes paid Anthropic calls using only the worktree's Anthropic API key,
the real static agent prompt, four real tool definitions and fabricated tool
results. It never executes tools, starts an API server or uses production
state. It streams through the same router helper and records the same model
TTFT. The comparison reconstructs the original string-system/message format
without cache markers for the uncached arm.

Each pair uses identical prompt content, model, reasoning setting, output
limit and tool schemas. Arm order alternates, concurrency is one, and a unique
prefix per pair isolates cold writes from other agents using the same key.
The second and third requests replay growing tool-result histories. Model
output is not fed back, so both arms receive identical transcripts. Each pair
runs within the cache lifetime. Run at least twice under matching machine and
network conditions; retain sample counts and individual observations.

The JSON contains timings, token counts, model/SDK version and a router source
hash, without request/response text or credentials. It separates first-round
latency from continuation latency. `reads_cover_first_request` counts cached
continuations whose reads cover at least the full cold first request, including
the system and tools. Missing TTFT stays missing.

This replay measures client-observed provider streaming latency, including
network and provider queueing. It does not isolate server-side prefill, establish
production end-to-end chat percentiles or replace the normal-use collection
described in `performance-baselines.md`. Tool-set changes, thinking/tool-choice
changes, long gaps and provider/network variance can reduce cache reuse or
mask its latency benefit.

## Measured results

Two repeated runs on 2026-10-21 used `claude-sonnet-4-6`, Anthropic SDK 0.84.0,
no thinking, 64 output tokens, 10 alternating pairs and three requests per arm
per pair. Each run supplies 20 continuation observations per arm.

| Run | Uncached continuation p50 / p95 (ms) | Cached continuation p50 / p95 (ms) | Cached continuations covering the first request |
| --- | --- | --- | --- |
| 1 | 968.7 / 1910.9 | 943.0 / 2503.7 | 20 / 20 |
| 2 | 922.2 / 1760.7 | 931.9 / 1334.6 | 20 / 20 |
| Combined | 960.6 / 1779.6 | 936.3 / 2169.9 | 40 / 40 |

All first cached requests were cold writes of 7,573–7,581 tokens. Later requests
read the full initial prefix and wrote 79 newly appended tokens each, with three
uncached input tokens per call. Across 60 calls per arm, both arms had 459,516
total input tokens. The cached arm read 304,644 tokens, wrote 154,692 tokens and
processed 180 uncached tokens. No request failed. Raw observations are retained
locally in `outputs/agent-prompt-cache-run1.json` and
`outputs/agent-prompt-cache-run2.json` (generated files, not committed).

The cache-reuse criterion is verified. These measurements do **not** establish
the expected 0.3–1 second continuation TTFT reduction: the combined median
improved by 24.3 ms, and p95 regressed. The four-continuation pilot showed a
larger median improvement but was not reproduced by the larger runs. A normal-use
production comparison using TL-179's `chat_model`/`chat_round` events remains
necessary; cache hits alone are not evidence of lower end-to-end latency.

### Follow-up latency validation

A second protocol ran on 2026-10-21 from 21:11 to 21:18 UTC, using the same
model and SDK. Two fixed batches of 12 paired turns produced 192 measured
requests, plus four cache-boundary probes. Requests were serial on one shared
client, with cached/uncached order alternating within each phase. Each pair
had a fresh namespace, and no observations were removed. No request failed.

This protocol used the application's 8,192-token output limit, disabled
thinking, four real tool schemas, a fabricated 20-position portfolio result
(3,435 bytes) and risk result (1,561 bytes). It replayed four fixed histories:
initial forced tool use (`any`), a tool-result continuation (`auto`), synthesis
(`auto`), and an output continuation. The cached output continuation retained
tools with `none`; its uncached counterpart reproduced the old behavior of
dropping schemas. Output continuation used a short fixed truncated answer,
rather than generating 8,192 tokens first. Model output was not fed back, and
no tools or production state were accessed. This tests request shapes and
provider latency, rather than a complete live agent conversation.

The production streaming helper recorded text TTFT. Additional instrumentation
recorded response headers, the first parsed event and the first text/tool-use
output. The initial and tool-continuation calls produced only tool calls, so
their text TTFT is missing; the table uses first tool-use output for those
phases. It uses text TTFT for synthesis and output continuation. Each cell has
24 observations per arm. Medians use the midpoint of the two middle values;
p95 uses nearest rank. The earlier replay used nearest rank for both.

| Phase | Uncached p50 / p95 (ms) | Cached p50 / p95 (ms) | p50 gain, uncached minus cached (ms) | 95% interval for p50 gain (ms) |
| --- | --- | --- | --- | --- |
| Initial tool use | 932.6 / 2753.4 | 968.3 / 1992.4 | -35.7 | -175.0 to 153.5 |
| Tool continuation | 1333.8 / 2743.1 | 1305.0 / 2363.5 | 28.9 | -156.2 to 414.8 |
| Synthesis | 1045.0 / 4793.4 | 999.4 / 2050.7 | 45.6 | -91.7 to 352.3 |
| Output continuation | 1108.4 / 2872.8 | 1053.1 / 2504.0 | 55.4 | -127.6 to 428.6 |

Intervals use a paired percentile bootstrap within each phase, resampling
turns 4,000 times with seed 190. They estimate uncertainty in the difference
between arm medians, not the median of individual paired differences. All
intervals include zero. Separate batch median gains were also inconsistent:

| Phase | Batch 1 gain (ms) | Batch 2 gain (ms) |
| --- | --- | --- |
| Initial tool use | -23.9 | -69.2 |
| Tool continuation | 275.3 | -64.1 |
| Synthesis | 94.6 | -9.0 |
| Output continuation | 50.0 | 87.5 |

All 72 cached continuation requests read the cache. Tool continuations read
7,213–7,222 tokens covering static instructions and tools after the `any` to
`auto` transition. Synthesis read 8,900–8,909 tokens, and output continuation
read 9,606–9,615 tokens. The probes independently verified that changing tool
choice or dynamic context preserves the 7,216-token stable prefix, while
adding a tool invalidates it. The median gap from response headers to first
event was below 1 ms in each arm; this does not distinguish provider queueing,
prefill and network time. Shared-host one-minute load averages ranged from
2.30 to 21.77; interleaving reduces temporal imbalance but does not remove
all sources of variance.

The follow-up again verifies cache reuse without establishing the expected
300–1,000 ms median improvement. Its p95 improvements are descriptive and
were not consistent across the earlier replays. A normal-use comparison is
still needed to establish a latency benefit.

The local experiment is reproducible with
`.venv/bin/python -m outputs.validate_latency --pairs 12 --runs 2`.
Its source and raw report are retained in `outputs/validate_latency.py` and
`outputs/agent-prompt-cache-latency-validation.json` (generated, not committed).

## Attachments (TL-225)

A message can cite PDFs, PNG/JPEG/WebP images and CSVs uploaded through
`POST /agent/attachments` (20 MiB PDF, 5 MiB image, 2 MiB CSV, five files and
20 MiB of PDFs and images per message). The bytes live in state storage under
`chat_attachments/<id>/`; a message row keeps only a descriptor, as an
`attachment` part. The model sees them as blocks ahead of the message text:
Anthropic `document`/`image`, OpenAI `input_file`/`input_image`, Gemini
`inline_data`. A CSV goes in as text, cut at about 100 KB. The Talisman model
gets PDF text (pdfminer) and a note in place of each image.

Files stay attached to the message that carried them while it is in the
verbatim window, newest first within the 20 MiB budget. The Anthropic breakpoint
on the latest message therefore covers a document sent earlier, and a
follow-up turn reads it from cache. A regenerated answer reuses the stored
question's files.

Routing, ticker detection and the domain guardrail read `message` only. The
egress scan, token estimate, classifier and provenance record skip the base64:
a file counts as private material, is estimated by size (PDF about 25 tokens
per KB up to 120,000, image about 1,600), and is charged against the turn's
input budget once rather than on every tool round.

