"""OpenAPI contract snapshot tests."""

from __future__ import annotations

import json
from pathlib import Path

from longaeva_app.api.main import app
from longaeva_app.api.schemas import OPENAPI_CONTRACT_SCHEMAS

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = PACKAGE_ROOT / "docs" / "openapi.json"

REQUIRED_SCHEMA_NAMES = {model.__name__ for model in OPENAPI_CONTRACT_SCHEMAS}


def test_openapi_includes_contract_schemas() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    names = set(schema.get("components", {}).get("schemas", {}))
    missing = REQUIRED_SCHEMA_NAMES - names
    assert not missing, f"Missing OpenAPI schemas: {sorted(missing)}"


def test_openapi_snapshot_matches_committed_file() -> None:
    if not SNAPSHOT_PATH.exists():
        # Container builds without a docs mount skip until `make openapi` writes the file.
        # With LONGAEVA_REQUIRE_DB / compose docs mount, the file is present.
        if not SNAPSHOT_PATH.parent.exists():
            return
        raise AssertionError(
            f"Missing {SNAPSHOT_PATH}; run `make openapi` or "
            "`python -m longaeva_app.cli export-openapi` to refresh the contract."
        )
    app.openapi_schema = None
    current = app.openapi()
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(current, sort_keys=True)) == json.loads(json.dumps(expected, sort_keys=True))
