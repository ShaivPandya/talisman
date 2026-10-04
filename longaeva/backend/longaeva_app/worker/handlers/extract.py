"""Worker handler for passage extraction (LON-16)."""

from __future__ import annotations

import uuid
from typing import Any

from longaeva_app.config import get_settings
from longaeva_app.extract.llm import ExtractionError, load_passages, run_extraction
from longaeva_app.extract.providers import build_provider
from longaeva_app.worker.handlers import HandlerContext, register


@register("extract")
def handle_extract(ctx: HandlerContext) -> dict[str, Any]:
    raw_ids = ctx.job.payload.get("document_text_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError("extract job payload missing document_text_ids")
    passage_ids = [uuid.UUID(str(item)) for item in raw_ids]
    provider_name = ctx.job.payload.get("provider")
    model_name = ctx.job.payload.get("model")
    provider_override = provider_name if isinstance(provider_name, str) and provider_name else None
    model_override = model_name if isinstance(model_name, str) and model_name else None
    settings = get_settings()
    provider = build_provider(settings, provider=provider_override, model=model_override)
    if provider is None:
        raise ExtractionError("Extraction is disabled for this job", status_code=503)
    try:
        with ctx.session_factory() as session:
            passages = load_passages(session, passage_ids, settings=settings)
            report = run_extraction(
                session,
                passages,
                provider=provider,
                settings=settings,
                store=ctx.artifact_store,
                job_id=ctx.job.id,
            )
            session.commit()
            return report.to_dict()
    finally:
        provider.close()
