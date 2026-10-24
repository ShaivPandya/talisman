from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

import api.agent_chat_worker as agent_chat_worker
import api.routers.agent as agent_router
from api import agent_turn_followup, memory_db, memory_manager
from api.agent_models import AgentChatJobRequest, AgentChatRequest
from api.agent_turn_followup import AgentTurnFollowupRequest, run_agent_turn_followup
from api.owned_model_rollout import RolloutDecision, RolloutTelemetry
from ontology.policy import actor_to_dict, admin_actor


@pytest.fixture
def temp_memory_db(tmp_path, monkeypatch):
    if memory_db._conn is not None:
        memory_db._conn.close()
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setattr(memory_db, "_DB_PATH", tmp_path / "memory.db")
    memory_db._conn = None
    yield
    if memory_db._conn is not None:
        memory_db._conn.close()
    memory_db._conn = None


def _shadow_inputs() -> dict:
    return {
        "candidate_provider": "talisman",
        "candidate_model": "talisman-test",
        "instructions": "agent instructions",
        "prompt_text": "How is NVDA demand?",
        "reasoning_effort": "none",
        "baseline_result": {"provider": "anthropic", "output_text": "Strong.", "tool_names": [], "status": "ok"},
        "max_tokens": 128,
    }


def test_followup_runs_summary_then_shadow_then_trajectory(monkeypatch):
    calls: list[str] = []
    stored: list[dict] = []

    def summarize(session_id, *, messages_before_turn, client_turn_id=None):
        calls.append(f"summary:{session_id}:{messages_before_turn}")
        return True

    def call_llm_text(**kwargs):
        calls.append(f"shadow:{kwargs['model']}")
        return "Strong.", [], SimpleNamespace(usage={"output_tokens": 1})

    monkeypatch.setattr("api.memory_manager.summarize_departed_messages", summarize)
    monkeypatch.setattr("llm_utils.call_llm_text", call_llm_text)
    monkeypatch.setattr("llm_utils.require_api_key", lambda provider: "key")
    monkeypatch.setattr("api.agent_trajectories.insert_trajectory", lambda record: stored.append(record) or "traj-1")

    result = run_agent_turn_followup(
        AgentTurnFollowupRequest(
            session_id="sess-1",
            client_turn_id="turn-1",
            messages_before_turn=16,
            trajectory={"raw_payload": {"owned_model_rollout": {"shadow_mode": True, "shadow_comparison": None}}},
            shadow=_shadow_inputs(),
        )
    )

    assert calls == ["summary:sess-1:16", "shadow:talisman-test"]
    assert result["steps"] == {"summary": "updated", "shadow": "compared", "trajectory": "stored"}
    comparison = stored[0]["raw_payload"]["owned_model_rollout"]["shadow_comparison"]
    assert comparison["output_text_match"] is True
    assert comparison["candidate_model"] == "talisman-test"


def test_followup_step_failure_does_not_stop_the_others(monkeypatch):
    stored: list[dict] = []

    def failing_summary(*args, **kwargs):
        raise RuntimeError("summarizer down")

    monkeypatch.setattr("api.memory_manager.summarize_departed_messages", failing_summary)
    monkeypatch.setattr("api.agent_trajectories.insert_trajectory", lambda record: stored.append(record) or "traj-1")

    result = run_agent_turn_followup(
        AgentTurnFollowupRequest(session_id="sess-1", messages_before_turn=20, trajectory={"raw_payload": {}})
    )

    assert result["steps"] == {"summary": "failed", "trajectory": "stored"}
    assert stored == [{"raw_payload": {}}]


def test_followup_is_one_job_per_turn():
    req = AgentTurnFollowupRequest(session_id="sess-1", client_turn_id="turn-1")
    assert agent_turn_followup.followup_cache_key(req) == "agent_turn_followup:sess-1:turn-1"
    assert agent_turn_followup.followup_cache_key(AgentTurnFollowupRequest(session_id="sess-1")) is None


def test_followup_dispatches_like_agent_chat_turns(monkeypatch):
    from api.async_job_runner import _dispatch_backend_for_job

    monkeypatch.setenv("ASYNC_JOB_BACKEND", "cloud_run_jobs")
    monkeypatch.setenv("AGENT_CHAT_DISPATCH_BACKEND", "warm_worker")

    assert _dispatch_backend_for_job("agent_turn_followup") == "warm_worker"


