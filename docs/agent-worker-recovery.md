# Durable chat worker concurrency and recovery (TL-211)

Agent worker instances run two chat turns concurrently by default. Execution
slots are capped at `POSTGRES_POOL_MAX_SIZE`, so the existing two-connection
worker pool and one-instance deployment retain their connection budget. The
analyzer, ontology, and companion follow-up loops remain serial.

## Failure handling

Each new chat claim stores `agent-lease:<uuid>` in the existing `claimed_by`
column. Its runner renews `updated_at` every 10 seconds on a separate thread,
including while a provider or tool is blocked. Both API lifespan and worker
startup start an independent recovery loop. Every five seconds it conditionally
fails running claims whose last renewal is at least 45 seconds old. A healthy
renewal or completion cannot match that update. Old workers draining during a
rollout have unprefixed claims and retain the existing timeout behavior.

Recovery fails the job rather than automatically repeating tool calls. It marks
the matching streaming transcript turn `failed`, keeps its saved partial text,
and records a replayable error event. A small `progress_json` marker keeps this
repair pending until it succeeds. Repeating repair cannot duplicate the error
event or change a completed transcript; an explicit newer retry takes precedence.
An explicit retry can create a new job with the same `client_turn_id` and cache
key after the failed job has released active deduplication.

Terminal chat jobs reject late completion/failure updates. The worker's claim
travels through the stream's context, and transcript writes lock and check it
inside their transaction. Expired workers cannot overwrite the recovered
transcript or append more output. Background partial writes carry the same
context. These checks require no new columns or migrations.

The 45-second lease plus five-second scan targets recovery within 50 seconds
with an available database and at least one API or worker process alive. During
a complete API/worker outage, repair resumes on startup. Database unavailability
also delays repair; pending transcript repair is retried after connectivity
returns. Queued work retains its existing overall timeout.

## Verification

Regression tests in `tests/test_agent_worker_recovery.py` exercise the memory
fallback and an isolated PostgreSQL schema: two simultaneous jobs with a third
waiting, blocked-provider heartbeats, stale snapshots, expired-worker output,
terminal-state preservation, retry after failure, restartable repair, duplicate
reapers, cancellation between claim and execution, and legacy claims during a
rollout.

Use a disposable local PostgreSQL database with pgvector. The benchmark accepts
only `TEST_POSTGRES_URL` with a local host/socket; it never loads `.env` or falls
back to the application's `DATABASE_URL`. Each sample creates and drops its own
schema. Run from the TL-211 worktree:

```bash
TEST_POSTGRES_URL='postgresql://postgres@127.0.0.1:55411/tl211_tests' \
  .venv/bin/python -m scripts.benchmark_agent_worker_recovery \
  --baseline-ref 4fe6f6c20 --repeats 5 --crash-repeats 3 --seconds 2 \
  --output outputs/tl211-worker-recovery.json
```

The benchmark loads the baseline runner, worker loop, and chat worker from Git
in the same checkout, using the compatible current storage helpers. Both cases
use a warmed two-connection pool, the same isolated database, and the real
claim/execute/SSE-event/transcript paths. A synthetic provider writes a partial
answer, blocks for two seconds without emitting events, then completes. Five
paired-workflow repetitions alternate before/after ordering and record overlap,
queue delay, total pair duration, checkout p95, checkout errors, and pool size.

Three additional repetitions per case send SIGKILL to the worker after it saves
partial text. The after case uses the same independent recovery loop as the API;
no worker shutdown or `finally` handler can repair a killed process. The before
case observes the legacy polling behavior for 60 seconds. It does not wait out
the full 21-minute timeout. All process-kill checks use the default lease and
recovery intervals.

These are local scheduling and persistence measurements. They exclude real
model/provider latency, browser rendering, and production resource contention.
Normal production throughput and memory usage still need observation after the
shared performance release is deployed.
