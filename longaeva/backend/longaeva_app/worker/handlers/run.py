"""Worker handler that executes a queued simulation run (LON-23)."""

from __future__ import annotations

import uuid
from typing import Any

from longaeva_app.runs.service import execute_run
from longaeva_app.worker.handlers import HandlerContext, register


@register("run")
def handle_run(ctx: HandlerContext) -> dict[str, Any]:
    raw_id = ctx.job.payload.get("run_id")
    if not raw_id:
        raise ValueError("run job payload missing run_id")
    run_id = uuid.UUID(str(raw_id))
    return execute_run(
        ctx.session_factory,
        run_id,
        job_id=ctx.job.id,
        artifact_store=ctx.artifact_store,
    )
