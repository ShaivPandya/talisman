"""Compare warm chat replay overhead against a Git baseline using local Postgres.

TEST_POSTGRES_URL must name a disposable local database with pgvector available.
Each run creates and drops its own schema; DATABASE_URL is overridden before any
runtime work. The synthetic model emits identical tokens for both paths. Queue
dispatch, provider network latency and browser rendering are outside this test.

Example:
    TEST_POSTGRES_URL=postgresql://... python -m scripts.benchmark_agent_chat_streaming \
        --baseline-ref ff6140d8 --output outputs/tl192-chat-streaming.json
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import math
import os
import runpy
import subprocess
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import psycopg
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def test_database_url() -> str:
    dsn = (os.getenv("TEST_POSTGRES_URL") or "").strip()
    if not dsn:
        raise ValueError("Set TEST_POSTGRES_URL to a disposable local Postgres + pgvector database.")
    config = conninfo_to_dict(dsn)
    host = str(config.get("host") or "")
    if host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"):
        raise ValueError("TEST_POSTGRES_URL must use a local TCP host or Unix socket.")
    if not config.get("dbname"):
        raise ValueError("TEST_POSTGRES_URL must name a disposable database.")
    return dsn


@contextmanager
def disposable_job_database(dsn: str) -> Iterator[str]:
    schema = f"tl192_{uuid.uuid4().hex}"
    # SQLAlchemy's URL is intentionally a dummy: the DBAPI creator owns the DSN.
    engine = sa.create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(dsn, options=f"-csearch_path={schema},public"),
    )
    migrations = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    upgrades = (
        "20260429_0001_gcp_state_schema.py",
        "20260429_0002_async_jobs_rq.py",
        "20260503_0014_async_job_events.py",
        "20261021_0002_async_job_claims.py",
        "20260515_0002_conversation_session_titles.py",
        "20261023_tl220_conversation_messages.py",
    )
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute("CREATE EXTENSION IF NOT EXISTS vector")
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        try:
            with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                for migration in upgrades:
                    runpy.run_path(str(migrations / migration))["upgrade"]()
            yield make_conninfo(dsn, options=f"-csearch_path={schema},public", application_name=schema)
        finally:
            from api.job_event_notifications import close_job_event_listeners
            from api.postgres import close_pools

            close_job_event_listeners()
            close_pools()
            engine.dispose()
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


def _baseline(ref: str, router: Any) -> tuple[Any, Any]:
    def source(path: str) -> str:
        return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True)

    old_events = ModuleType("baseline_job_events")
    exec(compile(source("api/job_events.py"), "baseline_job_events.py", "exec"), old_events.__dict__)
    old_worker = ModuleType("baseline_agent_chat_worker")
    exec(compile(source("api/agent_chat_worker.py"), "baseline_agent_chat_worker.py", "exec"), old_worker.__dict__)
    old_worker.append_job_event = old_events.append_job_event
    tree = ast.parse(source("api/routers/agent.py"))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_agent_chat_async_events"
    )
    function.decorator_list = []
    namespace = dict(vars(router))
    namespace["list_job_events"] = old_events.list_job_events
    exec(compile(ast.Module(body=[function], type_ignores=[]), "baseline_chat_events.py", "exec"), namespace)
    return old_worker, namespace["get_agent_chat_async_events"]


def _percentile(values: list[float], fraction: float) -> float:
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def benchmark(
    dsn: str, *, baseline_ref: str, repeats: int, idle_seconds: float, stream_seconds: float
) -> dict[str, Any]:
    overrides = {
        "DATABASE_URL": dsn,
        "ASYNC_JOB_BACKEND": "postgres",
        "ASYNC_JOB_SUCCESS_READ_AUDIT_ENABLED": "false",
        "STATE_DB_BACKEND": "sqlite",
        "TALISMAN_ALLOW_SQLITE_STATE": "true",
        "POSTGRES_POOL_MIN_SIZE": "0",
        "POSTGRES_POOL_MAX_SIZE": "2",
        "PERFORMANCE_BASELINES_ENABLED": "true",
        "AGENT_DELTA_FLUSH_INTERVAL_MS": "500",
        "AGENT_DELTA_FLUSH_BYTES": "1024",
    }
    with patch.dict(os.environ, overrides):
        from starlette.responses import StreamingResponse

        from api import agent_chat_worker, job_queue, postgres
        from api.agent_models import AgentChatJobRequest
        from api.job_event_notifications import close_job_event_listeners, watch_job_events
        from api.performance import TimingState, timing_context
        from api.routers import agent as agent_router

        old_worker, old_poll = _baseline(baseline_ref, agent_router)
        close_job_event_listeners()
        postgres.close_pools()
        with postgres.connect(read_only=True) as conn:
            conn.execute("SELECT 1").fetchone()
        with watch_job_events("warmup") as watch, watch.hub.condition:
            if not watch.hub.condition.wait_for(lambda: watch.hub.ready, timeout=5):
                raise RuntimeError("Postgres listener did not become ready")

        def frame(event: str, payload: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

        def model(req, actor):
            async def stream():
                await asyncio.sleep(0.15)
                yield frame("delta", {"text": "first "})
                for _ in range(max(1, int(stream_seconds / 0.02))):
                    await asyncio.sleep(0.02)
                    yield frame("delta", {"text": "token "})
                yield frame("done", {"session_id": req.session_id, "usage": {}})

            return StreamingResponse(stream(), media_type="text/event-stream")

        async def inline_first_token() -> float:
            req = AgentChatJobRequest(message="benchmark", session_id="benchmark-session", actor={})
            started = time.perf_counter()
            response = model(req, None)
            try:
                async for _chunk in response.body_iterator:
                    return (time.perf_counter() - started) * 1000
            finally:
                await response.body_iterator.aclose()
            raise AssertionError("Model emitted no tokens")

        cases = {
            "before": (old_worker, old_poll),
            "after": (agent_chat_worker, agent_router.get_agent_chat_async_events),
        }
        observations: dict[str, list[dict[str, float]]] = {key: [] for key in cases}
        with patch.object(agent_router, "agent_chat", model), ThreadPoolExecutor(max_workers=1) as executor:
            for trial in range(repeats):
                # Alternate order so background machine load doesn't favor a case.
                for name in list(cases) if trial % 2 == 0 else list(reversed(cases)):
                    worker, poll = cases[name]
                    inline_ms = asyncio.run(inline_first_token())
                    idle_job = job_queue.create_job("agent_chat_turn", payload={"session_id": "idle"})
                    idle_state = TimingState()
                    started = time.perf_counter()
                    with timing_context(idle_state):
                        poll(idle_job["job_id"], after_seq=0, wait_ms=int(idle_seconds * 1000))
                    idle_elapsed = time.perf_counter() - started

                    job = job_queue.create_job("agent_chat_turn", payload={"session_id": "benchmark-session"})
                    req = AgentChatJobRequest(message="benchmark", session_id="benchmark-session", actor={})
                    worker_state = TimingState()
                    poll_state = TimingState()
                    status_reads = []
                    status_name = "get_job" if name == "before" else "get_job_status"
                    read_status = getattr(worker, status_name)

                    def counted_status(job_id, reads=status_reads, read=read_status):
                        reads.append(time.perf_counter())
                        return read(job_id)

                    def execute(worker=worker, req=req, job=job, worker_state=worker_state):
                        with timing_context(worker_state):
                            result = worker._run_agent_chat_turn_job(req, job_id=job["job_id"])
                            job_queue.complete_job(job["job_id"], result)

                    with patch.object(worker, status_name, counted_status):
                        started = time.perf_counter()
                        future = executor.submit(execute)
                        cursor = 0
                        first_token_ms = None
                        with timing_context(poll_state):
                            while True:
                                response = poll(job["job_id"], after_seq=cursor, wait_ms=10_000)
                                cursor = response["next_seq"]
                                events = response["events"]
                                if first_token_ms is None and any(event["event_type"] == "delta" for event in events):
                                    first_token_ms = (time.perf_counter() - started) * 1000
                                if any(event["event_type"] in {"done", "error"} for event in events):
                                    break
                                if time.perf_counter() - started > stream_seconds + 10:
                                    raise RuntimeError("Benchmark chat did not finish")
                        future.result(timeout=5)
                        elapsed = time.perf_counter() - started
                    if first_token_ms is None:
                        raise AssertionError("Worker emitted no tokens")
                    sample = {
                        "inline_ttft_ms": round(inline_ms, 3),
                        "worker_ttft_ms": round(first_token_ms, 3),
                        "worker_added_ttft_ms": round(first_token_ms - inline_ms, 3),
                        "idle_poll_queries_s": round(idle_state.snapshot().get("db_calls", 0) / idle_elapsed, 3),
                        "stream_poll_queries_s": round(poll_state.snapshot().get("db_calls", 0) / elapsed, 3),
                        "cancellation_queries_s": round(len(status_reads) / elapsed, 3),
                        "minimum_cancellation_read_gap_ms": round(
                            min((b - a for a, b in zip(status_reads, status_reads[1:], strict=False)), default=0)
                            * 1000,
                            3,
                        ),
                        "worker_total_queries_s": round(worker_state.snapshot().get("db_calls", 0) / elapsed, 3),
                    }
                    observations[name].append(sample)
                    print(json.dumps({"case": name, "trial": trial + 1, **sample}), flush=True)
        summary = {}
        for name, samples in observations.items():
            summary[name] = {
                key: {
                    "p50": _percentile([sample[key] for sample in samples], 0.5),
                    "p95": _percentile([sample[key] for sample in samples], 0.95),
                }
                for key in samples[0]
            }
        return {
            "baseline_ref": baseline_ref,
            "repeats": repeats,
            "idle_seconds": idle_seconds,
            "stream_seconds": stream_seconds,
            "token_interval_ms": 20,
            "scope": "Warm model-stream-to-replay path; excludes queue dispatch, provider network and browser rendering",
            "observations": observations,
            "summary": summary,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--idle-seconds", type=float, default=2.0)
    parser.add_argument("--stream-seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or not 0 < args.idle_seconds <= 14 or args.stream_seconds <= 0:
        parser.error("Use repeats >= 1, 0 < idle-seconds <= 14, and stream-seconds > 0")
    with disposable_job_database(test_database_url()) as dsn:
        result = benchmark(
            dsn,
            baseline_ref=args.baseline_ref,
            repeats=args.repeats,
            idle_seconds=args.idle_seconds,
            stream_seconds=args.stream_seconds,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
