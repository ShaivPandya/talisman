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
a placeholder web page.

- API health: http://127.0.0.1:8000/health
- OpenAPI UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json (snapshot also at `docs/openapi.json`)
- Web placeholder: http://127.0.0.1:3000/
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
database. The isolation guard (LON-12) runs as part of pytest.

```bash
make guard
```

Runs only the isolation guard (`python -m longaeva_app.cli export-check`) against the
export file set.

## Isolation guard (LON-12)

[`.exportignore`](.exportignore) is the exclusion manifest for the future submission
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
[`docs/limitations.md`](docs/limitations.md).

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
calibration arrives in LON-20.

Register the built-in company without import-time side effects:

```python
from longaeva_app.companies import register_default_companies
register_default_companies()  # idempotent; registers "visa"
```

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

Vite frontend and demo data arrive in later issues (LON-11, LON-37).
