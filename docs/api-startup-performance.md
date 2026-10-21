# API startup (TL-186)

API import performs no schema seeding or database connections. Sentry keeps the
explicit Logging, FastAPI and Starlette integrations and its default error hooks;
integration auto-discovery is disabled. Anthropic, OpenAI and Gemini integrations
are no longer loaded automatically. Existing application chat measurements remain
available; automatic provider-specific Sentry spans require explicit setup.

Pandas, NumPy, the agent tool registry and market-data implementations load only
when used. The API lifespan warms these dependencies before accepting requests.
Cloud Run's HTTP startup probe calls `/api/health` only after this warmup succeeds.
A failed warmup fails startup. This moves deferred import work ahead of readiness
rather than making the first user request pay for it.

## Capacity and cost

The API defaults to one minimum instance, retains the existing two-instance cap,
enables startup CPU boost, and explicitly keeps request-based CPU throttling.
`API_MIN_INSTANCES` remains an override; setting it to zero permits scale-to-zero.

For one idle revision at the example region (`us-central1`), 1 vCPU and 1 GiB,
the published on-demand rates checked on 2026-10-21 give:

```text
730 hours × 3,600 × (1 × $0.0000025 CPU + 1 × $0.0000025 memory) = $13.14/month
```

This is a gross idle estimate before free-tier credits or discounts. Active
requests, startup CPU boost, request counts and network charges are additional.
Multiple revisions kept warm can cost more. CPU boost raises the 1-vCPU startup
allocation to 2 vCPUs through startup and the following 10 seconds.

Sources: [Cloud Run pricing](https://cloud.google.com/run/pricing),
[minimum instances](https://docs.cloud.google.com/run/docs/configuring/min-instances),
[startup CPU boost](https://docs.cloud.google.com/run/docs/configuring/services/cpu#startup-boost).

## Migration ownership

Routine backend deploys execute `python -m api.migrate` in the existing migration
job before deploying the API image. The runner applies `alembic upgrade head`,
then transactionally upserts ontology, action and API request definitions using
the existing schema registry writer. It seeds on every migration-job execution,
including when Alembic is already at head, so route changes are registered without
an otherwise unnecessary numbered migration. Seeding is idempotent; failures or
degraded routers fail the job and prevent the API rollout.

The migration job's separate one-time state-copy command remains unchanged.
Operators using `RUN_DB_MIGRATIONS=0` must run `python -m api.migrate` from the same
image before promoting API changes that introduce schema definitions.

## Local measurements

Measured on the same Mac with Python 3.12 and dependencies installed using
`requirements-dev.txt` constrained by `requirements-lock.txt`. The original
`881ff0ab` source was extracted inside the worktree for comparison. Each process
used `-X importtime`, the same virtual environment, isolated local SQLite state,
and Sentry enabled with a fake DSN and a discarding transport. No provider or cloud
requests were made. The old boot-time SQLite seed is included; production database
network latency is not. One warmup per version preceded five alternating pairs;
these are fresh Python processes with a warm filesystem, including process exit.

| Repeated paired run | Before | After |
| --- | ---: | ---: |
| Median elapsed | 3.538 s | 1.406 s |
| Elapsed range | 3.408–9.213 s | 1.301–1.465 s |
| Median process CPU | 5.003 s | 1.259 s |

The median elapsed reduction was 60%; every updated sample was below 2.5 s.
Other agents were active on the machine. An earlier contended paired batch had
medians of 6.019 s before and 3.879 s after, with an updated range of 2.250–7.544 s.
Both batches showed reduced CPU consumption; wall-clock thresholds remain
sensitive to host contention. No application tests ran concurrently with either
measurement batch.

The exact import can also be inspected without loading local credentials:

```bash
PYTHON_DOTENV_DISABLED=1 SENTRY_ENABLED=false DATABASE_URL= \
  .venv/bin/python -X importtime -c "import api.main"
```

`tests/test_api_startup.py` checks a fresh process both with and without Sentry:
all routers remain healthy, heavy dependencies remain deferred until lifespan,
no database connection is attempted, and the single `cold_start` observation
belongs to the health probe before a subsequent API request. Serializer, workflow,
signal, risk, schema registry and deployment tests cover the affected behavior.

## Combined rollout verification

Local implementation does not establish production cold-start acceptance. After
the combined release is deployed through the normal migration/deploy sequence,
use the same representative release/time window as the performance baselines:

1. Inspect the actual revision's minimum instances, CPU boost and HTTP startup
   probe. Confirm migrations and seeding completed for that image.
2. Confirm new instances' `cold_start` logs have `first_response_is_probe=true`.
   Filter `resource.type="cloud_run_revision"`, the API service, the release,
   `jsonPayload.event="cold_start"`, and
   `jsonPayload.first_response_is_probe=false`; retain the count and time window.
3. Compare client/API request latency and Cloud Run platform startup latency with
   the baseline. A probe being first does not rule out requests queued during a
   scale-out. Minimum instances reduce scale-from-zero latency but can restart
   and do not guarantee warm capacity for every possible burst.
4. Record sample counts and require zero user-facing cold-start observations in
   the representative window before claiming the production criterion is met.
