from __future__ import annotations

import pytest

from api import memory_db, memory_manager


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


def test_build_conversation_context_skips_duplicate_user_turn(temp_memory_db):
    session = memory_db.get_or_create_session(None)
    sid = session["session_id"]
    turn_id = "turn-context"
    memory_manager.begin_turn(
        sid,
        {"role": "user", "content": "Review NVDA", "timestamp": 1.0, "client_turn_id": turn_id},
        {"role": "assistant", "content": "", "timestamp": 2.0, "client_turn_id": turn_id, "is_streaming": True},
    )

    conversation, _ = memory_manager.build_conversation_context(
        sid,
        "Review NVDA",
        enable_retrieval=False,
        client_turn_id=turn_id,
    )

    user_messages = [item for item in conversation if item["role"] == "user" and item["content"] == "Review NVDA"]
    assert len(user_messages) == 1


def test_build_conversation_context_excludes_streaming_assistant(temp_memory_db):
    session = memory_db.get_or_create_session(None)
    sid = session["session_id"]
    turn_id = "turn-streaming"
    memory_manager.begin_turn(
        sid,
        {"role": "user", "content": "hello", "timestamp": 1.0, "client_turn_id": turn_id},
        {"role": "assistant", "content": "partial", "timestamp": 2.0, "client_turn_id": turn_id, "is_streaming": True},
    )

    conversation, _ = memory_manager.build_conversation_context(
        sid,
        "follow up",
        enable_retrieval=False,
        client_turn_id="turn-2",
    )

    assert not any(item.get("content") == "partial" for item in conversation)


def _seed_session(count: int, *, summary: str | None = None) -> str:
    sid = memory_db.get_or_create_session(None)["session_id"]
    memory_db.append_messages(
        sid,
        [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message-{i:02d}"} for i in range(count)],
    )
    if summary is not None:
        memory_db.update_rolling_summary(sid, summary)
    return sid


@pytest.fixture
def fake_summarizer(monkeypatch):
    prompts: list[str] = []

    def summarize(text: str):
        prompts.append(text)
        return f"summary-{len(prompts)}", ["NVDA"], ["demand"]

    monkeypatch.setattr("llm_utils.has_llm_api_key", lambda *args, **kwargs: True)
    monkeypatch.setattr("api.routers.memory._summarize_with_haiku", summarize)
    monkeypatch.setattr(memory_manager, "_index_rolling_summary", lambda *args: None)
    return prompts


def test_summary_only_sends_messages_that_just_left_the_window(temp_memory_db, fake_summarizer):
    # 16 earlier messages plus this turn's 2: the turn pushed messages 8 and 9 out of the window.
    sid = _seed_session(18, summary="covers messages 0-7")

    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=16) is True

    [prompt] = fake_summarizer
    assert "covers messages 0-7" in prompt
    sent = sorted(int(part.split("-")[1][:2]) for part in prompt.split() if part.startswith("message-"))
    assert sent == [8, 9]
    assert memory_db.get_or_create_session(sid)["rolling_summary"] == "summary-1"


def test_first_summary_covers_every_message_older_than_the_window(temp_memory_db, fake_summarizer):
    sid = _seed_session(16)

    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=14) is True

    [prompt] = fake_summarizer
    assert "[Previous summary]" not in prompt
    sent = sorted(int(part.split("-")[1][:2]) for part in prompt.split() if part.startswith("message-"))
    assert sent == list(range(8))


def test_summary_waits_for_the_threshold(temp_memory_db, fake_summarizer):
    sid = _seed_session(14)

    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=12) is False
    assert fake_summarizer == []


def test_summary_write_does_not_overwrite_a_concurrent_summary(temp_memory_db):
    sid = _seed_session(2, summary="first")

    assert memory_db.update_rolling_summary(sid, "second", expected="stale") is False
    assert memory_db.update_rolling_summary(sid, "second", expected="first") is True
    assert memory_db.get_or_create_session(sid)["rolling_summary"] == "second"

    fresh = _seed_session(2)
    assert memory_db.update_rolling_summary(fresh, "initial", expected="") is True


def test_summary_retries_against_a_summary_written_meanwhile(temp_memory_db, monkeypatch):
    sid = _seed_session(18, summary="before")
    prompts: list[str] = []

    def summarize(text: str):
        prompts.append(text)
        if len(prompts) == 1:
            memory_db.update_rolling_summary(sid, "written by another summarizer")
        return f"summary-{len(prompts)}", [], []

    monkeypatch.setattr("llm_utils.has_llm_api_key", lambda *args, **kwargs: True)
    monkeypatch.setattr("api.routers.memory._summarize_with_haiku", summarize)
    monkeypatch.setattr(memory_manager, "_index_rolling_summary", lambda *args: None)

    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=16) is True
    assert "written by another summarizer" in prompts[1]
    assert memory_db.get_or_create_session(sid)["rolling_summary"] == "summary-2"


def test_complete_turn_saves_without_summarizing_or_rereading(temp_memory_db, monkeypatch, fake_summarizer):
    sid = _seed_session(18)
    turn_id = "turn-complete"
    memory_manager.begin_turn(
        sid,
        {"role": "user", "content": "q", "client_turn_id": turn_id},
        {"role": "assistant", "content": "", "client_turn_id": turn_id, "is_streaming": True},
    )
    monkeypatch.setattr(memory_db, "turn_exists", lambda *args: pytest.fail("complete_turn re-read the session"))

    memory_manager.complete_turn(
        sid,
        {"role": "user", "content": "q", "client_turn_id": turn_id},
        {"role": "assistant", "content": "a", "client_turn_id": turn_id},
    )

    messages = memory_db.get_or_create_session(sid)["server_messages"]
    assert len(messages) == 20
    assert messages[-1]["content"] == "a" and messages[-1]["is_streaming"] is False
    assert fake_summarizer == []


def test_messages_before_turn_counts_from_the_turns_first_message(temp_memory_db):
    sid = _seed_session(4)
    session = memory_db.get_or_create_session(sid)
    assert memory_manager.messages_before_turn(session, "turn-new") == 4

    memory_manager.begin_turn(
        sid,
        {"role": "user", "content": "q", "client_turn_id": "turn-new"},
        {"role": "assistant", "content": "", "client_turn_id": "turn-new", "is_streaming": True},
    )
    session = memory_db.get_or_create_session(sid)
    assert memory_manager.messages_before_turn(session, "turn-new") == 4
    assert memory_manager.messages_before_turn(session, None) == 6


def test_build_conversation_context_uses_the_loaded_session(temp_memory_db, monkeypatch):
    sid = _seed_session(4, summary="earlier")
    session = memory_db.get_or_create_session(sid)
    monkeypatch.setattr(memory_db, "get_or_create_session", lambda *args: pytest.fail("session read twice"))

    conversation, resolved = memory_manager.build_conversation_context(
        sid, "next", enable_retrieval=False, session=session
    )

    assert resolved == sid
    assert "earlier" in str(conversation[0]["content"])
    assert conversation[-1] == {"role": "user", "content": "next"}
