"""Small, content-free performance observations shared by API and workers.

Durations are milliseconds on a monotonic clock. Counters describe work, not
exclusive wall time: parallel database/storage durations can exceed total time.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from api.logging_config import generate_request_id, request_id_var

logger = logging.getLogger("api.performance")
PROCESS_STARTED = time.perf_counter()


def enabled() -> bool:
    return os.getenv("PERFORMANCE_BASELINES_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class TimingState:
    scope: dict[str, Any] = field(default_factory=dict)
    counters: dict[str, float] = field(default_factory=dict)
    lock: Any = field(default_factory=threading.Lock)

    def add(self, name: str, value: float = 1) -> None:
        with self.lock:
            self.counters[name] = self.counters.get(name, 0) + max(0, value)

    def snapshot(self) -> dict[str, float]:
        with self.lock:
            return {key: round(value, 3) for key, value in self.counters.items()}

    def identity(self) -> dict[str, Any]:
        route = self.scope.get("route")
        return {
            "method": self.scope.get("method", "worker"),
            "route": getattr(route, "path", self.scope.get("route_template", "<unmatched>")),
        }


current_timings: ContextVar[TimingState | None] = ContextVar("performance_timings", default=None)


@contextmanager
def timing_context(state: TimingState | None) -> Iterator[None]:
    token = current_timings.set(state)
    try:
        yield
    finally:
        current_timings.reset(token)


def emit(event: str, **values: Any) -> None:
    """Emit only scalar fields supplied by instrumentation; never SQL/content."""
    if not enabled():
        return
    try:
        state = current_timings.get()
        payload = {
            "event": event,
            "environment": os.getenv("ENVIRONMENT", "development"),
            "component": os.getenv("K_SERVICE")
            or os.getenv("CLOUD_RUN_WORKER_POOL")
            or os.getenv("CLOUD_RUN_JOB")
            or os.getenv("JOB_WORKER_JOB_TYPE", "local"),
            "release": os.getenv("TALISMAN_RELEASE_GIT_SHA_SHORT")
            or os.getenv("PERFORMANCE_RELEASE")
            or os.getenv("K_REVISION", "unknown"),
            **(state.identity() if state else {}),
        }
        for key, value in values.items():
            if value is None or isinstance(value, (str, bool, int)):
                payload[key] = value
            elif isinstance(value, float) and math.isfinite(value):
                payload[key] = round(value, 3)
        logger.info(event, extra={"performance": payload})
    except Exception:
        # Telemetry must never change application success/failure.
        pass


def count(name: str, value: float = 1) -> None:
    state = current_timings.get()
    if state is not None and enabled():
        state.add(name, value)


@contextmanager
def measure(name: str) -> Iterator[None]:
    state = current_timings.get()
    if state is None or not enabled():
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        state.add(name, (time.perf_counter() - started) * 1000)


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    """Propagate timing/log context without changing business/policy contexts."""

    def submit(self, fn, /, *args, **kwargs):
        state = current_timings.get()
        request_id = request_id_var.get("")

        def run():
            request_token = request_id_var.set(request_id)
            try:
                with timing_context(state):
                    return fn(*args, **kwargs)
            finally:
                request_id_var.reset(request_token)

        return super().submit(run)


class PerformanceMiddleware:
    """Pure ASGI wrapper outside error handling; does not buffer response bodies."""

    def __init__(self, app):
        self.app = app
        self._first_response = False
        self._first_lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/") or not enabled():
            return await self.app(scope, receive, send)
        state = TimingState(scope=scope)
        started = time.perf_counter()
        headers_ms = None
        finished_ms = None
        finished_counters = None
        status = 500
        outcome = "incomplete"
        disconnected = False

        async def timed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def timed_send(message):
            nonlocal headers_ms, finished_ms, finished_counters, status, outcome
            if message["type"] == "http.response.start":
                headers_ms = (time.perf_counter() - started) * 1000
                status = message["status"]
                totals = state.snapshot()
                timing = ", ".join(
                    [f"{key};dur={totals.get(key + '_ms', 0):.3f}" for key in ("db", "pool", "cache", "storage")]
                    + [f"total;dur={headers_ms:.3f}"]
                    + [f'{key};desc="{int(totals.get(key, 0))}"' for key in ("cache_hit", "cache_miss")]
                )
                message = {
                    **message,
                    "headers": [*message.get("headers", []), (b"server-timing", timing.encode("ascii"))],
                }
            await send(message)
            if message["type"] == "http.response.start":
                # The first reply is its headers, even when an SSE body takes
                # minutes to complete. Keep cold start independent of streaming.
                with self._first_lock:
                    first = not self._first_response
                    self._first_response = True
                if first:
                    emit(
                        "cold_start",
                        duration_ms=(time.perf_counter() - PROCESS_STARTED) * 1000,
                        first_response_is_probe=scope.get("path") == "/api/health",
                    )
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished_ms = (time.perf_counter() - started) * 1000
                finished_counters = state.snapshot()
                outcome = "error" if status >= 500 else "completed"

        with timing_context(state):
            headers = dict(scope.get("headers", []))
            request_id = headers.get(b"x-request-id", b"").decode("latin1")[:128] or generate_request_id()
            request_token = request_id_var.set(request_id)
            try:
                await self.app(scope, timed_receive, timed_send)
            except asyncio.CancelledError:
                if finished_ms is None:
                    outcome = "cancelled"
                raise
            except Exception:
                if finished_ms is None:
                    outcome = "error"
                raise
            finally:
                if finished_ms is None and disconnected:
                    outcome = "cancelled"
                emit(
                    "api_request",
                    status=status,
                    outcome=outcome,
                    duration_ms=finished_ms if finished_ms is not None else (time.perf_counter() - started) * 1000,
                    headers_ms=headers_ms,
                    **(finished_counters if finished_counters is not None else state.snapshot()),
                )
                request_id_var.reset(request_token)