def test_agent_worker_also_drains_followups_on_its_own_loop(monkeypatch):
    from api import job_worker_loop

    started: list[dict] = []
    monkeypatch.setattr(job_worker_loop, "run_loop", lambda **kwargs: started.append(kwargs))
    stop = threading.Event()

    threads = job_worker_loop._start_companion_loops("agent_chat_turn", "agent", stop)
    for thread in threads:
        thread.join(2)

    assert started == [
        {"job_type": "agent_turn_followup", "queue_name": "agent", "poll_interval_s": 1.0, "stop_event": stop}
    ]
    assert job_worker_loop._start_companion_loops("analyzer", "analyzer", stop) == []


def test_crashed_followup_loop_stops_the_worker(monkeypatch):
    from api import job_worker_loop

    def crash(**kwargs):
        raise RuntimeError("bad claim query")

    monkeypatch.setattr(job_worker_loop, "run_loop", crash)
    stop = threading.Event()

    for thread in job_worker_loop._start_companion_loops("agent_chat_turn", "agent", stop):
        thread.join(2)

    assert stop.is_set()


# --- The chat turn sends "done" before any follow-up work -------------------------------------


class _FakeStream:
    def __iter__(self):
        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="Strong."))

    def get_final_message(self):
        return SimpleNamespace(
            content=[{"type": "text", "text": "Strong."}],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


class _FakeStreamManager:
    def __enter__(self):
        return _FakeStream()

    def __exit__(self, *exc):
        return False


@pytest.fixture
def chat_turn(temp_memory_db, monkeypatch):
    """A session beyond the token window, with every LLM call outside the stream recorded."""
    monkeypatch.setattr(memory_manager, "VERBATIM_TOKEN_BUDGET", 100)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-followup-test")
    fake_client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: _FakeStreamManager()))
    monkeypatch.setattr("anthropic.Anthropic", lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(agent_router, "_build_agent_instructions", lambda screen_context=None: "agent instructions")

    llm_calls: list[str] = []
    monkeypatch.setattr("llm_utils.call_llm_text", lambda **kwargs: llm_calls.append("call") or ("", [], None))
    events: list[str] = []
    followups: list[AgentTurnFollowupRequest] = []

    def queue(req):
        events.append("followup")
        followups.append(req)

    monkeypatch.setattr(agent_router, "queue_agent_turn_followup", queue)

    session_reads: list[str] = []
    real_get_or_create = memory_db.get_or_create_session

    def counting_get_or_create(session_id=None):
        session_reads.append(str(session_id))
        return real_get_or_create(session_id)

    sid = real_get_or_create(None)["session_id"]
    memory_db.append_messages(
        sid, [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"} for i in range(16)]
    )
    monkeypatch.setattr(memory_db, "get_or_create_session", counting_get_or_create)
    return SimpleNamespace(
        session_id=sid, events=events, followups=followups, llm_calls=llm_calls, session_reads=session_reads
    )


def _consume_live(req: AgentChatRequest, events: list[str]) -> dict:
    done_payload: dict = {}

    async def consume():
        import json

        response = agent_router.agent_chat(req, admin_actor(source="test"))
        async for chunk in response.body_iterator:
            text = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
            for frame in text.split("\n\n"):
                if frame.startswith("event: done"):
                    events.append("done")
                    done_payload.update(json.loads(frame.split("data: ", 1)[1]))

    asyncio.run(consume())
    return done_payload


def test_live_turn_sends_done_before_queueing_followup(chat_turn, monkeypatch):
    def shadow_rollout(**kwargs):
        decision = RolloutDecision(
            mode="shadow",
            baseline_provider=kwargs["baseline_provider"],
            candidate_provider="talisman",
            applied_provider=kwargs["baseline_provider"],
            task_class="agent_turn",
            confidence=1.0,
            canary_selected=False,
            candidate_id="cand-1",
            candidate_model="talisman-test",
            rule_version="test",
        )
        return decision, RolloutTelemetry(enabled=True, shadow_mode=True)

    monkeypatch.setattr(agent_router, "_resolve_owned_model_rollout", shadow_rollout)
    req = AgentChatRequest(
        message="How does NVDA data center demand look this quarter?",
        session_id=chat_turn.session_id,
        client_turn_id="turn-live",
    )

    done = _consume_live(req, chat_turn.events)

    assert chat_turn.events == ["done", "followup"]
    assert chat_turn.llm_calls == []  # the shadow call waits for the follow-up job
    assert chat_turn.session_reads == [chat_turn.session_id]
    assert done["owned_model_rollout"]["telemetry"]["shadow_comparison"] is None

    [followup] = chat_turn.followups
    assert followup.messages_before_turn == 16
    assert followup.shadow is not None and followup.shadow["baseline_result"]["output_text"] == "Strong."
    assert followup.trajectory is not None and followup.trajectory["final_disposition"] == "succeeded"


def test_worker_turn_publishes_done_before_queueing_followup(chat_turn, monkeypatch):
    def append_job_event(job_id, event_type, payload):
        if event_type == "done":
            chat_turn.events.append("done")

    monkeypatch.setattr(agent_chat_worker, "append_job_event", append_job_event)
    monkeypatch.setattr(agent_chat_worker, "get_job_status", lambda job_id: "running")
    # The API process begins the turn before queueing it.
    memory_db.begin_turn(
        chat_turn.session_id,
        {"role": "user", "content": "How does NVDA demand look?", "client_turn_id": "turn-worker"},
        {"role": "assistant", "content": "", "client_turn_id": "turn-worker", "is_streaming": True},
    )
    req = AgentChatJobRequest(
        message="How does NVDA demand look?",
        session_id=chat_turn.session_id,
        client_turn_id="turn-worker",
        actor=actor_to_dict(admin_actor(source="test")),
    )

    agent_chat_worker._run_agent_chat_turn_job(req, job_id="job-worker")

    assert chat_turn.events == ["done", "followup"]
    assert chat_turn.llm_calls == []
    assert chat_turn.session_reads == [chat_turn.session_id]
    assert chat_turn.followups[0].messages_before_turn == 16
    messages = memory_db.get_session(chat_turn.session_id)["transcript"]
    assert len(messages) == 18 and messages[-1]["content"] == "Strong."


def test_router_shadow_runs_after_done_and_stores_comparison_and_training(chat_turn, monkeypatch):
    import decision_quality.intent_router as intent_router

    monkeypatch.setenv("AGENT_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("AGENT_INTENT_ROUTER_SHADOW_MODE", "true")
    monkeypatch.setenv("AGENT_INTENT_ROUTER_TRAINING_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("AGENT_INTENT_ROUTER_TRAINING_CAPTURE_MISMATCH_ONLY", "true")
    router_calls = []
    rows = []
    trajectories = []

    def route(**kwargs):
        router_calls.append(kwargs)
        baseline = kwargs["regex_baseline"]
        return intent_router.RouteDecision(**{**baseline.to_meta(), "intent_class": "portfolio_query", "source": "llm"})

    monkeypatch.setattr(intent_router, "run_llm_route_decision", route)
    monkeypatch.setattr("api.intent_router_training_store.insert_training_row", lambda row: rows.append(row))
    monkeypatch.setattr("api.agent_trajectories.insert_trajectory", lambda row: trajectories.append(row) or "stored")
    req = AgentChatRequest(
        message="How does NVDA data center demand look this quarter?",
        session_id=chat_turn.session_id,
        client_turn_id="router-shadow-turn",
    )
    done = _consume_live(req, chat_turn.events)
    assert chat_turn.events == ["done", "followup"]
    assert router_calls == rows == []
    assert done["intent_router"]["telemetry"]["shadow_pending"] is True
    [followup] = chat_turn.followups
    assert followup.intent_router_shadow is not None
    assert "sk-ant-followup-test" not in followup.model_dump_json()
    # The queued schema must survive its JSON round-trip.
    followup = AgentTurnFollowupRequest.model_validate_json(followup.model_dump_json())
    followup.intent_router_shadow["opportunity_candidate_metadata"] = {"ticker": "NVDA"}
    run_agent_turn_followup(followup)
    assert len(router_calls) == len(rows) == len(trajectories) == 1
    meta = trajectories[0]["route"]["telemetry"]
    assert meta["shadow_pending"] is False
    assert meta["shadow_comparison"]["intent_match"] is False
    assert rows[0]["session_id"] == chat_turn.session_id
    assert rows[0]["opportunity_candidate_metadata"] == {"ticker": "NVDA"}
    route_step = next(step for step in trajectories[0]["steps"] if step["kind"] == "route")
    assert route_step["payload"]["telemetry"] == meta


def test_router_shadow_failure_still_records_trajectory(monkeypatch):
    def fail(req):
        raise RuntimeError("router unavailable")

    stored = []
    monkeypatch.setattr(agent_turn_followup, "_run_intent_router_shadow", fail)
    monkeypatch.setattr("api.agent_trajectories.insert_trajectory", lambda row: stored.append(row) or "stored")
    result = run_agent_turn_followup(
        AgentTurnFollowupRequest(
            session_id="s",
            trajectory={"route": {"applied": {"source": "regex"}}},
            intent_router_shadow={"route_meta": {"applied_source": "regex_shadow", "shadow_pending": True}},
        )
    )
    assert result["steps"] == {"intent_router_shadow": "failed", "trajectory": "stored"}
    assert stored[0]["route"]["telemetry"]["shadow_pending"] is False
