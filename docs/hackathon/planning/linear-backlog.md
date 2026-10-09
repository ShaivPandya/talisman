# Longaeva issue drafts — planning v1

October 1, 2026 · Phase 2 draft for review · Local draft IDs (`DRAFT-NN`) are not Linear identifiers. No Linear reads or writes have been performed: the Linear MCP connection reports `needsAuth`, so team/project discovery and duplicate checks against existing Linear issues were not possible. Requirements referenced below are in [requirements.md](requirements.md); sequencing in [implementation-plan.md](implementation-plan.md) §3–4; data gates in [data-plan.md](data-plan.md) §8.

Conventions: **Priority** P0 = critical path or gate for the MVP; P1 = MVP, parallelizable; P2 = MVP finishing work. **Effort** is hours of focused build plus review, assuming coding agents on bounded tasks. **Touchpoints** are planned paths inside the standalone package (`longaeva/…`) plus Talisman files consulted or copied (never imported). Uncertainty-reduction issues carry a question, timebox and decision artifact.

## A. Feasibility gates (uncertainty reduction)

### DRAFT-01 — Visa eligible-origin and vintage inventory
- **Outcome:** `data/fixtures/origins.csv` listing every Visa earnings 8-K from FY2017 to FY2026 with acceptance timestamp, fiscal quarter, target quarter, realized-release timestamp, and per-input-family eligibility, plus an inventory note with the eligible count and exclusion reasons.
- **Question / timebox:** How many origins satisfy the cutoff convention (data plan §2.3) with a realized next quarter and eligible inputs? 6 h.
- **Scope:** EDGAR `submissions` JSON (recent + `submissions-001.json`), 8-K/10-Q/10-K timestamps, amendment scan, prospective origin flag.
- **Exclusions:** Parsing release content (DRAFT-15); external-family parsing (DRAFT-04/05).
- **Requirements:** DR-02, DR-05, DR-06, ER-10.
- **Touchpoints:** `backend/longaeva_app/collect/edgar_index.py`, `data/fixtures/origins.csv`, `docs/origins-inventory.md`.
- **Acceptance:** CSV has ≥ 18 candidate rows (FY2022–FY2026) and ≥ 28 calibration quarters (FY2017–FY2023) with timestamps; every exclusion has a reason; prospective origin 2026-07-28 flagged; count stated without rounding up.
- **Validation:** Spot-check five timestamps against EDGAR filing index pages; unit test on the eligibility function with a late-document fixture.
- **Dependencies:** none. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** SEC User-Agent contact string for `.env`.

### DRAFT-02 — Visa driver and accounting definitions decision
- **Outcome:** `docs/definitions.md` fixing: payments volume vs total volume vs processed transactions coverage; cross-border total vs ex-intra-Europe and which drives international revenue; nominal vs constant-dollar handling; GAAP vs identified special items and the declared operating-profit basis; fiscal calendar; disclosure changes across the window (e.g., newer growth metrics).
- **Question / timebox:** Which definitions and bases does the model use, and are they stable FY2017–FY2026? 6 h.
- **Scope:** 10-K glossary/MD&A reading (FY2025 10-K and one earlier), release Key Business Drivers tables for two eras.
- **Exclusions:** Engine implementation.
- **Requirements:** MR-01, MR-05, MR-06, MR-07, DR-02.
- **Touchpoints:** `docs/definitions.md`, later copied into `docs/model-spec.md`.
- **Acceptance:** Each definition cites a filing section; the teaching fees from the proposal appear only as an explicit "not an input" note; nominal/constant decision recorded with rationale; basis for scoring declared.
- **Validation:** Reviewer sign-off; definitions referenced by DRAFT-15 parser field names.
- **Dependencies:** none. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** none.

### DRAFT-03 — Reconstruct two historical starting states from original exhibits
- **Outcome:** Two reconciled starting-state fixtures (e.g., origins 2024-07-23 and 2025-10-28) with values, periods, units, bases and source spans, reconciled to original release and prior 10-Q tables; a report of mismatches.
- **Question / timebox:** Can release-only inputs plus the previous 10-Q produce a complete starting state under the cutoff convention? 6 h.
- **Scope:** Manual/semi-automated extraction of category revenue, incentives, net revenue, opex, special items, driver growth (constant and nominal), prior-quarter PV growth, nominal PV level from the prior 10-Q, tax rate, net interest, diluted shares.
- **Exclusions:** General parser (DRAFT-15); calibration.
- **Requirements:** FR-01, MR-01, MR-07, DR-04, ER-02.
- **Touchpoints:** `data/fixtures/states/visa_2024-07-23.json`, `…/visa_2025-10-28.json`, `backend/tests/test_state_reconciliation.py`.
- **Acceptance:** Identities hold on each fixture (Σ categories − incentives = net revenue; net revenue − opex = operating profit) within rounding; every value has a span; any field unavailable at the cutoff is marked and the alternative cutoff convention is assessed in the report.
- **Validation:** Reconciliation test passes; reviewer compares five values against the HTML.
- **Dependencies:** DRAFT-01, DRAFT-02. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** none.

### DRAFT-04 — Booking Holdings family gate
- **Outcome:** Gate note with one measured fact and one qualitative/forward passage at two cutoffs (e.g., 2024-05-02 and 2026-08-04 releases), their eligibility against the nearest Visa origins, geography/currency notes, and a recommendation (required family / context only).
- **Question / timebox:** Does Booking provide usable, dated observations whose timing can inform a Visa cross-border prior? 4 h.
- **Scope:** Two Ex. 99.1 documents; passage spans; statement typing.
- **Exclusions:** Mapping-rule estimation (DRAFT-22).
- **Requirements:** DR-03, DR-04, FR-03.
- **Touchpoints:** `docs/gates/booking.md`, `data/fixtures/observations/booking_*.json`.
- **Acceptance:** Both passages carry publication timestamps from EDGAR; staleness relative to the Visa origin stated in weeks; recommendation explicit.
- **Validation:** Reviewer check against the filing.
- **Dependencies:** none. **Priority:** P0. **Effort:** 3–4 h.
- **Inputs:** none.

