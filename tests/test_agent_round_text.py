"""Tool-round narration goes to the activity list, so the answer is the final round, live and in history (TL-222, TL-227)."""

import json
from types import SimpleNamespace

import pytest

import api.routers.agent as agent_router
from api.agent_models import AgentChatRequest
from tests.test_agent_stream_retry import FAILED, _fails_after, _patch_tool_results, _run_turn
from tests.test_agent_streaming import (
    _event_text_delta,
    _event_tool_use_start,
    _FakeClient,
    _FakeStream,
    _FakeStreamManager,
    _gemini_chunk,
    _gemini_function_call_part,
    _gemini_text_part,
    _install_fake_anthropic,
    _install_fake_gemini_agent,
    _install_fake_openai,
    _openai_event_function_call,
    _openai_event_text_delta,
    _parse_sse,
)
from tests.test_agent_turn_terminal_state import (
    NORMAL_PROMPT,
    _assistant,
    _final_message,
    _new_turn,
    _stream_generator,
    agent_env,
    temp_memory_db,
)

pytestmark = pytest.mark.usefixtures("agent_env")

ANSWER = "Your book has concentrated technology exposure."


def _install_rounds(monkeypatch, provider, narrations, *, final_deltas=True):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-12345678901234567890")
    _patch_tool_results(monkeypatch)
    streams = []
    for index, text in enumerate([*narrations, ANSWER]):
        tool_round = index < len(narrations)
        call_id = f"call-{index}"
        emit_text = bool(text) and (tool_round or final_deltas)
        if provider == "anthropic":
            events = [_event_text_delta(text)] if emit_text else []
            content = [{"type": "text", "text": text}] if text else []
            if tool_round:
                events.append(_event_tool_use_start("query_ontology", call_id))
                content.append(
                    {"type": "tool_use", "name": "query_ontology", "id": call_id, "input": {"query": str(index)}}
                )
            streams.append(
                (
                    events,
                    SimpleNamespace(
                        content=content,
                        stop_reason="tool_use" if tool_round else "end_turn",
                        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
                    ),
                )
            )
        elif provider == "openai":
            events = [_openai_event_text_delta(text)] if emit_text else []
            output = [{"type": "message", "content": [{"type": "output_text", "text": text}]}] if text else []
            if tool_round:
                events.append(_openai_event_function_call("query_ontology", call_id))
                output.append(
                    {
                        "type": "function_call",
                        "name": "query_ontology",
                        "call_id": call_id,
                        "arguments": json.dumps({"query": str(index)}),
                    }
                )
            streams.append(
                (events, SimpleNamespace(output=output, usage=SimpleNamespace(input_tokens=1, output_tokens=2)))
            )
        else:
            parts = [_gemini_text_part(text)] if emit_text else []
            if tool_round:
                parts.append(_gemini_function_call_part("query_ontology", call_id, {"query": str(index)}))
            streams.append([_gemini_chunk(parts)])
    installers = {
        "anthropic": _install_fake_anthropic,
        "openai": _install_fake_openai,
        "gemini": _install_fake_gemini_agent,
    }
    return installers[provider](monkeypatch, streams)


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
@pytest.mark.parametrize(
    "narrations",
    [[], ["Let me pull your book."], [""], ["Let me pull your book.", "", "I found the positions."]],
    ids=["single-round", "narration", "silent-tool", "multiple-tools-with-silent-round"],
)
def test_tool_round_text_is_narration_and_the_answer_is_the_final_round(monkeypatch, provider, narrations):
    client = _install_rounds(monkeypatch, provider, narrations)
    model_outputs = []
    monkeypatch.setattr(
        agent_router,
        "_finish_model_call_provenance",
        lambda _event_id, **kwargs: model_outputs.append(kwargs.get("output_text")),
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    spoken = [text for text in narrations if text]
    assert turn.error is None
    assert not any(event == "error" for event, _payload in turn.parsed)
    assert turn.shown == ANSWER
    assert turn.narration == spoken
    assert turn.saved["content"] == ANSWER
    assert [item["text"] for item in turn.saved["narration"]] == spoken
    assert turn.saved["status"] == "complete"
    assert model_outputs == [*narrations, ANSWER]
    api = {"anthropic": "messages", "openai": "responses", "gemini": "models"}[provider]
    assert getattr(client, api).calls == len(narrations) + 1


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_final_message_without_deltas_is_not_hidden_by_prior_narration(monkeypatch, provider):
    _install_rounds(monkeypatch, provider, ["Let me pull your book."], final_deltas=False)

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert turn.shown == ANSWER
    assert turn.narration == ["Let me pull your book."]
    assert turn.saved["content"] == ANSWER


def test_research_with_many_large_reports_writes_and_saves_an_answer_within_input_budget(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_MAX_INPUT_TOKENS", "200000")
    monkeypatch.setattr(agent_router, "_select_tool_names", lambda *_args, **_kwargs: ["query_ontology"])
    monkeypatch.setattr(
        agent_router,
        "execute_tool",
        lambda *_args, **_kwargs: json.dumps(
            {
                "ticker": "DAL",
                "report": "Private research evidence. " * 3000,
                "sources": [{"url": "/api/names/DAL/documents/" + "a" * 32 + "/content", "title": "Private report"}],
            }
        ),
    )
    requests = []

    def stream(**kwargs):
        requests.append(kwargs)
        if kwargs.get("tool_choice") == "none":
            events = [_openai_event_text_delta(ANSWER)]
            output = [{"type": "message", "content": [{"type": "output_text", "text": ANSWER}]}]
        else:
            call_id = f"report-{len(requests)}"
            events = [_openai_event_function_call("query_ontology", call_id)]
            output = [
                {
                    "type": "function_call",
                    "name": "query_ontology",
                    "call_id": call_id,
                    "arguments": json.dumps({"query": f"report {len(requests)}"}),
                }
            ]
        response = SimpleNamespace(output=output, status="completed", usage=None)
        return _FakeStreamManager(_FakeStream(events, response))

    monkeypatch.setattr(
        agent_router, "_get_provider_client", lambda *_args: SimpleNamespace(responses=SimpleNamespace(stream=stream))
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert not any(event == "error" for event, _ in turn.parsed)
    assert turn.shown == turn.saved["content"] == ANSWER
    assert turn.saved["status"] == "complete"
    assert 2 < len(requests) < agent_router.MAX_TOOL_CONTINUATION_ROUNDS
    assert requests[-1]["tool_choice"] == "none"
    budget = [payload for event, payload in turn.parsed if event == "budget_update"][-1]
    assert budget["estimated_input_tokens"] <= budget["max_input_tokens"] == 200_000


def test_pause_turn_text_is_separated_from_the_next_round(monkeypatch):
    client = _install_rounds(monkeypatch, "anthropic", ["Let me check."])
    events, message = client.messages._streams[0]
    message.content = [message.content[0]]
    message.stop_reason = "pause_turn"
    client.messages._streams[0] = (events[:1], message)

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert turn.shown == f"Let me check.\n\n{ANSWER}"
    assert turn.saved["content"] == turn.shown


@pytest.mark.parametrize("first_text", ["Your book has ", ""])
def test_output_continuation_keeps_the_answer_in_one_paragraph(monkeypatch, first_text):
    """Text cut off at the output limit continues the answer. Only text ahead of a tool call is narration."""
    client = _install_rounds(monkeypatch, "anthropic", ["Let me check."])
    partial = _final_message(first_text)
    partial.stop_reason = "max_tokens"
    client.messages._streams[1] = ([_event_text_delta(first_text)], partial)
    remaining = ANSWER[len(first_text) :]
    client.messages._streams.append(([_event_text_delta(remaining)], _final_message(remaining)))

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert turn.shown == ANSWER
    assert turn.narration == ["Let me check."]
    assert turn.saved["content"] == ANSWER
    assert client.messages.calls == 3


def test_later_round_provider_fallback_keeps_the_narration(monkeypatch):
    client = _install_rounds(monkeypatch, "anthropic", ["Let me check."])
    client.messages._streams[1] = (_fails_after(["Your book "], RuntimeError("endpoint exploded")), FAILED)
    fallback_client = _FakeClient([([_event_text_delta(ANSWER)], _final_message(ANSWER))])
    fallbacks = []

    def fallback(**kwargs):
        fallbacks.append(True)
        return kwargs["rollout_decision"], "anthropic", "test-key", fallback_client, kwargs["raw_conversation"]

    monkeypatch.setattr(agent_router, "_owned_model_canary_should_fallback", lambda **_kwargs: not fallbacks)
    monkeypatch.setattr(agent_router, "_owned_model_apply_fallback", fallback)

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.error is None
    assert turn.resets[-1] == {"text": ""}
    assert turn.shown == ANSWER
    assert turn.narration == ["Let me check."]
    assert turn.saved["content"] == ANSWER


@pytest.mark.parametrize("ending", ["disconnect", "error"])
def test_interrupted_later_round_keeps_the_narration_and_partial_answer(monkeypatch, ending):
    client = _install_rounds(monkeypatch, "anthropic", ["Let me check."])
    client.messages._streams[1] = (_fails_after(["Your book has "], RuntimeError("connection lost")), FAILED)
    session_id, turn_id = _new_turn()
    gen = _stream_generator(
        monkeypatch,
        AgentChatRequest(
            session_id=session_id, client_turn_id=turn_id, message=NORMAL_PROMPT, finalize_synchronously=True
        ),
    )
    shown = ""
    for frame in gen:
        for event, payload in _parse_sse(frame):
            if event == "delta":
                shown += payload["text"]
            elif event == "reset":
                shown = payload["text"]
        if ending == "disconnect" and "Your book has " in shown:
            gen.close()
            break

    assistant = _assistant(session_id, turn_id)
    assert shown == "Your book has "
    assert assistant["content"] == shown
    assert assistant["narration"] == [{"id": "narration:0", "text": "Let me check."}]
    assert assistant["status"] == ("stopped" if ending == "disconnect" else "failed")
