"""Agent turn work that runs on the worker queue after the "done" event.

A chat turn sends "done" as soon as its answer is complete, then queues one
follow-up job for the work that used to delay it: the rolling summary update,
owned-model shadow synthesis and trajectory capture. Each step is best effort;
a failing step is logged and the others still run.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

JOB_TYPE = "agent_turn_followup"


class AgentTurnFollowupRequest(BaseModel):
    session_id: str
    client_turn_id: str | None = None
    # Set for completed turns: how many transcript messages precede the turn.
    messages_before_turn: int | None = None
    trajectory: dict[str, Any] | None = None
    # Inputs for the candidate-model call when the turn ran in owned-model shadow mode.
    shadow: dict[str, Any] | None = None
    # Routing context only: credentials are resolved by the worker, never queued.
    intent_router_shadow: dict[str, Any] | None = None
    # Set for answered turns: write the follow-up questions shown under the answer.
    suggest_followups: bool = False


def followup_cache_key(req: AgentTurnFollowupRequest) -> str | None:
    """One follow-up per turn, so a replayed turn can't summarize the same messages twice."""
    if not req.client_turn_id:
        return None
    return f"{JOB_TYPE}:{req.session_id}:{req.client_turn_id}"


def queue_agent_turn_followup(req: AgentTurnFollowupRequest) -> None:
    from api.async_job_runner import enqueue_registered_job

    # Job payloads are stored as JSON; tool payloads can carry values json can't encode.
    payload = json.loads(json.dumps(req.model_dump(exclude_none=True), default=str))
    enqueue_registered_job(JOB_TYPE, payload)


def run_agent_turn_followup(req: AgentTurnFollowupRequest) -> dict[str, Any]:
    steps: dict[str, str] = {}

    # The summary feeds the next turn's context, so it goes first.
    if req.messages_before_turn is not None:
        try:
            from api.memory_manager import summarize_departed_messages

            changed = summarize_departed_messages(
                req.session_id,
                messages_before_turn=req.messages_before_turn,
                client_turn_id=req.client_turn_id,
            )
            steps["summary"] = "updated" if changed else "skipped"
        except Exception:
            logger.exception("Rolling summarization failed for session %s", req.session_id)
            steps["summary"] = "failed"

    # The chat shows them under the answer within seconds, so they go before the slower steps.
    if req.suggest_followups and req.client_turn_id:
        try:
            steps["suggestions"] = _write_suggestions(req.session_id, req.client_turn_id)
        except Exception:
            logger.exception("Follow-up suggestions failed for session %s", req.session_id)
            steps["suggestions"] = "failed"

    shadow_comparison: dict[str, Any] | None = None
    router_meta: dict[str, Any] | None = None
    if req.intent_router_shadow:
        try:
            router_meta = _run_intent_router_shadow(req)
            steps["intent_router_shadow"] = "compared"
        except Exception:
            logger.exception("Intent-router shadow failed for session %s", req.session_id)
            router_meta = {
                **req.intent_router_shadow["route_meta"],
                "shadow_pending": False,
                "fallback_reason": "shadow_job_failed",
            }
            steps["intent_router_shadow"] = "failed"

    if req.shadow:
        try:
            shadow_comparison = _run_shadow_synthesis(req.shadow)
            steps["shadow"] = "compared"
        except Exception:
            logger.exception("Owned-model shadow synthesis failed for session %s", req.session_id)
            steps["shadow"] = "failed"

    if req.trajectory is not None:
        from api.agent_trajectories import insert_trajectory

        trajectory = dict(req.trajectory)
        if router_meta is not None:
            route = {**(trajectory.get("route") or {}), "telemetry": router_meta}
            trajectory["route"] = route
            trajectory["steps"] = [
                {**step, "payload": route, "status": router_meta["applied_source"]}
                if step.get("kind") == "route" and step.get("name") == "intent_router"
                else step
                for step in trajectory.get("steps") or []
            ]
        if shadow_comparison is not None:
            raw_payload = dict(trajectory.get("raw_payload") or {})
            rollout = dict(raw_payload.get("owned_model_rollout") or {})
            rollout["shadow_comparison"] = shadow_comparison
            raw_payload["owned_model_rollout"] = rollout
            trajectory["raw_payload"] = raw_payload
        # insert_trajectory logs its own failures and returns None for them and for duplicates.
        steps["trajectory"] = "stored" if insert_trajectory(trajectory) else "not_stored"

    return {"session_id": req.session_id, "client_turn_id": req.client_turn_id, "steps": steps}


