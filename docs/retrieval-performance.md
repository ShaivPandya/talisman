# Full-text retrieval (TL-193)

PostgreSQL retrieval uses full-text matching and `ts_rank` over all non-stale
chunks. The GIN index finds candidates; the database ranks them before applying
`top_k`. Only those final chunks' content and citation metadata are fetched.
There is no 1,000-row candidate cap. Reads retain TL-181's shared pool,
autocommit read path, and single retry for transient connection failures.

`search()` and `index_document()` no longer import or call an embedding model
on PostgreSQL. Existing embeddings remain stored, but new chunks have a null
embedding. The internal vector-search helper excludes those chunks. SQLite's
explicit compatibility mode retains its existing semantic/lexical behavior.

## Matching and ranking

The indexed vector combines ticker and document type (`simple`, weight A),
heading (`english`, weight B), and chunk content (`english`, weight D).
Queries OR together normalized English and simple lexemes, so a conversational
question can match individual research terms and tickers such as `ON` or `IT`
are not lost as English stop words. Query text is parameterized and each
normalized lexeme is quoted as tsquery data. Punctuation-only input returns no
matches. This is term matching and stemming, not semantic paraphrase matching;
phrase bonuses from the former Python regex scorer are not retained.

Ranking uses `ts_rank(..., 32)`, descending, with document ID, chunk index, and
chunk ID as deterministic tie breakers. Doc-type/ticker filters and stale
exclusion apply before the limit. Result metadata and citations are preserved;
`retrieval_mode` is `full_text`, without an embedding-failure reason.

## Migration and rollout

`20261021_tl193_retrieval_fts.py` adds and backfills `search_vector`, then builds
the GIN index. Chunk insert/content/heading/document changes and parent
ticker/type changes maintain it through database triggers. This also covers the
existing offline SQLite importer. Parent-row locking keeps concurrent metadata
updates from leaving a newly inserted chunk with an old vector.

Apply the migration before starting the new API/workers. Backfill and index
creation run in the migration transaction and require table locks; allow for
corpus-dependent migration time. This change does not apply the migration to
production. Inspect/measure migration duration on a production-sized copy before
rollout. Migration downgrade is tested before any text-only writes. After such
writes, downgrade refuses until missing embeddings are backfilled: it never
deletes chunks or invents embeddings to satisfy the former NOT NULL constraint.

## Reproduce the benchmark

Use a dedicated disposable Postgres 16 + pgvector container. Port 55493 belongs
to this experiment; choose another unused non-default port if necessary.

```bash
docker run --rm -d --name talisman-tl193-postgres \
  --cpus=1 --memory=600m -p 127.0.0.1:55493:5432 \
  -e POSTGRES_PASSWORD=tl193-local-only -e POSTGRES_DB=tl193_retrieval \
  pgvector/pgvector:pg16
docker exec talisman-tl193-postgres pg_isready -U postgres -d tl193_retrieval
docker exec talisman-tl193-postgres psql -U postgres -d tl193_retrieval \
  -c 'CREATE EXTENSION IF NOT EXISTS vector'
export TEST_POSTGRES_URL='postgresql://postgres:tl193-local-only@127.0.0.1:55493/tl193_retrieval'
.venv/bin/python -m scripts.benchmark_retrieval \
  --before-ref 8653b613 --chunks 10000 100000 \
  --samples 210 --warmup 70 --repeats 5 \
  --output outputs/tl193-retrieval.json
docker stop talisman-tl193-postgres
```

The script only accepts a local `TEST_POSTGRES_URL`, never loads `.env`, and
creates/drops its own schema. It applies the relevant original migrations,
seeds the pre-existing corpus, and applies TL-193 to exercise the backfill. It
uses explicit migration operations because the unrelated historical full
migration chain recreates `schema_definitions`.

The before implementation is loaded unchanged from the specified Git revision,
with the missing embedding dependency simulated. Synthetic embeddings are zero
vectors because neither comparison path uses them. Each chunk has about 1.5 KB
of text. There are 20 chunks per document, selective sector/macro terms, ticker
and document filters, absent matches, a best match at the final chunk, and a
broad term matching every chunk. After retrieval must find the final chunk or
the benchmark fails.

Measurements include the public `search()` call, pool checkout, query execution,
row transfer, and result serialization. Five rounds alternate before/after
order with fixed queries, a shared pool of two connections, and concurrency one.
Each case has 70 warmup queries and 210 measured queries (30 per query type).
Logging I/O is disabled in both cases, conservatively understating the old
exception-logging cost. Percentiles use nearest rank. Cold full-text calls are
reported separately. The report includes query-level percentiles, returned
chunk IDs, source hash, Postgres/Python versions, and the actual selective query's
`EXPLAIN (ANALYZE, BUFFERS)` plan.

Do not run other local tests/builds concurrently with final measurements. Other
agents' machine load can still affect results, so use the repeated ranges.
These are local synthetic measurements, not a production latency guarantee.

## Measured results (2026-10-21)

Postgres 16.15 (Debian 16.15-1.pgdg12+2), Python 3.12.2, one container CPU,
600 MiB memory, pool min/max 2. The complete workload has seven equally weighted
query types, including a term matching every chunk. Ranges below are the minimum
and maximum **per-round p95** across five rounds, not an average of percentiles.
The measured retrieval source SHA-256 is
`19d875f17eb7c36cfb69cc86d194fa874736bc891dba867ec375f93dc7831564`.

| Corpus | Before, all queries | After, all queries | After, broad query only |
| --- | ---: | ---: | ---: |
| 10,000 chunks | 60.063–148.308 ms | 6.196–15.565 ms | 6.968–29.506 ms |
| 100,000 chunks | 60.570–80.879 ms | 159.646–172.127 ms | 171.073–212.354 ms |

At 100,000 chunks, each of the six selective/no-match query types had per-round
p95 below 10 ms (maximum 9.864 ms). Full-text search consistently returned the
seeded best match at chunk 10,000/100,000; the old sample did not. The actual
selective application query used `idx_retrieval_chunks_search_vector` at both
sizes. Initial calls before pool warmup took 176.415 ms and 175.318 ms,
respectively, and are excluded from the warm percentiles.

**The 50 ms warm p95 target passes for the full 10,000-chunk workload and the
selective 100,000-chunk queries. It does not pass for the full 100,000-chunk mixed
workload or its broad query.** Exact ranking still processes every matching
chunk; a GIN index cannot avoid that work when a term matches the entire corpus.
The former implementation appears faster in that stress case because it only
scores an arbitrary 1,000-row sample. The accepted workload gate is the full
10,000-chunk workload and selective 100,000-chunk queries; the large broad query
is a documented stress limit.
No production latency claim is made.

## Correctness checks

```bash
TEST_POSTGRES_URL='postgresql://postgres:tl193-local-only@127.0.0.1:55493/tl193_retrieval' \
  .venv/bin/pytest -q tests/test_retrieval.py tests/test_retrieval_postgres.py \
  tests/test_postgres_pool_integration.py
```

Tests cover migration backfill, highest-ranked hits beyond chunk 1,000, tie
ordering, no-match/punctuation queries, model-free indexing/reindexing, filters,
stale exclusion, metadata and citations, parent and chunk updates, downgrade
safety, GIN use, and the shared-pool path.

## Validation

The initial complete backend suite passed with 2,032 passed and 9 skipped.
After rebasing onto `96e2df51` (including TL-194 and TL-195), the full run had
2,063 passed, 9 skipped, and one failure in the unchanged TL-184 retry tests:
their global `time.sleep` mock captured unrelated background sleeps. All 135
tests in that file passed on an isolated rerun. Postgres/auth/async integration
databases were explicitly set to the isolated local container.

The initial frontend smoke run passed all 107 tests. The final serial run after
rebasing passed 106 tests; the unchanged chat selection-restoration test passed
on an isolated retry. These used an ignored local Playwright config and Vite
port 5193. Python lint/format checks, frontend lint, and the frontend
TypeScript/production build passed.

`mypy api/ --ignore-missing-imports` reports 10 existing errors in seven files.
The exact same errors reproduce on the unmodified `8653b613` snapshot; there are
no new retrieval errors. They concern untyped return values in thesis/overview/
management-quality storage, portfolio optimizer caches, company research storage,
and news digests, and are outside TL-193.
