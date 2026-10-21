# Postgres pool sizing (TL-182)

## Target and evidence

This configuration targets the **existing** Cloud SQL `talisman` instance in
`project-a6b8946d-eba6-4f39-b83`, `us-central1`. Read-only inspection on
2026-10-21 found PostgreSQL 16 on `db-f1-micro`, not the `db-custom-2-7680`
assumed by the original issue. `pg_settings` reported:

- `max_connections = 25`
- `superuser_reserved_connections = 3`
- `reserved_connections = 0`

That leaves **22 application slots**. Increasing API/agent pools to 8–10 while
allowing 10 API instances would exceed this budget. The approved configuration
instead uses smaller pools and a lower API instance limit. This trades maximum
horizontal capacity for a connection footprint that fits the current database.

Production was still on release `d9f06dfb` during inspection. Cloud Logging
returned no `pool_checkout` or `pool_stats` events in the preceding 72 hours.
These are provisional settings supported by repeatable local experiments;
**normal-use production checkout p95 < 5 ms remains a post-deployment check**.
No database tier, flags, or production deployments were changed by TL-182.

## Production settings and budget

| Consumer | Maximum processes | Pool min / max | Maximum connections |
| --- | ---: | ---: | ---: |
| API | 2 | 2 / 2 | 4 |
| Agent worker | 1 | 2 / 2 | 2 |
| Analyzer worker | 0 | 2 / 2 | 0 |
| Ontology worker | 0 | 2 / 2 | 0 |
| Generic async executions | 2 | 2 / 2 | 4 |
| Top-50 refresh | 1 | 0 / 1 | 1 |
| Migration | 1 | One direct connection | 1 |
| Admin/diagnostics allowance | — | — | 2 |
| **Steady-state envelope** | | | **14** |
| Extra API fleet + agent replica during rollout | 2 + 1 | 2 / 2 | 6 |
| PostgreSQL reserved slots | | | 3 |
| **Budget including rollout and reserved slots** | | | **23 / 25** |

The remaining two slots provide additional headroom. The container entrypoints
run one Python process each; additional Uvicorn processes multiply their pools.
The migration allowance covers one migration process, not concurrent migration
commands. The budget assumes the optional worker pools stay at zero instances.

