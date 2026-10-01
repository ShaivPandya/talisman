SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
PROJECT ?= longaeva
export COMPOSE_PROJECT_NAME ?= $(PROJECT)

.PHONY: help up down logs check check-local seed lock build

help:
	@echo "Targets: up down logs check check-local seed lock build"

up:
	$(COMPOSE) up --build -d --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

build:
	$(COMPOSE) build

# Build images, ensure db is up, run lint/type/tests inside the api image against longaeva_test.
check: build
	$(COMPOSE) up -d --wait db
	$(COMPOSE) run --rm --no-deps \
		-e DATABASE_URL=postgresql://longaeva:longaeva@db:5432/longaeva \
		-e LONGAEVA_REQUIRE_DB=1 \
		-e LONGAEVA_TEST_DB=longaeva_test \
		api sh -c 'scripts/check.sh'

check-local:
	cd backend && \
	  if [[ ! -d .venv ]]; then python3.12 -m venv .venv; fi && \
	  .venv/bin/pip install -q -r requirements-dev.txt -c requirements.lock && \
	  LONGAEVA_REQUIRE_DB=1 DATABASE_URL=$${DATABASE_URL:-postgresql://longaeva:longaeva@127.0.0.1:55432/longaeva} \
	    .venv/bin/bash scripts/check.sh

seed:
	$(COMPOSE) run --rm --no-deps api python -m longaeva_app.cli seed-demo

# Compile a lockfile inside python:3.12-slim so the host needs no pip-tools.
lock:
	docker run --rm -v "$(CURDIR)/backend:/work" -w /work \
	  python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3 \
	  sh -c 'pip install -q "pip-tools>=7,<8" && pip-compile --strip-extras -o requirements.lock requirements-dev.txt'
