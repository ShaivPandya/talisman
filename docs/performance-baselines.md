# Performance baselines (TL-179)

This change supplies instrumentation and provisionable monitoring. Committing or
pushing it does **not** activate production monitoring or satisfy the multi-day
collection criterion. Production activation is a separate operational step.

## Measurements

`PERFORMANCE_BASELINES_ENABLED` defaults to `true`; set it to `false` to disable
the added backend headers, counters, and events. Sentry's existing enable/DSN
settings control browser instrumentation independently. No SQL text, query
parameters, chat content, cache keys, or connection strings are added to metrics.

Production JSON logs carry `event`, `environment`, `release`, normalized `route`,
`method`, and numeric metric fields. Request IDs are correlation fields, never
metric labels. Paths not resolved to a route use `<unmatched>`. Workers inherit
`PERFORMANCE_RELEASE` from the image tag; API logs prefer their existing release
SHA. Application performance logs are unsampled.

| Event | Observation |
| --- | --- |
| `api_request` | Full response duration, headers duration, outcome, DB/cache/storage counters |
| `pool_checkout` | One acquisition, including queueing and configured connection validation; success or error |
| `pool_stats` | Existing pools' gauges and cumulative counters, plus nonnegative interval deltas |
| `chat_turn` | Executed handler/worker entry to terminal stream event; first nonempty text delta |
| `chat_round` | One continuation round, including retries/tools; the last round includes finalization |
| `chat_model` | Individual model attempt, provider/model, phase, round, duration and available TTFT |
| `chat_queue` | Durable job's existing `created_at` to `started_at`; separate from execution TTFT |
| `cold_start` | Process entrypoint to first API response headers; identifies health probes |

`Server-Timing` exposes `db`, `pool`, `cache`, `storage`, and `total` durations in
milliseconds and `cache_hit`/`cache_miss` counts. It is a snapshot when headers are
sent. An SSE response's header cannot include later tokens/tools/finalization;
use the completed `api_request` and chat observations for those. Parallel and
nested work overlaps: component durations are not an additive waterfall. Cache
time includes lookup/storage work; DB time covers cursor execution, including
validation queries when enabled, rather than connection lifetime or Python work.

TTFT is null when no text was emitted, including tool-only rounds and failures
before text. Failed turns that emitted partial text retain that observation and
their failure outcome. Empty deltas and keepalives do not start the TTFT clock.
Dispatch handoffs and replay/polling requests do not duplicate executed turns.
Cancellation emits a terminal cancellation observation.

The pool sampler defaults to 60 seconds (`POSTGRES_POOL_STATS_INTERVAL_SECONDS`,
minimum 1 second), starts lazily at the first checkout, and never opens a pool or
queries the database. `usage_ms` and `connections_num` are cumulative counters;
`connections_num` counts connection attempts, **not** live connections. Use
`pool_size`/`pool_available` for capacity, interval deltas for rates, and individual
checkout observations for p50/p95. First snapshots have zero deltas. Sampling
can pause while Cloud Run request-based CPU allocation throttles an idle API.

The production entrypoint starts its monotonic clock before importing Uvicorn and
the API. Process-to-first-response includes imports and time waiting for the first
request. It excludes platform scheduling/image pull and is not itself an isolated
boot-duration measure. The dashboard also shows Cloud Run's platform startup
latency. Inspect `first_response_is_probe` in logs to distinguish probe replies.

## Activation runbook (execute later)

1. Choose an **instrumentation-only** release and record its SHA, image tag, and
   collection start time. The shared `performance` branch may contain other
   optimizations; deploying those together cannot establish a pre-Tier-1 baseline.
   Do not deploy Tier 1 changes until this window is captured.
2. Confirm the target project/database and existing Cloud SQL flags. Use a Cloud
   SQL administrator connection to the application database through the existing
   secure connection/proxy setup. Configure a local libpq service named
   `talisman-admin`; keep credentials out of command history and checked-in files.
   Run the idempotent setup/inspection SQL:

   ```bash
   PGSERVICE=talisman-admin psql -X --set=ON_ERROR_STOP=1 \
     --file=infra/gcp/setup-performance-postgres.sql
   ```

   Cloud SQL normally preloads `pg_stat_statements`. The script fails before
   installation if it is unavailable or not preloaded; investigate that instance
   rather than replacing its flags. It neither resets stats nor grants application
   roles administrative access. Retain query-ID/counter snapshots at the start
   and end; these are cumulative SQL statistics, not endpoint percentiles.