**At most two simultaneous generic async executions is an operational
assumption, not an enforced dispatch limit.** Count executions across all
callers, including Scheduler and manual runs. Cloud Run's `parallelism` setting
limits tasks *within an execution*, not the number of overlapping executions.
Exceeding the execution allowance invalidates the budget. A distributed dispatch
cap is separate work. See [Cloud Run job parallelism](https://docs.cloud.google.com/run/docs/configuring/parallelism).

`API_MAX_INSTANCES` sets both the service-wide `--max` and per-revision
`--max-instances` limits. The rollout allowance covers one additional API fleet
and agent replica; larger overlaps or additional consumers require recalculation.
It is not a substitute for global database admission control.

The shared production minimum is 2 and checkout timeout is 5 seconds. The API,
workers, and async job retain the existing `POSTGRES_POOL_*` overrides. The
serial top-50 job fixes its pool at 0 / 1 and shares the timeout override. Local
Python defaults remain unchanged. A minimum of 2 keeps established connections
available after idle periods; pools are still created lazily, so the first
checkout in a new process can pay connection setup time.

Before changing pool overrides, API capacity, worker counts, process counts,
async execution allowance, or the database tier, recalculate every row against
fresh `pg_settings` values. `usage_ms` and `connections_num` are cumulative;
`connections_num` counts attempts, not live connections. Use `pool_size` for
capacity and individual checkout observations for percentiles.

## Initial rollout and production verification

The existing API revision has a 0 / 4 pool and a 10-instance limit. The table
above applies after all consumers use the new settings. For the initial rollout:

1. Drain generic async, top-50, and migration executions. Keep them drained while
   old API/worker revisions are running.
2. Apply the API service-wide cap of 2 using `gcloud run services update --max=2`
   with the existing service, project, and region. Wait for existing API capacity
   to settle at at most two instances before deploying the new revision.
3. Roll components sequentially and verify old revisions have drained. Two old
   API processes at max 4 plus two new processes at max 2 consume 12 connections;
   allowing two agent processes at max 2 and two admin slots totals 18, or 21
   including the three PostgreSQL reserved slots. Resume batch work only after
   the final pool/instance settings are confirmed.
4. Activate the TL-179 instrumentation using
   [the baseline runbook](performance-baselines.md). Collect comparable normal
   traffic windows on an identified release, including the warm worker.
5. Report checkout count/p50/p95 by component, checkout errors, queue/usage
   deltas, peak `pool_size`, and database connection counts. The target is
   checkout p95 **below 5 ms** at normal load, with no capacity errors. Missing
   observations remain missing. If the target fails, inspect usage/queueing and
   DB CPU before raising pools; this database has little spare capacity.

Production rollout and verification are operational follow-up work. Committing
the configuration and passing a local benchmark do not establish production p95.

## Repeatable local benchmark

Use a disposable Postgres 16 database with pgvector. The following container
has no persistent volume and listens only on local port **55482**. Start Docker
first; never point these experiments at production.

```bash
docker run --rm -d --name talisman-tl182-postgres \
  --cpus=1 --memory=600m -p 127.0.0.1:55482:5432 \
  -e POSTGRES_PASSWORD=tl182-local-only -e POSTGRES_DB=tl182_pool_bench \
  pgvector/pgvector:pg16
docker exec talisman-tl182-postgres pg_isready -U postgres -d tl182_pool_bench
docker exec talisman-tl182-postgres psql -U postgres -d tl182_pool_bench \
  -c 'CREATE EXTENSION IF NOT EXISTS vector'
export TEST_POSTGRES_URL='postgresql://postgres:tl182-local-only@127.0.0.1:55482/tl182_pool_bench'
.venv/bin/python -m scripts.benchmark_postgres_pool \
  --concurrency 1 4 8 --samples 1000 --repeats 5 --hold-ms 1 \
  --output outputs/tl182-pool-1ms.json
.venv/bin/python -m scripts.benchmark_postgres_pool \
  --concurrency 1 4 8 --samples 1000 --repeats 5 --hold-ms 0 \
  --output outputs/tl182-pool-0ms.json
docker stop talisman-tl182-postgres
```

Wait for `pg_isready` to succeed before creating the extension. Record the
container image digest and runtime versions with results. The benchmark compares
the old API 0 / 4 / 30s and worker 0 / 2 / 5s with the new 2 / 2 / 5s settings.
Each run creates a fresh pool, measures its first checkout separately, waits for
the configured minimum, warms it using the same workload, then measures 1,000
autocommit reads. Case order and concurrency order alternate over five repeats.

Reports contain nearest-rank checkout p50/p95, operation p95, throughput, error
counts, pool gauges, and `get_stats()` counter deltas after warmup. The script
uses only `TEST_POSTGRES_URL`, accepts local hosts/sockets, and never loads
`.env` or falls back to the application's `DATABASE_URL`. It creates no schema
or test data. Zero- and one-millisecond SQL holds exercise different occupancy;
concurrency 4/8 is synthetic stress, not evidence of normal production demand.

Local TCP, container scheduling, and synthetic SQL do not reproduce Cloud SQL
CPU contention, TLS, network latency, or the application's transaction lifetimes.
Keep before/after runs on the same host/container settings, and repeat noisy
results while other agents are running. See [Psycopg pool statistics](https://www.psycopg.org/psycopg3/docs/advanced/pool.html#pool-stats).

## Recorded local results

Recorded on 2026-10-21 with Python 3.12.2, psycopg 3.3.3, psycopg_pool 3.3.1,
PostgreSQL 16.15, one container CPU, and 600 MiB memory. Immutable image:
`pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`.
Use that reference instead of the tag above to reproduce the image exactly.

Each cell below is the **median of five per-run checkout p95 values**, not a
pooled p95. Brackets show the minimum and maximum per-run p95 for the new pool.

| SQL hold (ms) | Concurrent clients | Old API p95 (ms) | Old worker p95 (ms) | New pool p95 (ms), range |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 0.032 | 0.021 | 0.021 [0.014–0.064] |
| 0 | 4 | 0.164 | 0.554 | 0.592 [0.499–1.204] |
| 0 | 8 | 0.922 | 1.497 | 1.725 [1.462–2.621] |
| 1 | 1 | 0.123 | 0.137 | 0.130 [0.120–0.300] |
| 1 | 4 | 0.083 | 5.111 | 5.003 [4.522–7.632] |
| 1 | 8 | 4.676 | 13.613 | 15.836 [14.702–16.942] |

All 90,000 measured operations completed without errors. The new pool stayed at
two connections in every run; the old API pool reached four at concurrency 4/8.
First-checkout medians across scenarios ranged from 18.7–51.3 ms, so these runs
do not establish a cold-start latency improvement. The API's configured maximum
connection footprint falls from 10 × 4 = 40 to 2 × 2 = 4, and the complete new
planning envelope fits 23 of 25 slots including rollout and reserved capacity.

The zero-hold workload met 5 ms in all repeats. The one-millisecond hold workload
exceeded it at concurrency 4/8: a two-slot pool offers less throughput than the
old four-slot API pool under contention. If normal production resembles those
stress cases, the latency target is not met. Revisit DB occupancy and database
capacity using production observations. **Production verification remains
pending.** Raw local reports are generated at
`outputs/tl182-pool-0ms.json` and `outputs/tl182-pool-1ms.json` (ignored artifacts).
