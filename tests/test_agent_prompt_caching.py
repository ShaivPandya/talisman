from __future__ import annotations

import copy
import logging
import time
from types import SimpleNamespace

import pytest

from api.agent_governance import AgentBudgetState
from api.agent_models import AgentResponsePreferences, ScreenContextModel
from api.routers import agent
from scripts.benchmark_agent_prompt_cache import summarize, uncached_request


def test_static_system_prefix_survives_changing_request_context(monkeypatch):
    requests = []
    for index in range(2):
        monkeypatch.setattr(agent, "_build_memory_context", lambda index=index: f"Memory version {index}")
        instructions = agent._with_response_preferences(
            agent._build_agent_instructions(ScreenContextModel(page_name=f"Page {index}", route=f"/page/{index}")),
            AgentResponsePreferences(custom_instructions=f"Preference {index}"),
        )
        kwargs = agent._model_stream_kwargs(
            provider="anthropic",
            instructions=instructions,
            conversation=[{"role": "user", "content": "Portfolio question"}],
            max_tokens=100,
        )
        blocks = kwargs["system"]
        assert "".join(block["text"] for block in blocks) == instructions
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "Memory version" not in blocks[0]["text"]
        assert f"/page/{index}" not in blocks[0]["text"]
        assert f"Preference {index}" not in blocks[0]["text"]
        assert "cache_control" not in blocks[1]
        requests.append(blocks)
    assert requests[0][0] == requests[1][0]
    assert requests[0][1] != requests[1][1]


def test_unrecognized_instructions_are_not_assumed_static():
    assert agent._anthropic_system_blocks("Per-request custom instructions") == [
        {"type": "text", "text": "Per-request custom instructions"}
    ]


def test_anthropic_tools_have_stable_order_without_changing_other_providers():
    tools = [{"name": "z_tool"}, {"name": "a_tool"}]
    kwargs = dict(instructions="instructions", conversation=[], max_tokens=100, tool_defs=tools)
    assert agent._model_stream_kwargs(provider="anthropic", **kwargs)["tools"] == list(reversed(tools))
    assert agent._model_stream_kwargs(provider="openai", **kwargs)["tools"] == tools
    assert tools == [{"name": "z_tool"}, {"name": "a_tool"}]


@pytest.mark.parametrize(
    "content",
    [
        "Question",
        [{"type": "text", "text": "Question"}],
        [{"type": "tool_result", "tool_use_id": "call-1", "content": "Result"}],
        [{"type": "image", "source": {"type": "url", "url": "https://example.com/image.png"}}],
        [{"type": "text", "text": "Answer"}, {"type": "thinking", "thinking": "Hidden", "signature": "s"}],
    ],
)
def test_latest_message_cache_marker_never_mutates_history(content):
    conversation = [{"role": "user", "content": content}]
    original = copy.deepcopy(conversation)
    first_request = agent._anthropic_cached_messages(conversation)
    assert first_request[-1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert conversation == original
    conversation.extend(
        [
            {"role": "assistant", "content": "Answer"},
            {"role": "user", "content": "Follow up"},
        ]
    )
    next_request = agent._anthropic_cached_messages(conversation)
    assert next_request[0] == original[0]
    assert next_request[-1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert first_request[-1]["content"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize("content", ["", "  ", [{"type": "thinking", "thinking": "Hidden", "signature": "s"}]])
def test_empty_or_thinking_only_message_is_not_marked(content):
    conversation = [{"role": "assistant", "content": content}]
    assert agent._anthropic_cached_messages(conversation) == conversation
    assert agent._anthropic_cached_messages([]) == []


def test_parallel_tool_results_mark_the_last_result_only():
    conversation = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "One"},
                {"type": "tool_result", "tool_use_id": "call-2", "content": "Two"},
            ],
        }
    ]
    messages = agent._anthropic_cached_messages(conversation)
    assert "cache_control" not in messages[-1]["content"][0]
    assert messages[-1]["content"][1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in block for block in conversation[-1]["content"])


