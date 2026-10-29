"""Reserve a final answer within the existing cumulative chat input budget."""

from __future__ import annotations

import json
import logging
from typing import Any

from api.agent_governance import AgentBudgetState, estimate_model_input_tokens
from api.conversation_messages import sources_from
from api.tool_result_memory import compact_tool_result

logger = logging.getLogger("api.agent")

SYNTHESIS_INSTRUCTION = (
    "Research is complete for this turn's remaining budget. Write the final answer now using the evidence "
    "already gathered; do not call more tools. Address the user's requested analysis, cite the available "
    "sources, distinguish private uploads from public sources, and disclose missing or truncated evidence. "
    "Do not claim to have reviewed omitted passages."
)


def _input_charge(kwargs: dict[str, Any], budget: AgentBudgetState) -> int:
    tokens, attached = estimate_model_input_tokens(kwargs)
    return tokens - min(attached, budget.attached_tokens_charged)


def _compact_results(value: Any, max_chars: int) -> Any:
    """Copy only provider tool-result envelopes; preserve call IDs and all user/system text."""
    if isinstance(value, list):
        return [_compact_results(item, max_chars) for item in value]
    if not isinstance(value, dict):
        return value
    field = None
    if value.get("type") == "function_call_output":
        field = "output"
    elif value.get("type") == "tool_result" or value.get("role") == "tool":
        field = "content"
    elif isinstance(value.get("result"), str):
        field = "result"  # Gemini's response.result envelope
    result = value.get(field) if field else None
    if isinstance(result, str) and len(result) > max_chars:
        compact = compact_tool_result({"result": result}, max_chars=max_chars)
        # Keep exact citation identities even if a large facts object was reduced.
        try:
            sources = sources_from(json.loads(result))
        except ValueError:
            sources = []
        replacement = {
            "facts": compact["facts"],
            "truncated": True,
            "sources": sources,
            "notice": "Tool evidence shortened to fit the remaining answer budget; omitted details are unavailable.",
        }
        return {**value, field: json.dumps(replacement, ensure_ascii=False, separators=(",", ":"))}
    # Recurse through message/result containers, never through function-call arguments or attachments.
    containers = {"content", "parts", "function_response", "functionResponse", "response"}
    return {key: _compact_results(child, max_chars) if key in containers else child for key, child in value.items()}


def reserve_chat_synthesis(
    provider: str, kwargs: dict[str, Any], budget: AgentBudgetState
) -> tuple[dict[str, Any], bool]:
    """Stop research before spending the final model call or the final prompt's input allowance.

    Called after at least one research round. Normal rounds keep their complete evidence. If a tool
    batch outgrew the remaining allowance, shorten tool results only for the final model request;
    the original results stay in the tool cache, provenance, and saved activity.
    """
    remaining = budget.max_input_tokens - budget.estimated_input_tokens
    if (
        2 * _input_charge(kwargs, budget) + 512 <= remaining
        and budget.model_calls + 1 < budget.max_model_calls
        and budget.tool_calls < budget.max_tool_calls
    ):
        return kwargs, False

    kwargs = dict(kwargs)
    if provider == "gemini":
        config = dict(kwargs.get("config") or {})
        config["system_instruction"] = str(config.get("system_instruction") or "") + "\n\n" + SYNTHESIS_INSTRUCTION
        config["tool_config"] = {"function_calling_config": {"mode": "NONE"}}
        kwargs["config"] = config
    elif provider == "anthropic":
        system = kwargs.get("system") or []
        kwargs["system"] = (
            [*system, {"type": "text", "text": SYNTHESIS_INSTRUCTION}]
            if isinstance(system, list)
            else str(system) + "\n\n" + SYNTHESIS_INSTRUCTION
        )
        kwargs["tool_choice"] = {"type": "none"}
    else:
        field = "system" if provider == "talisman" else "instructions"
        kwargs[field] = str(kwargs.get(field) or "") + "\n\n" + SYNTHESIS_INSTRUCTION
        kwargs["tool_choice"] = "none"

    # A large batch can consume more than the previous round's reserve. Compact only if needed.
    for max_chars in (6000, 3000, 1000):
        if _input_charge(kwargs, budget) + 512 <= remaining:
            break
        for field in ("input", "messages", "contents"):
            if field in kwargs:
                kwargs[field] = _compact_results(kwargs[field], max_chars)
    logger.info(
        "agent_chat_budget_synthesis provider=%s remaining_input_tokens=%d estimated_input_tokens=%d",
        provider,
        remaining,
        _input_charge(kwargs, budget),
    )
    return kwargs, True
