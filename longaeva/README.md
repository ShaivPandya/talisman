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
