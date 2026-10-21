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

            changed = summarize_departed_messages(req.session_id, messages_before_turn=req.messages_before_turn)
            steps["summary"] = "updated" if changed else "skipped"
        except Exception:
            logger.exception("Rolling summarization failed for session %s", req.session_id)
            steps["summary"] = "failed"

    shadow_comparison: dict[str, Any] | None = None
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
        if shadow_comparison is not None:
            raw_payload = dict(trajectory.get("raw_payload") or {})
            rollout = dict(raw_payload.get("owned_model_rollout") or {})
            rollout["shadow_comparison"] = shadow_comparison
            raw_payload["owned_model_rollout"] = rollout
            trajectory["raw_payload"] = raw_payload
        # insert_trajectory logs its own failures and returns None for them and for duplicates.
        steps["trajectory"] = "stored" if insert_trajectory(trajectory) else "not_stored"

    return {"session_id": req.session_id, "client_turn_id": req.client_turn_id, "steps": steps}


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
