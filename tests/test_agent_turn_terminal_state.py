"""Every agent turn ends non-streaming in the saved transcript (TL-208)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

import api.agent_chat_worker as agent_chat_worker
import api.routers.agent as agent_router
from api import agent_stream_liveness as liveness
from api import memory_db, memory_manager
from api.agent_models import AgentChatRequest
from ontology.policy import admin_actor
from tests.test_agent_streaming import _event_text_delta, _install_fake_anthropic, _parse_sse

NORMAL_PROMPT = "How is global liquidity affecting risk assets?"


@pytest.fixture
def temp_memory_db(tmp_path, monkeypatch):
    if memory_db._conn is not None:
        try:
            memory_db._conn.close()
        except Exception:
            pass
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setattr(memory_db, "_DB_PATH", tmp_path / "memory.db")
    memory_db._conn = None
    yield
    if memory_db._conn is not None:
        try:
            memory_db._conn.close()
        except Exception:
            pass
    memory_db._conn = None


@pytest.fixture
def agent_env(monkeypatch, temp_memory_db):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(agent_router, "_build_agent_instructions", lambda screen_context=None: "agent instructions")


def _final_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[{"type": "text", "text": text}],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
    )


class _FailingStream:
    """Streams some text, then fails with a non-retryable error."""

    def __init__(self, texts: list[str]):
        self._texts = texts

    def __iter__(self):
        for text in self._texts:
            yield _event_text_delta(text)
        raise RuntimeError("model connection reset")

    def get_final_message(self):
        raise AssertionError("stream failed before completing")


class _FailingClient:
    def __init__(self, texts: list[str]):
        self.messages = SimpleNamespace(stream=lambda **_kwargs: _ContextManager(_FailingStream(texts)))


class _ContextManager:
    def __init__(self, value: Any):
        self._value = value

    def __enter__(self):
        return self._value

    def __exit__(self, *_args):
        return False


def _new_turn() -> tuple[str, str]:
    session_id = str(memory_db.get_or_create_session(None)["session_id"])
    return session_id, f"turn-{time.monotonic_ns()}"


def _assistant(session_id: str, client_turn_id: str) -> dict[str, Any]:
    session = memory_db.get_session(session_id)
    assert session is not None
    matches = [
        msg
        for msg in session["transcript"]
        if msg.get("role") == "assistant" and msg.get("client_turn_id") == client_turn_id
    ]
    assert len(matches) == 1, session["transcript"]
    return matches[0]


def _stream_generator(monkeypatch, req: AgentChatRequest):
    """Return the turn's raw SSE generator, as Starlette iterates it."""
    monkeypatch.setattr(
        agent_router, "_ClosingStreamingResponse", lambda content, **_kwargs: SimpleNamespace(content=content)
    )
    response = agent_router._agent_chat_impl(req, admin_actor(), turn_started=time.perf_counter())
    return response.content


def test_client_disconnect_mid_stream_saves_partial_text_as_stopped(monkeypatch, agent_env):
    _install_fake_anthropic(
        monkeypatch,
        [
            (
                [_event_text_delta("Hello "), _event_text_delta("wor"), _event_text_delta("ld")],
                _final_message("Hello world"),
            )
        ],
    )
    session_id, turn_id = _new_turn()
    gen = _stream_generator(
        monkeypatch,
        AgentChatRequest(
            session_id=session_id, client_turn_id=turn_id, message=NORMAL_PROMPT, finalize_synchronously=True
        ),
    )

    seen: list[str] = []
    for frame in gen:
        parsed = _parse_sse(frame)
        seen.extend(payload["text"] for event, payload in parsed if event == "delta")
        if len(seen) == 2:
            break
    # Starlette stops iterating on disconnect, then the response closes the generator (GeneratorExit).
    gen.close()

    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "stopped"
    assert assistant["content"] == "Hello wor"


def _slow_deltas(texts: list[str], gap_s: float):
    for text in texts:
        yield _event_text_delta(text)
        time.sleep(gap_s)


