# Reuse notes (PR-08)

Components adapted from Talisman are listed here with origin and changes. Nothing in
this package imports Talisman at runtime.

| Package path | Origin (Talisman) | Decision | Adaptations |
| --- | --- | --- | --- |
| `backend/migrations/env.py` | `migrations/env.py` | Pattern only | Reads `DATABASE_URL` / `DATABASE_URL_MIGRATION`; rewrites `postgresql://` → `postgresql+psycopg://`; binds `target_metadata` to Longaeva `Base.metadata`. |
| `backend/Dockerfile` | `Dockerfile` | Pattern only | Same `python:3.12-slim` digest and non-root user pattern; install layer cached before app copy; workdir layout `/srv/longaeva/backend` so LON-1 `PACKAGE_ROOT = parents[3]` still resolves. |
| Job queue status model | `api/job_queue.py`, `api/async_job_runner.py` | Pattern only | Postgres table + `FOR UPDATE SKIP LOCKED` claim; single polling worker; no in-memory Talisman job runner and no app imports. |

Later issues will extend this file when chart components, evidence UI, and action-cost
arithmetic are copied (LON-11, LON-26, LON-35).
