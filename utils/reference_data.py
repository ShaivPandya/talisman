"""Daily, single-flight caching for the reference fields used by data jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class _ReferenceUnavailable(Exception):
    """An empty provider result must not become a day-long cached default."""


def daily_reference(namespace: str, ticker: str, loader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    from api.cache import daily_cache, get_or_set_cached

    def load() -> dict[str, Any]:
        value = loader()
        if not value:
            raise _ReferenceUnavailable
        return value

    try:
        result = get_or_set_cached(daily_cache, f"data_job_reference:v1:{namespace}:{ticker.strip().upper()}", load)
    except _ReferenceUnavailable:
        return {}
    return {key: value for key, value in result.items() if key != "_meta"}
