"""Machine endpoint for the newsletter pipeline to publish digests without a browser session."""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from api.exceptions import NotFoundError, ValidationError
from api.request_limits import read_upload_file_bytes
from api.routers.portfolio_news import MAX_UPLOAD_SIZE_BYTES, _decode_markdown_upload, _is_markdown_upload

router = APIRouter()
log = logging.getLogger(__name__)

SECRET_ENV = "NEWS_DIGEST_SYNC_SECRET"
SECRET_HEADER = "X-News-Digest-Sync-Secret"
SOURCE_ID = "news_digest_sync"


def require_news_digest_sync_secret(provided: str | None) -> None:
    expected = (os.getenv(SECRET_ENV) or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="News digest sync is not configured"
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid news digest sync secret")


def _apply_action(action_id: str, payload: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Propose and approve in one step: the shared secret is the user's standing approval."""
    from ontology.command_service import OntologyCommandContext, OntologyCommandService
    from ontology.policy import system_actor

    service = OntologyCommandService()
    context = OntologyCommandContext(
        actor=system_actor(SOURCE_ID),
        source_type="workflow",
        source_id=SOURCE_ID,
        request_mode="self_apply",
    )
    approval = service.propose_action(action_id, payload, context, reason=reason)
    return service.resolve_approval(str(approval["id"]), "approved", "Applied by the newsletter pipeline", context)


def _publish_digest(payload: bytes, *, filename: str) -> dict[str, Any]:
    from portfolio.news_digests import find_existing_digest

    filename = Path(filename).name
    content = _decode_markdown_upload(payload)
    existing = find_existing_digest(content, filename=filename)
    if existing:
        return {"status": "unchanged", "id": existing["id"], "story_count": existing.get("story_count")}

    approval = _apply_action(
        "create_portfolio_news_digest",
        {"content": content, "filename": filename},
        reason=f"Newsletter pipeline upload {filename}",
    )
    if approval.get("application_status") != "applied":
        raise HTTPException(
            status_code=500, detail=f"Digest upload was not applied: {approval.get('application_status')}"
        )
    published = find_existing_digest(content, filename=filename)
    if not published:
        raise HTTPException(status_code=500, detail="Digest upload applied but the digest is missing")
    log.info("Published news digest %s (%s stories)", published["id"], published.get("story_count"))
    return {"status": "published", "id": published["id"], "story_count": published.get("story_count")}


@router.get("/news-digest-sync")
def list_synced_digests(secret: str | None = Header(default=None, alias=SECRET_HEADER)):
    """List stored digests so the pipeline can reconcile or clear them."""
    require_news_digest_sync_secret(secret)
    from portfolio.news_digests import list_digest_summaries

    keys = ("id", "title", "filename", "generated_date", "story_count", "content_hash")
    return {"items": [{key: item.get(key) for key in keys} for item in list_digest_summaries()]}


@router.post("/news-digest-sync")
async def publish_digest(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI parameter declaration
    secret: str | None = Header(default=None, alias=SECRET_HEADER),
):
    """Publish a markdown digest immediately; re-sending identical content is a no-op."""
    require_news_digest_sync_secret(secret)
    if not _is_markdown_upload(file):
        raise ValidationError("File must be a Markdown (.md) file.")
    payload = await read_upload_file_bytes(file, limit_bytes=MAX_UPLOAD_SIZE_BYTES, limit_label="10 MiB")
    if not payload:
        raise ValidationError("Uploaded file is empty.")
    return await run_in_threadpool(_publish_digest, payload, filename=file.filename or "digest.md")


@router.delete("/news-digest-sync/{digest_id}")
def delete_synced_digest(digest_id: str, secret: str | None = Header(default=None, alias=SECRET_HEADER)):
    require_news_digest_sync_secret(secret)
    from portfolio.news_digests import get_digest, validate_digest_id

    try:
        normalized = validate_digest_id(digest_id)
    except ValueError as exc:
        raise ValidationError("Invalid news digest id.") from exc
    try:
        get_digest(normalized)
    except FileNotFoundError as exc:
        raise NotFoundError("news digest", normalized) from exc
    approval = _apply_action(
        "delete_portfolio_news_digest",
        {"digest_id": normalized},
        reason=f"Newsletter pipeline delete {normalized}",
    )
    return {"status": approval.get("application_status"), "id": normalized}
