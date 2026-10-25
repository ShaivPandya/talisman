# GCP Production State Runbook

This repository now has the code-level migration pieces for the GCP state move:

- Alembic schema in `migrations/versions/20260429_0001_gcp_state_schema.py`.
- Snapshot and migration CLI in `api/gcp_state_migration.py`.
- Cloud Storage-backed document writes via `api/state_storage.py`.
- Production local-write guard via `api/local_write_guard.py`.
- Firebase Hosting rewrite config in `firebase.json`.

## Deploy automation (this directory)

- `cloudbuild.yaml` — builds the API image and pushes to Artifact Registry. It pulls the previous `latest` image first so unchanged dependency layers can be reused.
- `config.example.sh` — copy to `config.sh` (gitignored) and fill in project / SA / bucket values.
- `lib.sh` — shared helpers sourced by every other script. Defaults `IMAGE_TAG` to the current short git SHA, verifies the image exists in Artifact Registry, and refuses to run if the active gcloud project differs from `PROJECT_ID`.
- `bootstrap.sh` — idempotent provisioning of APIs, Artifact Registry, service accounts, Cloud SQL (with backups + PITR + deletion protection + require-SSL), and the GCS state bucket.
- `setup-secrets.sh` — generates random secrets, prompts for the rest, creates Cloud SQL users with their generated passwords, writes everything to Secret Manager, and binds per-secret accessor IAM to each SA.
- `setup-data-source-secrets.sh` — previews/imports issued optional data-source credentials from an ignored env file, grants API/worker access, and saves deploy bindings. Use `--apply` to write; see [alternative-data setup](../../docs/alternative_data.md#access-and-configuration). Runtime configuration is updated separately.
- `iam.sh` — idempotently grants the project-, bucket-, and Cloud Run-job-level IAM bindings the deploy SAs need (cloudsql.client, logging.logWriter, bucket objectAdmin, job executor on scheduled jobs, and job executor with overrides on the async runner).
- `deploy-api.sh` — Cloud Run service `${API_SERVICE}` (matches the `firebase.json` rewrite). Tunables: `API_CPU`, `API_MEMORY`, `API_CONCURRENCY`, `API_MIN_INSTANCES`, `API_MAX_INSTANCES`, `API_TIMEOUT`. Defaults are `1` vCPU, `1Gi`, and concurrency `20` because long-running analysis is offloaded to workers; raise these if synchronous endpoints show memory pressure or CPU saturation.
- `deploy-async-job.sh` — generic Cloud Run Job running `python -m api.async_job_runner run`. Tunables: `ASYNC_JOB_CPU`, `ASYNC_JOB_MEMORY`, `ASYNC_JOB_TIMEOUT`, `ASYNC_JOB_MAX_RETRIES`.
- `deploy-agent-worker.sh` — warm Cloud Run worker pool running `python -m api.agent_worker_loop run` for durable agent workflow turns. A second loop in the same process drains `agent_turn_followup` jobs (rolling summary, shadow synthesis and trajectory capture after each chat turn's "done"), so turns never wait behind them. Defaults to `1` vCPU and `512Mi`.
- `deploy-analyzer-worker.sh` — warm Cloud Run worker pool running `python -m api.job_worker_loop run` with analyzer job/queue defaults from env for low-latency portfolio analyzer jobs. Defaults to `1` instance, `1` vCPU, and `1Gi`.
- `deploy-ontology-worker.sh` — warm Cloud Run worker pool running `python -m api.job_worker_loop run` with ontology job/queue defaults from env for low-latency ontology query jobs. Defaults to `1` instance, `1` vCPU, and `512Mi`.
- `deploy-migration-job.sh` — Cloud Run Job that runs `python -m api.gcp_state_migration migrate`.
- `deploy-top50-refresh-job.sh` — Cloud Run Job that refreshes the cached S&P 500 top-50.
- `deploy-backend.sh` — build via Cloud Build at the current short git SHA, run Alembic migrations, then roll API + Cloud Run Jobs to that SHA. Refuses to run on a dirty tree (override with `ALLOW_DIRTY=1`); skip the build with `SKIP_BUILD=1`. Routine deploys skip IAM, Scheduler, and monitoring reconciliation by default; use `FULL_SYNC=1` after infrastructure/config changes.
- `deploy-frontend.sh` — builds `frontend/dist` and deploys Firebase Hosting for the configured `PROJECT_ID`.
- `deploy-all.sh` — deploys the full production stack by running `deploy-backend.sh` first and `deploy-frontend.sh` second. `SKIP_BUILD=1` skips the backend container build; `SKIP_FRONTEND_BUILD=1` deploys the existing `frontend/dist`.
- `setup-scheduler.sh` — idempotently create/update the required Cloud Scheduler jobs (async-job-sweep hourly, top50-refresh weekday 23:00 UTC, market-snapshot-refresh weekday 16:20 America/New_York, macro-snapshot-refresh weekday 16:25 America/New_York, workspace-source-refresh weekday 16:30 America/New_York, and continuous-optimizer weekday 10:15 America/New_York) and delete optional/deprecated jobs unless explicitly enabled. Pulls `X-Scheduler-Secret` and `X-Api-Proxy-Secret` from Secret Manager so the values never live in this repo. Optional owned-model release refresh (`agent-model-release-refresh`, Monday 06:00 UTC) is **disabled by default**; enable with `SCHEDULE_AGENT_MODEL_RELEASE_REFRESH=1`. See [docs/talisman_model_release_operations.md](../docs/talisman_model_release_operations.md).
- `setup-governance-monitoring.sh` — idempotently creates/updates governance audit/provenance log-based metrics and the alert policy in `monitoring-governance-alerts.json`.
- `Dockerfile.inference` — governed vLLM inference image with registry/digest startup checks.
- `deploy-inference-service.sh` — provisions the private GPU Cloud Run inference service for an approved registry candidate (`TL-95`).
- `setup-inference-monitoring.sh` — log-based metrics and alert policy for the inference service (`monitoring-inference-alerts.json`).
- Owned-model program index: [docs/talisman_owned_agent_model_program.md](../docs/talisman_owned_agent_model_program.md) (`TL-97`).
- `cleanup-stale.sh` — dry-runs (or `--apply` deletes) GCP resources that pre-date the current scripts and are no longer referenced.

First-time setup:

```bash
cp infra/gcp/config.example.sh infra/gcp/config.sh   # then edit
./infra/gcp/bootstrap.sh           # provision foundation infra
./infra/gcp/setup-secrets.sh       # SQL users + Secret Manager + per-secret IAM
./infra/gcp/iam.sh                 # project + bucket + run-job IAM
# (still need: CREATE EXTENSION vector + alembic upgrade head as the migrator)
./infra/gcp/deploy-all.sh          # deploy backend, then frontend, at the current SHA
./infra/gcp/iam.sh                 # re-run to bind job executor roles on the now-deployed jobs
./infra/gcp/setup-scheduler.sh     # wire up Cloud Scheduler
./infra/gcp/setup-governance-monitoring.sh
```

Routine deploys:

```bash
# full stack
./infra/gcp/deploy-all.sh

# or deploy components separately:
./infra/gcp/deploy-backend.sh
./infra/gcp/deploy-frontend.sh

# or roll a single component:
./infra/gcp/deploy-api.sh
./infra/gcp/deploy-async-job.sh
./infra/gcp/deploy-agent-worker.sh
./infra/gcp/deploy-ontology-worker.sh
```

Routine backend deploys are optimized for the common code-rollout path:

- `deploy-backend.sh` deploys the migration job and runs Alembic migrations first, then starts the non-migration Cloud Run Job and warm worker updates in parallel, waits for them, and deploys the API service. New worker code can therefore rely on additive schema changes.
- IAM, Scheduler, and monitoring syncs are intentionally skipped by default because those resources rarely change and each sync performs multiple GCP control-plane calls.
- Run `FULL_SYNC=1 ./infra/gcp/deploy-backend.sh` when service accounts, Scheduler definitions, monitoring policy files, or other infra config changed.
- Set `PARALLEL_JOB_DEPLOYS=0` if you need the older sequential Cloud Run Job deploy behavior for debugging.
- Drain generic async executions and pause their callers during rollouts. Worker replicas and the extra API fleet are separate rollout phases; see the [connection budget](../../docs/postgres-pool-sizing.md) before changing capacities.

## Cloud SQL

Use Unix socket connectivity:

```bash
INSTANCE_CONNECTION_NAME="PROJECT_ID:REGION:INSTANCE_ID"
DATABASE_URL_API="postgresql+psycopg://talisman_app:${DB_PASSWORD}@/talisman?host=/cloudsql/${INSTANCE_CONNECTION_NAME}"
DATABASE_URL_WORKER="postgresql+psycopg://talisman_worker:${DB_PASSWORD}@/talisman?host=/cloudsql/${INSTANCE_CONNECTION_NAME}"
DATABASE_URL_MIGRATION="postgresql+psycopg://talisman_migrator:${DB_PASSWORD}@/talisman?host=/cloudsql/${INSTANCE_CONNECTION_NAME}"
```

Cloud Run services and jobs must include:

```bash
--add-cloudsql-instances="${INSTANCE_CONNECTION_NAME}"
```

## Async Jobs

Production async work uses the `async_jobs` Postgres table for durable status,
progress, results, and dedupe. Analyzer, ontology, and agent chat jobs use their
warm Cloud Run worker pools by default, avoiding per-request Cloud Run Job
startup latency. Sizer jobs run inline; other batch jobs use the generic Cloud
Run Job.

Every runner must atomically claim a queued job before computing. Direct
runners use `claim_job(job_id)`; warm workers select and claim the oldest
matching queued row with `claim_queued_job`, then call `execute_claimed(row)`.
Both claims set `started_at`, a unique `claimed_by`, and increment `attempt`.
A competing or retried runner gets no claim and exits successfully without
computing or replacing the result. Crashed owners are failed by the stale-job
sweep; claims do not automatically requeue jobs.

Apply migration `20261021_0002` before deploying these runners. For the initial
upgrade, pause analyzer/ontology submissions and drain their existing jobs,
including Cloud Run executions, so old runners cannot bypass the new claim.
Ensure existing `config.sh` files set both analysis worker instance counts to
`1`; older copies of the example set them to `0`.

Required services:

- Cloud Run service `${API_SERVICE}`: `uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}`
- Cloud Run Job `${ASYNC_JOB_RUNNER_JOB}`: `python -m api.async_job_runner run`
- Cloud Run worker pool `${AGENT_WORKER_POOL}`: `python -m api.agent_worker_loop run`
- Cloud Run worker pool `${ANALYZER_WORKER_POOL}`: `python -m api.job_worker_loop run` with `JOB_WORKER_JOB_TYPE=analyzer` and `JOB_WORKER_QUEUE=analyzer`; defaults to `1` instance
- Cloud Run worker pool `${ONTOLOGY_WORKER_POOL}`: `python -m api.job_worker_loop run` with `JOB_WORKER_JOB_TYPE=ontology` and `JOB_WORKER_QUEUE=ontology`; defaults to `1` instance
- Cloud Scheduler jobs:
  - hourly: `POST /api/admin/jobs/enqueue-async-job-sweep`
  - weekdays at 23:00 UTC: run `${TOP50_REFRESH_JOB}`
  - weekdays at 16:20 America/New_York: `POST /api/admin/jobs/enqueue-market-snapshot-refresh`
  - weekdays at 16:25 America/New_York: `POST /api/admin/jobs/enqueue-macro-snapshot-refresh`
  - weekdays at 16:30 America/New_York: `POST /api/admin/jobs/enqueue-workspace-source-refresh`
  - weekdays at 10:15 America/New_York: `POST /api/admin/jobs/enqueue-continuous-optimizer`

Cloud Run worker pools run a fixed number of instances, not min/max autoscaling.
Set `AGENT_WORKER_INSTANCES`, `ANALYZER_WORKER_INSTANCES`, and
`ONTOLOGY_WORKER_INSTANCES` in `infra/gcp/config.sh` to control warm worker
capacity.

The warm workers preload their job path and poll every `0.25` seconds by
default. Agent workers execute up to `AGENT_WORKER_CONCURRENCY=2` chat turns
per instance, capped at `POSTGRES_POOL_MAX_SIZE`. Analyzer and ontology workers
remain serial. Chat concurrency shares the existing pool; it adds no connections
or worker instances. Follow-up jobs retain their separate serial loop.
Raise `*_WORKER_INSTANCES` only after recalculating the database budget.

Durable chat claims heartbeat every 10 seconds on a separate thread, including
while a model or tool blocks. The API and agent worker independently check every
5 seconds for running claims with no heartbeat for 45 seconds. They fail abandoned
jobs and repair their transcripts, preserving saved partial text. Explicit retries
can create a new job with the same turn id; recovery does not automatically replay
tool calls. Terminal jobs reject late completion and expired workers cannot change
the transcript or publish further events. Transcript repair remains pending until
it succeeds, so recovery itself can safely restart.

`AGENT_JOB_HEARTBEAT_SECONDS`, `AGENT_JOB_LEASE_SECONDS`, and
`AGENT_JOB_RECOVERY_INTERVAL_SECONDS` may shorten those intervals. Values are
capped at 10/45/5 seconds, with heartbeat at most one third of the lease. Use the
same settings for the API and workers; default values require no API override.
Workers draining an older release retain the legacy timeout until they finish;
new claims carry an `agent-lease:` prefix in the existing `claimed_by` column.
No database migration is required. Recovery within a minute assumes a functioning
database and a live API or worker process. See the [local verification runbook](../../docs/agent-worker-recovery.md).
If Cloud Monitoring shows p95 memory approaching roughly 80% of a configured
worker limit, raise the affected `*_WORKER_MEMORY` setting before the next deploy.

The governance outbox drain scheduler is disabled by default because the
runtime job is now a no-op. To recreate it for a temporary safety check, run
`SCHEDULE_GOVERNANCE_OUTBOX_DRAIN=1 ./infra/gcp/setup-scheduler.sh`; override
the cadence with `GOVERNANCE_OUTBOX_DRAIN_SCHEDULE` if needed.

The watch trigger monitor scheduler is disabled by default while its ontology-ID
handling is repaired. The endpoint remains available for manual/admin use, and
can be scheduled with
`SCHEDULE_WATCH_TRIGGER_MONITOR=1 ./infra/gcp/setup-scheduler.sh`; override the
cadence with `WATCH_TRIGGER_MONITOR_SCHEDULE` if needed.

Scheduled cache warming is disabled by default. The cache-warm endpoint remains
available for manual/admin use, and can be scheduled with
`SCHEDULE_CACHE_WARM=1 CACHE_WARM_SCHEDULE="0 * * * *" ./infra/gcp/setup-scheduler.sh`,
but the default deployment does not schedule it because the warmer executes in a
separate Cloud Run Job and does not share the API service's process cache.

Cloud Run services and jobs also set `API_DISK_CACHE_DISABLE=true` through the
shared deployment environment. This disables only `api.cache`'s generic JSON
disk cache for route-level `short_cache` / `long_cache` entries; it does not
disable module-specific durable caches, GCS/Postgres state, or market snapshot
storage. Local development keeps the generic disk cache enabled unless that env
var is set explicitly.

Cloud Scheduler should send both `X-Scheduler-Secret: $SCHEDULER_SECRET` and
`X-Api-Proxy-Secret: $API_PROXY_SECRET` when it calls the API service directly.
The setup script pulls both values from Secret Manager.

Required async env/secrets:

```bash
ASYNC_JOB_BACKEND="cloud_run_jobs"
AGENT_CHAT_DISPATCH_BACKEND="warm_worker"
ASYNC_DISPATCH_BACKEND_ANALYZER="warm_worker"
ASYNC_DISPATCH_BACKEND_SIZER="inline"
ASYNC_DISPATCH_BACKEND_ONTOLOGY="warm_worker"
ASYNC_QUEUE_ANALYZER="analyzer"
ASYNC_QUEUE_SIZER="sizer"
ASYNC_QUEUE_ONTOLOGY="ontology"
ASYNC_CLOUD_RUN_JOB="talisman-async-job"
ASYNC_JOB_COMPLETED_TTL_SECONDS="86400"
ASYNC_JOB_FAILED_TTL_SECONDS="604800"
ASYNC_JOB_STALE_GRACE_SECONDS="300"
SCHEDULER_SECRET="..."
```

### Single execution verification (TL-185)

The race tests cover both analyzer and ontology, both runner orderings, task
retries, eight simultaneous claimers, terminal rows, cancellation after claim,
inline/local dispatch, and migration upgrade/downgrade on existing rows. Run
them against disposable Postgres on a dedicated local port:

```bash
docker run --rm -d --name talisman-tl185-postgres \
  --cpus=1 --memory=600m -p 127.0.0.1:55485:5432 \
  -e POSTGRES_PASSWORD=tl185-local-only -e POSTGRES_DB=tl185_claim \
  pgvector/pgvector:pg16
TEST_ASYNC_POSTGRES_URL='postgresql://postgres:tl185-local-only@127.0.0.1:55485/tl185_claim' \
  .venv/bin/python -m pytest tests/test_async_job_claims.py tests/test_deploy_scripts.py -q
docker stop talisman-tl185-postgres
```

Local measurements on 2026-10-21 compared base `881ff0ab` with TL-185 using
the same Postgres 16 container, two-connection pool, no provider calls, and
the default 250 ms warm poll interval. Each of three trials ran 20 races per
type/order and 20 idle-queue start samples per type with the same arrival seed.

| Measurement | Before | After |
| --- | ---: | ---: |
| Warm runner first, each type: compute / completion calls for 60 jobs | 120 / 120 | 60 / 60 |
| Cloud Run runner first, each type: compute / completion calls for 60 jobs | 60 / 60 | 60 / 60 |
| Analyzer warm start p95, range across trials | 242–248 ms | 238–245 ms |
| Ontology warm start p95, range across trials | 240–243 ms | 239–244 ms |

These warm measurements check claim overhead with an idle queue. The default
dispatch now selects this warm path and avoids launching a Cloud Run task for
these queues. After rollout, compare `async_jobs.started_at - created_at` for
equivalent analyzer traffic windows and confirm the production start target
below one second. Queue backlog and worker startup affect that measurement;
local results do not establish production latency.

The API service account needs `roles/run.jobsExecutorWithOverrides` on the async
Cloud Run Job because dispatch passes `ASYNC_JOB_ID` as a per-execution env
override. `iam.sh` applies that binding after the job exists.

## Database Migrations

Run Alembic with the migration URL:

```bash
DATABASE_URL="${DATABASE_URL_MIGRATION}" alembic upgrade head
```

The retrieval schema is pinned to all-MiniLM-L6-v2:

- `retrieval_chunks.embedding vector(384) not null`
- HNSW cosine index: `USING hnsw (embedding vector_cosine_ops)`

## Source Snapshot

After freezing writes, create the source tarball locally or on the old runtime:

```bash
python3 -m api.gcp_state_migration snapshot \
  --project-root . \
  --output /tmp/source.tar.zst
```

Upload it to:

```bash
gs://$GCS_STATE_BUCKET/backups/pre-migration/$MIGRATION_RUN_ID/source.tar.zst
```

The snapshot command copies each SQLite DB plus `-wal` and `-shm` siblings, runs
`PRAGMA wal_checkpoint(TRUNCATE)` on the copy, and then reads from a `VACUUM INTO`
compact snapshot.

## Migration Job

The Cloud Run Job entrypoint should be:

```bash
python3 -m api.gcp_state_migration migrate
```

Required env/secrets for the migration job:

```bash
DATABASE_URL="$DATABASE_URL_MIGRATION"
GCS_STATE_BUCKET="talisman-state-prod"
MIGRATION_RUN_ID="YYYYMMDDTHHMMSSZ"
ENVIRONMENT="production"
STATE_STORAGE_BACKEND="gcs"
```

The migration service account should have only:

- `roles/cloudsql.client`
- Secret accessor for `DATABASE_URL_MIGRATION`
- GCS access to `backups/pre-migration/**` and the live destination prefixes

It should not have LLM or data-vendor secrets.

## Cutover Checks

Before migration:

- Deploy old API with `WRITE_FREEZE=true`.
- Disable scheduled report workflows.
- Verify `GET /api/admin/quiescence` returns `write_freeze=true`, `active_jobs=0`, `pending_writes=0`.

After migration:

- Cloud Run `/api/health` is healthy.
- Firebase frontend loads and authenticates.
- Thesis and overview writes land in `live/theses/**` and `live/overviews/**`.
- Async jobs persist status in `async_jobs`.
- `ENVIRONMENT=production` direct writes under project root raise `ProductionLocalWriteError`.

## Deploy Smoke Tests (SHA-34)

The smoke runner authenticates against the live API using a dedicated smoke
password (separate from the normal admin password) and probes multiple endpoints.
Run it explicitly after deploying, with the expected image tag.

### Required Secrets

`setup-secrets.sh` creates two paired secrets:

- `AUTH_SMOKE_PASSWORD` — plaintext password used by the deploy runner. **Not
  bound to any service account** (only the deploy operator accesses it).
- `AUTH_SMOKE_PASSWORD_HASH` — bcrypt hash bound to `API_SA`. The API reads
  this to authenticate smoke logins (subject `smoke`).

To rotate: delete both secrets and re-run `setup-secrets.sh`:

```bash
gcloud secrets delete AUTH_SMOKE_PASSWORD --project=${PROJECT_ID}
gcloud secrets delete AUTH_SMOKE_PASSWORD_HASH --project=${PROJECT_ID}
./infra/gcp/setup-secrets.sh
```

### Default Behavior

`deploy-backend.sh` does not run smoke tests automatically. A backend rollout
ends after deploying the API service and the requested infrastructure syncs:

```bash
./infra/gcp/deploy-backend.sh
```

Run smoke manually when you want a live diagnostic:

```bash
EXPECTED_IMAGE_TAG=<deployed-tag> ./infra/gcp/run-backend-smoke.sh
```

For the dedicated `smoke` account, which has viewer access, select the viewer
profile explicitly:

```bash
AUTH_DEFAULT_USERNAME=smoke SMOKE_AUTH_PROFILE=viewer EXPECTED_IMAGE_TAG=<deployed-tag> \
  ./infra/gcp/run-backend-smoke.sh
```

This profile verifies login, the session's unprivileged viewer role, workspace
reads, and required 403 responses from approval and admin diagnostics. It does
not execute the admin-only database and migration invariant checks. The default
admin profile still requires those checks to succeed. Login sends the same
request schema headers as the frontend.

### Manual Post-Rollback Smoke

After a manual rollback, run smoke tests against the rolled-back tag:

```bash
SMOKE_MODE=post-rollback EXPECTED_IMAGE_TAG=<rolled-back-tag> \
  ./infra/gcp/run-backend-smoke.sh
```

### Smoke Checks

The default admin profile performs these required checks:

1. `GET /api/health` — expects 200, `status=ok`, matching `release.image_tag`
2. `POST /api/auth/login` — authenticates with the smoke password
3. `GET /api/auth/me` — proves the session token works
4. `GET /api/workspace` — proves core read-model route returns expected keys
5. `GET /api/approvals/summary?limit=1` — proves approval read path is available
6. `GET /api/admin/deploy-smoke` — checks Postgres, migration head, read-model,
   and action/approval invariants

### Admin Deploy Smoke Endpoint

`GET /api/admin/deploy-smoke` (requires auth) runs backend invariant checks:

- **postgres**: Postgres connectivity via `SELECT 1`
- **migration_head**: Alembic version matches `TALISMAN_RELEASE_MIGRATION_HEAD`
- **read_model**: Temporal ontology read service is queryable
- **action_approval_safety**: Action/approval command service is available

Returns 200 when all pass, 503 with `failed_checks` array on any failure.

### Failure Triage

| Symptom | Likely Cause |
|---------|-------------|
| Health/release mismatch | New revision not fully rolled out; retry in 30s |
| Login/proxy secret failure | `AUTH_SMOKE_PASSWORD` or `API_PROXY_SECRET` out of sync; re-run `setup-secrets.sh` |
| Migration mismatch | Alembic upgrade didn't complete; check migration job logs |
| Read-model failure | Ontology DB tables missing or Postgres pool exhausted |
| Approval safety failure | Command service initialization error; check API logs |
