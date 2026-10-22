"""Replay, cancellation and wakeup contracts for durable chat streams."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from api import agent_chat_worker, job_event_notifications, job_events, job_queue
from api.routers import agent as agent_router


@pytest.fixture(autouse=True)
def isolated_job_events(monkeypatch):
    monkeypatch.setenv("ASYNC_JOB_BACKEND", "local")
    monkeypatch.setattr(job_queue, "_memory_jobs", {})
    monkeypatch.setattr(job_events, "_memory_events", {})
    job_event_notifications.close_job_event_listeners()
    yield
    job_event_notifications.close_job_event_listeners()


def _job(job_id="events-job"):
    return job_queue.create_job(
        "agent_chat_turn",
        job_id=job_id,
        payload={"session_id": "session-1", "actor": {"actor_id": "reader"}, "message": "large request"},
    )


def test_first_delta_flushes_immediately_then_coalesces(monkeypatch):
    now = [0.001]
    emitted = []
    monkeypatch.setattr(agent_chat_worker, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(agent_chat_worker, "append_job_event", lambda *args: emitted.append(args))
    monkeypatch.setenv("AGENT_DELTA_FLUSH_INTERVAL_MS", "500")
    monkeypatch.setenv("AGENT_DELTA_FLUSH_BYTES", "1024")
    state = {}
    buffer = ["first"]
    agent_chat_worker._append_agent_delta("job", buffer, state=state)
    assert emitted == [("job", "delta", {"text": "first"})]
    now[0] = 0.002
    buffer.append("next")
    agent_chat_worker._append_agent_delta("job", buffer, state=state)
    assert buffer == ["next"] and len(emitted) == 1
    now[0] = 0.501
    agent_chat_worker._append_agent_delta("job", buffer, state=state)
    assert emitted[-1] == ("job", "delta", {"text": "next"})


def test_cancellation_reads_at_most_once_per_second_and_latches(monkeypatch):
    now = [0.0]
    reads = []

    def status(job_id):
        reads.append((job_id, now[0]))
        return "cancelled" if now[0] >= 1.0 else "running"

    monkeypatch.setattr(agent_chat_worker, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(agent_chat_worker, "get_job_status", status)
    check = agent_chat_worker._CancellationCheck("job")
    for tick in range(1000):
        now[0] = tick / 1000
        assert not check()
    now[0] = 1.0
    assert check()
    now[0] = 2.0
    assert check()
    assert reads == [("job", 0.0), ("job", 1.0)]


def test_snapshot_preserves_cursor_session_and_terminal_result():
    _job()
    job_events.append_job_event("events-job", "delta", {"text": "first"})
    job_events.append_job_event("events-job", "done", {"usage": {}})
    row, events = job_events.read_job_events_snapshot("events-job", after_seq=1)
    assert row["payload_json"] == {"session_id": "session-1", "actor": {"actor_id": "reader"}}
    assert [event["seq"] for event in events] == [2]
    assert row["result_json"] is None
    job_queue.complete_job("events-job", {"answer": "finished"})
    row, events = job_events.read_job_events_snapshot("events-job", after_seq=2)
    assert events == []
    assert row["result_json"] == {"answer": "finished"}
    assert job_events.read_job_events_snapshot("missing") == (None, [])


@pytest.mark.parametrize("terminal", ["complete", "fail", "cancel"])
def test_events_endpoint_preserves_terminal_contract(terminal):
    _job()
    if terminal == "complete":
        job_queue.complete_job("events-job", {"session_id": "session-1"})
    elif terminal == "fail":
        job_queue.fail_job("events-job", "failed deliberately")
    else:
        job_queue.cancel_job("events-job", "cancelled deliberately")
    response = agent_router.get_agent_chat_async_events("events-job", after_seq=4, wait_ms=1000)
    assert response["status"] == {"complete": "done", "fail": "error", "cancel": "cancelled"}[terminal]
    assert response["events"] == [] and response["next_seq"] == 4
    assert response["session_id"] == "session-1"
    assert response["timeout_s"] > 0


def test_events_endpoint_returns_404_for_unknown_job():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        agent_router.get_agent_chat_async_events("missing", after_seq=0, wait_ms=1000)
    assert error.value.status_code == 404


def test_long_poll_wakes_all_subscribers_and_replays_once():
    _job()
    barrier = threading.Barrier(3)

    def read():
        with job_event_notifications.watch_job_events("events-job") as watch:
            watch.record(_job_row(), 0, watch.generation)
            barrier.wait(timeout=2)
            watch.wait(0, 1.0)
        return agent_router.get_agent_chat_async_events("events-job", after_seq=0, wait_ms=1000)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read) for _ in range(2)]
        barrier.wait(timeout=2)
        job_events.append_job_event("events-job", "delta", {"text": "visible"})
        for future in futures:
            response = future.result(timeout=2)
            assert response["next_seq"] == 1
            assert response["events"][0]["payload"] == {"text": "visible"}
    replay = agent_router.get_agent_chat_async_events("events-job", after_seq=1, wait_ms=0)
    assert replay["events"] == [] and replay["next_seq"] == 1


def _job_row():
    return {"job_id": "events-job", "status": "running"}


def test_recent_cursor_avoids_empty_query_but_reconnect_invalidates_snapshot():
    hub = job_event_notifications._EventHub(None)
    signal = job_event_notifications._Signal(threading.Condition(hub.lock))
    watch = job_event_notifications.JobEventWatch(hub, signal)
    watch.record(_job_row(), 7, watch.generation)
    assert watch.cached_job(7) == _job_row()
    assert watch.cached_job(6) is None
    hub._set_ready(False)
    assert watch.cached_job(7) is None
    hub._set_ready(True)
    assert watch.cached_job(7) is None
    watch.record(_job_row(), 7, watch.generation)
    hub.signals["events-job"] = signal
    hub.publish("events-job", 8)
    assert watch.cached_job(7) is None


def test_missed_notification_is_recovered_by_periodic_snapshot(monkeypatch):
    _job()
    monkeypatch.setattr(job_event_notifications, "RESYNC_SECONDS", 0.03)
    monkeypatch.setattr(job_event_notifications, "publish_local_job_event", lambda *_args: None)

    def publish():
        time.sleep(0.02)
        job_events.append_job_event("events-job", "delta", {"text": "durable"})

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(publish)
        response = agent_router.get_agent_chat_async_events("events-job", after_seq=0, wait_ms=500)
        future.result(timeout=1)
    assert response["events"][0]["payload"] == {"text": "durable"}


def test_local_event_reset_invalidates_recent_cursors():
    _job()
    with job_event_notifications.watch_job_events("events-job") as watch:
        job_events.append_job_event("events-job", "delta", {"text": "old"})
        watch.record(_job_row(), 1, watch.generation)
        job_events.clear_memory_events()
        assert watch.cached_job(1) is None
        assert watch.signal.latest_seq == 0


def test_recent_cursor_cache_never_evicts_live_subscribers(monkeypatch):
    monkeypatch.setattr(job_event_notifications, "_RECENT_JOBS", 2)
    with job_event_notifications.watch_job_events("live") as watch:
        for index in range(5):
            with job_event_notifications.watch_job_events(str(index)):
                pass
        assert watch.hub.signals["live"] is watch.signal
        assert len(watch.hub.signals) == 2


def test_listener_ready_between_snapshot_and_wait_forces_another_read(monkeypatch):
    hub = job_event_notifications._EventHub(None)
    hub._set_ready(False)
    watch = job_event_notifications.JobEventWatch(hub, job_event_notifications._Signal(threading.Condition(hub.lock)))
    generation = watch.generation
    hub._set_ready(True)
    watch.record(_job_row(), 0, generation)

    def unexpected_wait(*args, **kwargs):
        raise AssertionError("a snapshot taken before LISTEN must be refreshed before waiting")

    monkeypatch.setattr(watch.signal.condition, "wait", unexpected_wait)
    watch.wait(0, 1.0)


def test_full_replay_page_reads_next_page_without_waiting_for_a_notification(monkeypatch):
    _job()
    monkeypatch.setattr(job_event_notifications, "publish_local_job_event", lambda *_args: None)
    for index in range(501):
        job_events.append_job_event("events-job", "delta", {"text": str(index)})

    def unexpected_wait(*args, **kwargs):
        raise AssertionError("a full page must not suppress the next replay read")

    monkeypatch.setattr(job_event_notifications.JobEventWatch, "wait", unexpected_wait)
    first = agent_router.get_agent_chat_async_events("events-job", after_seq=0, wait_ms=1000)
    assert first["next_seq"] == 500 and len(first["events"]) == 500
    second = agent_router.get_agent_chat_async_events("events-job", after_seq=500, wait_ms=1000)
    assert second["next_seq"] == 501 and len(second["events"]) == 1


def test_stale_job_timeout_is_preserved_and_not_cached_as_active():
    _job()
    job_queue._memory_jobs["events-job"]["created_at"] = datetime.now(UTC) - timedelta(hours=1)
    response = agent_router.get_agent_chat_async_events("events-job", after_seq=0, wait_ms=1000)
    assert response["status"] == "error"
    assert "exceeded timeout" in response["error"]
    with job_event_notifications.watch_job_events("events-job") as watch:
        assert watch.cached_job(0) is None
