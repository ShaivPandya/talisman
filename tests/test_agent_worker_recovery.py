"""Durable chat concurrency, lease races, and transcript repair."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from api import agent_job_recovery as recovery
from api import agent_worker_loop, job_events, job_queue, job_worker_loop, memory_db, postgres
from api import async_job_runner as runner
from scripts.benchmark_agent_worker_recovery import disposable_agent_database, enqueue_turn


@pytest.fixture(scope="module")
def agent_database():
    from scripts.benchmark_agent_chat_streaming import test_database_url as local_url

    if not os.getenv("TEST_POSTGRES_URL"):
        pytest.skip("TEST_POSTGRES_URL must identify a disposable local database")
    with disposable_agent_database(local_url()) as dsn:
        yield dsn


@pytest.fixture(params=["memory", "postgres"])
def store(request, monkeypatch, tmp_path):
    postgres.close_pools()
    job_queue.clear_memory_jobs()
    job_events.clear_memory_events()
    monkeypatch.setattr(runner, "_emit_job_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_worker_loop, "preload_job_path", lambda *_args: None)
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "2")
    if memory_db._conn:
        memory_db._conn.close()
    memory_db._conn = None
    if request.param == "postgres":
        monkeypatch.setenv("DATABASE_URL", request.getfixturevalue("agent_database"))
        monkeypatch.setenv("STATE_DB_BACKEND", "postgres")
        monkeypatch.setenv("ASYNC_JOB_BACKEND", "postgres")
        with postgres.connect() as conn:
            conn.execute("TRUNCATE async_jobs, async_job_events, conversation_sessions CASCADE")
            conn.commit()
    else:
        monkeypatch.setenv("ASYNC_JOB_BACKEND", "local")
        monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
        monkeypatch.setattr(memory_db, "_DB_PATH", tmp_path / "memory.db")
    yield request.param
    if memory_db._conn:
        memory_db._conn.close()
    memory_db._conn = None
    postgres.close_pools()
    job_queue.clear_memory_jobs()
    job_events.clear_memory_events()


def age(row, seconds=60):
    stamp = datetime.now(UTC) - timedelta(seconds=seconds)
    if job_queue.postgres_jobs_enabled():
        with postgres.connect() as conn:
            conn.execute("UPDATE async_jobs SET updated_at = %s WHERE job_id = %s", (stamp, row["job_id"]))
            conn.commit()
    else:
        job_queue._memory_jobs[row["job_id"]]["updated_at"] = stamp
    return job_queue.get_job(row["job_id"])


def assistant(key):
    return memory_db.get_or_create_session(key)["server_messages"][-1]


def claimed(key="turn"):
    row = enqueue_turn(key)
    owner = job_queue.claim_job(row["job_id"])
    memory_db.begin_job_turn(key, key, row["job_id"])
    return owner


def test_expiry_repairs_transcript_preserves_partial_and_allows_retry(store, monkeypatch):
    row = claimed()
    memory_db.update_assistant_message("turn", "turn", {"content": "saved partial"})
    age(row)
    assert recovery.recover_expired_turns() == 1
    assert (
        assistant("turn").items()
        >= {
            "role": "assistant",
            "content": "saved partial",
            "client_turn_id": "turn",
            "is_streaming": False,
            "status": "failed",
            "async_job_id": row["job_id"],
        }.items()
    )
    job = job_queue.get_job(row["job_id"])
    assert job["status"] == "failed" and job["result_expires_at"] is not None
    assert recovery.recover_expired_turns() == 0
    assert [event["event_type"] for event in job_events.list_job_events(row["job_id"])] == ["error"]
    # An explicit retry gets a new job even with the same client_turn_id/cache key.
    monkeypatch.setenv("AGENT_CHAT_DISPATCH_BACKEND", "warm_worker")
    retry, disposition = runner.enqueue_registered_job("agent_chat_turn", row["payload_json"], cache_key="turn")
    assert disposition == "created" and retry["job_id"] != row["job_id"]
    assert job_queue.claim_job(retry["job_id"])["status"] == "running"


def test_old_snapshot_cannot_expire_renewed_claim(store):
    old = age(claimed())
    assert job_queue.renew_agent_job_lease(old["job_id"], old["claimed_by"])
    updated = runner._sync_stale_active_job(old)
    assert updated["status"] == "running"
    assert assistant("turn")["is_streaming"]
    assert not job_queue.renew_agent_job_lease(old["job_id"], "different-owner")


def test_blocked_provider_keeps_heartbeat_alive(store, monkeypatch):
    monkeypatch.setenv("AGENT_JOB_LEASE_SECONDS", "0.18")
    monkeypatch.setenv("AGENT_JOB_HEARTBEAT_SECONDS", "0.025")
    monkeypatch.setenv("AGENT_JOB_RECOVERY_INTERVAL_SECONDS", "0.025")
    row = claimed()
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()

    def blocked(_req, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"answer": "completed"}

    monkeypatch.setattr(runner, "import_string", lambda _path: blocked)
    reaper = recovery.start_recovery_loop(stop)
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(runner.execute_claimed, row)
        try:
            assert entered.wait(5)
            time.sleep(0.45)  # More than two leases, without a model delta or ping.
            assert job_queue.get_job_status(row["job_id"]) == "running"
        finally:
            release.set()
            stop.set()
            reaper.join(5)
        assert future.result(timeout=5) == {"answer": "completed"}
    assert job_queue.get_job_status(row["job_id"]) == "completed"


def test_expired_worker_cannot_publish_or_overwrite_transcript(store):
    row = claimed()
    with recovery.claimed_turn(row):
        job_queue.expire_agent_job_leases(datetime.now(UTC) + timedelta(seconds=1), failed_ttl_s=600)
        with pytest.raises(recovery.AgentLeaseLost):
            memory_db.complete_turn_messages("turn", "turn", {}, {"role": "assistant", "content": "late output"})
        with pytest.raises(recovery.AgentLeaseLost):
            job_events.append_job_event(row["job_id"], "delta", {"text": "late output"})
        job_queue.complete_job(row["job_id"], {"late": True})
    recovery.recover_expired_turns()
    assert job_queue.get_job_status(row["job_id"]) == "failed"
    assert assistant("turn")["status"] == "failed"
    assert assistant("turn")["content"] == ""


def test_completed_turn_is_preserved_and_completion_cannot_be_failed(store):
    row = claimed()
    memory_db.complete_turn_messages("turn", "turn", {}, {"role": "assistant", "content": "final"})
    age(row)
    recovery.recover_expired_turns()
    assert assistant("turn")["content"] == "final"
    assert not assistant("turn")["is_streaming"]
    other = claimed("other")
    job_queue.complete_job(other["job_id"], {"answer": "final"})
    job_queue.fail_job(other["job_id"], "late error")
    recovery.recover_expired_turns(now=datetime.now(UTC) + timedelta(hours=1))
    assert job_queue.get_job_status(other["job_id"]) == "completed"


def test_repair_is_retried_after_database_failure(store, monkeypatch):
    row = age(claimed())
    original = memory_db.fail_turn
    monkeypatch.setattr(memory_db, "fail_turn", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("DB unavailable")))
    with pytest.raises(RuntimeError, match="DB unavailable"):
        recovery.recover_expired_turns()
    assert job_queue.get_job_status(row["job_id"]) == "failed"
    assert assistant("turn")["is_streaming"]
    monkeypatch.setattr(memory_db, "fail_turn", original)
    assert recovery.recover_expired_turns() == 1
    assert assistant("turn")["status"] == "failed"


def test_pending_old_repair_does_not_fail_a_new_attempt(store):
    row = age(claimed())
    job_queue.expire_agent_job_leases(datetime.now(UTC), failed_ttl_s=600)
    retry = enqueue_turn("turn")
    assert retry["job_id"] != row["job_id"]
    job_queue.claim_job(retry["job_id"])
    memory_db.begin_job_turn("turn", "turn", retry["job_id"])
    recovery.recover_expired_turns()
    assert assistant("turn")["is_streaming"]


def test_legacy_claim_does_not_expire_during_rollout(store):
    row = age(claimed())
    if job_queue.postgres_jobs_enabled():
        with postgres.connect() as conn:
            conn.execute("UPDATE async_jobs SET claimed_by = 'legacy-uuid' WHERE job_id = %s", (row["job_id"],))
            conn.commit()
    else:
        job_queue._memory_jobs[row["job_id"]]["claimed_by"] = "legacy-uuid"
    assert recovery.recover_expired_turns() == 0
    assert job_queue.get_job_status(row["job_id"]) == "running"


def test_simultaneous_reapers_do_not_duplicate_error_events(store):
    row = age(claimed())
    with ThreadPoolExecutor(4) as executor:
        list(executor.map(lambda _i: recovery.recover_expired_turns(), range(4)))
    assert len(job_events.list_job_events(row["job_id"])) == 1
    assert assistant("turn")["status"] == "failed"


def test_two_jobs_run_together_and_third_waits_for_a_slot(store, monkeypatch):
    for key in ["first", "second", "third"]:
        enqueue_turn(key)
    entered, active, lock = [], [], threading.Lock()
    release, stop = threading.Event(), threading.Event()

    def compute(req, **kwargs):
        with lock:
            entered.append(req.session_id)
            active.append(req.session_id)
        assert release.wait(5)
        with lock:
            active.remove(req.session_id)
        return {"answer": req.session_id}

    monkeypatch.setattr(runner, "import_string", lambda _path: compute)
    worker = threading.Thread(target=agent_worker_loop.run_loop, kwargs={"poll_interval_s": 0.01, "stop_event": stop})
    worker.start()
    try:
        deadline = time.monotonic() + 4
        while len(entered) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(entered) == len(active) == 2
        assert sorted(row["status"] for row in job_queue.list_active_jobs()) == ["queued", "running", "running"]
    finally:
        stop.set()
        release.set()
        worker.join(8)
    assert not worker.is_alive()


@pytest.mark.parametrize("slots,pool,want", [(2, 2, 2), (8, 2, 2), (2, 1, 1), (1, 4, 1)])
def test_concurrency_respects_pool_budget(monkeypatch, slots, pool, want):
    monkeypatch.setenv("AGENT_WORKER_CONCURRENCY", str(slots))
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", str(pool))
    assert job_worker_loop.agent_concurrency() == want


def test_cancel_between_claim_and_compute_is_a_successful_noop(store, monkeypatch):
    row = claimed()
    job_queue.cancel_job(row["job_id"])
    monkeypatch.setattr(runner, "import_string", lambda _path: pytest.fail("cancelled turn computed"))
    assert runner.execute_claimed(row) is None
    assert job_queue.get_job_status(row["job_id"]) == "cancelled"


def test_explicit_retry_reopens_and_completes_the_same_turn(store, monkeypatch):
    from api import memory_manager

    row = age(claimed())
    recovery.recover_expired_turns()
    retry = enqueue_turn("turn")
    owner = job_queue.claim_job(retry["job_id"])
    monkeypatch.setattr(memory_manager, "_ensure_session_title", lambda *args: None)
    with recovery.claimed_turn(owner):
        assert memory_db.begin_job_turn("turn", "turn", retry["job_id"])
        assert assistant("turn")["is_streaming"]
        memory_manager.complete_turn(
            "turn",
            {"role": "user", "client_turn_id": "turn"},
            {"role": "assistant", "client_turn_id": "turn", "content": "retry answer"},
        )
        job_queue.complete_job(retry["job_id"], {"answer": "retry answer"})
    assert job_queue.get_job_status(row["job_id"]) == "failed"
    assert job_queue.get_job_status(retry["job_id"]) == "completed"
    assert assistant("turn")["status"] == "complete"
    assert assistant("turn")["content"] == "retry answer"
    assert not assistant("turn")["is_streaming"]


def test_background_partial_retains_expired_claim_context(store, monkeypatch):
    from api import memory_manager

    row = claimed()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = memory_db.update_assistant_message

    def delayed_write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        try:
            return original(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(memory_db, "update_assistant_message", delayed_write)
    with recovery.claimed_turn(row):
        memory_manager.save_partial_turn_async("turn", "turn", "late partial")
        try:
            assert entered.wait(5)
            job_queue.expire_agent_job_leases(datetime.now(UTC) + timedelta(seconds=1), failed_ttl_s=600)
        finally:
            release.set()
        assert finished.wait(5)
    recovery.recover_expired_turns()
    assert assistant("turn")["content"] == ""
    assert assistant("turn")["status"] == "failed"