3. Provision the metrics **before deploying instrumentation**: log-based metrics
   are not retroactive. Supply the existing Sentry organization slug and numeric
   project ID. The operator needs Logging metric and Monitoring dashboard write
   permissions; application service accounts need no new cloud permissions.

   ```bash
   python3 infra/gcp/setup-performance-monitoring.py \
     --project YOUR_PROJECT --sentry-org YOUR_ORG --sentry-project YOUR_PROJECT_ID \
     --dry-run --output /tmp/talisman-performance-definitions
   ```

   Review the rendered files, then rerun without `--dry-run` to provision. The
   script creates or updates metrics by name and the dashboard by display name,
   preserves the dashboard's current etag, and refuses ambiguous duplicates.
   Authentication errors abort rather than being treated as absent resources.
4. Deploy the selected backend image and workers using the existing scripts.
   Build/deploy the frontend with `VITE_SENTRY_TRACES_SAMPLE_RATE=1`, preserving
   its DSN, environment, and release identity. This setting is a **build-time**
   variable; it requires a rebuild. Do not enable profiling or session replay.
5. Verify a warm endpoint response has `Server-Timing`; inspect one structured
   request log and an agent turn/round. Confirm worker-pool observations appear
   alongside API observations, the pool sampler reports after a minute of active
   use, and release labels match the deployed image. Verify browser page loads,
   actual interactions, and route navigations in Sentry.
   With SDK 9, INP is finalized when the page is hidden/left. LCP stays on the
   pageload transaction; standalone CLS retains zero layout-shift values. Do not
   enable both standalone LCP and CLS on SDK 9: its self-removing lifecycle
   listeners can skip the second observer.
6. Collect **72 consecutive hours of normal use** on that instrumentation release.
   Keep the workload representative; do not use synthetic/load-test traffic as
   normal-use evidence. Record gaps, deploys, errors, and sample counts. The top
   20 table excludes probes and unmatched routes and ranks by volume over 72h.
   Choose the exact release in the dashboard and the same release/time range in
   the linked Sentry browser/traces views.
7. Save the endpoint count/p50/p95 table, chat TTFT and duration, checkout p50/p95,
   pool capacity/usage/wait deltas, and Sentry LCP/INP/CLS/navigation percentiles
   with counts. Low-volume or unsupported browser metrics remain missing, never
   zero. Record browser/device mix; Web Vitals are not supported identically in
   every browser. Feed checkout and pool observations into TL-182's sizing work.
8. Rebuild/deploy the frontend with `VITE_SENTRY_TRACES_SAMPLE_RATE=0.05`. Only
   mark TL-179's collection acceptance complete after the saved 72-hour evidence
   exists. Tier 1 comparisons must use the same definitions and representative
   workload. No production activation was performed by this implementation.

## Dashboard and verification

The checked-in metric definitions use distributions with sub-5ms checkout
buckets. The dashboard merges histogram buckets across instances **before**
computing percentiles; it does not average instance percentiles. Counts are
derived from distributions' `_count`, operations from `_sum`. Snapshot means and
counter deltas are labeled separately from request percentiles. The release
variable defaults to all releases; choose one for a valid baseline comparison.

Relevant local checks:

```bash
pytest -q tests/test_performance_baselines.py tests/test_performance_monitoring.py
pytest -q tests/test_agent_streaming.py tests/test_cache.py tests/test_postgres_state_backend.py tests/test_deploy_scripts.py tests/test_sentry_observability.py
npm --prefix frontend run lint
npm --prefix frontend run build
cd frontend
npx playwright test --config playwright.observability.config.ts
npm run test:smoke
```

The dedicated Playwright configuration uses a fake Sentry DSN, full tracing, and
intercepts envelopes locally. It verifies real browser interactions, Web Vitals,
named navigation transactions, and scrubbing without sending events to Sentry.
Provisioning tests use mocked cloud commands; live dashboard/SQL validation and
the multi-day collection remain activation steps.

References: [Cloud Logging distributions](https://docs.cloud.google.com/logging/docs/logs-based-metrics/distribution-metrics),
[Cloud Monitoring PromQL](https://docs.cloud.google.com/monitoring/promql),
[Cloud SQL observability](https://cloud.google.com/blog/products/databases/guide-to-the-database-observability-with-cloud-sql),
[Psycopg pool statistics](https://www.psycopg.org/psycopg3/docs/advanced/pool.html#pool-stats).
