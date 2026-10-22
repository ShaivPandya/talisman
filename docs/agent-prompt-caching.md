# Anthropic agent prompt caching (TL-190)

The chat router sends the contents of `system.md` and `agent_system.md` as
one system text block with an ephemeral cache breakpoint. Memory, screen
context, response preferences and domain instructions follow in a separate
block. The combined instruction text is unchanged. Other providers retain
their existing request formats.

Anthropic tool definitions are sorted by name. Because Anthropic orders its
cache prefix as tools → system → messages, the stable system breakpoint also
covers the tools. Tool discovery can expand the set, causing an expected cache
miss. Final synthesis and output-limit continuations keep the same definitions
and use `tool_choice: {"type": "none"}` to prohibit additional calls rather than
removing tools and invalidating the prefix.

A second breakpoint marks the last eligible content block of the latest
message, including tool results. Stored history is not annotated, so markers
do not accumulate over successive rounds. Empty text and thinking blocks are
not marked. The cache uses the default five-minute lifetime; no extended TTL
or new configuration is required.

## Observations

Each completed Anthropic streaming call logs `agent_chat_prompt_cache` with
`model`, `cache_read_input_tokens` and `cache_creation_input_tokens`. The same
counts are included in the existing TL-179 `chat_model` performance event and
the model timings in the SSE `done` payload. Existing phase, round, duration
and TTFT fields can be used to compare continuation calls. No prompts, tool
arguments or response text are added to logs.

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