def test_response_cost_matches_completed_message_in_history(auth_client, monkeypatch, agent_env):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL_MID", "claude-sonnet-5-5")
    _install_fake_anthropic(monkeypatch, [([_event_text_delta("Liquidity answer")], _final_message("Liquidity answer"))])
    session_id, turn_id = _new_turn()
    response = auth_client.post("/api/agent/chat", json={
        "session_id": session_id, "client_turn_id": turn_id, "message": NORMAL_PROMPT,
        "finalize_synchronously": True,
    })
    done = next(payload for event, payload in _parse_sse(response.text) if event == "done")
    assert done["cost"]["estimated_usd"] == pytest.approx(0.000022)
    assert done["cost"]["complete"] is True
    assert _assistant(session_id, turn_id)["cost"] == done["cost"]


def test_asgi_disconnect_closes_the_stream_and_saves_partial_text(monkeypatch, agent_env):
    _install_fake_anthropic(monkeypatch, [(_slow_deltas(["Hello ", "wor", "ld"], 0.2), _final_message("Hello world"))])
    session_id, turn_id = _new_turn()
    response = agent_router._agent_chat_impl(
        AgentChatRequest(
            session_id=session_id, client_turn_id=turn_id, message=NORMAL_PROMPT, finalize_synchronously=True
        ),
        admin_actor(),
        turn_started=time.perf_counter(),
    )
    sent: list[str] = []

    async def drive() -> None:
        disconnected = asyncio.Event()

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body":
                body = bytes(message.get("body", b"")).decode()
                sent.extend(payload["text"] for event, payload in _parse_sse(body) if event == "delta")
                if len(sent) >= 2:
                    disconnected.set()

        async def receive() -> dict[str, Any]:
            await disconnected.wait()
            return {"type": "http.disconnect"}

        # uvicorn 0.23 speaks ASGI 2.3: Starlette cancels the stream on disconnect and returns.
        await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)

    asyncio.run(drive())

    # Settled when the response returns, not whenever garbage collection closes the generator.
    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "stopped"
    assert assistant["content"].startswith("Hello wor")


def test_model_error_saves_partial_text_as_failed(auth_client, monkeypatch, agent_env):
    monkeypatch.setattr("anthropic.Anthropic", lambda *args, **kwargs: _FailingClient(["Partial ", "answer"]))
    session_id, turn_id = _new_turn()

    resp = auth_client.post(
        "/api/agent/chat",
        json={
            "session_id": session_id,
            "client_turn_id": turn_id,
            "message": NORMAL_PROMPT,
            "finalize_synchronously": True,
        },
    )

    assert resp.status_code == 200
    events = [event for event, _payload in _parse_sse(resp.text)]
    assert "error" in events and events[-1] == "done"
    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "failed"
    assert assistant["content"] == "Partial answer"


def test_uncaught_error_on_portfolio_summary_saves_partial_text_as_failed(monkeypatch, agent_env):
    monkeypatch.setattr("anthropic.Anthropic", lambda *args, **kwargs: _FailingClient(["Your portfolio "]))
    monkeypatch.setattr(
        agent_router,
        "execute_tool",
        lambda *_args, **_kwargs: json.dumps({"summary": {}, "_meta": {"status": "ok"}}),
    )
    session_id, turn_id = _new_turn()
    gen = _stream_generator(
        monkeypatch,
        AgentChatRequest(
            session_id=session_id,
            client_turn_id=turn_id,
            message="Summarize my portfolio's performance",
            finalize_synchronously=True,
        ),
    )

    with pytest.raises(RuntimeError, match="model connection reset"):
        for _frame in gen:
            pass

    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "failed"
    assert assistant["content"] == "Your portfolio "


def test_workflow_error_marks_turn_failed(auth_client, monkeypatch, agent_env):
    def failing_workflow(*_args, **_kwargs):
        raise RuntimeError("workflow exploded")

    monkeypatch.setattr(agent_router, "execute_workflow", failing_workflow)
    session_id, turn_id = _new_turn()

    resp = auth_client.post(
        "/api/agent/chat",
        json={
            "session_id": session_id,
            "client_turn_id": turn_id,
            "message": "/workflow:thesis_review:NVDA",
            "allow_workflow_handoff": False,
            "finalize_synchronously": True,
        },
    )

    assert resp.status_code == 200
    assert any(event == "error" for event, _payload in _parse_sse(resp.text))
    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "failed"


