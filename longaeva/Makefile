SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
PROJECT ?= longaeva
export COMPOSE_PROJECT_NAME ?= $(PROJECT)

# Mount the package root so the isolation guard (LON-12) can see README,
# .exportignore, frontend/, data/, and docs/ (the API image only contains backend/).
GUARD_MOUNT := -v "$(CURDIR):/srv/longaeva-src:ro" -e LONGAEVA_GUARD_ROOT=/srv/longaeva-src

COMPOSE_BUILD_ARGS ?=
WEB_CHECK_BUILD_ARGS ?=
GUARD_ARGS ?=

.PHONY: help up down logs check check-web check-local seed lock build openapi guard collect engine-benchmark submit-run replay export verify-export

help:
	@echo "Targets: up down logs check check-web check-local guard seed lock build openapi collect engine-benchmark submit-run replay export verify-export"

up:
	$(COMPOSE) up --build -d --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

build:
	$(COMPOSE) build $(COMPOSE_BUILD_ARGS)

# Build images, ensure db is up, run lint/type/tests inside the api image against longaeva_test.
# Frontend lint + unit tests run in the Node check stage (NR-03).
check: build
	$(COMPOSE) up -d --wait db
	$(COMPOSE) run --rm --no-deps \
		$(GUARD_MOUNT) \
		-e DATABASE_URL=postgresql://longaeva:longaeva@db:5432/longaeva \
		-e LONGAEVA_REQUIRE_DB=1 \
		-e LONGAEVA_TEST_DB=longaeva_test \
		api sh -c 'scripts/check.sh'
	$(MAKE) check-web

# Frontend lint + Vitest inside the Node image (no host Node required).
check-web:
	docker build $(WEB_CHECK_BUILD_ARGS) --target check -t $(PROJECT)-web-check ./frontend
	docker run --rm $(PROJECT)-web-check sh -c 'npm run lint && npm test'

# Isolation guard only (LON-12). Uses the same root mount as ``check``.
# GUARD_ARGS=--strict is for an unpacked export copy (LON-24).
guard: build
	$(COMPOSE) run --rm --no-deps \
		$(GUARD_MOUNT) \
		api python -m longaeva_app.cli export-check $(GUARD_ARGS)

check-local:
	cd backend && \
	  if [[ ! -d .venv ]]; then python3.12 -m venv .venv; fi && \
	  .venv/bin/pip install -q -r requirements-dev.txt -c requirements.lock && \
	  LONGAEVA_REQUIRE_DB=1 DATABASE_URL=$${DATABASE_URL:-postgresql://longaeva:longaeva@127.0.0.1:55432/longaeva} \
	    LONGAEVA_GUARD_ROOT="$(CURDIR)" \
	    .venv/bin/bash scripts/check.sh

seed:
	$(COMPOSE) run --rm --no-deps api python -m longaeva_app.cli seed-demo

# Collect curated manifests into the Compose artifact volume + database (LON-13).
# Usage: make collect ARGS='--only visa:release:FY2026Q3'
# Passes SEC_USER_AGENT via compose --env-file when .env exists (value never printed).
collect:
	$(COMPOSE) up -d --wait db
	$(COMPOSE) $(if $(wildcard .env),--env-file .env,) run --rm --no-deps \
		-e DATABASE_URL=postgresql://longaeva:longaeva@db:5432/longaeva \
		api sh -c 'alembic upgrade head && python -m longaeva_app.cli collect $(ARGS)'

# Time Visa Monte Carlo paths (LON-19 / NR-01). Uses the API image's Python + NumPy.
engine-benchmark: build
	$(COMPOSE) run --rm --no-deps api python -m longaeva_app.cli engine-benchmark $(ARGS)

# Submit a run (LON-23). Example: make submit-run ARGS='--origin 2024-07-23 --n-paths 64 --inline'
submit-run:
	$(COMPOSE) up -d --wait db
	$(COMPOSE) $(if $(wildcard .env),--env-file .env,) run --rm --no-deps \
		-e DATABASE_URL=postgresql://longaeva:longaeva@db:5432/longaeva \
		api sh -c 'alembic upgrade head && python -m longaeva_app.cli submit-run $(ARGS)'

# Replay a saved run. Example: make replay RUN=<uuid>
replay:
	$(COMPOSE) $(if $(wildcard .env),--env-file .env,) run --rm --no-deps \
		-e DATABASE_URL=postgresql://longaeva:longaeva@db:5432/longaeva \
		-e LLM_PROVIDER= \
		api python -m longaeva_app.cli replay $(RUN)

# Submission ZIP (LON-24). Optional: make export ARGS='--output /tmp/longaeva.zip'
export:
	./scripts/export_submission.sh $(ARGS)

# Verify a ZIP in /tmp. Example: make verify-export ZIP=dist/foo.zip LOG=/tmp/early-export.md ARGS='--keep'
verify-export:
	@test -n "$(ZIP)" || (echo "ZIP=path is required" >&2; exit 2)
	./scripts/verify_export.sh --zip "$(ZIP)" $(if $(LOG),--log "$(LOG)",) $(ARGS)

openapi:
	$(COMPOSE) run --rm --no-deps \
		-v "$(CURDIR)/docs:/out" \
		api python -m longaeva_app.cli export-openapi --output /out/openapi.json

# Compile a lockfile inside python:3.12-slim so the host needs no pip-tools.
lock:
	docker run --rm -v "$(CURDIR)/backend:/work" -w /work \
	  python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3 \
	  sh -c 'pip install -q "pip-tools>=7,<8" && pip-compile --strip-extras -o requirements.lock requirements-dev.txt'
