"""Authenticated research library; administrators manage files and readers can cite them."""

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api import research, research_store
from api.request_limits import read_upload_file_bytes
from api.research_processing import MAX_UPLOAD_BYTES
from api.routers.auth import require_actor, require_admin
from ontology.policy import Actor

router = APIRouter()
Admin = Annotated[Actor, Depends(require_admin)]
Reader = Annotated[Actor, Depends(require_actor)]
Category = Literal["equity_strategy", "credit_strategy", "economic", "industry_thematic"]


class CategoryUpdate(BaseModel):
    category: Category


@router.get("/research/reports")
def list_reports(
    actor: Reader,
    q: str = Query("", max_length=300),
    category: Category | None = None,
    institution: str = Query("", max_length=300),
    date_from: str = "",
    date_to: str = "",
    sort: Literal["publication", "uploaded"] = "publication",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    result = research.list_reports(
        query=q,
        category=category,
        institution=institution,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        offset=offset,
        limit=limit,
    )
    return {**result, "can_manage": "admin" in actor.roles}


@router.post("/research/reports", status_code=202)
async def upload_report(actor: Admin, file: UploadFile = File(...), category: Category | None = Form(None)):  # noqa: B008
    data = await read_upload_file_bytes(file, limit_bytes=MAX_UPLOAD_BYTES, limit_label="30 MiB")
    return await run_in_threadpool(research.upload, data, file.filename or "", category, research.actor_dict(actor))


@router.get("/research/reports/{report_id}")
def get_report(report_id: str, actor: Reader):
    return {**research.detail(report_id), "can_manage": "admin" in actor.roles}


@router.patch("/research/reports/{report_id}")
def update_category(report_id: str, body: CategoryUpdate, actor: Admin):
    return research.change_category(report_id, body.category, research.actor_dict(actor))


@router.post("/research/reports/{report_id}/retry", status_code=202)
def retry_report(report_id: str, actor: Admin):
    return research.retry(report_id, research.actor_dict(actor))


@router.post("/research/reports/{report_id}/reindex", status_code=202)
def reindex_report(report_id: str, actor: Admin):
    state = research_store.get(report_id)
    research.enqueue_index(state, research.actor_dict(actor))
    return {"status": "queued"}


@router.delete("/research/reports/{report_id}", status_code=204)
def delete_report(report_id: str, actor: Admin):
    research.delete(report_id, research.actor_dict(actor))
    return Response(status_code=204)


@router.get("/research/reports/{report_id}/markdown")
def download_markdown(report_id: str, actor: Reader):
    data, filename = research.markdown_download(report_id)
    return Response(
        data,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/research/reports/{report_id}/original")
def original_pdf(report_id: str, actor: Reader):
    state = research_store.get(report_id)
    return Response(
        research_store.read_blob(report_id, "original.pdf"),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(state['filename'], safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )
