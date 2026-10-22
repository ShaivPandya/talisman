# GET /ideas performance (TL-195)

The list now reads ideas, each idea's newest evaluation, factor scores and missing
information in one SQL statement against authoritative temporal versions. It
preserves the existing response fields, archive filtering after pagination, the
500-idea ceiling and the limit of 100 children per evaluation/type.

`DISTINCT ON` selects evaluations by `evaluated_at` as a timestamp, with object UID
as a deterministic tie breaker. Missing or malformed timestamps sort last.
Superseded, expired and future-valid versions are excluded. This deliberately
changes the evaluation shown when the old business-key ordering chose an older
record. PostgreSQL 16 is required, matching the deployment bootstrap.

The new Alembic migration adds partial expression indexes on evaluation `idea_id`
and child `parent_uid` using `CREATE INDEX CONCURRENTLY`. Both upgrade and downgrade
run outside a transaction. Apply the migration before serving the new query for
the measured performance; it adds no columns or data transformations.

## Repeated local measurements

Measured on 2026-10-21 against PostgreSQL 16.15 in a dedicated Docker container on
port 55495. Each path had an isolated schema with identical synthetic data:
200 ideas, 20 evaluations per idea, and two factor scores plus one missing-field
record per evaluation (16,200 objects total). The baseline was `8653b613` without
the new indexes; the new path included the indexes.

Each case used three warmups followed by 30 samples, alternating before/after
order. Both paths reused a warm connection. Timings include database round trips
and route projection, excluding authentication, HTTP transport and pool checkout.
Other agents were active on the machine, so absolute timings varied materially.
The fixed query-count reduction is the primary regression guarantee.

| Ideas | Queries before → after | Median before → after (ms) | p95 before → after (ms) |
| --- | --- | --- | --- |
| 1 | 4 → 1 | 19.268 → 4.564 | 54.745 → 10.566 |
| 50 | 151 → 1 | 1491.542 → 46.723 | 2245.826 → 95.309 |
| 200 | 601 → 1 | 1362.548 → 37.030 | 2500.112 → 120.126 |

At 200 ideas the median fell by about 97.3%. The benchmark also asserts that the
old path returns evaluation 0 and the new path returns evaluation 19. The query
plan uses both new indexes. The evaluation batch explicitly retains the known
page-size bound to avoid inflated PostgreSQL 16 CTE estimates and JIT overhead.

## Reproduce

Use a disposable local PostgreSQL 16 database and set `TEST_POSTGRES_URL` to its
connection URL. The commands create and drop only their own schemas; they never
fall back to the application's `DATABASE_URL` or read `.env` credentials.

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m scripts.benchmark_ideas_list \
  --baseline-ref 8653b613 --samples 30 --output outputs/tl195-ideas-list.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/pytest tests/test_ideas_list.py -q
```

The JSON output includes the full `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plan.
Tests cover query counts for actual GET requests, timestamp offsets, ties,
malformed timestamps, temporal visibility, child projection and limits, missing
evaluations, filtering, and concurrent migration upgrade/downgrade. PostgreSQL
tests skip when `TEST_POSTGRES_URL` is unset; projection and migration-SQL tests
always run.
