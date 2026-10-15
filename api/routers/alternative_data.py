from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api import alternative_data as service
from api.async_job_runner import enqueue_registered_job, enqueue_response
from api.routers.auth import require_actor
from ontology.policy import Actor, actor_to_dict

router = APIRouter()
ActorDep = Annotated[Actor, Depends(require_actor)]


@router.get("/alternative-data/catalog")
def catalog(query: str = "", group: str | None = None, ticker: str | None = None, available_only: bool = False):
    try:
        return service.search_catalog(query, group=group, ticker=ticker, available_only=available_only)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/alternative-data/fetch")
def fetch(req: service.FetchRequest, actor: ActorDep):
    try:
        return service.enqueue_fetch(req.model_copy(update={"actor": actor_to_dict(actor)}))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/alternative-data/jobs/{job_id}")
def poll(job_id: str):
    try:
        return service.poll_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown alternative-data job") from exc


@router.get("/alternative-data/sites")
def sites(ticker: str):
    try:
        return {"sites": service.list_sites(ticker)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/alternative-data/sites/confirm")
def confirm(req: service.SiteRequest, actor: ActorDep):
    try:
        return service.confirm_site(req, actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/alternative-data/sites/suggest")
def suggest(req: service.CompanyEvidenceRequest, actor: ActorDep):
    row, _ = enqueue_registered_job(
        "alternative_data_sites",
        req.model_copy(update={"actor": actor_to_dict(actor)}).model_dump(),
        reuse_completed=False,
    )
    return enqueue_response(row, "/api/alternative-data/jobs/{job_id}")


@router.delete("/alternative-data/sites/{site_id}")
def remove(site_id: str, actor: ActorDep):
    try:
        return service.remove_site(site_id, actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