### DRAFT-05 — Census MARTS vintage gate
- **Outcome:** Two parsed archived advance-release tables (e.g., `adv2406.pdf`, `adv2506.pdf`) as dated vintage series; a revision example showing a later vintage differing from the first print; category continuity notes; recommendation.
- **Question / timebox:** Can archived PDFs yield stable, nominal, seasonally adjusted series with vintage integrity? 5 h.
- **Scope:** PDF table extraction (pdfplumber/pdfminer), total and selected kind-of-business lines, SA/NSA flags, release date capture.
- **Exclusions:** Full monthly backfill (DRAFT-16).
- **Requirements:** DR-03, DR-04.
- **Touchpoints:** `docs/gates/census.md`, `data/fixtures/census/adv2406.csv`, `adv2506.csv`.
- **Acceptance:** Parsed totals match the PDF text; revision example documented; the revised XLSX is shown as not a vintage source.
- **Validation:** Parse → compare three cells manually.
- **Dependencies:** none. **Priority:** P0. **Effort:** 3–5 h.
- **Inputs:** none.

### DRAFT-06 — Benchmark and price data decision
- **Outcome:** `docs/gates/benchmarks.md` choosing among data plan §4 options A/B/C for S&P 500 total return and a Visa price/dividend source; terms summary; redistribution decision (bundle vs fetch script); exact UI label text.
- **Question / timebox:** Which license-compliant free source supports after-cost excess-return scoring? 4 h.
- **Scope:** Read terms for Tiingo/Alpha Vantage free tiers (registration-only keys flagged as such), FRED S&P terms, Ken French usage note, Shiller data note; test one download per chosen path.
- **Exclusions:** Ingestion code (DRAFT-27).
- **Requirements:** DR-01, DR-07, FR-14.
- **Touchpoints:** `docs/gates/benchmarks.md`, `data/manifest/benchmarks.yaml`.
- **Acceptance:** Decision names series, provider, access method, terms URL and retrieval date; label text never says "S&P 500 total return" without the derivation; fallback chain recorded.
- **Validation:** Reviewer approval of label text.
- **Dependencies:** none. **Priority:** P0. **Effort:** 3–4 h.
- **Inputs:** Whether the user is willing to register a free API key (affects option A).

### DRAFT-07 — Guidance availability and consensus confirmation
- **Outcome:** Gate note listing which Visa quarterly outlook statements (earnings presentation / prepared remarks) are recoverable with dates for the origin window, their metric/period comparability, and a confirmation that no free licensed historical consensus source exists.
- **Question / timebox:** Can the guidance baseline cover all eligible origins? 3 h.
- **Scope:** investor.visa.com quarterly pages for four sample quarters; capture method and hashing.
- **Exclusions:** Baseline implementation (DRAFT-29).
- **Requirements:** FR-15, ER-07.
- **Touchpoints:** `docs/gates/guidance.md`, `data/manifest/visa_ir.yaml`.
- **Acceptance:** Per-origin availability table; statement-type `guidance` examples; the word "consensus" appears only as "unavailable".
- **Validation:** Reviewer check.
- **Dependencies:** none. **Priority:** P1. **Effort:** 2–3 h.
- **Inputs:** none.

### DRAFT-08 — Second-wave disclosure families selection (airline, retailer, payment processor)
- **Outcome:** Selection note choosing one airline, one retailer and one payment processor/acquirer whose EDGAR earnings releases provide a dated metric tied to a named Visa driver, with publication timing relative to Visa origins and a context-vs-rule recommendation per family.
- **Question / timebox:** Which three companies qualify under DR-03? 5 h.
- **Scope:** Candidate screen (e.g., Delta; Walmart/Target; PayPal/Fiserv/Global Payments); two releases each; timing table.
- **Exclusions:** Parsing beyond passage capture; rule estimation.
- **Requirements:** DR-03, FR-03.
- **Touchpoints:** `docs/gates/second-wave.md`, `data/manifest/second_wave.yaml`.
- **Acceptance:** Each selected family lists driver, metric, timing, limitation; rejected candidates listed with reasons.
- **Validation:** Reviewer check.
- **Dependencies:** DRAFT-02. **Priority:** P1. **Effort:** 3–5 h.
- **Inputs:** none.

## B. Standalone bootstrap

