"""Persisted evidence, token windows and follow-ups through the real chat path (TL-223)."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from api import memory_db, memory_manager, tool_result_memory
from api.agent_governance import estimate_tokens
from api.agent_models import AgentChatRequest
from api.routers import agent
from api.tool_result_memory import compact_tool_result, tool_memory_context
from tests.test_agent_streaming import _event_text_delta, _event_tool_use_start, _install_fake_anthropic, _parse_sse
from tests.test_agent_turn_terminal_state import _final_message
from tests.test_memory_manager_turn import fake_summarizer, temp_memory_db

FACTS = {
    "as_of": "2026-10-22T16:00:00Z",
    "ranked": [{"ticker": "NVDA", "beta": 1.8}, {"ticker": "AMD", "beta": 1.6}, {"ticker": "INTC", "beta": 1.2}],
}


def payload(**changes):
    return {
        "id": "call-1",
        "name": "query_ontology",
        "status": "ok",
        "arguments": {"query": "ranked beta"},
        "result": json.dumps(FACTS),
        **changes,
    }


def test_compaction_preserves_order_numbers_and_distinct_source_observation_times():
    result = compact_tool_result(payload(), observed_at="2026-10-23T12:00:00Z")
    assert result["facts"] == FACTS
    assert result["facts"]["ranked"][2] == {"ticker": "INTC", "beta": 1.2}
    assert result["source_times"]["as_of"] == FACTS["as_of"]
    assert result["observed_at"] == "2026-10-23T12:00:00Z"
    assert result["truncated"] is False


@pytest.mark.parametrize("value", ["x" * 100000, {"rows": [dict(FACTS, narrative="x" * 10000) for _ in range(1000)]}])
def test_oversized_results_are_bounded_with_explicit_omissions(value):
    result = compact_tool_result(payload(result=value))
    assert (
        len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= tool_result_memory.TOOL_RESULT_MAX_CHARS
    )
    assert result["truncated"] is True
    assert "omitted" in json.dumps(result)


def test_source_time_survives_when_late_metadata_is_compacted_away():
    result = compact_tool_result(
        payload(result={**{f"field{i}": "x" * 1000 for i in range(100)}, "_meta": {"as_of": "2026-10-21"}})
    )
    assert result["source_times"] == {"as_of": "2026-10-21"}


def test_two_turn_limit_includes_turns_without_tools_and_ignores_streaming_placeholder():
    old = {"role": "assistant", "tool_result_memory": [compact_tool_result(payload(id="expired"))]}
    recent = {"role": "assistant", "tool_result_memory": [compact_tool_result(payload(id="retained"))]}
    no_tools = {"role": "assistant", "content": "Explanation"}
    streaming = {"role": "assistant", "is_streaming": True}
    context = tool_memory_context([old, recent, no_tools, streaming])
    assert "retained" in context and "expired" not in context
    assert tool_memory_context([old, no_tools, no_tools]) == ""


def test_tool_memory_has_an_independent_total_token_budget():
    records = [compact_tool_result(payload(id=str(i), result={"description": "x" * 5000})) for i in range(30)]
    context = tool_memory_context([{"role": "assistant", "tool_result_memory": records}])
    assert estimate_tokens(context) <= tool_result_memory.TOOL_MEMORY_TOKEN_BUDGET
    assert "additional result(s) omitted" in context
    assert '"id":"29"' in context


def test_legacy_results_and_errors_are_data_with_honest_times():
    context = tool_memory_context(
        [{"role": "assistant", "tool_calls": [payload(status="error", result="upstream unavailable")]}]
    )
    assert '"status":"error"' in context
    assert '"observed_at":"unknown"' in context
    assert "failed or blocked results are not evidence" in context


@pytest.mark.usefixtures("temp_memory_db")
def test_completed_tool_facts_survive_an_interrupted_turn_with_no_assistant_text():
    sid = memory_db.get_or_create_session()["session_id"]
    req = AgentChatRequest(
        session_id=sid, client_turn_id="interrupted", message="rank beta", finalize_synchronously=True
    )
    agent._agent_turn_begin(req, sid)
    guard = agent._TurnTranscriptGuard(req)
    guard.session_id = sid
    guard.observe(agent._sse("tool_result", payload()))
    guard.settle()
    saved = memory_db.get_session(sid)["transcript"][-1]
    assert saved["status"] == "stopped" and saved["content"] == ""
    assert saved["tool_result_memory"][0]["facts"] == FACTS
    conversation, _ = memory_manager.build_conversation_context(sid, "third one?", enable_retrieval=False)
    assert '"beta":1.2' in str(conversation)


def test_verbatim_window_keeps_more_than_eight_short_messages_and_bounds_long_ones(monkeypatch):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"short-{i}"} for i in range(20)]
    session = {"session_id": "supplied", "server_messages": messages}
    conversation, _ = memory_manager.build_conversation_context(None, "next", session=session, enable_retrieval=False)
    assert conversation[:-1] == messages
    monkeypatch.setattr(memory_manager, "VERBATIM_TOKEN_BUDGET", 100)
    messages.insert(18, {"role": "assistant", "content": "huge" * 10000})
    conversation, _ = memory_manager.build_conversation_context(None, "next", session=session, enable_retrieval=False)
    assert conversation[:-1] == messages[19:]
    assert sum(estimate_tokens(message) for message in conversation[:-1]) <= 100


@pytest.mark.usefixtures("temp_memory_db")
def test_summary_covers_all_messages_displaced_by_one_large_turn(monkeypatch, request):
    prompts = request.getfixturevalue("fake_summarizer")
    sid = memory_db.get_or_create_session()["session_id"]
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"prior-{i}"} for i in range(8)]
    # The old window holds all eight short messages; one larger turn displaces them all.
    old_cost = sum(estimate_tokens(message) for message in messages)
    monkeypatch.setattr(memory_manager, "VERBATIM_TOKEN_BUDGET", old_cost)
    messages += [{"role": "user", "content": "large " * 70}, {"role": "assistant", "content": "large " * 70}]
    memory_db.append_messages(sid, messages)
    memory_db.update_rolling_summary(sid, "earlier history")
    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=8)
    assert all(f"prior-{i}" in prompts[0] for i in range(8))


@pytest.mark.parametrize("exceeds_budget", [False, True])
def test_summary_work_is_only_queued_under_token_pressure(monkeypatch, exceeds_budget):
    monkeypatch.setattr(agent, "_agent_trajectory_payload", lambda **kwargs: None)
    history = [{"role": "user", "content": "x" * (30000 if exceeds_budget else 100)}]
    followup = agent._turn_followup(
        req=AgentChatRequest(message="next"),
        session_id="session",
        turn_started=time.perf_counter(),
        timings={},
        final_disposition="succeeded",
        messages=[{"role": "assistant", "content": "answer"}],
        messages_before_turn=1,
        session_messages=history,
    )
    assert followup.messages_before_turn == (1 if exceeds_budget else None)


@pytest.mark.parametrize(
    "followup",
    ["What's the beta on the third one?", "What is INTC's beta?", "What's the market beta on the third one?"],
)
@pytest.mark.usefixtures("temp_memory_db")
def test_followup_after_database_reload_uses_facts_without_tools_and_refresh_executes(
    auth_client, monkeypatch, followup
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(agent, "_build_agent_instructions", lambda screen_context=None: "agent instructions")
    monkeypatch.setattr(memory_manager, "_ensure_session_title", lambda *args: None)
    monkeypatch.setattr(agent, "queue_agent_turn_followup", lambda *args, **kwargs: None)
    executions = []

    def execute(name, args, **kwargs):
        executions.append((name, args))
        return json.dumps(FACTS)

    monkeypatch.setattr(agent, "execute_tool", execute)
    tool_final = SimpleNamespace(
        content=[{"type": "tool_use", "name": "query_ontology", "id": "call-1", "input": {"query": "ranked beta"}}],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    fake = _install_fake_anthropic(
        monkeypatch,
        [
            ([_event_tool_use_start("query_ontology", "call-1")], tool_final),
            ([_event_text_delta("NVDA, AMD, then INTC.")], _final_message("NVDA, AMD, then INTC.")),
            (
                [_event_text_delta("INTC's beta was 1.2 as of October 22.")],
                _final_message("INTC's beta was 1.2 as of October 22."),
            ),
            ([_event_tool_use_start("query_ontology", "call-1")], tool_final),
            ([_event_text_delta("Refreshed beta.")], _final_message("Refreshed beta.")),
        ],
    )

    def turn(message, turn_id, sid=None):
        response = auth_client.post(
            "/api/agent/chat",
            json={"message": message, "client_turn_id": turn_id, "session_id": sid, "finalize_synchronously": True},
        )
        events = _parse_sse(response.text)
        assert not any(event == "error" for event, _ in events), events
        return events, next(value["session_id"] for event, value in events if event == "done")

    _, sid = turn("Show the market beta for NVDA, AMD and INTC", "first")
    assert len(executions) == 1
    persisted = memory_db.get_session(sid)["transcript"][-1]
    assert persisted["tool_result_memory"][0]["facts"] == FACTS
    assert persisted["tool_result_memory"][0]["observed_at"] != "unknown"
    memory_db._conn.close()
    memory_db._conn = None
    events, _ = turn(followup, "followup", sid)
    assert not any(event == "tool_call" for event, _ in events)
    assert len(executions) == 1
    request = fake.messages.kwargs_history[2]
    assert "tool_choice" not in request
    assert tool_result_memory.TOOL_MEMORY_GUIDANCE in str(request["system"])
    assert tool_result_memory.TOOL_MEMORY_GUIDANCE not in str(fake.messages.kwargs_history[0]["system"])
    assert "INTC" in str(request["messages"]) and "1.2" in str(request["messages"])
    assert FACTS["as_of"] in str(request["messages"])
    turn("Refresh the market beta on the third one with fresh data", "refresh", sid)
    assert len(executions) == 2
    assert executions[-1][1]["_force_refresh"] is True
    assert fake.messages.kwargs_history[3]["tool_choice"] == {"type": "any"}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "talisman"])
def test_recent_facts_reach_each_provider_format(provider):
    session = {
        "session_id": "supplied",
        "server_messages": [{"role": "assistant", "content": "ranked list", "tool_calls": [payload()]}],
    }
    conversation, _ = memory_manager.build_conversation_context(
        None, "third one?", session=session, enable_retrieval=False
    )
    converted = agent._conversation_for_provider(provider, conversation)
    assert FACTS["as_of"] in str(converted) and "1.2" in str(converted)


def test_decision_quality_context_keeps_the_budgeted_facts_preamble():
    history = [{"role": "user", "content": tool_memory_context([{"role": "assistant", "tool_calls": [payload()]}])}]
    history += [{"role": "user", "content": f"short-{i}"} for i in range(12)]
    context = agent._build_decision_quality_chat_context(
        user_text="third?", screen_context=None, raw_conversation=history, tool_results=[]
    )
    assert "1.2" in str(context)