def test_workflow_missing_ticker_reply_is_saved_as_complete(auth_client, agent_env):
    session_id, turn_id = _new_turn()

    resp = auth_client.post(
        "/api/agent/chat",
        json={
            "session_id": session_id,
            "client_turn_id": turn_id,
            "message": "/workflow:thesis_review",
            "allow_workflow_handoff": False,
            "finalize_synchronously": True,
        },
    )

    assert resp.status_code == 200
    replies = [payload["text"] for event, payload in _parse_sse(resp.text) if event == "delta"]
    assert replies and "I need a ticker" in replies[0]
    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "complete"
    assert assistant["content"] == replies[0]


class _DeferredThread:
    """Holds background writes until the test releases them, after finalize."""

    pending: list[_DeferredThread] = []

    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self) -> None:
        _DeferredThread.pending.append(self)

    def run(self) -> None:
        self._target(*self._args, **self._kwargs)


def test_late_streaming_write_cannot_reopen_a_finished_turn(auth_client, monkeypatch, agent_env):
    _DeferredThread.pending = []
    monkeypatch.setattr(memory_manager, "threading", SimpleNamespace(Thread=_DeferredThread))
    _install_fake_anthropic(monkeypatch, [([_event_text_delta("Final answer")], _final_message("Final answer"))])
    session_id, turn_id = _new_turn()

    resp = auth_client.post(
        "/api/agent/chat",
        json={
            "session_id": session_id,
            "client_turn_id": turn_id,
            "message": NORMAL_PROMPT,
            "finalize_synchronously": True,
        },
    )
    assert resp.status_code == 200
    assert _assistant(session_id, turn_id)["is_streaming"] is False

    for write in _DeferredThread.pending:
        write.run()

    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "complete"
    assert assistant["content"] == "Final answer"


def test_durable_cancel_saves_streamed_text_as_stopped(auth_client, monkeypatch, temp_memory_db):
    from api import cache
    from api.job_events import append_job_event

    cache.invalidate_all()
    started = threading.Event()
    release = threading.Event()

    def slow_agent_job(req, *, job_id):
        append_job_event(job_id, "delta", {"text": "Partial "})
        append_job_event(job_id, "delta", {"text": "text"})
        started.set()
        release.wait(timeout=2)
        return {"status": "done", "session_id": req.session_id}

    monkeypatch.setattr(agent_chat_worker, "_run_agent_chat_turn_job", slow_agent_job)
    session_id, turn_id = _new_turn()

    started_resp = auth_client.post(
        "/api/agent/chat/async",
        json={"session_id": session_id, "message": "cancel me", "client_turn_id": turn_id},
    )
    assert started_resp.status_code == 202
    job_id = started_resp.json()["job_id"]
    assert started.wait(timeout=2)

    try:
        cancel_resp = auth_client.post(f"/api/agent/chat/async/{job_id}/cancel")
        assert cancel_resp.status_code == 200

        deadline = time.monotonic() + 3
        assistant = _assistant(session_id, turn_id)
        while assistant.get("is_streaming") and time.monotonic() < deadline:
            time.sleep(0.02)
            assistant = _assistant(session_id, turn_id)
    finally:
        release.set()

    assert assistant["is_streaming"] is False
    assert assistant["status"] == "stopped"
    assert assistant["content"] == "Partial text"


def _begin_streaming_turn(content: str = "") -> tuple[str, str]:
    session_id, turn_id = _new_turn()
    memory_db.begin_turn(
        session_id,
        {"role": "user", "content": "hi", "timestamp": 1.0, "client_turn_id": turn_id},
        {"role": "assistant", "content": content, "timestamp": 2.0, "client_turn_id": turn_id, "is_streaming": True},
    )
    return session_id, turn_id


@pytest.mark.parametrize("partial_saved", [False, True])
def test_reading_session_mid_direct_stream_preserves_full_answer(auth_client, monkeypatch, agent_env, partial_saved):
    monkeypatch.setattr("api.job_queue.list_active_jobs", lambda: [])
    monkeypatch.setattr(agent_router, "TURN_PARTIAL_SAVE_INTERVAL_S", 0 if partial_saved else float("inf"))
    _install_fake_anthropic(
        monkeypatch,
        [([_event_text_delta("Hello "), _event_text_delta("world")], _final_message("Hello world"))],
    )
    session_id, turn_id = _new_turn()
    gen = _stream_generator(
        monkeypatch,
        AgentChatRequest(
            session_id=session_id, client_turn_id=turn_id, message=NORMAL_PROMPT, finalize_synchronously=True
        ),
    )
    streamed: list[str] = []
    try:
        for frame in gen:
            streamed.extend(payload["text"] for event, payload in _parse_sse(frame) if event == "delta")
            if streamed:
                break
        assert _assistant(session_id, turn_id)["content"] == ("Hello " if partial_saved else "")

        mid_stream = auth_client.get(f"/api/memory/sessions/{session_id}")
        assert mid_stream.status_code == 200
        for frame in gen:
            streamed.extend(payload["text"] for event, payload in _parse_sse(frame) if event == "delta")
    finally:
        gen.close()

    reloaded = auth_client.get(f"/api/memory/sessions/{session_id}")
    assert reloaded.status_code == 200
    saved = next(m for m in reloaded.json()["transcript"] if m["role"] == "assistant")
    assert "".join(streamed) == "Hello world"
    assert saved["content"] == "".join(streamed)
    assert saved["status"] == "complete"
    assert next(m for m in mid_stream.json()["transcript"] if m["role"] == "assistant")["is_streaming"] is True