### DRAFT-09 — Standalone backend skeleton with Compose, Postgres, Alembic and worker
- **Outcome:** `longaeva/` with `docker-compose.yml` (db, api, worker, web placeholders), FastAPI app with `/health`, SQLAlchemy session, Alembic configured, Postgres-backed job table and polling worker, `.env.example`, `Makefile` targets `up`, `check`, `seed`, and a README quickstart.
- **Scope:** Project layout per implementation plan §1.1; dependency manifests and lock; lint/type config; pytest config.
- **Exclusions:** Domain models (DRAFT-11); frontend (DRAFT-10).
- **Requirements:** PR-01, PR-03, NR-03, NR-04, NR-05.
- **Touchpoints:** `longaeva/docker-compose.yml`, `backend/pyproject.toml`, `backend/alembic.ini`, `backend/longaeva_app/api/main.py`, `backend/longaeva_app/worker/loop.py`, `Makefile`, `README.md`. Talisman reference: `requirements.txt`, `Dockerfile`, `migrations/env.py` (patterns only).
- **Acceptance:** `docker compose up` from an empty checkout reaches healthy `api` and `worker`; `alembic upgrade head` runs on an empty DB; `make check` runs pytest + ruff + mypy; no import of any Talisman module (checked by DRAFT-13's guard).
- **Validation:** Fresh clone of the directory into `/tmp`, run quickstart.
- **Dependencies:** none. **Priority:** P0. **Effort:** 6–10 h.
- **Inputs:** none.

### DRAFT-10 — Frontend shell with adapted chart components and a minimal run page
- **Outcome:** Vite/React/TS app in `longaeva/frontend` with theme tokens, adapted `TimeSeriesChart`, new `FanChart` and `PairedDiffChart`, plain fetch API client, router with the five pages stubbed, and a minimal Run page that lists saved runs and charts one run's quantiles.
- **Scope:** Copy/adapt per implementation plan §2; `docs/reuse-notes.md` entries.
- **Exclusions:** Full page features (DRAFT-34/35/36).
- **Requirements:** PR-01, PR-08, UF-03 (minimal).
- **Touchpoints:** `frontend/src/lib/api.ts`, `frontend/src/components/charts/*`, `frontend/src/pages/*`, `frontend/src/styles/theme.css`. Talisman sources copied: `frontend/src/components/shared/TimeSeriesChart.tsx`, `ChartTile.tsx`, `SurfaceCard.tsx`, CSS variables from `frontend/src/index.css`.
- **Acceptance:** `npm ci && npm run build` passes; no `@/lib/api` auth/CSRF code, Sentry or Talisman router imports; Run page renders a saved run from the API contract fixed in DRAFT-11.
- **Validation:** Build + one Playwright or manual smoke in the exported copy.
- **Dependencies:** DRAFT-09, DRAFT-11. **Priority:** P0. **Effort:** 5–8 h.
- **Inputs:** none.

### DRAFT-11 — Core schema, migrations, artifact storage and API contracts
- **Outcome:** SQLAlchemy models and Alembic migration for the records in implementation plan §1.2; local artifact store; Pydantic API schemas for sources, documents, observations, review, parameter sets, scenarios, runs, forecasts, evaluation results; OpenAPI published.
- **Scope:** Record definitions, indexes (tsvector on document text; publication_ts), immutability constraints on `forecast`.
- **Exclusions:** Business logic.
- **Requirements:** FR-01, FR-03, FR-06, FR-09, FR-17, FR-18, PR-03.
- **Touchpoints:** `backend/longaeva_app/db/models.py`, `backend/migrations/versions/0001_core.py`, `backend/longaeva_app/storage/local.py`, `backend/longaeva_app/api/schemas.py`. Talisman patterns consulted: `ontology/temporal_repository.py` (`SourceRecordWrite`), `api/state_storage.py`.
- **Acceptance:** Migration applies/reverts cleanly; `forecast` update attempt is rejected; publication_ts and retrieval_ts are separate non-null columns; a stub second company passes the `CompanyModel` interface test.
- **Validation:** pytest on a disposable Postgres (Compose).
- **Dependencies:** DRAFT-09. **Priority:** P0. **Effort:** 6–9 h.
- **Inputs:** none.

### DRAFT-12 — Early export rehearsal outside Talisman
- **Outcome:** `scripts/export_submission.sh` and `scripts/verify_export.sh`; a validation log under `docs/hackathon/planning/validation/early-export-<date>.md` showing startup, scenario execution and saved-run replay in a temporary directory outside Talisman.
- **Scope:** Exclusion manifest; ZIP build; unpack to `/tmp`; guard test; compose up; smoke; replay; fresh `git init` check in the temp copy only.
- **Exclusions:** Final packaging docs (DRAFT-38).
- **Requirements:** PR-06, PR-07, UF-08.
- **Touchpoints:** `scripts/export_submission.sh`, `scripts/verify_export.sh`, `.exportignore`.
- **Acceptance:** Log shows all steps passing from the exported copy; ZIP contains no `.git`, `.env`, `node_modules`, or `/Users/` paths.
- **Validation:** Run the script; attach log.
- **Dependencies:** DRAFT-10, DRAFT-13, DRAFT-14, DRAFT-15, DRAFT-20, DRAFT-24. **Priority:** P0. **Effort:** 3–5 h.
- **Inputs:** none.

### DRAFT-13 — Isolation guard tests and exclusion manifest
- **Outcome:** A test that fails on any import outside the package namespace or third-party deps, any symlink, any absolute developer path, any secret-like string (regex set), any `.env`; an `.exportignore` manifest; a personal-data checklist.
- **Scope:** Static scan over backend, frontend `src`, data, docs.
- **Exclusions:** Runtime checks.
- **Requirements:** PR-02, PR-07.
- **Touchpoints:** `backend/tests/test_isolation_guard.py`, `.exportignore`, `docs/limitations.md` (personal data note).
- **Acceptance:** Guard passes on the package; a deliberate `from api import x` or `/Users/...` string fails it.
- **Validation:** Negative test fixtures.
- **Dependencies:** DRAFT-09. **Priority:** P0. **Effort:** 2–4 h.
- **Inputs:** none.

## C. Source collection and extraction

### DRAFT-14 — Manifest-driven collector with caching, hashing and timestamps
- **Outcome:** Collector that reads `data/manifest/*.yaml`, fetches EDGAR documents (index JSON → primary doc/exhibit), Census PDFs and IR PDFs with declared User-Agent, rate limiting, retries/backoff, on-disk originals, content hashes, publication_ts (EDGAR acceptance) and retrieval_ts; creates `source` and `document_text` rows with page/char spans; marks 403/JS-challenge sources unavailable without bypass.
- **Scope:** EDGAR, Census, IR; dedup by content hash; supersedes links.
- **Exclusions:** Table parsing; LLM extraction.
- **Requirements:** FR-01, FR-02 (storage), DR-02, DR-04, DR-08, DR-09.
- **Touchpoints:** `backend/longaeva_app/collect/{manifest.py,edgar.py,census.py,ir.py,http.py}`, `data/manifest/visa.yaml`, `booking.yaml`, `census.yaml`. Talisman pattern: `ontology/source_ingestion.py` hashing; `ontology/extractors/deterministic.py::_extract_text` adapted without page limits.
- **Acceptance:** Re-collecting yields no duplicate sources; publication_ts ≠ retrieval_ts in all rows; rate limiter test; pdfminer extraction keeps page numbers.
- **Validation:** Integration test against three cached fixtures; one live fetch in development.
- **Dependencies:** DRAFT-11. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** SEC User-Agent contact string.

### DRAFT-15 — Visa release and 10-Q structured table parser
- **Outcome:** Parsers producing typed `measured` observations with spans: income statement summary (categories, incentives, net revenue, opex, special items, EPS), Key Business Drivers (constant and nominal), prior-quarter PV growth sentence, 10-Q nominal PV level, tax rate, net interest, diluted shares; coverage FY2020+ formats first, FY2017–FY2019 best effort with per-quarter status.
- **Scope:** HTML table parsing; unit/basis tagging per DRAFT-02; identity validation at parse time.
- **Exclusions:** LLM extraction; guidance.
- **Requirements:** FR-03, MR-01, MR-07, ER-02, DR-02.
- **Touchpoints:** `backend/longaeva_app/extract/visa_tables.py`, `backend/tests/test_visa_tables.py`, `data/fixtures/visa_releases/`.
- **Acceptance:** All FY2024–FY2026 releases parse with identities within rounding; FY2017–FY2023 parse status reported per quarter; the two DRAFT-03 fixtures reproduce exactly.
- **Validation:** Fixture tests; reconciliation against DRAFT-03.
- **Dependencies:** DRAFT-02, DRAFT-14. **Priority:** P0. **Effort:** 6–10 h.
- **Inputs:** none.

### DRAFT-16 — Census MARTS archived-release parser and vintage series
- **Outcome:** Parser over archived `advYYMM.pdf` files producing per-vintage nominal SA/NSA series for total retail and food services and selected lines, with release dates; a vintage table keyed by (release, reference month).
- **Scope:** FY2017–FY2026 window monthly; revision linkage.
- **Exclusions:** E-commerce quarterly report (SR-05).
- **Requirements:** DR-03, DR-04, FR-01.
- **Touchpoints:** `backend/longaeva_app/extract/census_marts.py`, `data/manifest/census.yaml`, `backend/tests/test_census_marts.py`.
- **Acceptance:** ≥ 95% of files in the window parse; failures listed; a query "latest vintage as of cutoff T" returns first-print values, never later revisions.
- **Validation:** Fixture tests on the two DRAFT-05 files plus five random files.
- **Dependencies:** DRAFT-05, DRAFT-14. **Priority:** P1. **Effort:** 3–5 h.
- **Inputs:** none.

### DRAFT-17 — LLM structured extraction with Pydantic schemas, caching and review persistence
- **Outcome:** Extraction service that takes selected passages (only), returns observations validated by Pydantic (statement type, value/range, unit, geography, period, span), caches by (model, prompt hash), records failures, supports Anthropic/OpenAI/Gemini-compatible providers via env, runs as a worker job; review endpoints accept/reject/correct with rationale; approved parameter sets never change without a review decision.
- **Scope:** Prompt templates with passage-only instruction; stub provider for tests; `UF-07` graceful degradation.
- **Exclusions:** Mapping rules (DRAFT-22); search (DRAFT-18).
- **Requirements:** FR-04, FR-05, MR-12, NR-02, PR-05.
- **Touchpoints:** `backend/longaeva_app/extract/llm.py`, `schemas.py`, `cache.py`, `backend/longaeva_app/review/service.py`, routers `observations`, `review`.
- **Acceptance:** Tests run with the stub provider and no network; cache hit avoids a call; confidence fields are not persisted as probabilities; a pending observation cannot alter an approved parameter set.
- **Validation:** Unit + integration tests; one manual run on a Booking passage with a configured provider (optional).
- **Dependencies:** DRAFT-11, DRAFT-14. **Priority:** P0. **Effort:** 8–12 h.
- **Inputs:** Optional provider API key for manual runs; provider choice.

### DRAFT-18 — Full-text search filtered by company, period and publication cutoff
- **Outcome:** Postgres `tsvector` search endpoint over `document_text` with filters company, observation period, publication_ts ≤ cutoff; results return spans.
- **Scope:** Index, query, API, tests.
- **Exclusions:** Semantic/embedding search.
- **Requirements:** FR-02.
- **Touchpoints:** `backend/longaeva_app/api/routers/search.py`, migration index.
- **Acceptance:** Query with cutoff excludes later documents in a fixture; response time < 500 ms on the demo corpus.
- **Validation:** Tests.
- **Dependencies:** DRAFT-11, DRAFT-14. **Priority:** P1. **Effort:** 2–4 h.
- **Inputs:** none.

### DRAFT-19 — Extraction evaluation set and scoring
- **Outcome:** ≥ 40 manually labeled items (numeric facts, qualitative statements, contradictions, period/unit/geography edge cases) across Visa, Booking, Census and second-wave passages; scoring script reporting error rates by type, separate from model errors.
- **Scope:** Labeling guide; gold file; scorer.
- **Exclusions:** Prompt tuning beyond one documented iteration.
- **Requirements:** ER-09.
- **Touchpoints:** `data/fixtures/extraction_eval/gold.jsonl`, `backend/longaeva_app/evaluation/extraction_scoring.py`, `docs/extraction-eval.md`.
- **Acceptance:** Scorer runs on cached extraction outputs; report table by error type; disagreements documented.
- **Validation:** Second reviewer checks 10 labels.
- **Dependencies:** DRAFT-17. **Priority:** P1. **Effort:** 4–6 h.
- **Inputs:** Labeling time from a reviewer.

## D. Model engine

### DRAFT-20 — Visa quarterly engine core with identities and seeded correlated Monte Carlo
- **Outcome:** `companies/visa` implementing the state, transition order, service-revenue lag, category rules, incentives, opex; `engine` with correlated factor sampler, seeded path runner, summaries (quantiles, SE); ablation switches `service_lag`, `pool_mix`; property tests for identities and lag.
- **Scope:** Pure Python/NumPy; interface `CompanyModel`; synthetic fixtures until DRAFT-15 data lands.
- **Exclusions:** Calibration (DRAFT-21); interventions (DRAFT-23); persistence (DRAFT-24).
- **Requirements:** MR-01–MR-08, MR-11, FR-18, NR-01.
- **Touchpoints:** `backend/longaeva_app/companies/base.py`, `companies/visa/{state.py,transitions.py,revenue.py}`, `backend/longaeva_app/engine/{sampler.py,runner.py,summary.py}`, `backend/tests/test_engine_identities.py`.
- **Acceptance:** Identities hold on every path/quarter (≤ 1e-9 relative) over randomized parameters; same seed → identical paths; lag test passes; 5,000 paths × 4 quarters ≤ 60 s on a laptop (measured); `pool_mix` and `service_lag=False` paths tested; no teaching-fee constants.
- **Validation:** pytest property tests; timing log.
- **Dependencies:** DRAFT-02. **Priority:** P0. **Effort:** 8–12 h.
- **Inputs:** none.

### DRAFT-21 — Parameter ranges, chronological calibration and ensemble weighting
- **Outcome:** Calibration routine fitting 6–8 free parameters on history ≤ cutoff (seasonal activity ratios, yield drift, incentive intensity, opex growth, shock scales/correlations), retaining alternative parameter combinations with weights; sensitivity report for yield and incentive assumptions; pandemic-quarter treatment decided and documented.
- **Scope:** pandas alignment of DRAFT-15 series; SciPy constrained fit; residual-based shock scales.
- **Exclusions:** External-family rules (DRAFT-22).
- **Requirements:** MR-09, MR-10, DR-06, FR-06.
- **Touchpoints:** `backend/longaeva_app/companies/visa/calibration.py`, `docs/model-spec.md` (parameters section), `backend/tests/test_calibration_leakage.py`.
- **Acceptance:** Fit at a historical cutoff uses no later-published value (test); parameter set saved with evidence links; ensemble weights sum to 1; sensitivity table produced.
- **Validation:** Tests; reviewer reads the parameter section.
- **Dependencies:** DRAFT-03, DRAFT-15, DRAFT-20. **Priority:** P0. **Effort:** 6–10 h.
- **Inputs:** Decision on pandemic treatment (recommendation inside the issue).

### DRAFT-22 — Mapping-rule registry and observation-to-parameter review
- **Outcome:** Rule registry (estimated and analyst-ranged rules) for Booking → travel factor, Census → domestic consumption factor, second-wave corroborators as context; application produces `parameter_update` records with before/after/size/rationale; qualitative-only observations remain context; parameter-set versioning with parent links.
- **Scope:** Rules, provenance records, API.
- **Exclusions:** UI (DRAFT-35).
- **Requirements:** FR-06, FR-07, MR-12, DR-03.
- **Touchpoints:** `backend/longaeva_app/review/rules.py`, `review/apply.py`, router `parameters`.
- **Acceptance:** Applying a rule creates a provenance record; an observation with no rule leaves the set unchanged and is listed as context; every parameter has evidence or an assumption flag.
- **Validation:** Tests with the DRAFT-04/05 fixtures.
- **Dependencies:** DRAFT-04, DRAFT-05, DRAFT-11, DRAFT-20. **Priority:** P0. **Effort:** 5–8 h.
- **Inputs:** none.

### DRAFT-23 — Paired scenarios, interventions and attribution
- **Outcome:** Scenario definitions with pair groups sharing draws; interventions `mix_shift_conserving_total` and `total_spend_reduction`; path-wise difference distributions; attribution computing parameter contributions, sensitivity ranking and weak-support flags with model-conditional labels and order-dependence note.
- **Scope:** Engine-level intervention transforms; summary API.
- **Exclusions:** Charts (DRAFT-34).
- **Requirements:** FR-10, FR-11, MR-11.
- **Touchpoints:** `backend/longaeva_app/companies/visa/interventions.py`, `engine/attribution.py`, router `scenarios`.
- **Acceptance:** Mix-shift total spending equals baseline per path/quarter; shared seed yields identical baseline paths; attribution output lists rule ids and source ids; no causal wording in labels.
- **Validation:** Tests.
- **Dependencies:** DRAFT-20. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** none.

### DRAFT-24 — Run persistence, worker execution and replay without LLM
- **Outcome:** Run API (submit → run id → status → results), worker handler executing the engine, run record with cutoff, manifest hash, parameter-set hash, code version, seed, n_paths, library versions, outputs hash; `replay` CLI/API comparing hashes; immutable forecast archive writes with `retrospective`/`prospective` kind.
- **Scope:** Hashing conventions; artifact storage of path outputs.
- **Exclusions:** Evaluation loop (DRAFT-28).
- **Requirements:** FR-08, FR-09, FR-17, ER-03, UF-06.
- **Touchpoints:** `backend/longaeva_app/api/routers/runs.py`, `worker/handlers/run.py`, `engine/replay.py`, `cli.py replay`.
- **Acceptance:** Integration test API → worker → result; replay with `LLM_PROVIDER` unset reproduces the hash; forecast rows immutable.
- **Validation:** Tests in Compose.
- **Dependencies:** DRAFT-11, DRAFT-20. **Priority:** P0. **Effort:** 5–8 h.
- **Inputs:** none.

## E. Valuation and illustrative actions

### DRAFT-25 — Earnings/multiple valuation bridge
- **Outcome:** Function mapping operating-profit paths to forward earnings (stated tax rate, net interest/other, diluted shares) and value ranges via a multiple range; business vs multiple uncertainty separated; unsupported cases documented; multiple range derived from a stated historical window with its data source labeled.
- **Scope:** Pure function + API + tests.
- **Exclusions:** DCF; price data ingestion (DRAFT-27).
- **Requirements:** FR-12.
- **Touchpoints:** `backend/longaeva_app/valuation/bridge.py`, router `valuation`.
- **Acceptance:** Synthetic-path tests; non-positive earnings → `unsupported` with reason; output distinguishes earnings-driven and multiple-driven spread.
- **Validation:** Tests.
- **Dependencies:** DRAFT-02, DRAFT-20. **Priority:** P1. **Effort:** 4–6 h.
- **Inputs:** Tax/net-interest/share assumptions from DRAFT-03 fixtures.

### DRAFT-26 — Illustrative actions with explicit costs and a predefined decision rule
- **Outcome:** Adapted sizing/cost arithmetic (hold/add/trim/exit; transaction, slippage, impact, optional funding) for a labeled, editable demo position; decision-rule config (thresholds on value-vs-price, sizing, holding period) versioned with a hash; no-action outcome.
- **Scope:** Copy/adapt from Talisman simulator functions with provenance note.
- **Exclusions:** Scoring (DRAFT-27).
- **Requirements:** FR-13, PR-08.
- **Touchpoints:** `backend/longaeva_app/valuation/actions.py`, `config/decision_rule.yaml`, `docs/reuse-notes.md`. Talisman source: `portfolio/scenario_simulator.py` lines 357–518; tests adapted from `tests/test_scenario_simulator.py`.
- **Acceptance:** Each action's cost components tested; rule hash recorded; labels say "illustrative".
- **Validation:** Tests.
- **Dependencies:** DRAFT-25. **Priority:** P1. **Effort:** 4–6 h.
- **Inputs:** Default cost assumptions (recommendation inside the issue).

### DRAFT-27 — Benchmark/price ingestion and exploratory portfolio scoring
- **Outcome:** Fetchers for the DRAFT-06 decision (benchmark and Visa prices; Visa dividends from SEC filings); scoring over eligible origins: entry at the first eligible session after cutoff, fixed holding period, costs, dividends, overlapping forecasts; excess return vs the labeled benchmark and vs Visa buy-and-hold; drawdown and exposure; results labeled exploratory with n.
- **Scope:** Fetch scripts (non-redistributable data not bundled); scoring module; report table.
- **Exclusions:** Any alpha claim; leverage.
- **Requirements:** FR-14, ER-11, DR-07.
- **Touchpoints:** `backend/longaeva_app/collect/benchmarks.py`, `evaluation/portfolio.py`, `docs/data-licenses.md`.
- **Acceptance:** Rule hash frozen before the scoring run (asserted); benchmark label text matches DRAFT-06; tests on synthetic prices.
- **Validation:** Tests; reviewer reads labels.
- **Dependencies:** DRAFT-06, DRAFT-26, DRAFT-28. **Priority:** P1. **Effort:** 5–8 h.
- **Inputs:** Free API key if option A chosen.

## F. Evaluation

### DRAFT-28 — Evaluation harness: origins loop, leakage guard, errors, coverage and scoring
- **Outcome:** Harness iterating `origins.csv`, building cutoff-filtered inputs, calibrating (DRAFT-21), running the full model, scoring next-quarter net revenue, operating profit (declared basis) and drivers (abs/pct errors), 80% coverage, CRPS/WIS; four-quarter scoring separate; results persisted as `evaluation_result` with config hash; leakage guard raising on any late input.
- **Scope:** Full model only; report data, not prose.
- **Exclusions:** Baselines/ablations (29–31).
- **Requirements:** ER-04, ER-05, ER-06, ER-13, MR-10.
- **Touchpoints:** `backend/longaeva_app/evaluation/{origins.py,leakage.py,metrics.py,harness.py}`, `cli.py evaluate`.
- **Acceptance:** Deliberately late fixture raises; metrics match hand-computed values on a toy case; results table per origin and aggregate; n displayed.
- **Validation:** Tests; one full run on eligible origins.
- **Dependencies:** DRAFT-01, DRAFT-21, DRAFT-24. **Priority:** P0. **Effort:** 6–10 h.
- **Inputs:** none.

### DRAFT-29 — Baselines: seasonal/trend, financial-only driver model, guidance comparison
- **Outcome:** Three baseline configs run through the harness with matched inputs/horizon/scoring: seasonal/trend; financial-only driver model (no external updates); guidance comparison with a prior-data-only residual distribution where outlook statements exist.
- **Scope:** Configs + small model variants.
- **Exclusions:** LLM baseline (DRAFT-30).
- **Requirements:** ER-07, FR-15.
- **Touchpoints:** `backend/longaeva_app/evaluation/baselines/{seasonal.py,financial_only.py,guidance.py}`.
- **Acceptance:** Result rows for each origin per baseline; guidance rows marked where unavailable; no "consensus" label.
- **Validation:** Tests; report rows.
- **Dependencies:** DRAFT-07, DRAFT-28. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** none.

### DRAFT-30 — LLM same-document forecast baseline
- **Outcome:** Baseline that gives the configured model the same dated documents available at each cutoff and asks for next-quarter quantiles under the same horizon and scoring; cached; disclosure of pretrained-knowledge limitation in output metadata.
- **Scope:** Prompting, parsing, caching; skip gracefully when no provider configured (recorded as not run).
- **Exclusions:** Fine-tuning; multiple prompt variants beyond one documented iteration.
- **Requirements:** ER-07, ER-10, PR-05.
- **Touchpoints:** `backend/longaeva_app/evaluation/baselines/llm_docs.py`.
- **Acceptance:** Rows per origin or an explicit "not run (no provider)" status; same scoring code path; cache used on rerun.
- **Validation:** Stub-provider test; one real run if a key is available.
- **Dependencies:** DRAFT-17, DRAFT-28. **Priority:** P1. **Effort:** 3–5 h.
- **Inputs:** Provider key (optional but needed for real results).

### DRAFT-31 — Three ablations rebuilt and rerun across origins
- **Outcome:** Harness variants: (a) remove external commentary (rebuild parameter sets without external-family updates); (b) pool spending types into one growth driver; (c) remove service-revenue lag; persistence analysis across origins and parameter ranges.
- **Scope:** Config wiring to DRAFT-20/22 switches; result rows.
- **Exclusions:** New model features.
- **Requirements:** ER-08, MR-11.
- **Touchpoints:** `backend/longaeva_app/evaluation/ablations.py`.
- **Acceptance:** Each ablation has the same origin set as the full model; (a) demonstrably changes parameter sets (not just citations); persistence table produced.
- **Validation:** Tests + report rows.
- **Dependencies:** DRAFT-22, DRAFT-28. **Priority:** P0. **Effort:** 3–5 h.
- **Inputs:** none.

### DRAFT-32 — Register the prospective Q4 FY2026 forecast
- **Outcome:** Forecast from the 2026-07-28 origin for Q4 FY2026 saved as `prospective` in the archive with its parameter set, manifest and run hash, before Visa's late-October release; procedure documented for scoring it later.
- **Scope:** One run + archive write + doc note.
- **Exclusions:** Scoring (not possible before results).
- **Requirements:** FR-17, ER-10.
- **Touchpoints:** `data/demo/forecasts/prospective_fy2026q4.json`, `docs/evaluation-report.md` (prospective section).
- **Acceptance:** Archive entry exists with `kind=prospective` and creation timestamp before the release; immutable.
- **Validation:** DB query + replay hash.
- **Dependencies:** DRAFT-21, DRAFT-22, DRAFT-24. **Priority:** P1. **Effort:** 2–3 h.
- **Inputs:** none.

### DRAFT-33 — Evaluation report, model specification and failure case
- **Outcome:** `docs/evaluation-report.md` (origins and count, exclusions, errors vs baselines, coverage/scores, ablations, extraction error rates, benchmark comparison with labels, prospective section, hindsight/pretrained disclosures, limitations), `docs/model-spec.md` (inputs, rules, parameters, evidence per rule, definitions), and a failure case with invalidating conditions; both rendered in the UI (DRAFT-36).
- **Scope:** Report generator from `evaluation_result` plus hand-written sections.
- **Exclusions:** Marketing language; claims not backed by result rows.
- **Requirements:** FR-16, ER-12, NR-06.
- **Touchpoints:** `backend/longaeva_app/evaluation/report.py`, `docs/evaluation-report.md`, `docs/model-spec.md`, `docs/limitations.md`.
- **Acceptance:** Every number in the report traces to a result row or fixture; eligible count stated; failure case present; "consensus unavailable" stated; benchmark label matches DRAFT-06.
- **Validation:** Reviewer read-through against result tables.
- **Dependencies:** DRAFT-19, DRAFT-27, DRAFT-28, DRAFT-29, DRAFT-30, DRAFT-31, DRAFT-32. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** none.

## G. User interface

### DRAFT-34 — Scenario workspace: state, controls, runs, fan charts, paired comparison, attribution
- **Outcome:** Pages State & Evidence (starting values with period/unit/basis/source) and Scenarios (parameter controls with evidence links and assumption badges, pair definition, run with progress, fan charts for activity/net revenue/operating profit, path-wise difference chart, attribution panel with flags and conditional labels).
- **Scope:** Against DRAFT-23/24 APIs; charts from DRAFT-10.
- **Exclusions:** Review UI (DRAFT-35); valuation/evaluation pages (DRAFT-36).
- **Requirements:** UF-01, UF-03, FR-11.
- **Touchpoints:** `frontend/src/pages/StateAndEvidence.tsx`, `pages/Scenarios.tsx`, `components/scenario/*`.
- **Acceptance:** UF-01 and UF-03 acceptance met in a browser; charts read from saved runs only; attribution shows rule and source ids.
- **Validation:** Playwright smoke in the exported copy.
- **Dependencies:** DRAFT-10, DRAFT-23, DRAFT-24. **Priority:** P0. **Effort:** 8–12 h.
- **Inputs:** none.

### DRAFT-35 — Evidence and review UI with passage spans, decisions and search
- **Outcome:** Passage viewer highlighting spans; observation cards with statement type, period, geography, unit; accept/adjust/reject with rationale; mapping-rule display (before/after/size); context-only list; search with company/period/cutoff filters.
- **Scope:** Against DRAFT-17/18/22 APIs; adapted evidence-list pattern from Talisman's `EvidenceLedgerPanel.tsx` (rewritten).
- **Exclusions:** Bulk labeling tools.
- **Requirements:** UF-02, FR-02, FR-05, FR-07.
- **Touchpoints:** `frontend/src/pages/StateAndEvidence.tsx` (evidence tab), `components/evidence/*`, `components/review/*`.
- **Acceptance:** UF-02 acceptance met; search with cutoff hides later documents; review decision visible after reload.
- **Validation:** Playwright smoke.
- **Dependencies:** DRAFT-10, DRAFT-17, DRAFT-18, DRAFT-22. **Priority:** P1. **Effort:** 6–9 h.
- **Inputs:** none.

### DRAFT-36 — Valuation, actions, evaluation and replay pages
- **Outcome:** Valuation & Actions page (bridge with separate uncertainty bars, action table with cost components, illustrative label); Evaluation page (origin table with count and exclusions, errors vs baselines, coverage/scores, ablations, benchmark comparison with labels, extraction error rates, failure case, prospective section, rendered report and model spec); Replay page (select run, replay, hash comparison, library versions).
- **Scope:** Against DRAFT-25/26/27/28/33 outputs.
- **Exclusions:** Editing evaluation results.
- **Requirements:** UF-04, UF-05, UF-06, FR-16.
- **Touchpoints:** `frontend/src/pages/ValuationActions.tsx`, `pages/Evaluation.tsx`, `pages/Replay.tsx`, `components/valuation/*`, `components/evaluation/*`.
- **Acceptance:** UF-04/05/06 acceptance met; unsupported valuation cases show the documented message; benchmark label text exact.
- **Validation:** Playwright smoke.
- **Dependencies:** DRAFT-10, DRAFT-25, DRAFT-26, DRAFT-27, DRAFT-28. **Priority:** P1. **Effort:** 5–8 h.
- **Inputs:** none.

## H. Demo bundle and submission

### DRAFT-37 — Demo dataset, saved runs and seed command
- **Outcome:** Bundled public-domain originals (SEC, Census) for the demo origin(s), reviewed observations, parameter sets, paired saved runs, forecasts and evaluation results loaded by `make seed` (also on first Compose start); `docs/demo-script.md`; works with no LLM credentials.
- **Scope:** Export of DB rows and artifacts to `data/demo/`; loader; license rows in `docs/data-licenses.md`.
- **Exclusions:** Non-redistributable vendor data (fetch scripts instead).
- **Requirements:** PR-04, DR-01, UF-01, UF-03, UF-05, UF-06.
- **Touchpoints:** `data/demo/*`, `backend/longaeva_app/cli.py seed-demo`, `docs/demo-script.md`, `docs/data-licenses.md`.
- **Acceptance:** Fresh Compose start → demo flows UF-01/03/05/06 pass without `LLM_PROVIDER`; licenses listed for every bundled file.
- **Validation:** Executed inside DRAFT-38's verification.
- **Dependencies:** DRAFT-15, DRAFT-16, DRAFT-24, DRAFT-34, DRAFT-35, DRAFT-36. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** none.

### DRAFT-38 — Final export, clean-environment validation and submission docs
- **Outcome:** Final ZIP built by `scripts/export_submission.sh`; `scripts/verify_export.sh` log from a temporary directory outside Talisman (guard, Compose up, smoke, scenario run, replay hash, test suite, fresh `git init` check in the temp copy); README quickstart, limitations, data licenses, reuse notes finalized; secret and personal-data scans clean; no Talisman Git history.
- **Scope:** Packaging and docs only; no application feature work.
- **Exclusions:** Organizer upload (format unknown); hosting.
- **Requirements:** PR-01–PR-08, NR-05, NR-06, UF-08.
- **Touchpoints:** `scripts/*`, `README.md`, `docs/*`, `docs/hackathon/planning/validation/final-export-<date>.md` (Talisman side).
- **Acceptance:** Validation log all-pass; ZIP listing reviewed; `.git` absent; `.env` absent; no `/Users/` strings.
- **Validation:** Run the script; attach log and ZIP checksum.
- **Dependencies:** DRAFT-12, DRAFT-33, DRAFT-37. **Priority:** P0. **Effort:** 4–6 h.
- **Inputs:** Submission format and deadline time (if known by then); otherwise ZIP + optional fresh repository both prepared.

### DRAFT-39 — Demo rehearsal and presentation notes
- **Outcome:** Timed run-through of `docs/demo-script.md` from the exported copy; presentation notes covering hypothesis, evidence → forecast chain, results with actual counts, failure case, limitations, scalability (FR-18) and implementation roadmap (rules p. 5); fixes list.
- **Scope:** Rehearsal + notes; small fixes routed to the owning issue.
- **Exclusions:** Slide design beyond notes.
- **Requirements:** UF-08, C33, C35.
- **Touchpoints:** `docs/demo-script.md`, `docs/presentation-notes.md`.
- **Acceptance:** Rehearsal completes within a stated time; every claim in notes maps to a report row or fixture.
- **Validation:** Reviewer attends/reads.
- **Dependencies:** DRAFT-38. **Priority:** P2. **Effort:** 3–5 h.
- **Inputs:** Presentation expectations if the organizer specifies them.

## S. Stretch (not part of the MVP approval request)

### DRAFT-S1 — Reserve corroborators: I-94, BEA PCE tables, TSA, BTS
- Outcome: availability/vintage check and, if feasible, context observations. Requirements SR-02. Depends on DRAFT-14. Effort 4–8 h. Blocked for automation where 403/timeouts persist; no bypass.

### DRAFT-S2 — Second company (Mastercard) through the company-model boundary
- Outcome: Mastercard definitions, parser and model module exercising `CompanyModel`; separate validation. Requirements SR-01, FR-18. Depends on DRAFT-20, DRAFT-15. Effort 16–30 h.

### DRAFT-S3 — Optional Talisman integration
- Outcome: route embedding or API proxy from Talisman to the standalone app; never a package dependency. Requirements SR-03. Depends on DRAFT-38. Effort 6–12 h.

### DRAFT-S4 — Cloud hosting (conditional on submission rules)
- Outcome: Cloud Run/Cloud SQL/Cloud Storage deployment of the package. Requirements SR-04. Depends on DRAFT-38 and an organizer requirement. Effort 6–12 h.

### DRAFT-S5 — Census e-commerce share integration
- Outcome: quarterly e-commerce report vintages mapped to a frequency/mix prior. Requirements SR-05. Depends on DRAFT-16. Effort 4–8 h.

### DRAFT-S6 — Broader source discovery beyond selected families
- Outcome: documented screen of additional airline/retailer/processor disclosures with driver ties. Requirements SR-06. Depends on DRAFT-08, DRAFT-33 (do after evaluation). Effort 4–8 h.

## Coverage matrix (MVP requirements → drafts)

| Requirement group | Covered by |
| --- | --- |
| UF-01 | 15, 34, 37 · UF-02: 17, 22, 35 · UF-03: 23, 24, 34 · UF-04: 25, 26, 36 · UF-05: 28–33, 36 · UF-06: 24, 36, 37 · UF-07: 17 · UF-08: 12, 38, 39 |
| FR-01…FR-03 | 11, 14, 15, 18 · FR-04/05: 17 · FR-06/07: 21, 22 · FR-08/09: 24 · FR-10/11: 23, 34 · FR-12/13/14: 25, 26, 27 · FR-15: 07, 29 · FR-16: 33, 36 · FR-17: 11, 24, 32 · FR-18: 11, 20 |
| MR-01…MR-08, MR-11 | 02, 20 · MR-09/10: 21 · MR-12: 17, 22 |
| DR-01 | 06, 37 · DR-02: 01, 14, 15 · DR-03: 04, 05, 08, 16, 22 · DR-04: 01, 14, 16 · DR-05/06: 01, 21 · DR-07: 06, 27 · DR-08/09: 14 |
| ER-01 | 20 · ER-02: 03, 15 · ER-03: 24 · ER-04: 28 · ER-05/06/13: 28 · ER-07: 29, 30 · ER-08: 31 · ER-09: 19 · ER-10: 32, 33 · ER-11: 27 · ER-12: 33 |
| PR-01…PR-03 | 09, 10, 11 · PR-02/07: 13, 38 · PR-04: 37 · PR-05: 17, 30 · PR-06: 12, 38 · PR-08: 10, 26 |
| NR-01 | 20 · NR-02: 17 · NR-03: 09, 38 · NR-04: 09 · NR-05/06: 09, 33, 38 |

Every MVP requirement has at least one draft. Commitments C1–C36 map through the requirement table in [requirements.md](requirements.md) §2.

## Duplicate and cycle check

- Duplicates: none found. Parsers are split by source (15 Visa, 16 Census; Booking passages are captured by 14 and typed by 17/22, no separate parser). Baselines (29, 30) and ablations (31) share the harness (28) rather than re-implementing scoring. Export scripts are created once (12) and reused (38).
- Dependency graph is acyclic. Roots: 01, 02, 04, 05, 06, 07, 09. Longest chain: 02 → 15 → 21 → 28 → 31 → 33 → 38 → 39. Cross-track edges all point from lower-level infrastructure or gates to consumers; no draft depends on a UI or report draft except 37 (bundle after pages exist) and 38/39 (after bundle/report).

## Effort summary (MVP)

| Group | Drafts | Hours |
| --- | --- | --- |
| A Gates | 01–08 | 26–39 |
| B Bootstrap | 09–13 | 22–36 |
| C Collection/extraction | 14–19 | 27–43 |
| D Engine | 20–24 | 28–44 |
| E Valuation/actions | 25–27 | 13–20 |
| F Evaluation | 28–33 | 22–35 |
| G UI | 34–36 | 19–29 |
| H Bundle/submission | 37–39 | 11–17 |
| **Total** | 39 drafts | **168–263** |

## Linear import notes (for Phase 3, not performed)

- Linear MCP status today: `needsAuth`; no team/project/issue reads were possible. Import requires an authenticated, write-capable Linear connection and the user's named team/project.
- Suggested field mapping: title = draft title; description = full draft body; priority P0→Urgent/High, P1→Medium, P2→Low (confirm mapping); estimate = midpoint hours if the team uses estimates; labels only if pre-existing (none created without authorization); dependencies via "blocks/blocked by" relations after creation; stretch drafts excluded unless authorized.
