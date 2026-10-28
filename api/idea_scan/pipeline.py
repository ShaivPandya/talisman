"""The weekly idea scan job: universe → shared data → presets → macro → capped reviews → digest.

The output is a list of names worth a human look, not trade recommendations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from api.idea_scan import store
from api.idea_scan.budget import RunBudget
from api.idea_scan.data import fetch_dataset, fetch_eps_revisions, resolve_membership
from api.idea_scan.macro_view import resolve_effort, run_macro_view
from api.idea_scan.presets import UNIVERSE_KEYS, get_idea_scan_settings
from api.idea_scan.requests import IdeaScanRunRequest
from api.idea_scan.review import build_scout_record, review_candidate
from api.idea_scan.screening import (
    apply_macro,
    breakdown_revision_tickers,
    build_factor_frame,
    collect_near_misses,
    evaluate_preset,
    json_safe,
    merge_candidates,
    split_tracked,
    week_over_week,
)

LOGGER = logging.getLogger(__name__)

DIGEST_MAX_OUTPUT_TOKENS = 1200


def tracked_tickers() -> dict[str, str]:
    """Tickers already in the portfolio ("position") or on the Ideas list ("idea")."""
    from ontology.runtime_read_service import OntologyRuntimeReadService

    service = OntologyRuntimeReadService()
    out: dict[str, str] = {}
    try:
        for idea in service.ideas_list(include_archived=False, limit=1000):
            ticker = str(idea.get("ticker") or "").strip().upper()
            if ticker:
                out[ticker] = "idea"
    except Exception:
        LOGGER.warning("Idea scan could not read Ideas; nothing will be marked as tracked from them", exc_info=True)
    try:
        for position in service.positions():
            ticker = str(position.get("ticker") or "").strip().upper()
            if ticker:
                out[ticker] = "position"
    except Exception:
        LOGGER.warning("Idea scan could not read positions", exc_info=True)
    return out


def _existing_scout_status(candidate_id: str) -> str | None:
    from ontology.runtime_read_service import OntologyRuntimeReadService
    from ontology.schemas.identity import opportunity_candidate_id

    try:
        row = OntologyRuntimeReadService().get(opportunity_candidate_id(candidate_id))
    except Exception:
        return None
    return str(row.get("status")) if row else None


def publish_to_scout(candidate: dict[str, Any], *, run_id: str, week: str, screen_kinds: Mapping[str, str]) -> str:
    """Write a reviewed name to the Scout queue. Returns the publish status shown on the card."""
    from decision_quality.opportunity_scout import persist_proactive_opportunity_candidate

    record = build_scout_record(candidate, candidate["review"], run_id=run_id, week=week, screen_kinds=screen_kinds)
    if record is None:
        return "blocked"
    existing = _existing_scout_status(record["candidate_id"])
    if existing and existing != "open":
        # Rerunning the same week must not reopen a candidate someone already dismissed or promoted.
        candidate["scout_candidate_id"] = record["candidate_id"]
        return f"kept_{existing}"
    try:
        persist_proactive_opportunity_candidate(record, actor_id="idea_scan", source_id=record["source_id"])
    except Exception:
        LOGGER.warning("Scout publish failed for %s", candidate["ticker"], exc_info=True)
        return "failed"
    candidate["scout_candidate_id"] = record["candidate_id"]
    return "published"


def _fallback_summary(longs: int, shorts: int, reviewed: int, macro: dict[str, Any]) -> str:
    if not longs and not shorts:
        text = "Nothing cleared the bar this week. The near-misses below came closest."
    else:
        text = f"{longs} long and {shorts} short candidates cleared the screens; {reviewed} got a quick review."
    tail = [r["sector"] for r in macro.get("rows") or [] if r.get("score", 0) >= 1]
    head = [r["sector"] for r in macro.get("rows") or [] if r.get("score", 0) <= -1]
    if tail:
        text += f" Macro tailwinds: {', '.join(tail)}."
    if head:
        text += f" Headwinds: {', '.join(head)}."
    return text


def summarize_digest(
    candidates: list[dict[str, Any]],
    macro: dict[str, Any],
    *,
    budget: RunBudget,
    call: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """A short written lead for the digest; falls back to a counted summary if the budget or call fails."""
    from llm_utils import MODEL_MID, call_llm_text

    longs = sum(1 for c in candidates if c["direction"] == "long")
    shorts = len(candidates) - longs
    reviewed = [c for c in candidates if c.get("review_status") == "reviewed"]
    fallback = {"text": _fallback_summary(longs, shorts, len(reviewed), macro), "origin": "rule"}
    if not reviewed or not budget.can_start("digest"):
        if reviewed:
            budget.skip("digest", "Digest summary")
        return fallback
    lines = [
        f"- {c['ticker']} ({c['direction']}, {c.get('sector')}): {', '.join(p['name'] for p in c.get('presets') or [])}. "
        f"Why now: {(c.get('review') or {}).get('why_now') or 'n/a'}"
        for c in reviewed
    ]
    prompt = (
        "Write a three-sentence lead for this week's idea digest for an equity research team. "
        "Say what themes the screened names share and how the macro backdrop lines up with them. "
        "These are names to research, not recommendations; do not suggest buying, selling or shorting.\n\n"
        f"Macro summary: {macro.get('summary') or 'not available'}\n\nReviewed names:\n" + "\n".join(lines)
    )
    provider, effort = resolve_effort(MODEL_MID, "low")
    try:
        with budget.track("digest", "Digest summary"):
            text, _citations, _response = (call or call_llm_text)(
                prompt=prompt,
                model=MODEL_MID,
                provider=provider,
                max_tokens=DIGEST_MAX_OUTPUT_TOKENS,
                enable_web_search=False,
                reasoning_effort=effort,
            )
    except Exception:
        LOGGER.warning("Digest summary call failed", exc_info=True)
        return fallback
    from api.idea_scan.review import scrub_recommendation_language

    cleaned, _flagged = scrub_recommendation_language(str(text or "").strip()[:1500])
    return {"text": cleaned, "origin": "llm"} if cleaned else fallback


def run_weekly_idea_scan(
    req: IdeaScanRunRequest | dict[str, Any] | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    job_id: str | None = None,
    *,
    review_call: Callable[..., Any] | None = None,
    macro_call: Callable[..., Any] | None = None,
    digest_call: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    request = req if isinstance(req, IdeaScanRunRequest) else IdeaScanRunRequest.model_validate(req or {})
    settings = get_idea_scan_settings()
    config = settings.config
    presets = [p for p in settings.presets if p.enabled and (not request.preset_ids or p.id in request.preset_ids)]
    max_reviews = config.max_reviews if request.max_reviews is None else min(config.max_reviews, request.max_reviews)
    limit_usd = config.max_cost_usd if request.max_cost_usd is None else min(config.max_cost_usd, request.max_cost_usd)
    preset_universes = {u for p in presets for u in p.universes}
    universes = [u for u in UNIVERSE_KEYS if u in (set(request.universes) if request.universes else preset_universes)]
    limited = bool(
        request.tickers
        or request.preset_ids
        or (request.universes and set(request.universes) != preset_universes)
        or max_reviews < config.max_reviews
        or limit_usd < config.max_cost_usd
        or not request.publish_to_scout
    )

    now = datetime.now(UTC)
    run_id = store.new_run_id(now)
    week = store.iso_week(now)
    run: dict[str, Any] = {
        "run_id": run_id,
        "week": week,
        "status": "running",
        "phase": "universe",
        "source": request.source,
        "job_id": job_id,
        "limited": limited,
        "created_at": now.isoformat(),
        "request": request.model_dump(),
        "settings": settings.model_dump(),
        "stats": {},
        "cost": {"limit_usd": limit_usd, "spent_usd": 0.0},
    }
    store.save_run(run)

    def progress(phase: str, done: int, total: int) -> None:
        if progress_callback:
            try:
                progress_callback(phase, done, total)
            except Exception:
                LOGGER.debug("progress callback failed", exc_info=True)

    def enter(phase: str) -> None:
        run["phase"] = phase
        store.save_run(run)
        progress(phase, 0, 0)

    budget = RunBudget(limit_usd)
    try:
        membership = resolve_membership(universes, tickers=request.tickers)
        if not membership:
            raise ValueError("No tickers resolved for the scan universes.")
        enter("data")
        dataset = fetch_dataset(membership, progress=progress)

        enter("screens")
        frame = build_factor_frame(dataset)
        revision_tickers = breakdown_revision_tickers(frame, presets)
        revisions = fetch_eps_revisions(revision_tickers) if revision_tickers else {}
        results = [
            evaluate_preset(p, frame, revisions=revisions, near_miss_limit=config.near_miss_limit) for p in presets
        ]
        candidates = merge_candidates(results, frame)

        enter("macro")
        digest_reserve = budget.estimate("digest")
        previous = store.latest_completed_run(before_run_id=run_id, full_only=False)
        macro = run_macro_view(
            budget=budget,
            previous_view=(previous or {}).get("macro_view"),
            searches=config.macro_web_searches,
            reserve_usd=digest_reserve,
            call=macro_call,
        )
        macro["previous_run_id"] = (previous or {}).get("run_id")
        candidates = apply_macro(candidates, macro["rows"])
        fresh, already = split_tracked(candidates, tracked_tickers())
        near_misses = collect_near_misses(results, candidates, frame, limit=config.near_miss_limit)

        enter("reviews")
        macro_by_sector = {row["sector"]: row for row in macro["rows"]}
        to_review = min(max_reviews, len(fresh))
        reviewed = 0
        for index, candidate in enumerate(fresh):
            candidate.update({"review": None, "card_state": "open", "idea_id": None, "scout_status": None})
            if index >= max_reviews:
                candidate["review_status"] = "not_reviewed_cap"
                continue
            label = f"{candidate['ticker']} ({candidate['direction']})"
            if not budget.can_start("review", reserve_usd=digest_reserve):
                candidate["review_status"] = "not_reviewed_budget"
                budget.skip("review", label)
                continue
            review = review_candidate(
                candidate,
                macro_row=macro_by_sector.get(candidate.get("sector")),
                budget=budget,
                searches=config.review_web_searches,
                call=review_call,
            )
            candidate["review"] = json_safe(review)
            candidate["review_status"] = "reviewed" if review.get("status") == "ok" else "review_failed"
            reviewed += 1
            progress("reviews", reviewed, to_review)

        enter("publish")
        screen_kinds = {p.id: p.screen for p in presets}
        for candidate in fresh:
            if candidate.get("review_status") != "reviewed":
                continue
            candidate["scout_status"] = (
                publish_to_scout(candidate, run_id=run_id, week=week, screen_kinds=screen_kinds)
                if request.publish_to_scout
                else "not_published"
            )

        summary = summarize_digest(fresh, macro, budget=budget, call=digest_call)
        baseline = None if limited else store.latest_completed_run(before_run_id=run_id, full_only=True)
        changes = week_over_week(
            [*fresh, *already],
            [*(baseline or {}).get("candidates", []), *(baseline or {}).get("already_tracked", [])]
            if baseline
            else None,
        )
        statuses = [c.get("review_status") for c in fresh]
        run.update(
            {
                "status": "completed",
                "phase": "done",
                "completed_at": datetime.now(UTC).isoformat(),
                "macro_view": json_safe(macro),
                "candidates": fresh,
                "already_tracked": already,
                "near_misses": near_misses,
                "changes": changes,
                "compared_with_run_id": (baseline or {}).get("run_id"),
                "summary": summary,
                "presets": [r.summary() for r in results],
                "data": {
                    "dataset_key": dataset.key,
                    "fetched_at": dataset.fetched_at,
                    "reused_chunks": dataset.reused_chunks,
                    "failed": len(dataset.failed),
                    "failed_sample": dict(list(dataset.failed.items())[:20]),
                },
                "stats": {
                    "universes": universes,
                    "universe": len(membership),
                    "with_data": int(len(frame)),
                    "preset_hits": {r.preset.id: r.hits_total for r in results},
                    "candidates": len(candidates),
                    "already_tracked": len(already),
                    "review_slots": max_reviews,
                    "reviewed": statuses.count("reviewed"),
                    "review_failed": statuses.count("review_failed"),
                    "not_reviewed_budget": statuses.count("not_reviewed_budget"),
                    "not_reviewed_cap": statuses.count("not_reviewed_cap"),
                    "published": sum(1 for c in fresh if c.get("scout_status") == "published"),
                    "near_misses": len(near_misses),
                },
                "cost": budget.summary(),
            }
        )
        store.save_run(run)
    except Exception as exc:
        run.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "cost": budget.summary(),
            }
        )
        store.save_run(run)
        raise

    return {
        "run_id": run_id,
        "status": "completed",
        "week": week,
        "final_count": len(run["candidates"]),
        "spent_usd": run["cost"]["spent_usd"],
    }
