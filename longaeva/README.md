# Longaeva

Standalone Visa business-simulation package for the Longaeva AI Hackathon Stage 2.
This directory is self-contained: it does not import Talisman modules, share Talisman's
database, or require Talisman auth.

**Local review only — there is no authentication.** Bind ports to `127.0.0.1` (Compose
defaults). Do not expose this stack on a public network.

## Quickstart (one command)

From this directory, with Docker Desktop running:

```bash
make up
```

That starts Postgres, runs Alembic migrations, brings up the API and worker, and serves
the Vite-built web app.

- API health: http://127.0.0.1:8000/health
- OpenAPI UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json (snapshot also at `docs/openapi.json`)
- Web app: http://127.0.0.1:3000/ (run list at `/runs`)
- Postgres (host): `127.0.0.1:55432` user/pass/db `longaeva`

Optional: copy `.env.example` to `.env` and set `SEC_USER_AGENT` for live EDGAR fetches
(LON-1). Compose does not require a `.env` file.

Stop with `make down`.

Visa driver and accounting definitions (LON-2) are settled in
[`docs/definitions.md`](docs/definitions.md); canonical field names live in
`backend/longaeva_app/companies/visa/definitions.py`.

Two reconciled historical starting states (LON-3) live at
`data/fixtures/states/visa_2024-07-23.json` and
`data/fixtures/states/visa_2025-10-28.json`, with retained EDGAR originals under
`data/fixtures/states/sources/` and the gate report in
[`docs/gates/starting-states.md`](docs/gates/starting-states.md).

The Visa release / 10-Q table parser (LON-14) lives in
`backend/longaeva_app/extract/visa_tables.py`. Retained extras are under
`data/fixtures/visa_releases/`; regenerate with
`python -m longaeva_app.cli parse-visa --write`. See
[`docs/visa-parser.md`](docs/visa-parser.md).

Census MARTS vintage gate (LON-5): parsed advance releases
`data/fixtures/census/adv2406.csv` and `adv2506.csv`, release calendar
`data/fixtures/census/release_calendar.csv`, retained PDFs/XLSX under
`data/fixtures/census/sources/`, and the gate report in
[`docs/gates/census.md`](docs/gates/census.md). Every Visa origin in
`data/fixtures/origins.csv` now has Census timing columns.

Booking Holdings family gate (LON-4): observation fixtures
`data/fixtures/observations/booking_2024-05-02.json` and
`booking_2025-10-28.json`, release calendar
`data/fixtures/booking/release_calendar.csv`, retained Ex. 99.1 originals under
`data/fixtures/booking/sources/`, and the gate report in
[`docs/gates/booking.md`](docs/gates/booking.md). `origins.csv` now carries
Booking age-in-weeks, same-day margin, guidance-covers-target and fallback
accession columns.

Benchmark and price data decision (LON-6): no free API key. Primary benchmark is
the labeled FRED `SP500` + Shiller dividend approximation; Ken French daily
`Mkt-RF + RF` is the secondary reference (never relabeled as the S&P 500). Visa
daily prices are blocked, so buy-and-hold scoring is `not run` until a personal
Tiingo key is added. Manifest
[`data/manifest/benchmarks.yaml`](data/manifest/benchmarks.yaml), metadata-only
probe [`data/fixtures/benchmarks/probe.json`](data/fixtures/benchmarks/probe.json),
and gate report [`docs/gates/benchmarks.md`](docs/gates/benchmarks.md).

Guidance availability and analyst-estimate confirmation (LON-7): 16 of 19 origins have
a recoverable next-quarter company-guidance outlook (11 earnings decks from
FY2024Q1; 5 Visa-posted FactSet transcripts in the extension window). Three gaps
(FY2022Q2, FY2023Q3, FY2023Q4). Analyst estimates:
consensus unavailable (no licensed free historical source). Manifest
[`data/manifest/visa_ir.yaml`](data/manifest/visa_ir.yaml), fixtures under
[`data/fixtures/guidance/`](data/fixtures/guidance/), sample observations
`data/fixtures/observations/visa_guidance_*.json`, and gate report
[`docs/gates/guidance.md`](docs/gates/guidance.md). Originals stay in
`var/cache/visa_ir/` (fetch by script; never bundled).