def test_text_only_round_keeps_tools_but_disables_calls_with_thinking():
    tools = [{"name": "get_portfolio", "input_schema": {"type": "object"}}]
    kwargs = agent._model_stream_kwargs(
        provider="anthropic",
        instructions=agent._build_agent_base_instructions(),
        conversation=[{"role": "user", "content": "Finish the answer"}],
        max_tokens=100,
        tool_defs=tools,
        force_tool_use=True,
        disable_tool_use=True,
        reasoning_effort="high",
    )
    assert kwargs["tools"] == tools
    assert kwargs["tool_choice"] == {"type": "none"}
    assert kwargs["thinking"]["type"] == "adaptive"


@pytest.mark.parametrize("as_dict", [False, True])
def test_cached_input_counts_toward_budget_and_preserves_usage_breakdown(as_dict):
    usage = dict(input_tokens=11, output_tokens=7, cache_read_input_tokens=6000, cache_creation_input_tokens=50)
    response = {"usage": usage} if as_dict else SimpleNamespace(usage=SimpleNamespace(**usage))
    parsed = agent._usage_dict(response)
    assert parsed == {
        "input_tokens": 6061,
        "output_tokens": 7,
        "uncached_input_tokens": 11,
        "cache_read_input_tokens": 6000,
        "cache_creation_input_tokens": 50,
    }
    budget = AgentBudgetState()
    budget.record_model_usage(parsed)
    assert budget.actual_input_tokens == 6061
    assert budget.actual_output_tokens == 7


def test_cache_usage_is_logged_in_existing_model_observation(caplog):
    usage = SimpleNamespace(
        input_tokens=5, output_tokens=2, cache_read_input_tokens=6000, cache_creation_input_tokens=20
    )
    response = SimpleNamespace(usage=usage)

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter([])

        def get_final_message(self):
            return response

    caplog.set_level(logging.INFO)
    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: Stream()))
    timing = {"round_index": 1}
    started = time.perf_counter()
    list(agent._stream_llm_response(client, "anthropic", {"model": "claude-test"}, model_timing=timing))
    agent._record_model_timing({}, timing, started=started, status="ok", provider="anthropic", model="claude-test")
    metrics = [
        record.performance
        for record in caplog.records
        if getattr(record, "performance", {}).get("event") == "chat_model"
    ]
    assert len(metrics) == 1
    assert metrics[0]["cache_read_input_tokens"] == 6000
    assert metrics[0]["cache_creation_input_tokens"] == 20
    assert metrics[0]["input_tokens"] == 6025
    assert metrics[0]["round_index"] == 1
    assert "cache_read_input_tokens=6000 cache_creation_input_tokens=20" in caplog.text


def test_benchmark_uncached_arm_preserves_content_and_removes_breakpoints():
    request = {
        "system": [
            {"type": "text", "text": "Stable", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "\n\nDynamic"},
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Question", "cache_control": {"type": "ephemeral"}},
                ],
            }
        ],
        "tools": [{"name": "tool"}],
    }
    before = uncached_request(request)
    assert before == {
        "system": "Stable\n\nDynamic",
        "messages": [{"role": "user", "content": "Question"}],
        "tools": [{"name": "tool"}],
    }
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_benchmark_summary_distinguishes_full_prefix_reads_and_missing_ttft():
    rows = [
        {
            "cache_enabled": True,
            "pair": 0,
            "round_index": 0,
            "first_token_ms": 90,
            "input_tokens": 100,
            "cache_creation_input_tokens": 100,
        },
        {
            "cache_enabled": True,
            "pair": 0,
            "round_index": 1,
            "first_token_ms": 40,
            "input_tokens": 110,
            "cache_read_input_tokens": 100,
        },
        {
            "cache_enabled": True,
            "pair": 0,
            "round_index": 2,
            "first_token_ms": None,
            "input_tokens": 120,
            "cache_read_input_tokens": 80,
        },
    ]
    result = summarize(rows)
    assert result["uncached"]["continuation_ttft_p50_ms"] is None
    assert result["cached"]["continuation_ttft_samples"] == 1
    assert result["cached"]["continuation_ttft_p50_ms"] == 40
    assert result["verification"] == {"continuations": 2, "cache_hits": 2, "reads_cover_first_request": 1}
