# Longaeva implementation plan — planning v1

October 1, 2026 · Phase 2 draft for review · Requirements: [requirements.md](requirements.md). Data: [data-plan.md](data-plan.md). Issues: [linear-backlog.md](linear-backlog.md). Nothing here has been implemented; no directory, repository, export or dependency has been created.

## 1. Architecture

### 1.1 Shape

A self-contained directory, provisionally `longaeva/` inside this checkout, whose contents are the root of the submission ZIP or a fresh repository. It runs with one command via Docker Compose (PostgreSQL, API, worker, web) and also supports a documented local-process mode (Python venv + Node) for development. No runtime dependency on any Talisman module, database, auth, portfolio state, cloud account or deployment setting (PR-01, PR-02).

```
longaeva/
  README.md                      quickstart, one startup command, demo script link, limitations
  LICENSE-NOTES.md               third-party and data attribution pointers
  .env.example                   DATABASE_URL, ARTIFACT_DIR, LLM_PROVIDER (optional), provider keys (optional), SEC_USER_AGENT
  docker-compose.yml             db (postgres:16), api, worker, web; healthchecks; demo seed on first start
  Makefile                       make up / make check / make seed / make replay RUN=... / make export / make verify-export
  backend/
    pyproject.toml, requirements.txt, requirements.lock
    alembic.ini, migrations/
    longaeva_app/
      api/        FastAPI app, routers: sources, documents/search, observations, review, parameters, scenarios, runs, forecasts, valuation, actions, evaluation, health
      db/         SQLAlchemy models, session, repositories
      storage/    local artifact store (originals, run outputs, reports) under ARTIFACT_DIR
      worker/     job table polling worker (Postgres-backed queue), job handlers
      collect/    manifest-driven collector (EDGAR, Census, IR PDFs, benchmark fetchers)
      extract/    table parsers (Visa release/10-Q, Booking, Census PDF), LLM extraction with Pydantic schemas and cache
      review/     review decisions, mapping-rule application, parameter-set versioning
      companies/  base interface + visa/ (state, transitions, revenue rules, incentives, opex, interventions, ablation switches)
      engine/     correlated shock sampler, path runner, summaries, replay, hashing
      valuation/  earnings bridge, multiples, action/cost arithmetic (adapted from Talisman)
      evaluation/ origins, leakage guard, baselines, scoring, ablations, portfolio scoring, report builder
      cli.py      seed-demo, replay, evaluate, export-check
    tests/        unit, property, integration (API→worker→DB), guard tests
  frontend/
    package.json, package-lock.json, vite.config.ts, tsconfig*.json, index.html
    src/
      lib/api.ts (plain fetch client, no auth/CSRF), lib/format.ts
      components/charts/ (TimeSeriesChart adapted, FanChart new, PairedDiffChart new), components/evidence/, components/review/, components/scenario/, components/valuation/, components/evaluation/
      pages/ StateAndEvidence, Scenarios, ValuationActions, Evaluation, Replay
      styles/ theme tokens copied from Talisman CSS variables
  data/
    manifest/                    YAML source manifests (Visa, Booking, Census, gate families, benchmarks)
    originals/                   bundled public-domain originals for the demo (SEC, Census)
    fixtures/                    reconciled starting states, extraction eval set, origin table
    demo/                        saved runs, parameter sets, forecasts for replay without LLM
  docs/
    model-spec.md, evaluation-report.md, data-licenses.md, demo-script.md, limitations.md, reuse-notes.md
  scripts/
    export_submission.sh         builds ZIP from an exclusion manifest; no .git from Talisman
    verify_export.sh             unpack to temp dir outside Talisman, run guard tests, compose up, smoke, replay check
```

### 1.2 Core records (proposal p. 4, FR-01/03/06/09/17)

