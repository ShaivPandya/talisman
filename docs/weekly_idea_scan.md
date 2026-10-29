# Weekly idea scan

The Idea Digest page (`/idea-digest`) shows one entry per weekly scan: a sector
macro view, long and short names worth a closer look, near-misses, names that are
already tracked, the week-over-week changes and the run's cost. The output is a
list of names to research, not trade recommendations.

## Pipeline

`api/idea_scan/pipeline.py` runs as the `weekly_idea_scan` job on the `screens`
queue (150-minute timeout).

1. **Universe.** S&P 500, 400 and 600 (Wikipedia constituent tables, 24-hour
   cache, SPDR ETF holdings as a fallback) plus `equities/universes/russell2000.csv`,
   deduplicated.
2. **One fetch.** `api/idea_scan/data.py` downloads 3 years of adjusted closes in
   batches of 50 symbols a second, then a trimmed `.info` and four statements per
   ticker through the screens' Yahoo throttle. Rate-limited and expired-crumb
   calls are retried after a backoff. The data set is checkpointed in state
   storage per ISO week, so a retried or second run that week resumes. Fetching
   stops starting new tickers after `IDEA_SCAN_FETCH_DEADLINE_SECONDS` (100
   minutes) so a throttled week still publishes.
3. **Presets.** `api/idea_scan/screening.py` builds one factor frame (screen
   fields, price metrics, valuation, the rank_universe quality / momentum
   composite) and applies every enabled preset to it (six to start, including a long value + momentum + quality screen). Screen checks reuse the
   long and short screen predicates one criterion at a time, so cards list the
   signals that fired and near-misses name the one check they missed. A name hit
   by several presets is one candidate; agreement = presets hit + the composite
   percentile (inverted for shorts).
4. **Macro view.** One high-tier call over the latest macro snapshots, last
   week's view and up to 5 web searches scores each yfinance sector from -2 to
   +2. Rows without a snapshot or returned-URL citation, and score changes
   without an explanation, are dropped. A tailwind can only raise a long's rank
   and a headwind a short's; macro never removes a name.
5. **Quick reviews.** The top names (15 by default) get a mid-tier review with
   at most 2 web searches, recent 8-K and Form 4 filings from EDGAR, and the
   sector's macro row. Headlines are kept only when the search returned their
   URL, and recommendation phrasing is removed before the review becomes an
   OpportunityCandidate. Names already in Ideas or the portfolio don't use a slot.
6. **Publish.** Reviewed names go to the Scout queue (one candidate per ISO week,
   ticker and direction; a rerun never reopens a dismissed or promoted one), a
   short digest lead is written, and the run is saved as JSON under
   `idea_scan/runs/` in state storage.

## Budget

The run stops starting LLM steps when the next one's estimate would take spend
past `max_cost_usd` ($2 by default). Every provider response is costed through
`llm_utils.observe_llm_responses`, including pause-turn continuations and JSON
repairs; prices are in `api/idea_scan/budget.py`. Skipped names show as "Not
reviewed (budget)".

## Measured cost and runtime

From the first local runs (2026-10-28, default presets, all four universes):

| Step | Result |
| --- | --- |
| Universe | 2,843 unique tickers; 2,718 with usable data (most failures are delisted Russell symbols) |
| Data fetch | ~35 minutes cold (prices ~2.5 minutes in 50-symbol batches; fundamentals the rest); a resume the same week takes seconds |
| Factor frame, revisions, screens | 15 s, 33 s (399 names), 1 s; peak memory 364 MB |
| Macro view (Opus 5.5, 5 searches) | $0.39 |
| One review (Sonnet 5.5, 2 searches) | ~$0.08, so 15 reviews ≈ $1.20 |
| Digest lead | < $0.01 |

A full run should cost about $1.60 against the $2 limit.

## Settings

Presets and run limits are the `idea_scan.settings` app setting, editable from
the digest's **Presets** dialog or `PUT /api/idea-scan/settings`. Each preset sets
a direction, universes, a screen and its parameters, ranking weights and a
maximum number of names.

## Schedule and manual runs

`infra/gcp/setup-scheduler.sh` creates `weekly-idea-scan` (Saturday 08:00
America/New_York) only when `SCHEDULE_WEEKLY_IDEA_SCAN=1`. **Run now** on the
digest page, or `POST /api/idea-scan/runs`, starts a manual run; narrowing the
universes or review count makes it a test run that isn't used as the next
week's baseline.

## Known gaps

- No borrow cost or availability feed: short cards say so and list it as missing.
- Short interest comes from Yahoo `.info` and is missing for some names.
- The Russell 2000 file predates recent delistings, so a few symbols return
  "quote not found" and are reported as failed.
- There is no notification channel yet; the digest page is the output.
