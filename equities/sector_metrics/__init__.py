"""Allow payload helpers to load without importing market-data dependencies."""

from typing import Any

__all__ = ["get_data"]


def __getattr__(name: str) -> Any:
    if name == "get_data":
        from .sector_metrics import get_data

        globals()[name] = get_data
        return get_data
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
