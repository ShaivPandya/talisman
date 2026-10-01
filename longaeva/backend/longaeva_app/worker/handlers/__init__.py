"""Worker job handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from longaeva_app.db.models import Job

Handler = Callable[[Job], dict[str, Any]]

_HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        _HANDLERS[job_type] = fn
        return fn

    return decorator


def get_handler(job_type: str) -> Handler | None:
    return _HANDLERS.get(job_type)


def known_job_types() -> set[str]:
    return set(_HANDLERS)


@register("ping")
def handle_ping(job: Job) -> dict[str, Any]:
    message = job.payload.get("message", "pong")
    return {"message": message, "job_id": str(job.id)}
