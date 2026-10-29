"""Large research batches leave room for synthesis without increasing governance limits."""

import json

import pytest

from api.agent_context_budget import SYNTHESIS_INSTRUCTION, reserve_chat_synthesis
from api.agent_governance import AgentBudgetState, estimate_model_input_tokens, prepare_model_egress
from ontology.policy import admin_actor, agent_actor

SOURCE = "/api/names/DAL/documents/" + "a" * 32 + "/content"


def _request(provider, result):
    user = {"role": "user", "content": "Analyze DAL using all research reports."}
    call = {"type": "function_call", "name": "read_name_document", "call_id": "doc-1", "arguments": "{}"}
    if provider == "openai":
        return {
            "model": "gpt-test",
            "max_output_tokens": 8192,
            "instructions": "System policy",
            "input": [user, call, {"type": "function_call_output", "call_id": "doc-1", "output": result}],
        }
    if provider == "anthropic":
        return {
            "model": "claude-test",
            "max_tokens": 8192,
            "system": [{"type": "text", "text": "System policy"}],
            "messages": [
                user,
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "read_name_document", "id": "doc-1", "input": {"ticker": "DAL"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "doc-1", "content": result},
                    ],
                },
            ],
        }
    if provider == "gemini":
        return {
            "model": "gemini-test",
            "config": {"system_instruction": "System policy", "max_output_tokens": 8192},
            "contents": [
                {"role": "user", "parts": [{"text": user["content"]}]},
                {
                    "role": "tool",
                    "parts": [
                        {
                            "function_response": {
                                "name": "read_name_document",
                                "id": "doc-1",
                                "response": {"result": result},
                            }
                        }
                    ],
                },
            ],
        }
    return {
        "model": "talisman-test",
        "max_tokens": 8192,
        "system": "System policy",
        "messages": [
            user,
            {"role": "assistant", "content": None, "tool_calls": [{"id": "doc-1"}]},
            {"role": "tool", "tool_call_id": "doc-1", "content": result},
        ],
    }


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "talisman"])
def test_large_batch_is_shortened_only_for_final_prompt_and_passes_unchanged_budget(provider):
    result = json.dumps(
        {
            "ticker": "DAL",
            "name": "Management.pdf",
            "passages": [
                {"location": "page 1", "text": "Management evidence. " * 20_000},
            ],
            "sources": [{"url": SOURCE, "title": "Private upload: Management.pdf"}],
        }
    )
    request = _request(provider, result)
    original = json.dumps(request)
    budget = AgentBudgetState(max_input_tokens=200_000, estimated_input_tokens=180_000)
    # This is the production failure: the next request would exceed the cumulative input allowance.
    assert estimate_model_input_tokens(request)[0] > 20_000

    planned, synthesis = reserve_chat_synthesis(provider, request, budget)

    assert synthesis
    assert json.dumps(request) == original
    assert SYNTHESIS_INSTRUCTION in json.dumps(planned)
    assert SOURCE in json.dumps(planned)
    assert "doc-1" in json.dumps(planned)
    assert "omitted" in json.dumps(planned)
    assert estimate_model_input_tokens(planned)[0] < 20_000
    if provider != "talisman":
        _, manifest = prepare_model_egress(
            provider=provider,
            purpose="agent_chat",
            stream_kwargs=planned,
            budget=budget,
            actor=agent_actor(admin_actor()),
        )
        assert manifest["estimated_input_tokens"] > 0
        assert budget.estimated_input_tokens <= budget.max_input_tokens == 200_000


def test_final_answer_is_reserved_before_research_consumes_remaining_allowance():
    request = _request("openai", json.dumps({"report": "Full report evidence. " * 8000}))
    budget = AgentBudgetState(max_input_tokens=200_000, estimated_input_tokens=130_000)
    assert estimate_model_input_tokens(request)[0] < 70_000

    planned, synthesis = reserve_chat_synthesis("openai", request, budget)

    assert synthesis
    assert planned["tool_choice"] == "none"
    assert planned["input"] == request["input"]  # no excerpts lost when the full evidence fits


def test_normal_research_keeps_its_request():
    request = _request("openai", '{"summary":"Small result"}')
    budget = AgentBudgetState()
    planned, synthesis = reserve_chat_synthesis("openai", request, budget)
    assert not synthesis
    assert planned is request


def test_last_allowed_model_call_is_used_for_an_answer():
    request = _request("anthropic", '{"summary":"Small result"}')
    planned, synthesis = reserve_chat_synthesis("anthropic", request, AgentBudgetState(model_calls=11))
    assert synthesis
    assert planned["tool_choice"] == {"type": "none"}


def test_compaction_preserves_user_text_and_tool_call_arguments():
    request = _request("anthropic", json.dumps({"report": "Large evidence. " * 20_000}))
    user_text = "User's explicit analysis constraints. " * 100
    arguments = {"ticker": "DAL", "result": "Argument text must not be shortened. " * 100}
    request["messages"][0]["content"] = user_text
    request["messages"][1]["content"][0]["input"] = arguments

    planned, synthesis = reserve_chat_synthesis("anthropic", request, AgentBudgetState(estimated_input_tokens=180_000))

    assert synthesis
    assert planned["messages"][0]["content"] == user_text
    assert planned["messages"][1]["content"][0]["input"] == arguments
    assert estimate_model_input_tokens(planned)[0] < 20_000
