"""Regenerate, edit and resend: messages form a tree, and each turn continues one branch (TL-224)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api import memory_db, memory_manager
from api.conversation_messages import (
    TurnLineage,
    has_forks,
    latest_leaf_id,
    message_path,
    resolve_turn_lineage,
)
from tests.test_conversation_messages import begin, rows, store  # noqa: F401


def msg(id_, parent, role="user", **extra):
    return {"id": id_, "parent_id": parent, "role": role, "content": f"text {id_}", **extra}


# u1 -> a1, a1b (regenerated) ; a1 -> u2 -> a2 ; root edit: u1b -> a3
TREE = [
    msg("u1", None),
    msg("a1", "u1", "assistant"),
    msg("u2", "a1"),
    msg("a2", "u2", "assistant"),
    msg("a1b", "u1", "assistant"),
    msg("u1b", None),
    msg("a3", "u1b", "assistant"),
]


def ids(messages):
    return [m["id"] for m in messages]


def test_path_and_latest_leaf_follow_the_tree():
    assert ids(message_path(TREE, "a2")) == ["u1", "a1", "u2", "a2"]
    assert ids(message_path(TREE, "a1b")) == ["u1", "a1b"]
    assert message_path(TREE, "missing") == [] and message_path(TREE, None) == []
    assert latest_leaf_id(TREE) == "a3"
    assert has_forks(TREE)
    assert not has_forks(TREE[:4])


def test_a_cycle_in_parent_links_does_not_hang():
    assert ids(message_path([msg("x", "y"), msg("y", "x")], "x")) == ["y", "x"]


def test_lineage_for_each_kind_of_turn():
    regenerate = resolve_turn_lineage(TREE, regenerate_of_message_id="a1b")
    assert regenerate == TurnLineage(None, True, TREE[0])
    assert regenerate.history(TREE) == []

    edit_root = resolve_turn_lineage(TREE, edit_of_message_id="u1")
    assert edit_root.reused_user is None and edit_root.explicit and edit_root.history(TREE) == []

    edit_later = resolve_turn_lineage(TREE, edit_of_message_id="u2")
    assert ids(edit_later.history(TREE)) == ["u1", "a1"]

    reply = resolve_turn_lineage(TREE, parent_message_id="a1b")
    assert ids(reply.history(TREE)) == ["u1", "a1b"]

    # No parent, or one that isn't stored, continues the latest branch.
    for unnamed in (resolve_turn_lineage(TREE), resolve_turn_lineage(TREE, parent_message_id="gone")):
        assert not unnamed.explicit and ids(unnamed.history(TREE)) == ["u1b", "a3"]

    # An edit can't target an assistant message, and a regenerate can't target a user message.
    assert not resolve_turn_lineage(TREE, edit_of_message_id="a1").explicit
    assert not resolve_turn_lineage(TREE, regenerate_of_message_id="u1").explicit


def test_a_branch_action_needs_a_turn_id_and_cannot_be_two_actions():
    from api.agent_models import AgentChatRequest

    with pytest.raises(ValueError, match="client_turn_id"):
        AgentChatRequest(message="q", regenerate_of_message_id="a1")
    with pytest.raises(ValueError, match="not both"):
        AgentChatRequest(message="q", client_turn_id="t", regenerate_of_message_id="a1", edit_of_message_id="u1")
    assert AgentChatRequest(message="q", client_turn_id="t", edit_of_message_id="u1").edit_of_message_id == "u1"


def test_a_retried_turn_is_found_by_its_stored_user_message():
    stored = [*TREE, msg("u9", "a2", client_turn_id="turn-9"), msg("a9", "u9", "assistant", client_turn_id="turn-9")]
    by_id = resolve_turn_lineage(stored, user_message_id="u9", parent_message_id="a1b")
    by_turn = resolve_turn_lineage(stored, client_turn_id="turn-9")
    for lineage in (by_id, by_turn):
        assert ids(lineage.history(stored)) == ["u1", "a1", "u2", "a2"]


def complete(store, sid, turn, answer_id, text):  # noqa: F811
    store.complete_turn_messages(
        sid,
        turn,
        {"id": f"unused-{turn}", "role": "user", "content": "q"},
        {"id": answer_id, "role": "assistant", "content": text},
    )


def test_regenerating_adds_a_sibling_answer_and_not_a_second_question(store):  # noqa: F811
    sid, user, first = begin(store, turn="t1")
    complete(store, sid, "t1", first["id"], "first answer")
    again = {"id": "again", "role": "assistant", "content": "", "client_turn_id": "t2"}
    store.begin_turn(sid, {**user, "client_turn_id": "t2"}, again)
    store.begin_turn(sid, {**user, "client_turn_id": "t2"}, again)  # a retried job changes nothing
    complete(store, sid, "t2", "again", "second answer")

    stored = rows(store, sid)
    assert [(r["id"], r["parent_id"], r["role"]) for r in stored] == [
        (user["id"], None, "user"),
        (first["id"], user["id"], "assistant"),
        ("again", user["id"], "assistant"),
    ]
    assert [r["client_turn_id"] for r in stored] == ["t1", "t1", "t2"]
    assert store.get_session(sid)["message_count"] == 3
    transcript = store.get_session(sid)["transcript"]
    assert [m["content"] for m in transcript if m["role"] == "assistant"] == ["first answer", "second answer"]


def test_completing_a_regenerated_turn_never_stores_the_question_twice(store):  # noqa: F811
    sid, user, first = begin(store, turn="t1")
    complete(store, sid, "t1", first["id"], "first answer")
    # The turn was never begun, as when a guardrail answers it directly.
    store.complete_turn_messages(
        sid, "t2", {**user, "client_turn_id": "t2"}, {"id": "again", "role": "assistant", "content": "blocked"}
    )
    assert [r["role"] for r in rows(store, sid)] == ["user", "assistant", "assistant"]
    assert rows(store, sid)[-1]["parent_id"] == user["id"]


def test_editing_the_first_message_starts_a_second_root(store):  # noqa: F811
    sid, user, first = begin(store, turn="t1")
    complete(store, sid, "t1", first["id"], "first answer")
    edited = {"id": "edited", "role": "user", "content": "better question", "client_turn_id": "t2", "parent_id": None}
    store.begin_turn(sid, edited, {"id": "new-answer", "role": "assistant", "content": "", "client_turn_id": "t2"})
    stored = rows(store, sid)
    assert [(r["id"], r["parent_id"]) for r in stored[2:]] == [("edited", None), ("new-answer", "edited")]
    assert [r["position"] for r in stored] == [0, 1, 2, 3]


def test_a_named_parent_that_is_not_stored_continues_the_latest_branch(store):  # noqa: F811
    sid, user, first = begin(store, turn="t1")
    complete(store, sid, "t1", first["id"], "first answer")
    follow = {"id": "u2", "role": "user", "content": "next", "client_turn_id": "t2", "parent_id": "never-stored"}
    store.begin_turn(sid, follow, {"id": "a2", "role": "assistant", "content": "", "client_turn_id": "t2"})
    assert rows(store, sid)[2]["parent_id"] == first["id"]


def seed_tree(store):  # noqa: F811
    sid = store.get_or_create_session()["session_id"]
    for m in TREE:
        store.append_messages(sid, [{**m, "content": m["content"]}])
    return sid


def conversation(store, sid, **lineage):  # noqa: F811
    session = store.get_or_create_session(sid)
    built, _ = memory_manager.build_conversation_context(
        sid,
        "new question",
        enable_retrieval=False,
        session=session,
        lineage=resolve_turn_lineage(session["server_messages"], **lineage),
    )
    return [(m["role"], m["content"]) for m in built]


def test_context_holds_only_the_branch_a_turn_continues(store):  # noqa: F811
    sid = seed_tree(store)
    assert conversation(store, sid, parent_message_id="a2") == [
        ("user", "text u1"),
        ("assistant", "text a1"),
        ("user", "text u2"),
        ("assistant", "text a2"),
        ("user", "new question"),
    ]
    assert conversation(store, sid, parent_message_id="a1b") == [
        ("user", "text u1"),
        ("assistant", "text a1b"),
        ("user", "new question"),
    ]
    assert conversation(store, sid, edit_of_message_id="u2") == [
        ("user", "text u1"),
        ("assistant", "text a1"),
        ("user", "new question"),
    ]
    assert conversation(store, sid, edit_of_message_id="u1b") == [("user", "new question")]
    assert conversation(store, sid) == [("user", "text u1b"), ("assistant", "text a3"), ("user", "new question")]


def test_a_summary_is_used_only_on_the_branch_it_covers(store):  # noqa: F811
    sid = seed_tree(store)
    memory_db.update_rolling_summary(sid, "covers a1", through_id="a1")

    def preamble(**lineage):
        first = conversation(store, sid, **lineage)[0][1]
        return "covers a1" in first

    assert preamble(parent_message_id="a2")
    assert not preamble(parent_message_id="a1b")
    assert not preamble(parent_message_id="a3")


def test_a_summary_written_before_branches_is_trusted_only_while_there_are_none(store):  # noqa: F811
    linear = store.get_or_create_session()["session_id"]
    store.append_messages(linear, [msg("l1", None), msg("l2", "l1", "assistant")])
    memory_db.update_rolling_summary(linear, "older summary")
    assert "older summary" in conversation(store, linear)[0][1]
    store.append_messages(linear, [msg("l3", "l1", "assistant")])
    assert "older summary" not in conversation(store, linear)[0][1]


def test_summarizing_follows_the_turns_own_branch(store, monkeypatch):  # noqa: F811
    inputs: list[str] = []
    monkeypatch.setattr("llm_utils.has_llm_api_key", lambda: True)
    monkeypatch.setattr("api.memory_manager._index_rolling_summary", lambda *args: None)
    monkeypatch.setattr(
        "api.routers.memory._summarize_with_haiku",
        lambda text: inputs.append(text) or (f"summary {len(inputs)}", [], []),
    )
    # A token budget that holds exactly eight of the equally long messages below.
    monkeypatch.setattr(
        memory_manager,
        "VERBATIM_TOKEN_BUDGET",
        sum(
            memory_manager.estimate_tokens({"role": "user" if i % 2 == 0 else "assistant", "content": "main-00"})
            for i in range(8)
        ),
    )

    def chain(prefix, count, parent, turn):
        made = []
        for i in range(count):
            made.append(
                {
                    "id": f"{prefix}{i}",
                    "parent_id": f"{prefix}{i - 1}" if i else parent,
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"{'main' if prefix == 'm' else 'fork'}-{i:02d}",
                }
            )
        made[-1]["client_turn_id"] = turn
        return made

    sid = store.get_or_create_session()["session_id"]
    store.append_messages(sid, chain("m", 20, None, "turn-main"))
    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=18, client_turn_id="turn-main")
    assert store.get_session(sid)["rolling_summary_through_id"] == "m11"
    assert "[Previous summary]" not in inputs[0] and "main-11" in inputs[0] and "main-12" not in inputs[0]

    # A branch from m3 shares only m0..m3 with the summarized one, so its summary starts over.
    store.append_messages(sid, chain("f", 18, "m3", "turn-fork"))
    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=20, client_turn_id="turn-fork")
    assert "[Previous summary]" not in inputs[1] and "main-03" in inputs[1] and "main-04" not in inputs[1]
    assert "fork-09" in inputs[1] and "fork-10" not in inputs[1]
    assert store.get_session(sid)["rolling_summary_through_id"] == "f9"

    # Another turn on that branch extends its summary instead.
    more = chain("f", 20, "m3", "turn-fork-2")[18:]
    store.append_messages(sid, more)
    assert memory_manager.summarize_departed_messages(sid, messages_before_turn=22, client_turn_id="turn-fork-2")
    previous, _, new = inputs[2].partition("[New messages to incorporate]")
    assert "summary 2" in previous and "fork-10" in new and "fork-11" in new and "fork-09" not in new
    assert store.get_session(sid)["rolling_summary_through_id"] == "f11"


@pytest.fixture
def chat(store, auth_client, monkeypatch):  # noqa: F811
    import api.routers.agent as agent
    from tests.test_agent_streaming import _event_text_delta, _install_fake_anthropic, _parse_sse

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(agent, "_build_agent_instructions", lambda screen_context=None: "agent instructions")
    monkeypatch.setattr("api.memory_manager._ensure_session_title", lambda *args: None)
    followups = []
    monkeypatch.setattr(agent, "queue_agent_turn_followup", followups.append)
    replies = [f"answer {n}" for n in range(1, 8)]
    client = _install_fake_anthropic(
        monkeypatch,
        [
            (
                [_event_text_delta(text)],
                SimpleNamespace(
                    content=[{"type": "text", "text": text}],
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                ),
            )
            for text in replies
        ],
    )

    def send(**body):
        response = auth_client.post("/api/agent/chat", json={"finalize_synchronously": True, **body})
        return next(payload for event, payload in _parse_sse(response.text) if event == "done")

    def model_input():
        sent = client.messages.kwargs_history[-1]["messages"]
        return [
            (
                m["role"],
                m["content"] if isinstance(m["content"], str) else "".join(b.get("text", "") for b in m["content"]),
            )
            for m in sent
        ]

    def transcript(sid):
        return auth_client.get(f"/api/memory/sessions/{sid}").json()["transcript"]

    return SimpleNamespace(send=send, model_input=model_input, transcript=transcript, followups=followups)


def test_regenerate_and_edit_keep_their_versions_and_choose_the_context(chat):
    first = chat.send(message="portfolio test", client_turn_id="t1", user_message_id="u1", assistant_message_id="a1")
    sid = first["session_id"]

    again = chat.send(
        message="portfolio test",
        session_id=sid,
        client_turn_id="t2",
        user_message_id="u1",
        assistant_message_id="a2",
        regenerate_of_message_id="a1",
    )
    assert again["user_message_id"] == "u1" and again["assistant_message_id"] == "a2"
    assert chat.model_input() == [("user", "portfolio test")]
    stored = chat.transcript(sid)
    assert [(m["id"], m["parent_id"], m["content"]) for m in stored] == [
        ("u1", None, "portfolio test"),
        ("a1", "u1", "answer 1"),
        ("a2", "u1", "answer 2"),
    ]

    # Replying to the first version continues that version, not the newest one.
    chat.send(
        message="follow up",
        session_id=sid,
        client_turn_id="t3",
        user_message_id="u2",
        assistant_message_id="a3",
        parent_message_id="a1",
    )
    assert chat.model_input() == [("user", "portfolio test"), ("assistant", "answer 1"), ("user", "follow up")]
    chat.send(
        message="other",
        session_id=sid,
        client_turn_id="t4",
        user_message_id="u3",
        assistant_message_id="a4",
        parent_message_id="a2",
    )
    assert chat.model_input() == [("user", "portfolio test"), ("assistant", "answer 2"), ("user", "other")]

    # Editing the first message branches at the root and sees no earlier history.
    chat.send(
        message="edited",
        session_id=sid,
        client_turn_id="t5",
        user_message_id="u4",
        assistant_message_id="a5",
        edit_of_message_id="u1",
    )
    assert chat.model_input() == [("user", "edited")]
    stored = {m["id"]: m for m in chat.transcript(sid)}
    assert stored["u4"]["parent_id"] is None and stored["a5"]["parent_id"] == "u4"
    assert [m["id"] for m in stored.values()].count("u1") == 1


def test_each_regenerated_answer_has_its_own_trajectory_in_its_prompts_split_group(chat):
    first = chat.send(message="portfolio test", client_turn_id="t1", user_message_id="u1", assistant_message_id="a1")
    chat.send(
        message="portfolio test",
        session_id=first["session_id"],
        client_turn_id="t2",
        user_message_id="u1",
        assistant_message_id="a2",
        regenerate_of_message_id="a1",
    )
    original, regenerated = (followup.trajectory for followup in chat.followups)
    assert original["trajectory_id"] != regenerated["trajectory_id"]
    assert (original["client_turn_id"], regenerated["client_turn_id"]) == ("t1", "t2")
    assert regenerated["dataset_split_group"].startswith("agent_turn:")
    assert "dataset_split_group" not in original

    from api.agent_trajectories import dataset_split_group_for

    assert regenerated["dataset_split_group"] == dataset_split_group_for(
        session_id=first["session_id"], client_turn_id="t1", messages=[]
    )
