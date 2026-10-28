"""Weekly idea scan: run history, digest cards, presets and manual runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.async_job_runner import enqueue_registered_job, enqueue_response, poll_registered_job
from api.idea_scan import store
from api.idea_scan.presets import (
    IdeaScanSettings,
    default_settings,
    get_idea_scan_settings,
    reset_idea_scan_settings,
    set_idea_scan_settings,
)
from api.idea_scan.requests import IdeaScanRunRequest

router = APIRouter()

Direction = Literal["long", "short"]


class ManualRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universes: list[Literal["sp500", "sp400", "sp600", "russell2000"]] | None = None
    tickers: list[str] | None = Field(default=None, max_length=300)
    preset_ids: list[str] | None = None
    max_reviews: int | None = Field(default=None, ge=0, le=50)
    max_cost_usd: float | None = Field(default=None, ge=0, le=10)
    publish_to_scout: bool = True


def _run_or_404(run_id: str) -> dict[str, Any]:
    try:
        return store.get_run(run_id)
    except store.RunNotFound:
        raise HTTPException(status_code=404, detail="Unknown idea scan run")  # noqa: B904


def _find_card(run: dict[str, Any], direction: str, ticker: str) -> dict[str, Any]:
    wanted = ticker.strip().upper()
    for card in run.get("candidates") or []:
        if card.get("ticker") == wanted and card.get("direction") == direction:
            return cast(dict[str, Any], card)
    raise HTTPException(status_code=404, detail="Unknown candidate for this run")


@router.get("/idea-scan/runs")
def list_idea_scan_runs(limit: int = 52):
    return {"runs": store.list_runs(limit=max(1, min(limit, store.INDEX_LIMIT)))}


@router.get("/idea-scan/runs/{run_id}")
def get_idea_scan_run(run_id: str):
    return _run_or_404(run_id)


@router.post("/idea-scan/runs")
def start_idea_scan_run(body: ManualRunRequest | None = None):
    payload = IdeaScanRunRequest(source="manual", **(body.model_dump() if body else {})).model_dump()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    row, _disposition = enqueue_registered_job(
        "weekly_idea_scan",
        payload,
        cache_key=f"idea_scan:manual:v1:{digest}",
        reuse_completed=False,
    )
    return enqueue_response(row, "/api/idea-scan/jobs/{job_id}")


@router.get("/idea-scan/jobs/{job_id}")
def get_idea_scan_job(job_id: str):
    try:
        return poll_registered_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown job_id")  # noqa: B904


@router.get("/idea-scan/settings")
def get_idea_scan_settings_endpoint():
    return {"settings": get_idea_scan_settings().model_dump(), "defaults": default_settings().model_dump()}


@router.put("/idea-scan/settings")
def put_idea_scan_settings(body: IdeaScanSettings):
    return {"settings": set_idea_scan_settings(body).model_dump()}


@router.post("/idea-scan/settings/reset")
def reset_idea_scan_settings_endpoint():
    return {"settings": reset_idea_scan_settings().model_dump()}


@router.post("/idea-scan/runs/{run_id}/candidates/{direction}/{ticker}/dismiss")
def dismiss_idea_scan_candidate(run_id: str, direction: Direction, ticker: str):
    _find_card(_run_or_404(run_id), direction, ticker)

    def change(run: dict[str, Any]) -> None:
        _find_card(run, direction, ticker)["card_state"] = "dismissed"

    run = store.mutate_run(run_id, change)
    return {"candidate": _find_card(run, direction, ticker)}


def card_notes(run: dict[str, Any], card: dict[str, Any]) -> str:
    """The digest card as markdown notes for a new idea."""
    review = card.get("review") or {}
    lines = [
        f"From the weekly idea scan ({run.get('week')}, {card['direction']}).",
        "",
        f"Presets: {', '.join(p['name'] for p in card.get('presets') or [])}",
        f"Agreement score: {card.get('agreement_score', 0):.2f} (macro boost {card.get('macro_boost', 0):+.2f})",
    ]
    signals = card.get("signals") or []
    if signals:
        lines += ["", "Signals:", *[f"- {s['label']}" for s in signals]]
    fit = card.get("macro_fit")
    if fit:
        lines += ["", f"Macro fit: {fit['sector']} {fit['score']:+d} ({fit['confidence']}) — {fit.get('reason') or ''}"]
    for key, label in (("trigger", "Trigger"), ("why_now", "Why now"), ("variant_view", "Variant view")):
        if review.get(key):
            lines += ["", f"{label}: {review[key]}"]
    headlines = review.get("headlines") or []
    if headlines:
        lines += [
            "",
            "Headlines:",
            *[f"- [{h['title']}]({h['url']}) {h.get('date') or ''}".rstrip() for h in headlines],
        ]
    missing = review.get("missing_inputs") or []
    if missing:
        lines += ["", "Still missing:", *[f"- {m}" for m in missing]]
    lines += ["", f"Idea scan run: {run['run_id']}"]
    return "\n".join(lines)


@router.post("/idea-scan/runs/{run_id}/candidates/{direction}/{ticker}/promote")
def promote_idea_scan_candidate(run_id: str, direction: Direction, ticker: str):
    from api.routers.ideas import IdeaCreateRequest, create_idea

    run = _run_or_404(run_id)
    card = _find_card(run, direction, ticker)
    if card.get("idea_id"):
        return {"candidate": card, "idea_id": card["idea_id"], "created": False}

    idea = create_idea(
        IdeaCreateRequest(
            ticker=card["ticker"],
            company_name=card.get("company") or None,
            user_notes=card_notes(run, card),
            tags=[p["name"] for p in card.get("presets") or []],
            status="watching",
            analyzer_direction=direction,
        )
    )
    idea_id = str(((idea or {}).get("idea") or {}).get("id") or "")
    if not idea_id:
        raise HTTPException(status_code=502, detail="The idea was not created")

    def change(current: dict[str, Any]) -> None:
        target = _find_card(current, direction, ticker)
        target["card_state"] = "promoted"
        target["idea_id"] = idea_id

    run = store.mutate_run(run_id, change)
    return {"candidate": _find_card(run, direction, ticker), "idea_id": idea_id, "created": True}