Second-wave disclosure families (LON-8): **United** (airline), **Costco**
(retailer) and **PayPal** (pure processor) selected as context-first external
families. Timing table
[`data/fixtures/second_wave/timing.csv`](data/fixtures/second_wave/timing.csv),
release scan
[`data/fixtures/second_wave/release_scan.csv`](data/fixtures/second_wave/release_scan.csv),
retained Ex. 99.1/99.2 originals under
[`data/fixtures/second_wave/sources/`](data/fixtures/second_wave/sources/),
observation fixtures `data/fixtures/observations/{united,costco,paypal}_*.json`,
manifest [`data/manifest/second_wave.yaml`](data/manifest/second_wave.yaml), and
gate report [`docs/gates/second-wave.md`](docs/gates/second-wave.md). Mastercard /
Amex / JPMorgan are out of family (stretch S6). Does not change origin eligibility.

## Core read API (LON-10)

Read-only list/detail endpoints (writes arrive in later issues):

| Method | Path |
| --- | --- |
| GET | `/sources`, `/sources/{id}`, `/sources/{id}/passages` |
| GET | `/observations`, `/observations/{id}` |
| GET | `/parameter-sets`, `/parameter-sets/{id}` |
| GET | `/scenarios`, `/scenarios/{id}` |
| GET | `/runs`, `/runs/{id}` |
| GET | `/forecasts?kind=`, `/forecasts/{id}` |
| GET | `/evaluation-results` |

Forecast rows are immutable in the database; PUT/PATCH/DELETE on `/forecasts/{id}` return 405.

Refresh the committed OpenAPI snapshot after schema changes:

```bash
make openapi
```

## Checks

```bash
make check
```

Runs ruff, mypy, and pytest inside the API image against a disposable `longaeva_test`
database, then frontend lint + Vitest in a Node image. The isolation guard (LON-12)
runs as part of pytest. Frontend type-check is `tsc -b` inside `npm run build` (Compose
web image).

```bash
make guard
```

Runs only the isolation guard (`python -m longaeva_app.cli export-check`) against the
export file set. On an unpacked ZIP copy, use `make guard GUARD_ARGS=--strict`.

## Export and verification (LON-24)

Build a deterministic submission ZIP from the `.exportignore` file set (top-level
`longaeva/` folder). The builder runs the isolation guard first and refuses to write
a ZIP if it finds anything. Identity strings from `git config user.name` / `user.email`
are treated as forbidden and never printed.

```bash
make export
# -> dist/longaeva-export-<UTC>-<sha7>[-dirty].zip and a sibling .sha256
```

Verify in a temporary directory under `/tmp` (outside this checkout). The verifier
uses its own Compose project and ports **18000 / 13000 / 15432** so a developer stack
on 8000 / 3000 / 55432 is left alone.

```bash
make verify-export ZIP=dist/longaeva-export-<file>.zip \
  LOG=/absolute/path/outside/the/package/early-export.md \
  ARGS='--no-cache --keep'
```

Steps: checksum, unpack, listing checks (no `.git` / `.env` / `node_modules`, no
developer home paths), `make guard GUARD_ARGS=--strict`, fresh `git init` whose
tracked-file count equals the unpacked count, `make check`, `make up`, API and web
smoke, worker-executed runs plus replay (including after a restart). `--keep` leaves
the stack and temp dir; default teardown is `docker compose down -v --rmi local`.

The validation log is **not** part of the package. Write it outside `longaeva/`
(Talisman: `docs/hackathon/planning/validation/`). Flags: `--skip-tests` (iteration
only), `--keep`, `--no-cache`.

## Frontend (LON-11)

Compose `web` serves the production Vite build through nginx on port 3000 and proxies
`/api/` to the API (prefix stripped).

Local Vite (API already running on 8000):

