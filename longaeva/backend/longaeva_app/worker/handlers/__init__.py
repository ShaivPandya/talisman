"""Worker job handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.db.models import Job
from longaeva_app.storage.local import LocalArtifactStore

INTERNAL_JOB_TYPES: frozenset[str] = frozenset({"run", "extract"})


@dataclass(frozen=True, slots=True)
class HandlerContext:
    job: Job
    session_factory: sessionmaker[Session]
    artifact_store: LocalArtifactStore
    worker_id: str


Handler = Callable[[HandlerContext], dict[str, Any]]

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


def public_job_types() -> set[str]:
    return {name for name in _HANDLERS if name not in INTERNAL_JOB_TYPES}


@register("ping")
def handle_ping(ctx: HandlerContext) -> dict[str, Any]:
    message = ctx.job.payload.get("message", "pong")
    return {"message": message, "job_id": str(ctx.job.id)}


def load_handlers() -> None:
    from longaeva_app.worker.handlers import extract as _extract  # noqa: F401
    from longaeva_app.worker.handlers import run as _run  # noqa: F401


load_handlers()
