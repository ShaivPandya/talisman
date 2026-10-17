"""Authenticated company research and global prompt endpoints."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api import company_research_store as store
from api.async_job_runner import enqueue_registered_job, poll_registered_job
from api.audit import emit_audit_event
from api.company_research import (
    RESEARCH_KINDS,
    ResearchKind,
    ResearchPromptsUpdate,
    archived_report_status,
    read_research_report,
    require_research_key,
    research_cache_key,
    research_settings,
    save_research_prompts,
)
from api.exceptions import AppError, ConflictError, NotFoundError
from api.job_queue import latest_job_for_key
from api.routers.auth import ActorDep
from api.routers.overview import _normalize_ticker, _validate_ticker
from ontology.policy import actor_to_dict

router = APIRouter()


class StartCompanyResearchRequest(BaseModel):
    kinds: list[ResearchKind] = Field(default_factory=lambda: list(RESEARCH_KINDS), min_length=1, max_length=2)
    resume_run_id: UUID | None = None


def _report_status(state, kind, actor_id=None):
    report = state["reports"][kind]
    expired = state["deadline"] <= time.time()
    stopped = report["status"] != "done" and (
        expired or (state["status"] == "running" and state.get("lease_until", 0) <= time.time())
    )
    status = "incomplete" if stopped else report["status"]
    resumable = (
        status == "incomplete"
        and not expired
        and state["charged_usd"] < state["max_cost_usd"]
        and actor_id == state["snapshot"]["actor"].get("actor_id")
    )
    return {
        "job_id": state["run_id"],
        "run_id": state["run_id"],
        "status": status,
        "error": "Research reached its 55-minute limit; completed evidence is retained."
        if expired and stopped
        else report.get("error"),
        "report_available": report.get("report_available", False),
        "progress": report,
        "budget": store.budget_summary(state),
        "resumable": resumable,
    }


@router.get("/settings/company-research")
def get_company_research_settings():
    return research_settings()


@router.put("/settings/company-research")
def update_company_research_settings(body: ResearchPromptsUpdate, actor: ActorDep):
    result = save_research_prompts(body)
    emit_audit_event(
        "settings.company_research.update",
        "settings",
        "succeeded",
        actor=actor,
        after_summary={
            "overview_prompt": body.overview_prompt,
            "management_quality_prompt": body.management_quality_prompt,
        },
    )
    return result


@router.post("/company-research/{ticker}", status_code=202)
def start_company_research(ticker: str, body: StartCompanyResearchRequest, actor: ActorDep):
    ticker = _normalize_ticker(ticker)
    _validate_ticker(ticker)
    require_research_key()
    actor_id = actor_to_dict(actor).get("actor_id")
    if body.resume_run_id:
        try:
            state = store.get_run(str(body.resume_run_id))
        except KeyError as exc:
            raise NotFoundError("Research run") from exc
        if state["ticker"] != ticker or state["snapshot"]["actor"].get("actor_id") != actor_id:
            raise NotFoundError("Research run")
        if state["status"] == "done":
            return {"ticker": ticker, "reports": {k: _report_status(state, k, actor_id) for k in state["reports"]}}
        if state["deadline"] <= time.time() or state["charged_usd"] >= state["max_cost_usd"]:
            raise ConflictError(
                "This run has exhausted its original allowance. Start a new run explicitly to research again."
            )
        state = store.resume_run(state["run_id"])
    else:
        settings = research_settings()
        if settings["model"] != "gpt-6.1-sol":
            raise AppError("Budgeted research requires COMPANY_RESEARCH_MODEL=gpt-6.1-sol.", status_code=503)
        try:
            state, _created = store.create_run(
                {
                    "ticker": ticker,
                    "kinds": list(dict.fromkeys(body.kinds)),
                    "prompts": {kind: settings[f"{kind}_prompt"] for kind in body.kinds},
                    "prompt_version": settings["updated_at"] or "default-v1",
                    "model": settings["model"],
                    "actor": actor_to_dict(actor),
                    "requested_at": datetime.now(UTC).isoformat(),
                    "pricing_version": "gpt-6.1-sol-standard-2026-10-17",
                }
            )
        except store.ResearchLimitReached as exc:
            raise ConflictError(str(exc)) from exc
    try:
        row, _ = enqueue_registered_job(
            "company_research_run",
            {"run_id": state["run_id"]},
            cache_key=f"company_research_run:{state['run_id']}:{state.get('dispatch_generation', 0)}",
            reuse_completed=False,
        )
        state = store.mutate_run(state["run_id"], lambda s: s.update(job_id=str(row["job_id"])))
    except Exception as exc:

        def failed(s):
            if s["status"] != "running":
                s["status"] = "incomplete"
                for report in s["reports"].values():
                    if report["status"] != "done":
                        report.update(
                            status="incomplete",
                            error="Could not dispatch research. Resume to retry within the original allowance.",
                        )

        store.mutate_run(state["run_id"], failed)
        raise AppError(
            "Could not dispatch research. The run and its original allowance are retained.", status_code=503
        ) from exc
    return {"ticker": ticker, "reports": {k: _report_status(state, k, actor_id) for k in state["reports"]}}


@router.get("/company-research/{ticker}")
def get_company_research_status(ticker: str, actor: ActorDep):
    ticker = _normalize_ticker(ticker)
    _validate_ticker(ticker)
    reports = {}
    runs = store.latest_runs(ticker)
    for kind in RESEARCH_KINDS:
        state = next((r for r in runs if kind in r["reports"] and r["apply"]), None)
        if state:
            reports[kind] = _report_status(state, kind, actor_to_dict(actor).get("actor_id"))
            continue
        row = latest_job_for_key("company_research", research_cache_key(ticker, kind))
        if row:
            response = poll_registered_job(str(row["job_id"]), row=row)
            response["report_available"] = bool(
                (response.get("result") or {}).get("report_available")
                or (response.get("progress") or {}).get("report_available")
            )
            reports[kind] = response
        else:
            reports[kind] = archived_report_status(ticker, kind)
    return {"ticker": ticker, "reports": reports}


@router.get("/company-research/{ticker}/reports/{kind}")
def get_company_research_report(ticker: str, kind: ResearchKind, job_id: UUID | None = None):
    ticker = _normalize_ticker(ticker)
    _validate_ticker(ticker)
    return read_research_report(ticker, kind, str(job_id) if job_id else None)
