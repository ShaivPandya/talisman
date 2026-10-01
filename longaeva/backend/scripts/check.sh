#!/usr/bin/env bash
# Run lint, type-check, and tests. Invoked by `make check` and `make check-local`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== ruff check =="
ruff check .
echo "== ruff format --check =="
ruff format --check .
echo "== mypy =="
mypy --config-file pyproject.toml longaeva_app tests
echo "== pytest =="
pytest -q