```bash
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173/ — `/api` is proxied to the API. There is no authentication.

The Runs page lists saved runs and charts quantiles from `GET /runs/{id}/results`.
Submit runs with `make submit-run`; the Scenarios page will add in-app submit later.

See [`docs/reuse-notes.md`](docs/reuse-notes.md) for chart provenance.

## Isolation guard (LON-12)

[`.exportignore`](.exportignore) is the exclusion manifest for the submission
ZIP (LON-24). The guard scans every path that would ship and fails on:

- out-of-package Python/JS imports, path escapes, and absolute developer paths
- symlinks, non-regular files, and `.env` files other than `.env.example`
- secret-shaped strings and leaked values of local secret keys / `SEC_USER_AGENT`

CLI:

```bash
python -m longaeva_app.cli export-check            # exit 1 on findings
python -m longaeva_app.cli export-check --list      # print export paths
python -m longaeva_app.cli export-check --strict    # also fail if excluded paths exist
```

`--strict` is for the unpacked export copy (LON-24), not the developer working tree
(where a gitignored `.env` for `SEC_USER_AGENT` is expected). Personal-data checklist:
[`docs/limitations.md`](docs/limitations.md). `make export` / `make verify-export`
are documented above.

## Visa engine (LON-19)

Pure NumPy quarterly Monte Carlo for Visa operating metrics. Company code never
generates random numbers; the engine samples correlated factors and checks
accounting identities on every path.

```bash
cd backend
.venv/bin/python - <<'PY'
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.starting_state import load_fixture, required_fixture_paths, to_starting_state
from longaeva_app.engine import simulate, summarize_paths

model = VisaModel()
fixture = load_fixture(required_fixture_paths()[0])
result = simulate(
    model,
    to_starting_state(fixture),
    model.default_parameters(),
    origin=FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter),
    seed=42,
    n_paths=5000,
    n_quarters=4,
)
print(summarize_paths(result, metrics=("net_revenue", "operating_profit_ex_special_items"))[0])
PY

# NR-01 timing (JSON to stdout)
.venv/bin/python -m longaeva_app.cli engine-benchmark --repeats 3
```

Model specification: [`docs/model-spec.md`](docs/model-spec.md). Ablation switches:
`service_lag` (default on) and `pool_mix` (default off). Defaults are uncalibrated;
use LON-20 calibration for forecasts.

Register the built-in company without import-time side effects:

```python
from longaeva_app.companies import register_default_companies
register_default_companies()  # idempotent; registers "visa"
```

## Calibration (LON-20)

Chronological fit of free parameters, seasonal ratios, shock scales and correlations
as-of an origin cutoff. Ensemble members (last 4q / last 8q / full history) get
inverse-MSE weights that sum to 1; the pooled set is what runs use today. Pandemic
quarters FY2020Q2–FY2021Q4 are excluded from estimation. Details:
[`docs/model-spec.md`](docs/model-spec.md) §6.1.

```bash
# Host venv (Compose mounts data/ read-only; --write needs the host)
make calibrate ARGS='--write'
make calibrate ARGS='--origin 2024-07-23 --persist --json'

# Then submit against the calibrated scenario UUID printed by --persist
make submit-run ARGS='--origin 2024-07-23 --scenario <uuid> --n-paths 2000 --inline'
```

Committed artifacts: `data/calibration/visa_2024-07-23.json` and
`data/calibration/visa_2025-10-28.json`.

## Runs and replay (LON-23)

Submit a Visa run, execute it on the worker, fetch summaries, and replay without
an LLM. Details: [`docs/runs-and-replay.md`](docs/runs-and-replay.md).

```bash
# Inline (no worker): creates an uncalibrated baseline if --scenario is omitted
make submit-run ARGS='--origin 2024-07-23 --n-paths 64 --inline'

# Any buildable origins.csv candidate also works (LON-27 state builder)
make submit-run ARGS='--origin 2024-01-25 --n-paths 64 --inline'

