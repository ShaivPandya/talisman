"""Process-local source-health cache with one expiry for all derived inputs.

Snapshot writers invalidate this process after committing. Other API/worker
processes observe changes within the 60-second TTL. No persistent cache I/O.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from typing import Any, cast

SOURCE_HEALTH_TTL_SECONDS = 60
_condition = threading.Condition()
_values: dict[str, Any] = {}
_pending: set[tuple[int, str]] = set()
_generation = 0
_expires_at = 0.0


def invalidate_source_health() -> None:
    """Discard cached values without allowing an older fill to restore them."""
    global _generation, _expires_at
    with _condition:
        _generation += 1
        _expires_at = 0.0
        _values.clear()
        _condition.notify_all()


def cached_source_health_value[T](key: str, load: Callable[[], T]) -> T:
    """Coalesce each fill and return an isolated copy of the compact read model."""
    global _generation, _expires_at
    while True:
        with _condition:
            now = time.monotonic()
            if now >= _expires_at:
                _generation += 1
                _values.clear()
                # Inputs and their derived health result share an expiry, so
                # stacked caches cannot extend the freshness window to 120 s.
                _expires_at = now + SOURCE_HEALTH_TTL_SECONDS
            token = (_generation, key)
            if key in _values:
                return cast(T, copy.deepcopy(_values[key]))
            if token in _pending:
                _condition.wait()
                continue
            _pending.add(token)
            break
    try:
        value = load()
        with _condition:
            if token[0] == _generation and time.monotonic() < _expires_at:
                _values[key] = copy.deepcopy(value)
        return value
    finally:
        with _condition:
            _pending.discard(token)
            _condition.notify_all()
