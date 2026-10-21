"""Opt-in checks against an isolated local Postgres schema (TEST_POSTGRES_URL)."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.types.json import Jsonb

from api import job_event_notifications, job_events, job_queue, postgres
from api.performance import TimingState, timing_context
from api.routers import agent as agent_router
from scripts.benchmark_agent_chat_streaming import disposable_job_database
from scripts.benchmark_agent_chat_streaming import test_database_url as local_database_url


@pytest.fixture(scope="module")
def job_database():
    if not os.getenv("TEST_POSTGRES_URL"):
        pytest.skip("TEST_POSTGRES_URL must point at a disposable local Postgres + pgvector database")
    with disposable_job_database(local_database_url()) as dsn:
        yield dsn


@pytest.fixture
def pg_jobs(job_database, monkeypatch):
    job_event_notifications.close_job_event_listeners()
    postgres.close_pools()
    monkeypatch.setenv("DATABASE_URL", job_database)
    monkeypatch.setenv("ASYNC_JOB_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "0")
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("PERFORMANCE_BASELINES_ENABLED", "true")
    monkeypatch.setenv("ASYNC_JOB_SUCCESS_READ_AUDIT_ENABLED", "false")
    yield job_database
    job_event_notifications.close_job_event_listeners()
    postgres.close_pools()


def _new_job():
    return job_queue.create_job(
        "agent_chat_turn",
        payload={"session_id": "pg-session", "message": "x" * 100_000, "actor": {"actor_id": "reader"}},
    )["job_id"]


def _ready(watch):
    with watch.hub.condition:
        assert watch.hub.condition.wait_for(lambda: watch.hub.ready, timeout=5)


def test_snapshot_uses_one_narrow_read_and_preserves_empty_and_terminal_jobs(pg_jobs):
    job_id = _new_job()
    with postgres.connect() as conn:
        conn.execute(
            "UPDATE async_jobs SET result_json = %s WHERE job_id = %s", (Jsonb({"large": "x" * 100_000}), job_id)
        )
        conn.commit()
    state = TimingState()
    with timing_context(state):
        row, events = job_events.read_job_events_snapshot(job_id)
    assert state.snapshot()["db_calls"] == 1
    assert row["payload_json"] == {"session_id": "pg-session", "actor": {"actor_id": "reader"}}
    assert row["result_json"] is None and events == []
    with timing_context(TimingState()):
        assert job_queue.get_job_status(job_id) == "queued"
    assert job_events.read_job_events_snapshot("unknown") == (None, [])
    job_queue.complete_job(job_id, {"answer": "finished"})
    row, events = job_events.read_job_events_snapshot(job_id)
    assert row["result_json"] == {"answer": "finished"} and events == []


def test_snapshot_event_pages_keep_order_and_cursor(pg_jobs):
    job_id = _new_job()
    for index in range(7):
        job_events.append_job_event(job_id, "delta", {"text": str(index)})
    row, events = job_events.read_job_events_snapshot(job_id, after_seq=2, limit=3)
    assert row["job_id"] == job_id
    assert [event["seq"] for event in events] == [3, 4, 5]
    assert [event["payload"]["text"] for event in events] == ["2", "3", "4"]
    assert all(isinstance(event["created_at"], str) for event in events)


def test_notification_commit_wakes_request_and_does_not_consume_pool_slot(pg_jobs):
    job_id = _new_job()
    with job_event_notifications.watch_job_events(job_id) as watch:
        _ready(watch)
        row, _ = job_events.read_job_events_snapshot(job_id)
        watch.record(row, 0, watch.generation)
        with psycopg.connect(pg_jobs) as writer, ThreadPoolExecutor(max_workers=1) as executor:
            writer.execute(
                """WITH inserted AS (
                       INSERT INTO async_job_events (job_id, seq, event_type, payload_json, created_at)
                       VALUES (%s, 1, 'delta', '{"text":"committed"}', now()) RETURNING seq
                   ) SELECT pg_notify('talisman_job_events', json_build_array(%s::text, seq)::text) FROM inserted""",
                (job_id, job_id),
            )
            future = executor.submit(agent_router.get_agent_chat_async_events, job_id, after_seq=0, wait_ms=2000)
            time.sleep(0.04)
            assert not future.done(), "uncommitted events must not be visible"
            writer.commit()
            response = future.result(timeout=2)
            assert response["events"][0]["payload"] == {"text": "committed"}
            assert response["session_id"] == "pg-session"
            assert response["next_seq"] == 1
        assert postgres._get_pool().get_stats()["pool_available"] >= 1
        with psycopg.connect(pg_jobs, autocommit=True) as admin:
            assert (
                admin.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = 'talisman-job-events'"
                ).fetchone()[0]
                == 1
            )


def test_poll_queries_stay_below_four_per_second(pg_jobs):
    job_id = _new_job()
    with job_event_notifications.watch_job_events(job_id) as watch:
        _ready(watch)
    # Pool/pgvector setup is warm before counting request queries.
    state = TimingState()
    started = time.monotonic()
    with timing_context(state):
        response = agent_router.get_agent_chat_async_events(job_id, after_seq=0, wait_ms=1200)
    elapsed = time.monotonic() - started
    assert response["events"] == []
    assert state.snapshot()["db_calls"] / elapsed < 4


def test_same_cursor_wait_avoids_an_extra_read_and_checks_again_on_reconnect(pg_jobs):
    job_id = _new_job()
    with job_event_notifications.watch_job_events(job_id) as watch:
        _ready(watch)
        row, _ = job_events.read_job_events_snapshot(job_id)
        watch.record(row, 0, watch.generation)
        assert watch.cached_job(0) is not None
        generation = watch.generation
        with psycopg.connect(pg_jobs, autocommit=True) as admin:
            pid = admin.execute(
                "SELECT pid FROM pg_stat_activity WHERE application_name = 'talisman-job-events'"
            ).fetchone()[0]
            admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        with watch.hub.condition:
            assert watch.hub.condition.wait_for(lambda: watch.hub.generation > generation, timeout=3)
        assert watch.cached_job(0) is None
        _ready(watch)
        job_events.append_job_event(job_id, "delta", {"text": "after reconnect"})
        response = agent_router.get_agent_chat_async_events(job_id, after_seq=0, wait_ms=1000)
        assert response["events"][0]["payload"] == {"text": "after reconnect"}


def test_http_event_response_replays_persisted_postgres_events(auth_client, pg_jobs):
    job_id = _new_job()
    job_events.append_job_event(job_id, "delta", {"text": "visible over HTTP"})
    job_events.append_job_event(job_id, "done", {"session_id": "pg-session", "usage": {}})
    job_queue.complete_job(job_id, {"session_id": "pg-session"})
    response = auth_client.get(f"/api/agent/chat/async/{job_id}/events", params={"after_seq": 1, "wait_ms": 1000})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done" and body["session_id"] == "pg-session"
    assert [event["seq"] for event in body["events"]] == [2]
