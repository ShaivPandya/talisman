"""A model call retried mid-stream shows its answer once, in the UI and the saved transcript (TL-219)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

import api.agent_chat_worker as agent_chat_worker
import api.routers.agent as agent_router
from api.agent_models import AgentChatJobRequest, AgentChatRequest
from tests.test_agent_decision_quality_chat import _dq_result, _oc_result
from tests.test_agent_streaming import (
    _event_text_delta,
    _event_tool_use_start,
    _FakeClient,
    _install_fake_anthropic,
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

# The saved-transcript assertions need the temp memory db that `agent_env` sets up.
pytestmark = pytest.mark.usefixtures("agent_env")

ANSWER = "Hello world"
ANSWER_STREAM = [_event_text_delta("Hello "), _event_text_delta("world")]
THESIS_PROMPT = "Here is my Meta thesis? What do you think?"
THESIS_SCREEN = {"page_name": "Research", "route": "/research/meta", "ticker": "META"}
DISCOVERY_PROMPT = "Scan semiconductors for anything interesting right now?"


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch):
    monkeypatch.setattr(agent_router, "RETRY_BASE_DELAY", 0.0)


def _overloaded() -> Exception:
    exc = RuntimeError("overloaded_error: Overloaded")
    exc.status_code = 529  # type: ignore[attr-defined]
    return exc


def _fails_after(texts: list[str], exc: Exception | None = None):
    """Stream events that send the given deltas, then fail mid-stream."""

    def events():
        for text in texts:
            yield _event_text_delta(text)
        raise exc or _overloaded()

    return events()


class _NeverCompleted:
    """Final message of a stream that fails before it completes."""

    def __getattr__(self, name: str):
        raise AssertionError(f"stream failed before completing; read {name}")


FAILED = _NeverCompleted()


@dataclass
class _Turn:
    frames: list[str]
    session_id: str
    turn_id: str
    error: Exception | None = None
    parsed: list[tuple[str, dict]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.parsed = [item for frame in self.frames for item in _parse_sse(frame)]

    @property
    def shown(self) -> str:
        """What the chat bubble holds: deltas append, `reset` swaps in the text it carries."""
        shown = ""
        for event, payload in self.parsed:
            if event == "delta":
                shown += payload["text"]
            elif event == "reset":
                shown = payload["text"]
        return shown

    @property
    def resets(self) -> list[dict]:
        return [payload for event, payload in self.parsed if event == "reset"]

    @property
    def narration(self) -> list[str]:
        """What the activity list holds: the text of each tool round, kept out of the answer."""
        return [payload["text"] for event, payload in self.parsed if event == "narration"]

    @property
    def saved(self) -> dict[str, Any]:
        return _assistant(self.session_id, self.turn_id)


def _run_turn(monkeypatch, message: str, **request_fields: Any) -> _Turn:
    session_id, turn_id = _new_turn()
    gen = _stream_generator(
        monkeypatch,
        AgentChatRequest(
            session_id=session_id,
            client_turn_id=turn_id,
            message=message,
            finalize_synchronously=True,
            **request_fields,
        ),
    )
    frames: list[str] = []
    error: Exception | None = None
    try:
        for frame in gen:
            frames.append(frame)
    except Exception as exc:  # some paths surface a model error by raising out of the stream
        error = exc
    return _Turn(frames, session_id, turn_id, error)


def _assert_answer_once(turn: _Turn, answer: str = ANSWER) -> None:
    assert turn.error is None
    assert turn.shown == answer
    assert turn.saved["content"] == answer
    assert turn.saved["status"] == "complete"


def _initial_verdict(turn: _Turn) -> str:
    """The verdict card thesis and opportunity answers stream ahead of the model's synthesis."""
    verdict = next(payload["text"] for event, payload in turn.parsed if event == "delta")
    assert verdict.startswith("Initial verdict:")
    return verdict


def _patch_tool_results(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_router,
        "execute_tool",
        lambda name, args, **_kwargs: json.dumps(
            {"name": name, "args": args, "summary": {}, "_meta": {"status": "ok"}}
        ),
    )


@pytest.mark.parametrize("delta_count", [1, 2, 3])
def test_main_loop_retry_after_n_deltas_shows_answer_once(monkeypatch, delta_count):
    partial = ["Hello ", "wor", "ld "][:delta_count]
    _install_fake_anthropic(monkeypatch, [(_fails_after(partial), FAILED), (ANSWER_STREAM, _final_message(ANSWER))])

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    _assert_answer_once(turn)
    assert turn.resets == [{"text": ""}]


def test_main_loop_retry_without_streamed_text_sends_no_reset(monkeypatch):
    _install_fake_anthropic(monkeypatch, [(_fails_after([]), FAILED), (ANSWER_STREAM, _final_message(ANSWER))])

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    _assert_answer_once(turn)
    assert turn.resets == []


