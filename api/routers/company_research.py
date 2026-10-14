"""Authenticated company research and global prompt endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.agent_governance import redact_secrets
from api.async_job_runner import enqueue_registered_job, job_response, poll_registered_job
from api.audit import emit_audit_event
from api.company_research import (
    RESEARCH_KINDS,
    CompanyResearchJobRequest,
    ResearchKind,
    ResearchPromptsUpdate,
    archived_report_status,
    read_research_report,
    require_research_key,
    research_cache_key,
    research_settings,
    save_research_prompts,
)
from api.exceptions import AppError
from api.job_queue import latest_job_for_key
from api.routers.auth import ActorDep
from api.routers.overview import _normalize_ticker, _validate_ticker
from ontology.policy import actor_to_dict

router = APIRouter()


class StartCompanyResearchRequest(BaseModel):
    kinds: list[ResearchKind] = Field(default_factory=lambda: list(RESEARCH_KINDS), min_length=1, max_length=2)


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
    settings = research_settings()
    reports = {}
    for kind in dict.fromkeys(body.kinds):
        req = CompanyResearchJobRequest(
            ticker=ticker,
            kind=kind,
            prompt=settings[f"{kind}_prompt"],
            prompt_version=settings["updated_at"] or "default-v1",
            model=settings["model"],
            actor=actor_to_dict(actor),
            requested_at=datetime.now(UTC).isoformat(),
        )
        try:
            row, _disposition = enqueue_registered_job(
                "company_research",
                req.model_dump(),
                cache_key=research_cache_key(ticker, kind),
                reuse_completed=False,
            )
            reports[kind] = job_response(row)
        except Exception as exc:
            # Attempt the other report even if this dispatch failed.
            message = (
                exc.message if isinstance(exc, AppError) else "Could not start this research report. Please retry."
            )
            sanitized, _findings = redact_secrets({"error": message})
            reports[kind] = {"status": "error", "error": sanitized["error"], "report_available": False}
    return {"ticker": ticker, "reports": reports}


@router.get("/company-research/{ticker}")
def get_company_research_status(ticker: str):
    ticker = _normalize_ticker(ticker)
    _validate_ticker(ticker)
    reports = {}
    for kind in RESEARCH_KINDS:
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
