"""Observe checkout latency and sample existing pools without opening a DB."""

from __future__ import annotations

import atexit
import math
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from api.performance import count, emit, enabled, measure

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_previous: dict[int, tuple[float, dict[str, int]]] = {}

_GAUGES = ("requests_waiting", "pool_size", "pool_available", "pool_min", "pool_max")
_COUNTERS = ("usage_ms", "connections_num", "requests_num", "requests_queued", "requests_wait_ms", "requests_errors")


def log_pool_stats() -> None:
    if not enabled():
        return
    from api.postgres import _POOLS, _POOLS_LOCK

    with _POOLS_LOCK:
        pools = list(_POOLS.values())
    now = time.monotonic()
    for pool in pools:
        try:
            stats = pool.get_stats()
            with _lock:
                previous_at, previous = _previous.get(id(pool), (now, stats))
                _previous[id(pool)] = (now, stats.copy())
            values = {key: stats.get(key, 0) for key in (*_GAUGES, *_COUNTERS)}
            values.update({f"{key}_delta": max(0, stats.get(key, 0) - previous.get(key, 0)) for key in _COUNTERS})
            emit("pool_stats", pool=pool.name, sample_interval_s=max(0, now - previous_at), **values)
        except Exception:
            # Missing/failed pools must not interrupt requests or the sampler.
            continue


def start_pool_sampler() -> None:
    global _thread, _stop
    if not enabled():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        try:
            interval = max(1.0, float(os.getenv("POSTGRES_POOL_STATS_INTERVAL_SECONDS", "60")))
            if not math.isfinite(interval):
                interval = 60.0
        except ValueError:
            interval = 60.0
        stop = _stop = threading.Event()

        def sample() -> None:
            log_pool_stats()
            while not stop.wait(interval):
                log_pool_stats()

        _thread = threading.Thread(target=sample, name="postgres-pool-stats", daemon=True)
        _thread.start()


def stop_pool_sampler() -> None:
    global _thread
    _stop.set()
    thread = _thread
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=2)
    _thread = None
    log_pool_stats()
    with _lock:
        _previous.clear()


@contextmanager
def observe_checkout(pool: Any) -> Iterator[None]:
    try:
        start_pool_sampler()
    except Exception:
        pass
    started = time.perf_counter()
    outcome = "error"
    try:
        with measure("pool_ms"):
            yield
        outcome = "ok"
    finally:
        count("pool_acquisitions")
        emit(
            "pool_checkout",
            duration_ms=(time.perf_counter() - started) * 1000,
            pool=getattr(pool, "name", "default"),
            outcome=outcome,
        )


atexit.register(stop_pool_sampler)
