# Reuse notes (PR-08)

Components adapted from Talisman are listed here with origin and changes. Nothing in
this package imports Talisman at runtime.

| Package path | Origin (Talisman) | Decision | Adaptations |
| --- | --- | --- | --- |
| `backend/migrations/env.py` | `migrations/env.py` | Pattern only | Reads `DATABASE_URL` / `DATABASE_URL_MIGRATION`; rewrites `postgresql://` → `postgresql+psycopg://`; binds `target_metadata` to Longaeva `Base.metadata`. |
| `backend/Dockerfile` | `Dockerfile` | Pattern only | Same `python:3.12-slim` digest and non-root user pattern; install layer cached before app copy; workdir layout `/srv/longaeva/backend` so LON-1 `PACKAGE_ROOT = parents[3]` still resolves. |
| Job queue status model | `api/job_queue.py`, `api/async_job_runner.py` | Pattern only | Postgres table + `FOR UPDATE SKIP LOCKED` claim; single polling worker; no in-memory Talisman job runner and no app imports. |
| `backend/longaeva_app/storage/local.py` | `api/state_storage.py` | Pattern only | Local atomic write (`tempfile` + `os.replace`), directory layout under `ARTIFACT_DIR`; no GCS branch and no Talisman project write-guard import. Keys are relative POSIX paths only. |
| Source publication vs retrieval timestamps | `ontology/temporal_repository.py` (`SourceRecordWrite`) | Pattern only | Valid-time / transaction-time split maps to required `publication_ts` / `retrieval_ts` on `source` (CHECK `publication_ts < retrieval_ts`); no ontology versioning tables. |
| Content-addressed originals + SHA-256 | `ontology/source_ingestion.py` | Pattern only | `LocalArtifactStore.put_original` stores under `originals/<ab>/<sha256>`; collector dedups on `source.content_hash`. No Talisman ontology imports. |
| PDF/HTML text extraction | `ontology/extractors/deterministic.py::_extract_text` | Pattern only | pdfminer.six `extract_pages` with no page/character caps; HTML via stdlib `HTMLParser` with CSS page-break splits. Adapted without Talisman's 25-page limit. |

Later issues will extend this file when chart components, evidence UI, and action-cost
arithmetic are copied (LON-11, LON-26, LON-35).
