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
| `backend/longaeva_app/extract/providers.py`, `extract/schemas.py` | `llm_utils.py` provider calls and `_openai_strict_json_schema` / `_gemini_response_schema` | Pattern only | httpx adapters for Anthropic Messages (forced tool), OpenAI Responses (strict JSON schema), and Gemini `generateContent` (response schema). Schema converters copied and narrowed to the extraction object. No Talisman import, no new dependency. |
| `frontend/src/styles/theme.css` | `frontend/src/index.css` | Copy + adapt | Light/dark CSS variables, `theme-*` layout/button/badge classes, and text utilities. Dropped Talisman gray-remap shims, portfolio editor, slider, Sentry/theme localStorage. |
| `frontend/src/components/shared/SurfaceCard.tsx` | `frontend/src/components/shared/SurfaceCard.tsx` | Copy + adapt | Same surface classes; local `cx` join instead of `clsx` / `tailwind-merge`. |
| `frontend/src/components/shared/ChartTile.tsx` | `frontend/src/components/shared/ChartTile.tsx` | Copy + adapt | Title/subtitle/meta card; `Link` from this package's `react-router-dom`, not Talisman's router. |
| `frontend/src/components/charts/TimeSeriesChart.tsx` | `frontend/src/components/shared/TimeSeriesChart.tsx` | Copy + adapt | Multi-series lines, legend toggles, Recharts styling via CSS variables. Added `xKey` + `category` mode for fiscal-period labels (no `Date` parse). Dropped `calcReturn`. |
| `frontend/vite.config.ts`, `tsconfig*.json`, `eslint.config.js` | `frontend/` counterparts | Pattern only | Vite 8 + React plugin + Tailwind 4 plugin; `@` → `src`; `/api` proxy strips the prefix to match nginx. No Sentry, axios, or TanStack Query. |
| `frontend/src/lib/api.ts` | — | New | Plain `fetch` client. No auth, CSRF, or Sentry. |
| `frontend/src/components/charts/FanChart.tsx` | — | New | Nested quantile bands (5–95 / 10–90 / 25–75) plus median and mean. |
| `frontend/src/components/charts/PairedDiffChart.tsx` | — | New | Path-wise difference quantiles around a zero line. Not mounted until difference summaries exist. |
| `backend/longaeva_app/valuation/actions.py` | `portfolio/scenario_simulator.py` `_apply_delta`, `_traded_notional`, `_execution_friction` (lines 357–518); tests `tests/test_scenario_simulator.py` | Copy + adapt | Percent-of-position sizing only (hold/add/trim/exit). Costs are transaction, slippage, impact, and funding. Funding applies only to added notional over the configured holding period. Dropped the ADV cap, policy gate, ontology writeback, and scenario P&L. The rule is `config/decision_rule.yaml`, hashed with `content_hash`. |

Later issues will extend this file when evidence UI is copied.

## LON-35 evidence and review

The evidence-card hierarchy (source metadata, status, and a detail action) was
adapted from Talisman's `frontend/src/components/shared/EvidenceLedgerPanel.tsx`.
The Longaeva implementation was rewritten around its own observation, review,
search, and mapping contracts; it imports no Talisman components or contexts.
Source excerpts reuse Longaeva's LON-34 server resolver and shared evidence view.