- `source` (id, provider, company, doc_type, url, publication_ts, retrieval_ts, period_start/end, content_hash, original_path, license_note, supersedes_id)
- `document_text` (source_id, page, char_start, char_end, text, tsvector)
- `observation` (id, source_id, span, statement_type, activity_type, geography, period, value, range_low/high, unit, basis, source_family, extractor_id, extractor_version, review_status)
- `review_decision` (observation_id, decision, corrected_payload, rationale, decided_at, decided_by)
- `mapping_rule` (id, version, input_type, target_parameter, transform, rationale) and `parameter_update` (rule_id, observation_ids, before, after, size, parameter_set_id)
- `parameter_set` (id, cutoff_ts, company, values/ranges JSON, evidence links, assumption flags, content_hash, parent_id)
- `scenario` (id, parameter_set_id, interventions JSON, pair_group_id)
- `run` (id, scenario_id, cutoff_ts, source_manifest_hash, parameter_set_hash, code_version, seed, n_paths, lib_versions, status, outputs_path, outputs_hash)
- `forecast` (id, run_id, origin_ts, target_period, metric, quantiles, kind ∈ {retrospective, prospective}, created_at, immutable)
- `evaluation_result` (id, suite_version, origin_ts, model_variant, metric, value, config_hash)
- `job` (id, type, payload, status, started/finished, error)

### 1.3 Numerical engine (MR-*)

Pure Python + NumPy; pandas for history alignment; SciPy for constrained fitting. Per quarter: sample correlated factors (demand, travel, FX) from a seeded generator → activity indices (PV, cross-border ex-intra-Europe, transactions) → category revenue (service from PV_{t−1}; data processing from TXN_t; international from CB_t × FX/yield factor; other by rule) → incentives (intensity × gross revenue) → recurring opex → operating profit. Interventions are transformations of the path inputs: mix shift rescales cross-border vs domestic components so Σ equals baseline per path/quarter; total-spend reduction scales PV. Ablation switches: `external_commentary=False` rebuilds the parameter set without external-family updates; `pool_mix=True` replaces the two spending components by one growth driver; `service_lag=False` uses PV_t for service revenue. Paired runs share the random draws by seeding the same generator and consuming draws in the same order.

### 1.4 Jobs and replay