# Replay a saved run (LLM_PROVIDER unset)
make replay RUN=<run-uuid>
```

API:

| Method | Path |
| --- | --- |
| POST | `/runs` (202 queued) |
| GET | `/runs`, `/runs/{id}`, `/runs/{id}/results` |
| POST | `/runs/{id}/replay` |
| POST | `/runs/{id}/forecasts` `{ "kind": "retrospective" \| "prospective" }` |

Committed LON-3 fixtures and other buildable candidate/prospective origins are
runnable. Forecast archive is explicit and refuses uncalibrated defaults.

## Evaluation (LON-27)

Score the full model across eligible origins: next-quarter levels and drivers,
80% coverage, CRPS/WIS, plus a separate four-quarter table. Details:
[`docs/evaluation.md`](docs/evaluation.md).

```bash
make evaluate ARGS='--output /out/visa_full_model.json'
make evaluate ARGS='--origin 2024-07-23 --origin 2025-10-28 --n-paths 256 --json'
```

Committed results: `data/evaluation/visa_full_model.json` (16 scored, 2 excluded).

## Collector (LON-13)

Curated manifests under [`data/manifest/`](data/manifest/) drive polite fetches of
EDGAR filings, Census MARTS advance PDFs, and Visa IR CDN decks/transcripts.

```bash
# Regenerate visa/booking/census YAML from committed fixtures
python -m longaeva_app.cli build-manifests

# Collect (Compose db + artifact volume). Requires SEC_USER_AGENT in the environment.
make collect ARGS='--only visa:release:FY2026Q3 --only visa:release:FY2017Q1'
make collect ARGS='--manifest census.yaml --only census:marts:adv2406'
make collect ARGS='--manifest visa_ir.yaml --only visa_ir:deck:FY2024Q3'
```

Rules:

- **Cache:** a previously collected key whose original is still on disk is skipped
  unless `--refresh` is passed.
- **Dedup:** identical bytes reuse the existing `source` row and add a
  `source_retrieval` row only.
- **Supersede:** `--refresh` with changed bytes creates a new `source` with
  `supersedes_id` pointing at the prior row for that key.
- **Unavailable:** HTTP 403 and JavaScript-challenge pages are logged as
  unavailable and never bypassed (DR-09). `visa_ir:quarterly_html` is marked
  unavailable in the manifest.
- **Timestamps:** EDGAR `publication_ts` is the filing-index Accepted time;
  Census uses the printed release line; IR uses HTTP `Last-Modified`.
  `retrieval_ts` is always later.
- **Passages:** HTML/PDF text is stored in `document_text` with page-local spans
  and a generated normalized `text_hash` for DR-08 dedup.

## Extraction and review (LON-16)

Passage-only LLM extraction into pending observations, plus a versioned accept /
reject / correct workflow. With `LLM_PROVIDER` unset, `POST /observations/extract`
returns 503 and no provider client is created. Setup, cache, and the manual
check: [`docs/extraction.md`](docs/extraction.md).

```bash
make extract ARGS='--status'
make extract ARGS='--source-key booking:release:0001075531-25-000050 --contains "Room nights grew"'
```

Pending or rejected observation rows cannot back `POST /runs`. Replay is unchanged.
Extraction does not write parameter sets.

## Paired scenarios (LON-22)

Two interventions, paired runs on one seed, path-wise comparison from saved
`paths.npz`, and model-conditional attribution. Details:
[`docs/scenarios.md`](docs/scenarios.md).

```bash
make pair-run ARGS='--origin 2024-07-23 --n-paths 5000 --inline'
```

| Method | Path |
| --- | --- |
| POST | `/scenarios` (interventions and optional parameter overrides) |
| POST | `/scenarios/pair-runs` (202; shared seed, variants store `baseline_run_id`) |
| GET | `/scenarios/comparison?run_id=&baseline_run_id=` |
| GET | `/scenarios/attribution?run_id=&baseline_run_id=&metric=` |

A mix shift leaves total payments volume equal to the baseline on every path.
The forecast archive still refuses intervention runs. Charts are LON-34.

## Seed

```bash
make seed
```

Stub until LON-37 (prints that no demo dataset exists yet).

## Local process mode (optional)

```bash
cp .env.example .env   # set DATABASE_URL to the Compose db if using make up for Postgres only
make up                # or: docker compose up -d --wait db
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt -c requirements.lock
.venv/bin/alembic upgrade head
.venv/bin/uvicorn longaeva_app.api.main:app --reload --port 8000
# other terminal:
.venv/bin/python -m longaeva_app.worker.loop
```

## Layout

See `docs/reuse-notes.md` for Talisman pattern provenance (copied/adapted, never imported).

Demo data arrives in LON-37.
