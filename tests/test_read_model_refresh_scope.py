from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from ontology.read_model import TemporalReadModelRepository
from ontology.read_model_scope import DeferredReadModelRefreshMiddleware


class _RecordingConnection:
    def __init__(self, events: list[str]):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql: str, params: object | None = None):
        self.events.append("refresh" if "refresh_changed_ontology_read_models" in sql else "read")
        return self

    def fetchall(self):
        return []

    def commit(self):
        return None


def _app(events: list[str]) -> FastAPI:
    repo = TemporalReadModelRepository(connection_factory=lambda: _RecordingConnection(events))
    app = FastAPI()

    @app.post("/approve")
    def approve():  # sync, so it runs in the threadpool like most routes
        repo.refresh()  # after the proposal
        repo.refresh()  # after the approval
        return {"ok": True}

    @app.post("/approve-then-read")
    def approve_then_read():
        repo.refresh()
        with repo._connect(read_only=True) as conn:
            conn.execute("SELECT * FROM ontology_current_operational_object_read_model")
        repo.refresh()
        return {"ok": True}

    @app.post("/stream")
    def stream():
        def body():
            yield b"a"
            repo.refresh()
            yield b"b"

        return StreamingResponse(body())

    @app.post("/fails")
    def fails():
        repo.refresh()
        raise RuntimeError("boom")

    app.add_middleware(DeferredReadModelRefreshMiddleware)

    @app.middleware("http")
    async def mark_response_start(request, call_next):
        response = await call_next(request)
        events.append("response")
        return response

    return app


@pytest.fixture
def postgres_state(monkeypatch):
    monkeypatch.setenv("STATE_DB_BACKEND", "postgres")


def test_two_refreshes_in_a_request_run_once_before_the_response(postgres_state):
    events: list[str] = []

    response = TestClient(_app(events)).post("/approve")

    assert response.status_code == 200
    assert events == ["refresh", "response"]


def test_a_read_in_the_same_request_sees_its_own_writes(postgres_state):
    events: list[str] = []

    TestClient(_app(events)).post("/approve-then-read")

    assert events == ["refresh", "read", "refresh", "response"]


def test_refresh_requested_while_streaming_runs_when_the_request_ends(postgres_state):
    events: list[str] = []

    response = TestClient(_app(events)).post("/stream")

    assert response.content == b"ab"
    assert events.count("refresh") == 1


def test_refresh_still_runs_when_the_route_fails(postgres_state):
    events: list[str] = []

    response = TestClient(_app(events), raise_server_exceptions=False).post("/fails")

    assert response.status_code == 500
    assert events.count("refresh") == 1


def test_outside_postgres_refreshes_run_immediately(monkeypatch):
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setenv("TALISMAN_ALLOW_SQLITE_STATE", "true")
    events: list[str] = []

    TestClient(_app(events)).post("/approve")

    assert events == ["refresh", "refresh", "response"]