SUGGESTIONS_WAIT_S = 5.0


def _write_suggestions(session_id: str, client_turn_id: str) -> str:
    """Save 2-3 suggested questions on the turn's answer, once the answer itself is saved."""
    from api import memory_db
    from api.chat_rich_parts import generate_suggestions, suggestions_enabled

    if not suggestions_enabled():
        return "disabled"
    deadline = time.monotonic() + SUGGESTIONS_WAIT_S
    exchange = memory_db.turn_exchange(session_id, client_turn_id)
    # The answer is saved by a thread that may still be running when this job starts.
    while exchange["status"] != "complete" and time.monotonic() < deadline:
        time.sleep(0.25)
        exchange = memory_db.turn_exchange(session_id, client_turn_id)
    if exchange["status"] != "complete" or exchange["suggestions"]:
        return "skipped"
    suggestions = generate_suggestions(exchange["question"], exchange["answer"])
    if not suggestions:
        return "skipped"
    saved = memory_db.update_assistant_message(
        session_id, client_turn_id, {"suggestions": [{"text": text} for text in suggestions]}
    )
    return "written" if saved else "skipped"


def _run_intent_router_shadow(req: AgentTurnFollowupRequest) -> dict[str, Any]:
    from api.intent_router_training_store import insert_training_row
    from api.routers.agent import _load_required_prompt_file
    from decision_quality.intent_router import (
        RouteContext,
        RouteDecision,
        intent_router_training_capture_mismatch_only,
        resolve_shadow_route,
        should_capture_training_row,
        training_row_from_telemetry,
    )
    from llm_utils import require_api_key

    inputs = req.intent_router_shadow
    assert inputs is not None
    context = RouteContext(**inputs["context"])
    baseline = RouteDecision(**inputs["route_meta"]["regex_baseline"])
    applied, meta = resolve_shadow_route(
        context=context,
        regex_baseline=baseline,
        provider=inputs["provider"],
        api_key=require_api_key(inputs["provider"]),
        system_prompt=_load_required_prompt_file("intent_router.md"),
        route_meta=inputs["route_meta"],
    )
    capture, reason = should_capture_training_row(route_meta=meta)
    if capture:
        try:
            insert_training_row(
                training_row_from_telemetry(
                    user_text=context.user_text,
                    route_meta=meta,
                    session_id=req.session_id,
                    client_turn_id=req.client_turn_id,
                    screen_context=context.screen_context,
                    recent_session_features=context.recent_session_features,
                    applied_route=applied.to_meta(),
                    opportunity_candidate_metadata=inputs.get("opportunity_candidate_metadata"),
                    capture_policy="mismatch_only" if intent_router_training_capture_mismatch_only() else "shadow_all",
                    sampling_reason=reason,
                )
            )
        except Exception:
            logger.exception("intent_router_training_capture_failed session_id=%s", req.session_id)
    logger.info("intent_router_shadow_complete session_id=%s telemetry=%s", req.session_id, meta)
    return meta


def _run_shadow_synthesis(shadow: dict[str, Any]) -> dict[str, Any]:
    """Ask the candidate model the turn's prompt and compare it with the answer the user got."""
    from api.owned_model_rollout import compare_model_outcomes
    from llm_utils import MODEL_MID, call_llm_text, require_api_key, resolve_model

    provider = str(shadow["candidate_provider"])
    started = time.perf_counter()
    candidate: dict[str, Any]
    try:
        candidate_model = shadow.get("candidate_model") or resolve_model(MODEL_MID, provider)
        text, _citations, response = call_llm_text(
            prompt=shadow["prompt_text"],
            model=candidate_model,
            api_key=require_api_key(provider),
            max_tokens=int(shadow["max_tokens"]),
            system=shadow["instructions"],
            provider=provider,
            reasoning_effort=shadow["reasoning_effort"],
        )
        candidate = {
            "provider": provider,
            "model": candidate_model,
            "output_text": text,
            "tool_names": [],
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "usage": getattr(response, "usage", {}) if response is not None else {},
            "status": "ok",
        }
    except Exception as exc:
        candidate = {
            "provider": provider,
            "model": shadow.get("candidate_model"),
            "output_text": "",
            "tool_names": [],
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "usage": {},
            "status": "error",
            "error": str(exc) or exc.__class__.__name__,
        }
    return compare_model_outcomes(baseline=shadow["baseline_result"], candidate=candidate)
