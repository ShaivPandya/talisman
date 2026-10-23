"""Tool activity, sources and thinking summaries stream to the client and are saved with the message (TL-227)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import api.routers.agent as agent_router
from tests.test_agent_stream_retry import ANSWER, _overloaded, _patch_tool_results, _run_turn
from tests.test_agent_streaming import (
    _event_text_delta,
    _event_tool_use_start,
    _gemini_chunk,
    _gemini_text_part,
    _install_fake_anthropic,
    _install_fake_gemini_agent,
    _install_fake_openai,
    _openai_event_text_delta,
)
from tests.test_agent_turn_terminal_state import (
    NORMAL_PROMPT,
    _final_message,
    agent_env,
    temp_memory_db,
)

pytestmark = pytest.mark.usefixtures("agent_env")

CITATION = {"title": "Fed minutes", "url": "https://example.com/fed"}
FETCHED_AT = "2026-10-23T09:30:00"
TOOL_RESULT = json.dumps(
    {
        "rows": [1, 2, 3],
        "citations": [CITATION, {"url": CITATION["url"]}, {"title": "No link"}],
        "_meta": {"status": "ok", "fetched_at": FETCHED_AT, "cache": "hit", "duration_ms": 12.5},
    }
)


def _utc(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).isoformat()


# ---------------------------------------------------------------------------
# The payload the client sees
# ---------------------------------------------------------------------------


def test_public_tool_payload_replaces_the_result_with_a_preview_and_activity_fields():
    payload = {
        "name": "search_web",
        "id": "call-1",
        "status": "ok",
        "arguments": {"query": "Fed minutes"},
        "result": TOOL_RESULT,
        "elapsed_ms": 48.3,
        "cache": "miss_fetch",
    }

    public = agent_router._public_tool_payload(payload)

    assert "result" not in public
    assert public["arguments"] == {"query": "Fed minutes"}
    assert public["result_preview"] == TOOL_RESULT
    assert public["result_bytes"] == len(TOOL_RESULT.encode())
    assert "result_truncated" not in public
    assert public["elapsed_ms"] == 48.3
    assert public["cache"] == "miss_fetch"
    assert public["as_of"] == _utc(FETCHED_AT)
    assert public["sources"] == [CITATION]
    # The trajectory keeps the whole payload.
    assert payload["result"] == TOOL_RESULT


def test_public_tool_payload_caps_long_results_and_arguments():
    result = json.dumps({"rows": ["x" * 100] * 100})
    arguments = {"text": "y" * 6000}

    public = agent_router._public_tool_payload({"id": "t", "name": "n", "arguments": arguments, "result": result})

    assert public["result_preview"] == result[: agent_router.TOOL_PREVIEW_CHARS]
    assert public["result_truncated"] is True
    assert public["result_bytes"] == len(result)
    assert public["arguments_truncated"] is True
    assert len(public["arguments"]) == agent_router.TOOL_PREVIEW_CHARS
    assert public["arguments"] == json.dumps(arguments)[: agent_router.TOOL_PREVIEW_CHARS]


def test_tool_as_of_prefers_the_data_date_then_the_fetch_time_then_now():
    fetched = {"fetched_at": FETCHED_AT}
    # A date stays a date, and the data's own date wins over the time it was fetched.
    assert agent_router._tool_as_of({"as_of": "2026-10-22"}, fetched) == "2026-10-22"
    assert agent_router._tool_as_of({"price_as_of": "2026-10-21"}, fetched) == "2026-10-21"
    # Cache metadata holds naive local timestamps, which are sent as UTC.
    assert agent_router._tool_as_of({}, fetched) == _utc(FETCHED_AT)
    assert agent_router._tool_as_of({"as_of": "not a date"}, fetched) == _utc(FETCHED_AT)
    before = datetime.now(UTC)
    assert before <= datetime.fromisoformat(agent_router._tool_as_of(None, {})) <= datetime.now(UTC)


def test_public_tool_payload_handles_results_that_are_not_json():
    public = agent_router._public_tool_payload({"id": "t", "name": "n", "result": "plain text"})

    assert public["result_preview"] == "plain text"
    assert public["result_bytes"] == len("plain text")
    assert "sources" not in public and datetime.fromisoformat(public["as_of"])


# ---------------------------------------------------------------------------
# A turn with a tool round
# ---------------------------------------------------------------------------


def _install_tool_turn(monkeypatch, *, narration="Let me look."):
    monkeypatch.setattr(agent_router, "execute_tool", lambda _name, _args, **_kwargs: TOOL_RESULT)
    tool_round = SimpleNamespace(
        content=[{"type": "tool_use", "name": "search_web", "id": "call-1", "input": {"query": "Fed minutes"}}],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    return _install_fake_anthropic(
        monkeypatch,
        [
            ([_event_text_delta(narration), _event_tool_use_start("search_web", "call-1")], tool_round),
            ([_event_text_delta(ANSWER)], _final_message(ANSWER)),
        ],
    )


def test_tool_activity_streams_arguments_before_the_result_and_is_saved(monkeypatch):
    _install_tool_turn(monkeypatch)
    trajectories = []
    real_payload = agent_router._agent_trajectory_payload
    monkeypatch.setattr(
        agent_router,
        "_agent_trajectory_payload",
        lambda **kwargs: trajectories.append(kwargs.get("tool_calls")) or real_payload(**kwargs),
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    events = [event for event, _payload in turn.parsed]
    assert events.index("tool_call") < events.index("tool_progress") < events.index("tool_result")
    progress = next(payload for event, payload in turn.parsed if event == "tool_progress")
    assert progress == {
        "name": "search_web",
        "id": "call-1",
        "status": "running",
        "arguments": {"query": "Fed minutes"},
    }
    result = next(payload for event, payload in turn.parsed if event == "tool_result")
    assert result["arguments"] == {"query": "Fed minutes"}
    assert json.loads(result["result_preview"])["rows"] == [1, 2, 3]
    assert result["elapsed_ms"] == 12.5 and result["cache"] == "hit"
    assert result["as_of"] == _utc(FETCHED_AT)
    assert result["sources"] == [CITATION]
    assert "result" not in result

    saved = turn.saved
    assert saved["content"] == ANSWER
    assert len(saved["tool_calls"]) == 1
    assert saved["tool_calls"][0]["result_preview"] == result["result_preview"]
    assert saved["tool_calls"][0]["arguments"] == {"query": "Fed minutes"}
    assert saved["tool_calls"][0]["as_of"] == _utc(FETCHED_AT)
    assert saved["sources"] == [CITATION]
    assert saved["narration"] == [{"id": "narration:0", "text": "Let me look."}]
    done = next(payload for event, payload in turn.parsed if event == "done")
    assert done["sources"] == [CITATION]
    assert done["narration"] == saved["narration"]
    # The trajectory still gets the whole result, not the preview.
    assert trajectories and trajectories[0][0]["result"] == TOOL_RESULT


def test_a_turn_without_thinking_saves_no_thinking(monkeypatch):
    _install_tool_turn(monkeypatch)

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.saved["thinking"] == []
    assert not any(event == "thinking" for event, _payload in turn.parsed)


# ---------------------------------------------------------------------------
# Thinking summaries
# ---------------------------------------------------------------------------


def _anthropic_thinking_events(*chunks: str, index: int = 0):
    yield SimpleNamespace(type="content_block_start", index=index, content_block=SimpleNamespace(type="thinking"))
    for chunk in chunks:
        yield SimpleNamespace(
            type="content_block_delta", index=index, delta=SimpleNamespace(type="thinking_delta", thinking=chunk)
        )
    yield SimpleNamespace(type="content_block_stop", index=index)


def _thinking_events(turn):
    return [payload for event, payload in turn.parsed if event == "thinking"]


def test_anthropic_thinking_summary_streams_when_its_block_ends_and_is_saved(monkeypatch):
    _install_fake_anthropic(
        monkeypatch,
        [([*_anthropic_thinking_events("Weighing ", "the book."), _event_text_delta(ANSWER)], _final_message(ANSWER))],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    expected = {"id": "thinking:agent_chat:0:0", "text": "Weighing the book."}
    assert turn.error is None
    assert _thinking_events(turn) == [expected]
    events = [event for event, _payload in turn.parsed]
    assert events.index("thinking") < events.index("delta")
    assert turn.saved["thinking"] == [expected]
    assert turn.saved["content"] == ANSWER
    assert next(payload for event, payload in turn.parsed if event == "done")["thinking"] == [expected]


def test_anthropic_thinking_blocks_are_kept_in_order_and_empty_ones_dropped(monkeypatch):
    events = [
        *_anthropic_thinking_events("First.", index=0),
        *_anthropic_thinking_events("  ", index=1),
        *_anthropic_thinking_events("Second.", index=2),
        _event_text_delta(ANSWER),
    ]
    _install_fake_anthropic(monkeypatch, [(events, _final_message(ANSWER))])

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert [item["text"] for item in turn.saved["thinking"]] == ["First.", "Second."]


def test_a_retried_model_call_replaces_its_failed_attempts_thinking_summary(monkeypatch):
    def failing_attempt():
        yield from _anthropic_thinking_events("Weighing the book.")
        raise _overloaded()

    monkeypatch.setattr(agent_router, "RETRY_BASE_DELAY", 0.0)
    _install_fake_anthropic(
        monkeypatch,
        [
            (failing_attempt(), _final_message("")),
            ([*_anthropic_thinking_events("Weighing the book."), _event_text_delta(ANSWER)], _final_message(ANSWER)),
        ],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert len(_thinking_events(turn)) == 2  # the client replaces the first by id
    assert turn.saved["thinking"] == [{"id": "thinking:agent_chat:0:0", "text": "Weighing the book."}]


def test_openai_reasoning_summary_becomes_a_thinking_event(monkeypatch):
    summary = SimpleNamespace(type="response.reasoning_summary_text.done", text="Comparing exposures.")
    response = SimpleNamespace(
        output=[{"type": "message", "content": [{"type": "output_text", "text": ANSWER}]}],
        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
    )
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _install_fake_openai(monkeypatch, [([summary, _openai_event_text_delta(ANSWER)], response)])

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert turn.saved["thinking"] == [{"id": "thinking:agent_chat:0:0", "text": "Comparing exposures."}]
    assert turn.saved["content"] == ANSWER


def test_gemini_thought_parts_become_thinking_and_stay_out_of_the_answer(monkeypatch):
    thought = SimpleNamespace(text="Checking the ", thought=True)
    thought_tail = SimpleNamespace(text="positions.", thought=True)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-12345678901234567890")
    _install_fake_gemini_agent(
        monkeypatch,
        [[_gemini_chunk([thought]), _gemini_chunk([thought_tail, _gemini_text_part(ANSWER)])]],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert turn.shown == ANSWER
    assert turn.saved["thinking"] == [{"id": "thinking:agent_chat:0:0", "text": "Checking the positions."}]
    assert turn.saved["content"] == ANSWER


def test_thinking_tool_rounds_keep_summaries_separate_per_round(monkeypatch):
    _patch_tool_results(monkeypatch)
    tool_round = SimpleNamespace(
        content=[{"type": "tool_use", "name": "query_ontology", "id": "call-1", "input": {"query": "A"}}],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    _install_fake_anthropic(
        monkeypatch,
        [
            (
                [*_anthropic_thinking_events("Plan the lookup."), _event_tool_use_start("query_ontology", "call-1")],
                tool_round,
            ),
            ([*_anthropic_thinking_events("Write it up."), _event_text_delta(ANSWER)], _final_message(ANSWER)),
        ],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert [item["id"] for item in turn.saved["thinking"]] == ["thinking:agent_chat:0:0", "thinking:agent_chat:1:0"]
    assert [item["text"] for item in turn.saved["thinking"]] == ["Plan the lookup.", "Write it up."]