Postgres-backed job table; a single worker process polls it (adapting the dispatch/hash patterns from Talisman's job code without importing it). `replay` loads the run record, re-resolves the parameter set and manifest by hash, reruns the engine with the stored seed and compares output hashes. No LLM is involved in a replay; extraction results are inputs persisted in the database.

### 1.5 Frontend

Vite + React + TypeScript + Recharts (matching Talisman versions where practical: React 19, Recharts 3, Vite 8, Tailwind 4). Pages: State & Evidence, Scenarios, Valuation & Actions, Evaluation, Replay. Plain `fetch` client; no auth, CSRF, Sentry or router-protected areas.

## 2. Reuse / adapt / new map (PR-08)

| Talisman source | Decision | What is copied/adapted | Why not import |
| --- | --- | --- | --- |
| [TimeSeriesChart.tsx](/Users/shaivpandya/Desktop/talisman/frontend/src/components/shared/TimeSeriesChart.tsx) | Copy + adapt | Multi-series line chart, tick logic, legend toggles; add quantile band (FanChart) as a new sibling | Depends only on React/Recharts and CSS variables; CSS variables copied into `styles/` |
| [ChartTile.tsx](/Users/shaivpandya/Desktop/talisman/frontend/src/components/shared/ChartTile.tsx), SurfaceCard | Copy + adapt | Card layout without `react-router` `Link` dependency or with the package's own router | Small, portable |
| [EvidenceLedgerPanel.tsx](/Users/shaivpandya/Desktop/talisman/frontend/src/components/shared/EvidenceLedgerPanel.tsx) | Adapt pattern only | Claim → supporting evidence list with source quality badges; rewrite against the package's observation/review types | Imports `DecisionTraceContext`, `TraceTriggerButton`, `@/lib/api` types |
| [api.ts](/Users/shaivpandya/Desktop/talisman/frontend/src/lib/api.ts) | New | Plain fetch client | Auth/CSRF coupling |
| [scenario_simulator.py](/Users/shaivpandya/Desktop/talisman/portfolio/scenario_simulator.py) `_apply_delta`, `_normalize_execution_assumptions`, `_traded_notional`, `_execution_friction` (lines 357–518) | Copy + adapt | Action sizing and cost arithmetic (transaction, slippage, impact, funding) | Module imports portfolio exposure and policy infrastructure (lines 12, 769) |
| [tests/test_scenario_simulator.py](/Users/shaivpandya/Desktop/talisman/tests/test_scenario_simulator.py) | Adapt | Fixture style for cost arithmetic tests | n/a |
| [evidence_ledger.py](/Users/shaivpandya/Desktop/talisman/ontology/evidence_ledger.py), [temporal_repository.py](/Users/shaivpandya/Desktop/talisman/ontology/temporal_repository.py) `SourceRecordWrite` | Adapt pattern | Separate valid-time vs transaction-time fields; evidence/citation linking shape | Bound to Talisman's ontology repository and app settings |
| [source_ingestion.py](/Users/shaivpandya/Desktop/talisman/ontology/source_ingestion.py) | Pattern only | Content hashing, original retention; replace ingestion-time `as_of` with explicit publication_ts/retrieval_ts | Sets `as_of`/`valid_from` to upload time (line 194) |
| [deterministic.py](/Users/shaivpandya/Desktop/talisman/ontology/extractors/deterministic.py) `_extract_text` | Adapt | pdfminer text extraction; remove 25-page/2,000-char limits; keep page spans | Limits unsuitable |
| [job_queue.py](/Users/shaivpandya/Desktop/talisman/api/job_queue.py), [async_job_runner.py](/Users/shaivpandya/Desktop/talisman/api/async_job_runner.py) | Pattern only | Job status model and dispatch loop shape | In-memory local jobs; app imports |
| [state_storage.py](/Users/shaivpandya/Desktop/talisman/api/state_storage.py) | Pattern only | Local artifact directory layout and hashing | Imports local write guard (line 14) |
| [dcf.py](/Users/shaivpandya/Desktop/talisman/equities/valuation/dcf.py) | Not reused | Earnings/multiple bridge is new | Requires 5–8 annual projections and live yfinance inputs (line 841) |
| [eval_runner.py](/Users/shaivpandya/Desktop/talisman/decision_quality/eval_runner.py) | Pattern only | Fixture/hash conventions for evaluation artifacts | Grades agent behavior, not forecasts |
| Dependency manifests ([requirements.txt](/Users/shaivpandya/Desktop/talisman/requirements.txt), [frontend/package.json](/Users/shaivpandya/Desktop/talisman/frontend/package.json)) | Reference | Version pins for FastAPI, SQLAlchemy 2, Alembic, psycopg 3, httpx, pdfminer.six, React 19, Recharts 3, Vite 8 | Package has its own locks |
| Repository `.cursor/rules` | Noted | Instructs cloud agents to commit to the current branch; superseded for this task by the user's "do not commit" instruction | n/a |

New work (no Talisman precedent): Visa quarterly engine, correlated sampler, mapping rules and review, parameter-set versioning, immutable forecast archive, evaluation suite (origins, leakage guard, baselines, ablations, scoring, portfolio scoring), valuation bridge, release/10-Q/Census table parsers, LLM structured extraction with cache, fan/paired charts, review UI, export/verify scripts.

## 3. Milestones and calendar (October 1–9, 2026; America/New_York)

The deadline time and submission format are unresolved; the calendar assumes end of day October 9 and keeps October 9 as buffer. Dates are sequencing targets, not staffing claims.

| Milestone | Target | Contents | Exit check |
| --- | --- | --- | --- |
| M0 Gates and skeleton | Oct 1–2 | DRAFT-01…08 feasibility gates in parallel with DRAFT-09…11, 13 bootstrap | Gate artifacts written; `docker compose up` healthy on an empty DB; guard test exists |
| M1 First vertical slice | Oct 3–4 | DRAFT-14, 15, 20, 24, minimal run page in DRAFT-10; then DRAFT-12 early export rehearsal | One dated state → one reviewed external observation (manually entered if DRAFT-17 not ready) → paired runs; export validated in a temp dir outside Talisman |
| M2 Evidence, model, evaluation core | Oct 5–6 | DRAFT-16, 17, 18, 21, 22, 23, 25, 26, 28, 29 | Extraction → review → parameter set → run; evaluation harness scores the full model and two baselines on eligible origins |
| M3 Completion | Oct 7 | DRAFT-19, 27, 30, 31, 32, 34, 35, 36 | All baselines, ablations, benchmarks, UI pages; prospective forecast registered |
| M4 Report and package | Oct 8 | DRAFT-33, 37, 38, 39 | Evaluation report, model spec, demo bundle; final export validated |
| Buffer / submit | Oct 9 | Fixes; submission in the organizer's format once known | — |

## 4. Dependencies and critical path

Critical path: DRAFT-01/02/03 (Visa definitions and reconstructable states) → DRAFT-15 (Visa parser) → DRAFT-20/21 (engine, calibration) → DRAFT-28 (evaluation harness) → DRAFT-29/30/31 (baselines, ablations) → DRAFT-33 (report) → DRAFT-38 (final export). Parallel tracks: standalone bootstrap (09–13) with gates; Census/Booking parsers (16, 04/05) with the engine; UI (34–36) once run and evidence APIs exist; valuation/actions (25–27) after the engine summary format is fixed and DRAFT-06 is decided.

Data feasibility work that must precede dependent modeling: DRAFT-01, 02, 03 before DRAFT-20 is finalized (engine can start on synthetic fixtures); DRAFT-04/05 before DRAFT-22 mapping rules for those families; DRAFT-06 before DRAFT-27; DRAFT-07 before the guidance baseline in DRAFT-29.

Cycle check: dependencies in the backlog form a DAG (feasibility → data → model → evaluation → report → export; bootstrap is a parallel root; UI depends on APIs only). No issue depends on a later-numbered issue except where explicitly noted (DRAFT-12 depends on DRAFT-14/15/20/24; DRAFT-10's minimal run page depends on DRAFT-24's API shape, resolved by fixing the run API contract in DRAFT-11).

## 5. Effort

Issue-level ranges are summed in the backlog: **MVP 168–263 hours** (gates 26–39; bootstrap 22–36; collection/extraction 27–43; engine 28–44; valuation/actions 13–20; evaluation 22–35; UI 19–29; packaging/demo 11–17). This supersedes approach v2's area-level 110–186 estimate; the increase comes from itemizing the gated second-wave disclosure families, the extraction evaluation set, the isolation guard, the LLM baseline and two export validations. No staffing count or spend limit is assumed. Over eight calendar days this volume is a scheduling risk; if it threatens a commitment, the specific shortfall will be raised for decision rather than cut silently.

Assumptions: experienced builders plus coding agents executing bounded issues; curated corpus (tens of documents per family, not thousands); local containers; CPU-only numerics; LLM extraction calls bounded and cached.

## 6. Evaluation plan (ER-*)

1. **Correctness suites (continuous):** accounting identities per path (ER-01); starting-state reconciliation to original exhibits at two cutoffs (ER-02); replay hash equality (ER-03); leakage guard with deliberately late documents (ER-04).
2. **Origins:** from DRAFT-01's `origins.csv`; cutoff convention per data plan §2.3; eligible count and exclusions reported.
3. **Fitting:** chronological, at each origin using only publication ≤ cutoff; model choices and decision thresholds frozen (config hash recorded) before scoring.
4. **Metrics:** absolute and percentage errors for next-quarter net revenue, operating profit (declared basis), driver growth rates; 80% interval coverage; CRPS or WIS (ER-05/06). Four-quarter path scoring reported separately (ER-13).
5. **Baselines:** seasonal/trend; financial-only driver model; LLM given the same dated documents with the same horizon and scoring; guidance where comparable, made probabilistic with a prior-data residual distribution (ER-07).
6. **Ablations:** three, each rebuilding inputs and rerunning all origins; persistence across origins and parameter ranges (ER-08).
7. **Extraction errors:** ≥ 40 labeled items; error rates by type, separate from model error (ER-09).
8. **Prospective:** register the 2026-07-28 origin forecast for Q4 FY2026 before the late-October release; store as `prospective` (ER-10).
9. **Portfolio scoring (conditional on DRAFT-06):** fixed rule and horizon frozen before scoring; entry at the first eligible session after cutoff; explicit costs; dividends; overlapping forecasts handled; excess return vs the labeled benchmark and vs Visa buy-and-hold; drawdown and exposure; labeled exploratory (ER-11).
10. **Failure case:** chosen from results, documented with invalidating conditions (ER-12).
11. **Disclosures:** hindsight and pretrained-model limitations; actual counts; what was not verified.

## 7. Demo and submission plan

**Demo (docs/demo-script.md):** open saved Visa state at the 2026-04-28 origin → show a starting value's source span → open a Booking passage and its reviewed observation → accept a ranged travel-factor update → run paired scenarios (mix shift with conserved total; total-spend reduction) → compare distributions and the service-lag timing → attribution panel → valuation bridge and action table with costs → evaluation page: origins, baselines, ablations, coverage, benchmark comparison → failure case → replay the saved run and show the hash match with no LLM configured.

**Submission package:** built by `scripts/export_submission.sh` from an exclusion manifest (no `.git`, `node_modules`, `.env`, caches, developer paths). Contents: code, locks, migrations, compose file, bundled public-domain originals and fixtures, saved demo runs/forecasts, docs set, tests, fetch scripts for non-redistributable series.

**Validation (PR-06):** `scripts/verify_export.sh` unpacks the ZIP into a temporary directory outside Talisman, runs the guard test (no parent imports, symlinks, absolute paths, secrets, personal data), starts Compose, waits for health, runs the API smoke, executes a scenario run, replays a saved run and compares hashes, runs the test suite, and writes a log. Executed after M1 and again against the final ZIP; logs saved under `docs/hackathon/planning/validation/` in Talisman (not in the package). A fresh `git init` + first commit in the temp copy is part of the final check to prove the tree is self-sufficient; this does not create a repository for the user's submission.

**Unresolved submission logistics:** deadline time/timezone; required artifacts (ZIP vs repository link vs hosted URL vs video/slides); whether a hosted instance is expected (SR-04). Stage 3 (if advanced) requires a live demo, presentation, implementation plan and scalability roadmap (rules p. 5) — the docs set is written so those can be derived.

## 8. Risks and fallbacks

| Risk | Likelihood / impact | Mitigation | Fallback (requires decision) |
| --- | --- | --- | --- |
| Fewer than eight eligible origins after audit | Medium / high | Extend the window to FY2022 origins; keep definitions stable | Report actual count as a shortfall; do not pad |
| Historical release formats (2015–2019) resist parsing | Medium / medium | Start with 2020+ formats; XBRL for standard financials; manual fixtures for a few older quarters | Shorter calibration history (FY2019+) recorded in the spec |
| No license-compliant free S&P 500 TR source | Medium / medium | Option chain in data plan §4 | Labeled approximation (option B); never relabel |
| External families add no measurable signal | Medium / medium (hypothesis risk, not delivery risk) | Ablations and incremental tests designed to show it | Report honestly; evidence remains context |
| Hidden Talisman coupling in copied components | Medium / medium | Guard test from M0; early export at M1 | Rewrite the coupled piece |
| LLM extraction cost/latency | Low / medium | Cache; bounded corpus; stubbed provider in tests | Manual observation entry for the demo set |
| Guidance PDFs not recoverable historically | Medium / low | Capture what exists; report gaps | Guidance baseline on the subset with captured outlooks |
| Calendar: effort exceeds available hours | High / high | Strict sequencing; parallel tracks; agents on bounded issues | Raise specific shortfall for decision (no silent cut) |
