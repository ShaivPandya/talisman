"""Repeatable local worker throughput and SIGKILL recovery checks (TL-211).

Uses only TEST_POSTGRES_URL (local hosts required), fresh schemas and a synthetic
provider. Never loads .env or uses the application's database URL. The baseline
loads the previous worker/runner from Git, without creating another checkout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import multiprocessing as mp
import os
import platform
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from scripts.benchmark_agent_chat_streaming import disposable_job_database, test_database_url


def baseline_module(ref: str, path: str) -> ModuleType:
    source = subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True)
    module = ModuleType(f"baseline_{Path(path).stem}")
    exec(compile(source, path, "exec"), module.__dict__)
    return module


@contextmanager
def disposable_agent_database(dsn: str) -> Iterator[str]:
    with disposable_job_database(dsn) as isolated:
        yield isolated


def configure(dsn: str) -> None:
    os.environ.update(
        DATABASE_URL=dsn,
        STATE_DB_BACKEND="postgres",
        ASYNC_JOB_BACKEND="postgres",
        POSTGRES_POOL_MIN_SIZE="2",
        POSTGRES_POOL_MAX_SIZE="2",
        SENTRY_DSN="",
        AGENT_WORKER_CONCURRENCY="2",
        ASYNC_JOB_SUCCESS_READ_AUDIT_ENABLED="false",
    )


def synthetic_chat(req: Any, actor: Any, *, seconds: float):
    from starlette.responses import StreamingResponse

    from api import memory_db

    def generate():
        memory_db.update_assistant_message(
            req.session_id, req.client_turn_id, {"content": "partial answer", "is_streaming": True}
        )
        yield 'event: delta\ndata: {"text":"partial answer"}\n\n'
        # A blocked provider emits no deltas or pings; the heartbeat must still run.
        time.sleep(seconds)
        memory_db.complete_turn_messages(
            req.session_id,
            req.client_turn_id,
            {"role": "user", "content": req.message, "client_turn_id": req.client_turn_id},
            {"role": "assistant", "content": "partial answer complete", "client_turn_id": req.client_turn_id},
        )
        yield 'event: delta\ndata: {"text":" complete"}\n\n'
        yield 'event: done\ndata: {"usage":{}}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")


def worker_process(dsn: str, baseline: str | None, seconds: float, stop: Any, ready: Any) -> None:
    configure(dsn)
    from api import agent_chat_worker, async_job_runner, job_worker_loop, postgres
    from api.routers import agent

    checkouts: list[float] = []
    checkout_errors: list[str] = []

    @contextmanager
    def observe(pool):
        started = time.perf_counter()
        try:
            yield
        except Exception as exc:
            checkout_errors.append(type(exc).__name__)
            raise
        finally:
            checkouts.append((time.perf_counter() - started) * 1000)

    postgres.observe_checkout = observe
    with postgres.connect() as conn:
        conn.execute("SELECT 1")
    postgres._get_pool().wait()
    checkouts.clear()
    agent.agent_chat = lambda req, actor: synthetic_chat(req, actor, seconds=seconds)
    runner, loop, compute = async_job_runner, job_worker_loop, agent_chat_worker
    if baseline:
        runner = baseline_module(baseline, "api/async_job_runner.py")
        loop = baseline_module(baseline, "api/job_worker_loop.py")
        compute = baseline_module(baseline, "api/agent_chat_worker.py")
        loop.execute_claimed = runner.execute_claimed
    runner.import_string = lambda _path: compute._run_agent_chat_turn_job
    runner._emit_job_audit = lambda *args, **kwargs: None
    loop.preload_job_path = lambda _job_type: None
    recovery = None
    if not baseline:
        from api.agent_job_recovery import start_recovery_loop

        recovery = start_recovery_loop(stop)
    ready.send(True)
    kwargs = {"poll_interval_s": 0.01, "stop_event": stop}
    if not baseline:
        kwargs["concurrency"] = loop.agent_concurrency()
    try:
        loop.run_loop(**kwargs)
    finally:
        stop.set()
        if recovery:
            recovery.join(6)
        samples = sorted(checkouts)
        ready.send(
            {
                "checkout_p95_ms": samples[max(0, math.ceil(len(samples) * 0.95) - 1)] if samples else None,
                "checkout_count": len(samples),
                "checkout_errors": checkout_errors,
                "pool_size": postgres._get_pool().get_stats().get("pool_size"),
            }
        )
        ready.close()
        postgres.close_pools()


def start_worker(dsn: str, baseline: str | None, seconds: float):
    ctx = mp.get_context("spawn")
    stop = ctx.Event()
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=worker_process, args=(dsn, baseline, seconds, stop, child))
    process.start()
    child.close()
    if not parent.poll(45):
        process.kill()
        process.join()
        raise RuntimeError("Synthetic worker did not become ready")
    parent.recv()
    return process, stop, parent


def enqueue_turn(key: str):
    from api import job_queue, memory_db

    memory_db.get_or_create_session(key)
    memory_db.begin_turn(
        key,
        {"role": "user", "content": "workflow", "client_turn_id": key},
        {"role": "assistant", "content": "", "is_streaming": True, "client_turn_id": key},
    )
    row, _ = job_queue.create_or_reuse_job(
        "agent_chat_turn",
        payload={"session_id": key, "client_turn_id": key, "message": "workflow", "actor": {}},
        cache_key=key,
        queue_name="agent",
        reuse_completed=False,
    )
    return row


def wait_until(predicate: Any, *, timeout: float = 15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise TimeoutError("Worker benchmark condition timed out")


def paired_workflows(dsn: str, baseline: str | None, seconds: float) -> dict[str, Any]:
    from api import job_queue, postgres

    with disposable_agent_database(dsn) as isolated:
        configure(isolated)
        process, stop, metrics = start_worker(isolated, baseline, seconds)
        try:
            rows = [enqueue_turn(f"workflow-{index}") for index in range(2)]
            ids = [row["job_id"] for row in rows]
            finished = wait_until(
                lambda: (
                    [job_queue.get_job(job_id) for job_id in ids]
                    if all(job_queue.get_job_status(job_id) == "completed" for job_id in ids)
                    else None
                )
            )
            starts = [row["started_at"] for row in finished]
            ends = [row["completed_at"] for row in finished]
            result = {
                "overlap_seconds": max(0, (min(ends) - max(starts)).total_seconds()),
                "pair_seconds": (max(ends) - min(starts)).total_seconds(),
                "queue_delay_ms": [(row["started_at"] - row["created_at"]).total_seconds() * 1000 for row in finished],
                "attempts": [row["attempt"] for row in finished],
                "pool_max": 2,
            }
        finally:
            stop.set()
            process.join(12)
            if process.is_alive():
                process.kill()
                process.join()
            postgres.close_pools()
        if metrics.poll(5):
            result.update(metrics.recv())
        metrics.close()
        return result


def killed_worker(dsn: str, baseline: str | None, *, observation_seconds: float = 60) -> dict[str, Any]:
    from api import job_queue, memory_db, postgres
    from api.agent_job_recovery import start_recovery_loop

    with disposable_agent_database(dsn) as isolated:
        configure(isolated)
        process, stop, metrics = start_worker(isolated, baseline, 600)
        recovery_stop = threading.Event()
        # This is the independent recovery loop also started by the API lifespan.
        recovery = start_recovery_loop(recovery_stop) if not baseline else None
        try:
            row = enqueue_turn("crash-turn")
            job_id = row["job_id"]
            wait_until(lambda: memory_db.get_or_create_session("crash-turn")["server_messages"][-1].get("content"))
            process.kill()  # SIGKILL, so no finally/shutdown handler can repair it.
            process.join(5)
            killed_at = time.monotonic()
            poll = baseline_module(baseline, "api/async_job_runner.py").poll_registered_job if baseline else None
            if poll:
                # Avoid optional governance audit against the minimal fixture schema.
                poll.__globals__["_success_read_audit_enabled"] = lambda: False
            while time.monotonic() - killed_at < observation_seconds:
                if poll:
                    poll(job_id)
                job = job_queue.get_job(job_id)
                turn = memory_db.get_or_create_session("crash-turn")["server_messages"][-1]
                if job["status"] == "failed" and not turn.get("is_streaming"):
                    break
                time.sleep(0.05)
            elapsed = time.monotonic() - killed_at
            return {
                "observed_seconds": elapsed,
                "status": job["status"],
                "turn_status": turn.get("status"),
                "is_streaming": turn.get("is_streaming"),
                "partial_text": turn.get("content"),
                "recovered_within_minute": job["status"] == "failed" and not turn.get("is_streaming") and elapsed < 60,
            }
        finally:
            recovery_stop.set()
            if recovery:
                recovery.join(6)
            if process.is_alive():
                process.kill()
            process.join(5)
            metrics.close()
            postgres.close_pools()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--crash-repeats", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = test_database_url()
    import psycopg

    with psycopg.connect(dsn) as conn:
        postgres_version = conn.execute("SHOW server_version").fetchone()[0]
    result: dict[str, Any] = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "baseline_ref": args.baseline_ref,
        "provider_seconds": args.seconds,
        "python_version": platform.python_version(),
        "psycopg_version": psycopg.__version__,
        "postgres_version": postgres_version,
        "pairs": [],
        "crashes": [],
    }
    for index in range(args.repeats):
        # Alternate order to reduce bias from other agents' activity.
        for baseline in [args.baseline_ref, None] if index % 2 == 0 else [None, args.baseline_ref]:
            row = {
                "case": "before" if baseline else "after",
                "repeat": index + 1,
                **paired_workflows(dsn, baseline, args.seconds),
            }
            result["pairs"].append(row)
            print(json.dumps(row), flush=True)
    for index in range(args.crash_repeats):
        for baseline in [args.baseline_ref, None] if index % 2 == 0 else [None, args.baseline_ref]:
            row = {"case": "before" if baseline else "after", "repeat": index + 1, **killed_worker(dsn, baseline)}
            result["crashes"].append(row)
            print(json.dumps(row), flush=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