def test_direct_stream_lease_renews_while_provider_has_no_text(auth_client, monkeypatch, agent_env):
    monkeypatch.setattr("api.job_queue.list_active_jobs", lambda: [])
    monkeypatch.setattr(liveness, "STREAM_LEASE_SECONDS", 0.5)
    monkeypatch.setattr(liveness, "STREAM_HEARTBEAT_SECONDS", 0.02)
    waiting = threading.Event()
    release = threading.Event()

    def blocked_provider():
        waiting.set()
        assert release.wait(timeout=5)
        yield _event_text_delta("Full answer")

    _install_fake_anthropic(monkeypatch, [(blocked_provider(), _final_message("Full answer"))])
    session_id, turn_id = _new_turn()
    gen = _stream_generator(
        monkeypatch,
        AgentChatRequest(
            session_id=session_id, client_turn_id=turn_id, message=NORMAL_PROMPT, finalize_synchronously=True
        ),
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        response = executor.submit(list, gen)
        try:
            assert waiting.wait(timeout=3)
            first_expiry = datetime.fromisoformat(_assistant(session_id, turn_id)["stream_lease_expires_at"])
            # No SSE frames or partial text arrive during this provider wait.
            while datetime.now(UTC) <= first_expiry:
                time.sleep(0.01)
            loaded = auth_client.get(f"/api/memory/sessions/{session_id}")
            assert loaded.status_code == 200
            assistant = next(m for m in loaded.json()["transcript"] if m["role"] == "assistant")
            assert assistant["content"] == ""
            assert assistant["is_streaming"] is True
            assert datetime.fromisoformat(assistant["stream_lease_expires_at"]) > first_expiry
        finally:
            release.set()
            response.result(timeout=5)
    assert _assistant(session_id, turn_id)["content"] == "Full answer"
    assert _assistant(session_id, turn_id)["status"] == "complete"


def test_another_process_reads_a_live_direct_stream_without_stopping_it(temp_memory_db):
    session_id, turn_id = _begin_streaming_turn("Partial answer")
    memory_db.update_assistant_message(session_id, turn_id, liveness.stream_lease_metadata(), only_streaming=True)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; from pathlib import Path; from api import memory_db; "
            "from api.routers.memory import get_session; memory_db._DB_PATH = Path(sys.argv[1]); "
            "print(json.dumps(get_session(sys.argv[2])))",
            str(memory_db._DB_PATH),
            session_id,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    session = json.loads(result.stdout)
    assert session["active_jobs"] == []
    assert session["transcript"][-1]["is_streaming"] is True
    assert _assistant(session_id, turn_id)["is_streaming"] is True


def test_get_session_recovers_an_expired_direct_stream_lease(auth_client, monkeypatch, temp_memory_db):
    monkeypatch.setattr("api.job_queue.list_active_jobs", lambda: [])
    session_id, turn_id = _begin_streaming_turn("Partial answer")
    memory_db.update_assistant_message(
        session_id, turn_id, {"stream_lease_expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
    )

    resp = auth_client.get(f"/api/memory/sessions/{session_id}")

    assert resp.status_code == 200
    assert resp.json()["transcript"][-1]["status"] == "stopped"
    assert _assistant(session_id, turn_id)["status"] == "stopped"
    assert _assistant(session_id, turn_id)["content"] == "Partial answer"


@pytest.mark.parametrize("status", ["stopped", "failed"])
def test_live_lease_and_late_writes_cannot_reopen_terminal_turn(auth_client, temp_memory_db, status):
    session_id, turn_id = _begin_streaming_turn()
    lease = liveness.DirectStreamLease(session_id, turn_id)
    lease.renew()
    memory_manager.fail_turn(session_id, turn_id, status=status, content="Saved partial")
    lease.renew()
    memory_manager.save_partial_turn(session_id, turn_id, "Late partial")
    memory_manager.complete_turn(
        session_id,
        {"role": "user", "content": "hi", "client_turn_id": turn_id},
        {"role": "assistant", "content": "Late answer", "client_turn_id": turn_id},
    )

    resp = auth_client.get(f"/api/memory/sessions/{session_id}")

    assert resp.status_code == 200
    assert resp.json()["transcript"][-1]["status"] == status
    assert _assistant(session_id, turn_id)["content"] == "Saved partial"


def test_get_session_heals_a_streaming_turn_with_no_active_job(auth_client, monkeypatch, temp_memory_db):
    monkeypatch.setattr("api.job_queue.list_active_jobs", lambda: [])
    session_id, turn_id = _begin_streaming_turn("Half an answer")

    resp = auth_client.get(f"/api/memory/sessions/{session_id}")

    assert resp.status_code == 200
    returned = [m for m in resp.json()["transcript"] if m["role"] == "assistant"][0]
    assert returned["is_streaming"] is False
    assert returned["status"] == "stopped"
    assert returned["content"] == "Half an answer"
    stored = _assistant(session_id, turn_id)
    assert stored["is_streaming"] is False
    assert stored["status"] == "stopped"


def test_get_session_keeps_a_turn_with_an_active_job_streaming(auth_client, monkeypatch, temp_memory_db):
    session_id, turn_id = _begin_streaming_turn()
    monkeypatch.setattr(
        "api.job_queue.list_active_jobs",
        lambda: [
            {
                "job_id": "job-live",
                "job_type": "agent_chat_turn",
                "status": "running",
                "payload_json": {"session_id": session_id, "client_turn_id": turn_id},
            }
        ],
    )

    resp = auth_client.get(f"/api/memory/sessions/{session_id}")

    assert resp.status_code == 200
    returned = [m for m in resp.json()["transcript"] if m["role"] == "assistant"][0]
    assert returned["is_streaming"] is True
    assert _assistant(session_id, turn_id)["is_streaming"] is True


def test_fail_turn_does_not_overwrite_a_completed_turn(temp_memory_db):
    session_id, turn_id = _begin_streaming_turn()
    memory_manager.complete_turn(
        session_id,
        {"role": "user", "content": "hi", "timestamp": 1.0, "client_turn_id": turn_id},
        {"role": "assistant", "content": "Full answer", "timestamp": 3.0, "client_turn_id": turn_id},
    )

    assert memory_db.fail_turn(session_id, turn_id, status="stopped", content="Full") is False

    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["status"] == "complete"
    assert assistant["content"] == "Full answer"


def test_partial_save_applies_only_while_streaming(temp_memory_db):
    session_id, turn_id = _begin_streaming_turn()

    memory_manager.save_partial_turn(session_id, turn_id, "Some text")
    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is True
    assert assistant["content"] == "Some text"

    memory_manager.fail_turn(session_id, turn_id, status="stopped", content="Some text more")
    memory_manager.save_partial_turn(session_id, turn_id, "Some text")
    assistant = _assistant(session_id, turn_id)
    assert assistant["is_streaming"] is False
    assert assistant["content"] == "Some text more"


def test_context_keeps_stopped_text_and_skips_blank_stopped_turns(temp_memory_db):
    session_id, first_turn = _begin_streaming_turn()
    memory_manager.fail_turn(session_id, first_turn, status="stopped", content="Partial thought")
    second_turn = "turn-blank"
    memory_db.begin_turn(
        session_id,
        {"role": "user", "content": "again", "timestamp": 3.0, "client_turn_id": second_turn},
        {"role": "assistant", "content": "", "timestamp": 4.0, "client_turn_id": second_turn, "is_streaming": True},
    )
    memory_manager.fail_turn(session_id, second_turn, status="failed", content="")

    conversation, _sid = memory_manager.build_conversation_context(session_id, "next", enable_retrieval=False)

    assert {"role": "assistant", "content": "Partial thought"} in conversation
    assert all(msg["content"] for msg in conversation)