def test_main_loop_retry_in_a_later_round_keeps_earlier_round_narration(monkeypatch):
    _patch_tool_results(monkeypatch)
    tool_round = SimpleNamespace(
        content=[{"type": "tool_use", "name": "query_ontology", "id": "call-1", "input": {"query": "A"}}],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    _install_fake_anthropic(
        monkeypatch,
        [
            ([_event_text_delta("Let me check. "), _event_tool_use_start("query_ontology", "call-1")], tool_round),
            (_fails_after(["Based on "]), FAILED),
            (
                [_event_text_delta("Based on that, "), _event_text_delta("fine.")],
                _final_message("Based on that, fine."),
            ),
        ],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    _assert_answer_once(turn, "Based on that, fine.")
    assert turn.narration == ["Let me check."]
    assert turn.saved["narration"] == [{"id": "narration:0", "text": "Let me check."}]
    # The first reset moves the narration out of the answer. The second undoes the failed attempt's text.
    assert turn.resets == [{"text": ""}, {"text": ""}]


def test_main_loop_error_after_a_retry_saves_the_text_the_client_shows(monkeypatch):
    fatal = RuntimeError("model connection reset")
    _install_fake_anthropic(
        monkeypatch,
        [(_fails_after(["Hello ", "wor"]), FAILED), (_fails_after(["Hello "], fatal), FAILED)],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert turn.shown == "Hello "
    assert turn.saved["status"] == "failed"
    assert turn.saved["content"] == "Hello "


def test_main_loop_retries_exhausted_show_only_the_last_attempt(monkeypatch):
    _install_fake_anthropic(
        monkeypatch,
        [
            (_fails_after(["Hello ", "wor"]), FAILED),
            (_fails_after(["Hello ", "wo"]), FAILED),
            (_fails_after(["Hello ", "w"]), FAILED),
        ],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert len(turn.resets) == agent_router.MAX_API_RETRIES - 1
    assert turn.shown == "Hello w"
    assert turn.saved["status"] == "failed"
    assert turn.saved["content"] == "Hello w"


def test_canary_fallback_after_partial_text_shows_answer_once(monkeypatch):
    _install_fake_anthropic(monkeypatch, [(_fails_after(["Hello ", "wor"], RuntimeError("endpoint exploded")), FAILED)])
    fallback_client = _FakeClient([(ANSWER_STREAM, _final_message(ANSWER))])
    fallbacks: list[str] = []

    def should_fallback(**_kwargs) -> bool:
        return not fallbacks

    def apply_fallback(**kwargs):
        fallbacks.append("applied")
        return kwargs["rollout_decision"], "anthropic", "test-key", fallback_client, kwargs["raw_conversation"]

    monkeypatch.setattr(agent_router, "_owned_model_canary_should_fallback", should_fallback)
    monkeypatch.setattr(agent_router, "_owned_model_apply_fallback", apply_fallback)

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    assert fallbacks == ["applied"]
    _assert_answer_once(turn)
    assert turn.resets == [{"text": ""}]


def test_portfolio_summary_retry_shows_answer_once(monkeypatch):
    _patch_tool_results(monkeypatch)
    _install_fake_anthropic(
        monkeypatch, [(_fails_after(["Your port"]), FAILED), (ANSWER_STREAM, _final_message(ANSWER))]
    )

    turn = _run_turn(monkeypatch, "Summarize my portfolio's performance")

    _assert_answer_once(turn)
    assert turn.resets == [{"text": ""}]


def test_workflow_synthesis_retry_shows_answer_once(monkeypatch):
    monkeypatch.setattr(
        agent_router,
        "execute_workflow",
        lambda *_args, **_kwargs: (
            "run-wf",
            "synthesis prompt",
            [{"tool": "get_thesis", "data": {}, "duration_ms": 1.0}],
        ),
    )
    monkeypatch.setattr("api.workflow_artifacts.extract_artifacts", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("api.workflow_artifacts.persist_artifacts", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("api.workflows.complete_workflow_run", lambda *_args, **_kwargs: None)
    _install_fake_anthropic(monkeypatch, [(_fails_after(["Hello "]), FAILED), (ANSWER_STREAM, _final_message(ANSWER))])

    turn = _run_turn(monkeypatch, "/workflow:thesis_review:NVDA", allow_workflow_handoff=False)

    _assert_answer_once(turn)
    assert turn.resets == [{"text": ""}]


def test_decision_quality_synthesis_retry_shows_answer_once(monkeypatch):
    _patch_tool_results(monkeypatch)
    monkeypatch.setattr(agent_router, "_run_opportunity_candidate_structured_pass", lambda **_kwargs: _oc_result())
    monkeypatch.setattr(agent_router, "_run_decision_quality_structured_pass", lambda **_kwargs: _dq_result())
    _install_fake_anthropic(
        monkeypatch, [(_fails_after(["Hello ", "wor"]), FAILED), (ANSWER_STREAM, _final_message(ANSWER))]
    )

    turn = _run_turn(monkeypatch, THESIS_PROMPT, screen_context=THESIS_SCREEN)

    verdict = _initial_verdict(turn)
    _assert_answer_once(turn, verdict + ANSWER)
    assert turn.resets == [{"text": verdict}]


def test_opportunity_candidate_synthesis_retry_shows_answer_once(monkeypatch):
    _patch_tool_results(monkeypatch)
    monkeypatch.setattr(
        agent_router, "_run_opportunity_candidate_structured_pass", lambda **_kwargs: _oc_result(graduate=False)
    )
    _install_fake_anthropic(
        monkeypatch, [(_fails_after(["Hello ", "wor"]), FAILED), (ANSWER_STREAM, _final_message(ANSWER))]
    )

    turn = _run_turn(monkeypatch, DISCOVERY_PROMPT)

    verdict = _initial_verdict(turn)
    _assert_answer_once(turn, verdict + ANSWER)
    assert turn.resets == [{"text": verdict}]


@pytest.mark.parametrize(
    "structured_pass", ["_run_opportunity_candidate_structured_pass", "_run_decision_quality_structured_pass"]
)
def test_structured_pass_retry_stays_silent(monkeypatch, structured_pass):
    """The hidden structured passes don't stream, so retrying one leaves nothing for the client to undo."""
    _patch_tool_results(monkeypatch)
    results = {
        "_run_opportunity_candidate_structured_pass": _oc_result,
        "_run_decision_quality_structured_pass": _dq_result,
    }
    monkeypatch.setattr(agent_router, "_run_opportunity_candidate_structured_pass", lambda **_kwargs: _oc_result())
    monkeypatch.setattr(agent_router, "_run_decision_quality_structured_pass", lambda **_kwargs: _dq_result())
    calls: list[str] = []

    def flaky_pass(**_kwargs):
        calls.append(structured_pass)
        if len(calls) == 1:
            raise _overloaded()
        return results[structured_pass]()

    monkeypatch.setattr(agent_router, structured_pass, flaky_pass)
    _install_fake_anthropic(monkeypatch, [(ANSWER_STREAM, _final_message(ANSWER))])

    turn = _run_turn(monkeypatch, THESIS_PROMPT, screen_context=THESIS_SCREEN)

    assert calls == [structured_pass, structured_pass]
    _assert_answer_once(turn, _initial_verdict(turn) + ANSWER)
    assert turn.resets == []


def test_retry_backoff_still_sleeps_between_attempts(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(agent_router, "RETRY_BASE_DELAY", 0.5)
    monkeypatch.setattr(agent_router.time, "sleep", slept.append)
    _install_fake_anthropic(
        monkeypatch,
        [(_fails_after(["a"]), FAILED), (_fails_after(["b"]), FAILED), (ANSWER_STREAM, _final_message(ANSWER))],
    )

    turn = _run_turn(monkeypatch, NORMAL_PROMPT)

    _assert_answer_once(turn)
    assert slept == [0.5, 1.0]


def test_job_streamed_text_follows_reset_events(monkeypatch):
    events = [
        {"seq": 1, "event_type": "delta", "payload": {"text": "Let me check. "}},
        {"seq": 2, "event_type": "delta", "payload": {"text": "Hello wor"}},
        {"seq": 3, "event_type": "reset", "payload": {"text": "Let me check. "}},
        {"seq": 4, "event_type": "delta", "payload": {"text": "Hello world"}},
    ]
    monkeypatch.setattr(
        agent_router,
        "list_job_events",
        lambda _job_id, *, after_seq=0, limit=500: [e for e in events if e["seq"] > after_seq][:limit],
    )

    assert agent_router._job_streamed_text("job-1") == "Let me check. Hello world"


def test_worker_records_buffered_text_before_a_reset(monkeypatch):
    frames = [
        agent_router._sse("delta", {"text": "Hello "}),
        agent_router._sse("delta", {"text": "wor"}),
        agent_router._sse("reset", {"text": ""}),
        agent_router._sse("delta", {"text": ANSWER}),
        agent_router._sse("done", {"usage": {}, "session_id": "session-1"}),
    ]

    async def body():
        for frame in frames:
            yield frame

    recorded: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(agent_router, "agent_chat", lambda _req, _actor: SimpleNamespace(body_iterator=body()))
    monkeypatch.setattr(
        agent_chat_worker,
        "append_job_event",
        lambda _job_id, event_type, payload=None: recorded.append((event_type, payload)),
    )
    monkeypatch.setattr(agent_chat_worker, "get_job_status", lambda _job_id: "running")

    agent_chat_worker._run_agent_chat_turn_job(
        AgentChatJobRequest(session_id="session-1", message=NORMAL_PROMPT), job_id="job-1"
    )

    kinds = [event for event, _payload in recorded]
    reset_at = kinds.index("reset")
    assert kinds[0] == "status" and kinds[-1] == "done"
    assert set(kinds[1:reset_at]) == {"delta"} and set(kinds[reset_at + 1 : -1]) == {"delta"}
    # Text still buffered when the reset arrives is recorded before it, so replay can't apply it afterwards.
    assert "".join(payload["text"] for _event, payload in recorded[1:reset_at]) == "Hello wor"
    assert recorded[reset_at][1] == {"text": ""}
    assert "".join(payload["text"] for _event, payload in recorded[reset_at + 1 : -1]) == ANSWER
