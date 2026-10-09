"""Explicit, bounded capture using the LLM extraction provider and database cache.

Evaluation calls use stable fixture IDs in the exported artifact; their DB
document_text_id is null. They never create or correct production observations.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from longaeva_app.config import Settings
from longaeva_app.db.models import ExtractionCall
from longaeva_app.evaluation.extraction_scoring import (
    EvalPassage,
    GoldLabel,
    corpus_hash,
    require_reviewed,
)
from longaeva_app.extract.cache import find_cached_call, prompt_hash, record_call
from longaeva_app.extract.llm import locate_quote
from longaeva_app.extract.prompts import PROMPT_VERSION, SYSTEM_PROMPT, user_message
from longaeva_app.extract.providers import LLMProvider, ProviderError
from longaeva_app.extract.schemas import ExtractionResponse, extraction_json_schema
from longaeva_app.hashing import content_hash, utc_isoformat


def expected_prompt_hash(passage: EvalPassage) -> str:
    return prompt_hash(
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        user=user_message(
            company=passage.source.company,
            doc_type=passage.source.doc_type,
            passage=passage.text,
            period_label=f"{passage.period_start} to {passage.period_end}",
        ),
        schema=extraction_json_schema(),
    )


def _export_call(row: ExtractionCall, p: EvalPassage, *, cache_hit: bool) -> dict[str, Any]:
    return {
        "passage_id": p.id,
        "extraction_call_id": str(row.id),
        "provider": row.provider,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "prompt_hash": row.prompt_hash,
        "status": row.status,
        "error": row.error,
        "parsed": row.parsed,
        "response_text": row.response_text,
        "item_errors": row.item_errors,
        "attempts": row.attempts,
        "latency_ms": row.latency_ms,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "created_at": utc_isoformat(row.created_at),
        "cache_hit": cache_hit,
        "source_sha256": p.source.content_sha256,
        "text_sha256": p.text_sha256,
    }


def capture_extractions(
    session: Session,
    *,
    gold: list[GoldLabel],
    passages: list[EvalPassage],
    review: dict[str, Any],
    provider: LLMProvider,
    settings: Settings,
    output: Path,
) -> dict[str, Any]:
    require_reviewed(review, gold)
    if len(passages) > 20 or len({p.id for p in passages}) != len(passages):
        raise ValueError("Capture is limited to 20 unique passages")
    if any(len(p.text) > settings.extraction_max_passage_chars for p in passages):
        raise ValueError("Passage exceeds the configured character limit")
    result: dict[str, Any] = {
        "suite_version": "lon18-v1",
        "corpus_hash": corpus_hash(gold, passages),
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": PROMPT_VERSION,
        "prompt_policy_hash": content_hash({"system": SYSTEM_PROMPT, "schema": extraction_json_schema()}),
        "calls": [],
    }
    # A checkpoint prevents an interrupted run from repeating failed calls. A new
    # file is needed to explicitly budget a new capture; no automatic tuning loop.
    previous: dict[str, Any] = json.loads(output.read_text()) if output.is_file() else {}
    if previous and any(
        previous.get(k) != result[k]
        for k in ("corpus_hash", "provider", "model", "prompt_version", "prompt_policy_hash")
    ):
        raise ValueError("Existing capture checkpoint has different inputs")
    checkpoint: dict[str, dict[str, Any]] = {}
    by_id = {p.id: p for p in passages}
    for call in previous.get("calls", []):
        passage_id = call.get("passage_id")
        if passage_id not in by_id or passage_id in checkpoint:
            raise ValueError("Duplicate or unknown checkpoint passage ID")
        if call.get("prompt_hash") != expected_prompt_hash(by_id[passage_id]):
            raise ValueError("Checkpoint prompt mismatch")
        checkpoint[passage_id] = call
    output.parent.mkdir(parents=True, exist_ok=True)
    for p in passages:
        digest = expected_prompt_hash(p)
        existing = checkpoint.get(p.id)
        if existing:
            if existing.get("prompt_hash") != digest:
                raise ValueError("Checkpoint prompt mismatch")
            result["calls"].append(existing)
        else:
            row = find_cached_call(session, provider=provider.name, model=provider.model, prompt_hash=digest)
            hit = row is not None
            if row is None:
                started = time.perf_counter()
                status, parsed, response_text, error = "succeeded", None, None, None
                item_errors: list[dict[str, Any]] = []
                attempts, input_tokens, output_tokens = 0, None, None
                try:
                    response = provider.complete(
                        system=SYSTEM_PROMPT,
                        user=user_message(
                            company=p.source.company,
                            doc_type=p.source.doc_type,
                            passage=p.text,
                            period_label=f"{p.period_start} to {p.period_end}",
                        ),
                    )
                    response_text = response.text
                    attempts, input_tokens, output_tokens = (
                        response.attempts,
                        response.input_tokens,
                        response.output_tokens,
                    )
                    try:
                        validated = ExtractionResponse.model_validate(response.parsed)
                        parsed = validated.model_dump(mode="json")
                        item_errors = [
                            {"index": i, "code": "quote_not_found", "quote": o.quote}
                            for i, o in enumerate(validated.observations)
                            if locate_quote(p.text, o.quote) is None
                        ]
                    except ValidationError:
                        status, error = "invalid_response", "Response did not match the extraction schema"
                except ProviderError as exc:
                    status, error, attempts = "provider_error", exc.message, exc.attempts
                row = record_call(
                    session,
                    provider=provider.name,
                    model=provider.model,
                    prompt_version=PROMPT_VERSION,
                    prompt_hash=digest,
                    document_text_id=None,
                    job_id=None,
                    status=status,
                    response_text=response_text,
                    parsed=parsed,
                    item_errors=item_errors,
                    error=error,
                    attempts=attempts,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                session.commit()
            result["calls"].append(_export_call(row, p, cache_hit=hit))
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        temporary.replace(output)
        print(f"{p.id}: {result['calls'][-1]['status']} (cached={result['calls'][-1]['cache_hit']})", flush=True)
    return result
