"""Authenticated workspace source files; writes use the app's administrator role."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import name_documents as documents
from api.request_limits import read_upload_file_bytes
from api.routers.auth import require_admin
from ontology.policy import Actor

router = APIRouter()
Admin = Annotated[Actor, Depends(require_admin)]


class AttachDocumentsRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=20)


@router.get("/names/{ticker}/documents")
def list_name_documents(ticker: str):
    return documents.list_documents(ticker)


@router.post("/names/{ticker}/documents", status_code=201)
async def upload_name_document(ticker: str, actor: Admin, file: UploadFile = File(...)):  # noqa: B008
    data = await read_upload_file_bytes(file, limit_bytes=documents.MAX_UPLOAD_BYTES, limit_label="20 MiB")
    return await run_in_threadpool(documents.upload, ticker, data, file.filename or "")


@router.post("/names/{ticker}/documents/{document_id}/attach")
def attach_name_document(ticker: str, document_id: str, body: AttachDocumentsRequest, actor: Admin):
    return {"documents": documents.attach(ticker, document_id, body.tickers)}


@router.delete("/names/{ticker}/documents/{document_id}", status_code=204)
def delete_name_document(ticker: str, document_id: str, actor: Admin):
    documents.delete(ticker, document_id)
    return Response(status_code=204)


@router.get("/source-files")
def source_file_library():
    return documents.library()


@router.delete("/source-files/{sha256}", status_code=204)
def delete_source_file(sha256: str, actor: Admin):
    documents.delete_everywhere(sha256)
    return Response(status_code=204)


@router.get("/names/{ticker}/documents/{document_id}/content")
def read_name_document(ticker: str, document_id: str):
    meta = documents.get_document(ticker, document_id)
    return Response(
        content=documents.original(ticker, document_id),
        media_type=meta["mime_type"],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(meta['name'])}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
