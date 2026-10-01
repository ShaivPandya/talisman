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
- Web placeholder: http://127.0.0.1:3000/
- Postgres (host): `127.0.0.1:55432` user/pass/db `longaeva`

Optional: copy `.env.example` to `.env` and set `SEC_USER_AGENT` for live EDGAR fetches
(LON-1). Compose does not require a `.env` file.

Stop with `make down`.

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

Domain schema, Vite frontend, isolation guards, and demo data arrive in later issues
(LON-10, LON-11, LON-12, LON-37).
