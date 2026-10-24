"""Upload and read the files attached to agent chat messages."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from api.chat_attachments import MAX_UPLOAD_BYTES, load_attachment, read_attachment_bytes, store_attachment
from api.request_limits import read_upload_file_bytes

router = APIRouter()

# The largest any kind may be; ``store_attachment`` applies the limit for the file's actual kind.
_READ_LIMIT_BYTES = max(MAX_UPLOAD_BYTES.values())


def _store_upload(data: bytes, filename: str, content_type: str) -> dict[str, Any]:
    return store_attachment(data, filename=filename, content_type=content_type).descriptor()


@router.post("/agent/attachments")
async def upload_agent_attachment(file: UploadFile = File(...)):  # noqa: B008 - FastAPI parameter declaration
    data = await read_upload_file_bytes(file, limit_bytes=_READ_LIMIT_BYTES, limit_label="20 MiB")
    return await run_in_threadpool(_store_upload, data, file.filename or "", file.content_type or "")


@router.get("/agent/attachments/{attachment_id}")
def read_agent_attachment(attachment_id: str):
    attachment = load_attachment(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    disposition = "inline" if attachment.kind in {"image", "pdf"} else "attachment"
    return Response(
        content=read_attachment_bytes(attachment),
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(attachment.name)}",
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )
