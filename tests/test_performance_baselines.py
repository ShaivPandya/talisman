"""Behavioral contracts for request, stream, database, and worker baselines."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from api import performance, performance_chat, performance_pool
from api.logging_config import JSONFormatter, request_id_var


@pytest.fixture(autouse=True)
def _enable(monkeypatch, caplog):
    monkeypatch.setenv("PERFORMANCE_BASELINES_ENABLED", "true")
    caplog.set_level(logging.INFO, logger="api.performance")


def observations(caplog, event):
    return [record.performance for record in caplog.records if getattr(record, "performance", {}).get("event") == event]


def test_header_clock_stops_before_stream_and_context_reaches_sync_threads(monkeypatch, caplog):
    clock = [10.0]
    monkeypatch.setattr(performance.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(performance, "PROCESS_STARTED", 0.0)
    sent = []

    async def app(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/api/items/{item_id}")
        with performance.ContextThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(performance.count, "db_ms", 2) for _ in range(4)]
            for future in futures:
                future.result()
        performance.count("cache_hit")
        clock[0] = 10.1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        clock[0] = 12
        await send({"type": "http.response.body", "body": b"hello", "more_body": False})

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    asyncio.run(
        performance.PerformanceMiddleware(app)(
            {"type": "http", "method": "GET", "path": "/api/items/secret", "headers": []}, receive, send
        )
    )
    header = dict(sent[0]["headers"])[b"server-timing"].decode()
    assert "db;dur=8.000" in header
    assert "total;dur=100.000" in header
    assert 'cache_hit;desc="1"' in header
    event = observations(caplog, "api_request")[0]
    assert event["duration_ms"] == 2000
    assert event["headers_ms"] == 100
    assert event["route"] == "/api/items/{item_id}"
    assert "secret" not in json.dumps(event)
    assert observations(caplog, "cold_start")[0]["duration_ms"] == 10100
    assert performance.current_timings.get() is None
    assert request_id_var.get("") == ""


def test_overlapping_requests_are_isolated_and_startup_is_once(caplog):
    async def app(scope, receive, send):
        performance.count("db_calls", scope["amount"])
        await asyncio.sleep(0)
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b""})

    async def ignored(*_args):
        return {"type": "http.disconnect"}

    async def run():
        middleware = performance.PerformanceMiddleware(app)
        await asyncio.gather(
            *(
                middleware({"type": "http", "method": "GET", "path": "/api/health", "amount": number}, ignored, ignored)
                for number in range(1, 9)
            )
        )

    asyncio.run(run())
    assert sorted(event["db_calls"] for event in observations(caplog, "api_request")) == list(range(1, 9))
    assert len(observations(caplog, "cold_start")) == 1
    assert observations(caplog, "cold_start")[0]["first_response_is_probe"] is True


def test_pool_context_propagation_does_not_expand_business_policy_scope():
    policy = ContextVar("test_business_policy", default="worker-default")
    token = policy.set("request-policy")
    try:
        with performance.ContextThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(policy.get).result() == "worker-default"
    finally:
        policy.reset(token)


def test_errors_and_early_rejections_have_headers(caplog):
    app = FastAPI()

    @app.middleware("http")
    async def reject(request, next_handler):
        from fastapi.responses import JSONResponse

        if request.url.path == "/api/rejected":
            return JSONResponse({"detail": "denied"}, status_code=403)
        return await next_handler(request)

    @app.get("/api/error")
    def error():
        raise RuntimeError("private content")

    client = TestClient(performance.PerformanceMiddleware(app), raise_server_exceptions=False)
    assert "server-timing" in client.get("/api/rejected").headers
    response = client.get("/api/error")
    assert response.status_code == 500
    assert "server-timing" in response.headers
    assert [event["status"] for event in observations(caplog, "api_request")] == [403, 500]
    assert "private content" not in json.dumps(observations(caplog, "api_request"))


def test_cancelled_stream_is_not_a_completed_response(caplog):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        raise asyncio.CancelledError

    async def ignored(*_args):
        return {"type": "http.disconnect"}

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            performance.PerformanceMiddleware(app)(
                {"type": "http", "method": "POST", "path": "/api/agent/chat"}, ignored, ignored
            )
        )
    assert observations(caplog, "api_request")[0]["outcome"] == "cancelled"
    assert len(observations(caplog, "cold_start")) == 1  # Headers were successfully sent.


def test_disabled_instrumentation_does_not_change_headers_or_emit(monkeypatch, caplog):
    monkeypatch.setenv("PERFORMANCE_BASELINES_ENABLED", "false")
    app = FastAPI()
    app.get("/api/example")(lambda: {"ok": True})
    response = TestClient(performance.PerformanceMiddleware(app)).get("/api/example")
    assert response.json() == {"ok": True}
    assert "server-timing" not in response.headers
    assert observations(caplog, "api_request") == []


def test_structured_json_keeps_numeric_metrics_and_correlation(caplog):
    token = request_id_var.set("request-123")
    try:
        performance.emit("pool_checkout", duration_ms=1.5, metadata={"password": "secret"})
        entry = json.loads(JSONFormatter().format(caplog.records[-1]))
    finally:
        request_id_var.reset(token)
    assert entry["duration_ms"] == 1.5
    assert entry["request_id"] == "request-123"
    assert "metadata" not in entry


def test_timing_cursor_measures_success_and_failure_without_sql(monkeypatch):
    import psycopg

    from api.performance_postgres import timing_cursor_class

    class Cursor:
        def execute(self, sql):
            if sql == "fail":
                raise RuntimeError("failed")
            return self

        def executemany(self, sql, params):
            return self

    timing_cursor_class.cache_clear()
    monkeypatch.setattr(psycopg, "Cursor", Cursor)
    try:
        state = performance.TimingState()
        with performance.timing_context(state):
            cursor = timing_cursor_class()()
            assert cursor.execute("select private") is cursor
            cursor.executemany("insert private", [("secret",)])
            with pytest.raises(RuntimeError):
                cursor.execute("fail")
        assert state.snapshot()["db_calls"] == 3
        assert state.snapshot()["db_ms"] >= 0
        assert "private" not in json.dumps(state.snapshot())
    finally:
        timing_cursor_class.cache_clear()


def test_direct_and_pooled_connections_install_timing_cursor(monkeypatch):
    import psycopg
    import psycopg_pool

    from api import postgres
    from api.performance_postgres import timing_cursor_class

    calls = []
    monkeypatch.setattr(postgres, "require_database_url", lambda *_a: "postgresql://unused")
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: calls.append(kwargs) or SimpleNamespace())

    class Pool:
        check_connection = None

        def __init__(self, **kwargs):
            calls.append(kwargs["kwargs"])

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", Pool)
    postgres._new_direct_connection()
    postgres._new_pool()
    assert len(calls) == 2
    assert all(item["cursor_factory"] is timing_cursor_class() for item in calls)


def test_cache_hit_tiers_and_miss_are_counted_without_keys(monkeypatch, tmp_path):
    from api import cache

    monkeypatch.setattr(cache, "_DISK_CACHE_ENABLED", True)
    monkeypatch.setattr(cache, "_DISK_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(cache, "_gcs_get", lambda *_a: None)
    monkeypatch.setattr(cache, "_gcs_set", lambda *_a: None)
    cache.short_cache.clear()
    state = performance.TimingState()
    with performance.timing_context(state):
        cache.set_cached(cache.short_cache, "private-key", {"value": 1})
        assert cache.get_cached(cache.short_cache, "private-key")["value"] == 1
        cache.short_cache.clear()
        assert cache.get_cached(cache.short_cache, "private-key")["value"] == 1
        assert cache.get_cached(cache.short_cache, "missing") is None
    assert state.counters["cache_memory_hit"] == 1
    assert state.counters["cache_disk_hit"] == 1
    assert state.counters["cache_hit"] == 2
    assert state.counters["cache_miss"] == 1
    assert state.counters["storage_disk_reads"] >= 1
    assert "private" not in json.dumps(state.snapshot())
    cache.short_cache.clear()


def test_gcs_storage_reads_and_failures_are_measured(monkeypatch, tmp_path):
    from api import state_storage

    monkeypatch.setenv("STATE_STORAGE_BACKEND", "gcs")
    blob = SimpleNamespace(download_as_text=lambda **_kw: "hello")
    monkeypatch.setattr(state_storage, "_bucket", lambda: SimpleNamespace(blob=lambda _key: blob))
    state = performance.TimingState()
    with performance.timing_context(state):
        assert state_storage.read_text(tmp_path / "unused", "private-key") == "hello"
        monkeypatch.setattr(blob, "download_as_text", lambda **_kw: (_ for _ in ()).throw(OSError("unavailable")))
        with pytest.raises(OSError):
            state_storage.read_text(tmp_path / "unused", "private-key")
    assert state.counters["storage_gcs_reads"] == 2
    assert state.counters["storage_ms"] >= 0


def test_pool_failure_observed_and_missing_stat_keys_are_zero(monkeypatch, caplog):
    from api import postgres

    pool = SimpleNamespace(name="pool-1", get_stats=lambda: {"pool_size": 2})
    monkeypatch.setattr(postgres, "_POOLS", {"never log this credential": pool})
    monkeypatch.setattr(performance_pool, "start_pool_sampler", lambda: None)
    with pytest.raises(TimeoutError), performance_pool.observe_checkout(pool):
        raise TimeoutError
    performance_pool.log_pool_stats()
    assert observations(caplog, "pool_checkout")[0]["outcome"] == "error"
    stats = observations(caplog, "pool_stats")[0]
    assert stats["requests_waiting"] == 0
    assert stats["connections_num"] == 0
    assert stats["pool_size"] == 2
    assert "credential" not in json.dumps(stats)


def test_sampler_stops_and_never_opens_connections(monkeypatch):
    from api import postgres

    called = threading.Event()
    monkeypatch.setattr(postgres, "_POOLS", {})
    monkeypatch.setattr(postgres, "_get_pool", lambda *_a, **_kw: pytest.fail("sampler opened a pool"))
    monkeypatch.setattr(performance_pool, "log_pool_stats", called.set)
    performance_pool.start_pool_sampler()
    assert called.wait(1)
    thread = performance_pool._thread
    performance_pool.stop_pool_sampler()
    assert thread is not None and not thread.is_alive()


def sse(event, **payload):
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def test_turn_and_continuations_observed_once_with_null_empty_ttft(caplog):
    async def stream():
        performance_chat.begin_chat_round(0)
        yield sse("delta", text="")
        yield sse("tool_call", name="lookup")
        performance_chat.begin_chat_round(1)
        yield sse("delta", text="answer")
        yield sse("done")

    async def run():
        response = performance_chat.observe_chat_response(lambda _started: StreamingResponse(stream()))
        return [chunk async for chunk in response.body_iterator]

    assert len(asyncio.run(run())) == 4
    turns = observations(caplog, "chat_turn")
    rounds = observations(caplog, "chat_round")
    assert len(turns) == 1
    assert turns[0]["first_token_ms"] is not None
    assert turns[0]["outcome"] == "completed"
    assert [item["round_index"] for item in rounds] == [0, 1]
    assert rounds[0]["first_token_ms"] is None
    assert rounds[1]["first_token_ms"] is not None


@pytest.mark.parametrize(
    "terminal,expected", [("error", "failed"), ("cancelled", "cancelled"), ("blocked", "blocked"), ("handoff", None)]
)
def test_turn_failures_and_handoff(caplog, terminal, expected):
    async def stream():
        yield sse(terminal)
        if terminal != "handoff":
            yield sse("done")

    async def run():
        response = performance_chat.observe_chat_response(lambda _started: StreamingResponse(stream()))
        async for _ in response.body_iterator:
            pass

    asyncio.run(run())
    turns = observations(caplog, "chat_turn")
    assert len(turns) == (0 if expected is None else 1)
    if turns:
        assert turns[0]["outcome"] == expected
        assert turns[0]["first_token_ms"] is None


def test_chat_generator_close_records_cancellation(caplog):
    async def stream():
        yield sse("delta", text="partial")
        yield sse("done")

    async def run():
        response = performance_chat.observe_chat_response(lambda _started: StreamingResponse(stream()))
        await anext(response.body_iterator)
        await response.body_iterator.aclose()

    asyncio.run(run())
    assert len(observations(caplog, "chat_turn")) == 1
    assert observations(caplog, "chat_turn")[0]["outcome"] == "cancelled"


def test_queue_delay_uses_existing_timestamps(caplog):
    created = datetime.now(UTC)
    performance_chat.record_queue_delay(
        {"job_type": "agent_chat_turn", "created_at": created, "started_at": created + timedelta(seconds=2)}
    )
    assert observations(caplog, "chat_queue")[0]["duration_ms"] == 2000
