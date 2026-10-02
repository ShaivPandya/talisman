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
database.

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

Vite frontend, isolation guards, and demo data arrive in later issues (LON-11, LON-12, LON-37).
