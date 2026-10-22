"""Fresh-process checks for the API's import and readiness boundaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sentry_enabled", [False, True])
def test_import_defers_request_dependencies_and_never_connects(sentry_enabled):
    env = dict(os.environ)
    env.update(
        PYTHON_DOTENV_DISABLED="1",
        ENVIRONMENT="production",
        STATE_DB_BACKEND="postgres",
        DATABASE_URL="",
        STATE_STORAGE_BACKEND="local",
        SENTRY_ENABLED="true" if sentry_enabled else "false",
        SENTRY_DSN="https://public@example.invalid/1",
        PERFORMANCE_BASELINES_ENABLED="true",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sqlite3
import sys
import api.postgres as postgres

connections = []
def forbidden_connection(*args, **kwargs):
    connections.append(True)
    raise AssertionError("API startup must not open a database connection")

sqlite3.connect = forbidden_connection
postgres.connect = forbidden_connection
postgres._new_direct_connection = forbidden_connection

import sentry_sdk
original_init = sentry_sdk.init
def offline_init(*args, **kwargs):
    kwargs.update(transport=lambda event: None, shutdown_timeout=0)
    return original_init(*args, **kwargs)
sentry_sdk.init = offline_init

import api.main
assert not connections, connections
assert not api.main.get_degraded_modules(), api.main.get_degraded_modules()
deferred = {"pandas", "numpy", "api.agent_tools", "anthropic", "openai", "google.genai"}
assert not deferred.intersection(sys.modules), deferred.intersection(sys.modules)

from fastapi.testclient import TestClient
with TestClient(api.main.app) as client:
    assert {"pandas", "numpy", "api.agent_tools"}.issubset(sys.modules)
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/portfolio").status_code == 401
assert not connections, connections
""",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    cold_starts = [event for event in events if event.get("event") == "cold_start"]
    assert len(cold_starts) == 1
    assert cold_starts[0]["first_response_is_probe"] is True


def test_failed_warmup_prevents_readiness_and_closes_pools(monkeypatch):
    from api import main, postgres

    closed = []

    def fail_warmup():
        raise RuntimeError("warmup failed")

    monkeypatch.setattr(main, "_warm_request_imports", fail_warmup)
    monkeypatch.setattr(postgres, "close_pools", lambda: closed.append(True))
    with pytest.raises(RuntimeError, match="warmup failed"), TestClient(main.app):
        pytest.fail("startup must fail before admitting requests")
    assert closed == [True]
