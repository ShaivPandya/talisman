"""Chat attachments: upload checks, stored descriptors, provider content blocks and the budget (TL-225)."""

import base64
import json

import pytest

import api.routers.agent as agent_router
from api import chat_attachments, memory_db, memory_manager
from api.agent_governance import AgentBudgetExceeded, AgentBudgetState, prepare_model_egress, redact_secrets
from api.agent_models import AgentChatRequest
from api.exceptions import ValidationError
from ontology.policy import admin_actor, agent_actor
from talisman_openai_compat import conversation_to_chat_messages
from tests.test_agent_round_text import ANSWER, _install_rounds
from tests.test_agent_stream_retry import _run_turn, _Turn
from tests.test_agent_turn_terminal_state import NORMAL_PROMPT, _stream_generator, agent_env, temp_memory_db

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
CSV = b"ticker,weight\nAAPL,0.4\nMSFT,0.35\nNVDA,0.25\n"
PDF_TEXT = "Revenue grew 12 percent year over year"


def make_pdf(text: str = PDF_TEXT) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


@pytest.fixture(autouse=True)
def attachment_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_attachments, "ATTACHMENT_DIR", tmp_path / "attachments")


def stored(data: bytes, filename: str, content_type: str = "") -> chat_attachments.Attachment:
    return chat_attachments.store_attachment(data, filename=filename, content_type=content_type)


# --- upload endpoint -------------------------------------------------------------------------------------------


def test_upload_returns_a_descriptor_and_serves_the_bytes_back(auth_client):
    pdf = make_pdf()
    response = auth_client.post("/api/agent/attachments", files={"file": ("10-K.pdf", pdf, "application/pdf")})

    assert response.status_code == 200
    descriptor = response.json()
    assert descriptor["name"] == "10-K.pdf"
    assert (descriptor["kind"], descriptor["mime_type"], descriptor["size"]) == ("pdf", "application/pdf", len(pdf))
    assert set(descriptor) == {"id", "name", "mime_type", "kind", "size", "sha256"}

    fetched = auth_client.get(f"/api/agent/attachments/{descriptor['id']}")
    assert fetched.status_code == 200
    assert fetched.content == pdf
    assert fetched.headers["content-type"] == "application/pdf"
    assert fetched.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("data", "kind", "mime_type"),
    [
        (make_pdf(), "pdf", "application/pdf"),
        (PNG, "image", "image/png"),
        (b"\xff\xd8\xff\xe0" + b"0" * 32, "image", "image/jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image", "image/webp"),
    ],
)
def test_pdfs_and_images_are_recognised_by_their_bytes_whatever_the_name(data, kind, mime_type):
    for name in ("renamed.bin", "misleading.csv", ""):
        assert chat_attachments.sniff_attachment(data, filename=name, content_type="application/octet-stream") == (
            kind,
            mime_type,
        )


def test_a_csv_needs_a_csv_name_or_content_type():
    assert chat_attachments.sniff_attachment(CSV, filename="weights.CSV") == ("csv", "text/csv")
    assert chat_attachments.sniff_attachment(CSV, content_type="text/csv; charset=utf-8") == ("csv", "text/csv")
    with pytest.raises(ValidationError, match="Unsupported file type"):
        chat_attachments.sniff_attachment(CSV, filename="weights.bin", content_type="application/octet-stream")


@pytest.mark.parametrize(
    ("filename", "data", "content_type"),
    [
        ("empty.pdf", b"", "application/pdf"),
        ("fake.pdf", b"this is not a pdf", "application/pdf"),
        ("tool.exe", b"MZ\x90\x00\x03", "application/octet-stream"),
        ("notes.txt", b"plain text", "text/plain"),
        ("binary.csv", b"a,b\x00\x01\x02", "text/csv"),
        ("anim.gif", b"GIF89a\x01\x00\x01\x00", "image/gif"),
    ],
)
def test_upload_rejects_what_chat_cannot_use(auth_client, filename, data, content_type):
    response = auth_client.post("/api/agent/attachments", files={"file": (filename, data, content_type)})

    assert response.status_code == 422
    assert not list(chat_attachments.ATTACHMENT_DIR.glob("*")) if chat_attachments.ATTACHMENT_DIR.exists() else True


def test_each_kind_has_its_own_size_limit(auth_client, monkeypatch):
    monkeypatch.setitem(chat_attachments.MAX_UPLOAD_BYTES, "image", len(PNG) - 1)

    with pytest.raises(ValidationError, match="image is larger"):
        stored(PNG, "big.png")
    response = auth_client.post("/api/agent/attachments", files={"file": ("big.png", PNG, "image/png")})
    assert response.status_code == 422
    assert stored(CSV, "ok.csv").size == len(CSV)  # the other kinds keep their own limits


def test_an_unknown_or_malformed_id_reads_as_404(auth_client):
    assert auth_client.get(f"/api/agent/attachments/{'0' * 32}").status_code == 404
    assert auth_client.get("/api/agent/attachments/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert chat_attachments.load_attachment("../../etc/passwd") is None
    assert chat_attachments.load_attachment(None) is None


def test_names_are_reduced_to_a_safe_basename():
    assert stored(CSV, "../../etc/positions.csv").name == "positions.csv"
    assert stored(CSV, "a\\b\\c\x07.csv").name == "c.csv"
    assert stored(PNG, "").name == "attachment.png"
    assert len(stored(CSV, "x" * 300 + ".csv").name) == 120


# --- resolving a message's files ---------------------------------------------------------------------------------


def test_resolve_attachments_keeps_order_and_drops_duplicates():
    pdf, image = stored(make_pdf(), "a.pdf"), stored(PNG, "b.png")

    assert [a.id for a in chat_attachments.resolve_attachments([image.id, pdf.id, image.id])] == [image.id, pdf.id]


def test_resolve_attachments_rejects_missing_files_and_oversized_sets(monkeypatch):
    with pytest.raises(ValidationError, match="no longer available"):
        chat_attachments.resolve_attachments(["f" * 32])

    pdf = stored(make_pdf(), "a.pdf")
    monkeypatch.setattr(chat_attachments, "MAX_REQUEST_BINARY_BYTES", pdf.size)
    with pytest.raises(ValidationError, match="together"):
        chat_attachments.resolve_attachments([pdf.id, stored(PNG, "b.png").id])

    monkeypatch.setattr(chat_attachments, "MAX_ATTACHMENTS_PER_MESSAGE", 1)
    with pytest.raises(ValidationError, match="at most 1"):
        chat_attachments.resolve_attachments([stored(CSV, "a.csv").id, stored(CSV, "b.csv").id])


def test_request_model_caps_the_number_of_files():
    with pytest.raises(ValueError):
        AgentChatRequest(message="hi", attachment_ids=["a"] * 6)


# --- content blocks --------------------------------------------------------------------------------------------


def test_user_content_is_plain_text_without_files():
    assert chat_attachments.user_content("hello", [], binary_left=10) == ("hello", 0)


def test_user_content_puts_files_before_the_question():
    pdf, image, table = stored(make_pdf(), "10-K.pdf"), stored(PNG, "chart.png"), stored(CSV, "weights.csv")

    content, used = chat_attachments.user_content("Summarise these", [pdf, image, table], binary_left=10**9)

    assert used == pdf.size + image.size
    assert [block["type"] for block in content] == ["document", "image", "text", "text"]
    assert content[0]["title"] == "10-K.pdf"
    assert content[0]["source"] == {
        "type": "base64",
        "media_type": "application/pdf",
        "data": base64.b64encode(make_pdf()).decode(),
    }
    assert content[1]["source"]["media_type"] == "image/png"
    assert content[2]["text"] == '<attachment name="weights.csv" type="text/csv">\n' + CSV.decode() + "\n</attachment>"
    assert content[3] == {"type": "text", "text": "Summarise these"}


def test_a_long_csv_is_cut_at_a_row_and_says_so(monkeypatch):
    monkeypatch.setattr(chat_attachments, "CSV_TEXT_CHARS", 40)
    rows = "\n".join(f"row{i},{i}" for i in range(100)).encode()

    text = chat_attachments.csv_text(rows, "big.csv")

    assert "row0,0" in text and "row99,99" not in text
    assert "[Truncated: showing the first " in text and "of 100 rows]" in text


def test_a_csv_in_a_windows_encoding_is_still_readable():
    assert "café" in chat_attachments.csv_text("name\ncafé".encode("cp1252"), "x.csv")


def test_files_over_the_byte_budget_become_a_note_not_a_block():
    first, second = stored(make_pdf("one"), "one.pdf"), stored(make_pdf("two"), "two.pdf")

    content, used = chat_attachments.user_content("Compare", [first, second], binary_left=first.size)

    assert used == first.size
    assert content[0]["type"] == "document"
    assert content[1]["type"] == "text" and 'pdf "two.pdf" is not included' in content[1]["text"]


def test_a_file_deleted_from_storage_becomes_a_note():
    pdf = stored(make_pdf(), "gone.pdf")
    (chat_attachments.ATTACHMENT_DIR / pdf.id / "data.bin").unlink()

    content, used = chat_attachments.user_content("hi", [pdf], binary_left=10**9)

    assert used == 0 and "no longer available" in content[0]["text"]


# --- provider shapes -------------------------------------------------------------------------------------------


def blocks_for_all_kinds():
    content, _ = chat_attachments.user_content(
        "Question?", [stored(make_pdf(), "10-K.pdf"), stored(PNG, "chart.png"), stored(CSV, "w.csv")], binary_left=10**9
    )
    return content


def test_openai_gets_input_file_and_input_image_data_urls():
    out = chat_attachments.openai_content(blocks_for_all_kinds(), "user")

    assert [b["type"] for b in out] == ["input_file", "input_image", "input_text", "input_text"]
    assert out[0]["filename"] == "10-K.pdf"
    assert out[0]["file_data"] == "data:application/pdf;base64," + base64.b64encode(make_pdf()).decode()
    assert out[1]["image_url"].startswith("data:image/png;base64,")


def test_gemini_gets_inline_data_parts():
    out = chat_attachments.gemini_parts(blocks_for_all_kinds())

    assert out[0] == {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(make_pdf()).decode()}}
    assert out[1]["inline_data"]["mime_type"] == "image/png"
    assert out[2]["text"].startswith("<attachment") and out[3] == {"text": "Question?"}


def test_text_only_provider_gets_the_pdf_text_and_a_note_for_images():
    messages = conversation_to_chat_messages([{"role": "user", "content": blocks_for_all_kinds()}])

    text = messages[0]["content"]
    assert PDF_TEXT in text
    assert "[Attached image omitted: this model cannot read images]" in text
    assert "AAPL,0.4" in text and text.endswith("Question?")
    assert "base64" not in text


def test_text_only_conversations_convert_as_before():
    messages = conversation_to_chat_messages(
        [{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]
    )

    assert messages == [{"role": "user", "content": "ab"}]


# --- conversation building -------------------------------------------------------------------------------------


def session_with(*messages):
    linked, parent = [], None
    for index, message in enumerate(messages):
        linked.append({"id": f"m{index}", "parent_id": parent, **message})
        parent = f"m{index}"
    return {"session_id": "s1", "server_messages": linked, "rolling_summary": None}


def types_of(content):
    return [block["type"] for block in content] if isinstance(content, list) else content


def test_a_new_message_carries_its_files_and_history_without_files_stays_text():
    pdf = stored(make_pdf(), "10-K.pdf")
    session = session_with({"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"})

    conversation, _ = memory_manager.build_conversation_context(
        "s1", "Read this", enable_retrieval=False, session=session, attachments=[pdf]
    )

    assert [m["content"] for m in conversation[:2]] == ["hello", "hi"]
    assert types_of(conversation[-1]["content"]) == ["document", "text"]


def test_files_stay_with_the_earlier_messages_that_carried_them():
    pdf, image = stored(make_pdf(), "10-K.pdf"), stored(PNG, "chart.png")
    session = session_with(
        {"role": "user", "content": "Read this 10-K", "attachments": [pdf.descriptor()]},
        {"role": "assistant", "content": "Done."},
        {"role": "user", "content": "And this chart", "attachments": [image.descriptor()]},
        {"role": "assistant", "content": "Seen."},
    )

    conversation, _ = memory_manager.build_conversation_context(
        "s1", "Compare them", enable_retrieval=False, session=session
    )

    assert types_of(conversation[0]["content"]) == ["document", "text"]
    assert types_of(conversation[2]["content"]) == ["image", "text"]
    assert conversation[-1]["content"] == "Compare them"


def test_the_newest_files_win_when_history_exceeds_the_byte_budget(monkeypatch):
    old, new = stored(make_pdf("old"), "old.pdf"), stored(make_pdf("new"), "new.pdf")
    monkeypatch.setattr(memory_manager, "MAX_REQUEST_BINARY_BYTES", max(old.size, new.size))
    session = session_with(
        {"role": "user", "content": "first", "attachments": [old.descriptor()]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "second", "attachments": [new.descriptor()]},
        {"role": "assistant", "content": "ok"},
    )

    conversation, _ = memory_manager.build_conversation_context("s1", "now", enable_retrieval=False, session=session)

    assert types_of(conversation[0]["content"]) == ["text", "text"]
    assert 'pdf "old.pdf" is not included' in conversation[0]["content"][0]["text"]
    assert types_of(conversation[2]["content"]) == ["document", "text"]


def test_the_new_message_takes_the_byte_budget_before_history(monkeypatch):
    old, new = stored(make_pdf("old"), "old.pdf"), stored(make_pdf("new"), "new.pdf")
    monkeypatch.setattr(memory_manager, "MAX_REQUEST_BINARY_BYTES", max(old.size, new.size))
    session = session_with(
        {"role": "user", "content": "first", "attachments": [old.descriptor()]},
        {"role": "assistant", "content": "ok"},
    )

    conversation, _ = memory_manager.build_conversation_context(
        "s1", "now", enable_retrieval=False, session=session, attachments=[new]
    )

    assert types_of(conversation[-1]["content"]) == ["document", "text"]
    assert 'pdf "old.pdf" is not included' in conversation[0]["content"][0]["text"]


# --- governance ------------------------------------------------------------------------------------------------


def b64_payload(size: int = 3000) -> str:
    return base64.b64encode(b"%PDF-" + b"x" * size).decode()


def anthropic_message(data: str):
    return {
        "role": "user",
        "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
            {"type": "text", "text": "hi"},
        ],
    }


def test_inline_files_are_swapped_for_placeholders_and_priced_in_tokens():
    from api.agent_governance import strip_inline_files

    data = b64_payload(40_000)
    for message in (
        anthropic_message(data),
        {"role": "user", "content": [{"type": "input_file", "file_data": "data:application/pdf;base64," + data}]},
        {"role": "user", "parts": [{"inline_data": {"mime_type": "application/pdf", "data": data}}]},
    ):
        stripped, tokens = strip_inline_files([message])
        assert data not in json.dumps(stripped)
        assert "application/pdf payload" in json.dumps(stripped)
        assert tokens == len(data) * 3 // 4 // 40


def test_a_large_pdf_is_estimated_at_the_page_limit_not_by_its_size():
    from api.agent_governance import strip_inline_files

    _, tokens = strip_inline_files([anthropic_message(b64_payload(20 * 1024 * 1024))])

    assert tokens == 120_000


def test_text_only_messages_come_back_untouched():
    from api.agent_governance import strip_inline_files

    messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": [{"type": "text", "text": "x"}]}]

    stripped, tokens = strip_inline_files(messages)

    assert stripped is messages and tokens == 0


def test_redaction_leaves_a_files_bytes_alone():
    # Base64 can spell a key-shaped string by chance; rewriting it would corrupt the file.
    data = "AIza" + "B" * 40 + b64_payload()
    message = anthropic_message(data)

    sanitized, findings = redact_secrets([message])

    assert sanitized[0]["content"][0]["source"]["data"] == data
    assert not findings
    assert redact_secrets([{"role": "user", "content": "key AIza" + "B" * 40}])[1]


def test_a_file_is_charged_against_the_input_budget_once_per_turn():
    budget = AgentBudgetState(max_input_tokens=1_000, max_model_calls=5, max_cost_usd=10.0)

    for _ in range(3):
        budget.check_model_call(estimated_input_tokens=600, attached_tokens=500)

    assert budget.estimated_input_tokens == 600 + 100 + 100
    with pytest.raises(AgentBudgetExceeded):
        budget.check_model_call(estimated_input_tokens=900, attached_tokens=500)


def egress(messages, budget=None):
    return prepare_model_egress(
        provider="anthropic",
        purpose="agent_chat",
        stream_kwargs={"model": "claude-test", "max_tokens": 256, "system": "s", "messages": messages},
        actor=agent_actor(admin_actor()),
        budget=budget,
        session_id="s1",
    )


def test_egress_treats_an_attachment_as_private_and_counts_it_without_its_base64():
    data = b64_payload(200_000)
    budget = AgentBudgetState(max_input_tokens=200_000, max_model_calls=3, max_cost_usd=10.0)

    kwargs, manifest = egress([anthropic_message(data)], budget)

    assert manifest["data_sensitivity"] == "research_private"
    assert kwargs["messages"][0]["content"][0]["source"]["data"] == data  # the provider still gets the file
    assert manifest["estimated_input_tokens"] == len(data) * 3 // 4 // 40 + budget.estimated_input_tokens - (
        len(data) * 3 // 4 // 40
    )
    assert 5_000 < manifest["estimated_input_tokens"] < 6_000
    assert budget.attached_tokens_charged == len(data) * 3 // 4 // 40


def test_egress_for_text_only_chat_is_unchanged():
    _, manifest = egress([{"role": "user", "content": "How is the S&P 500 doing?"}])

    assert manifest["data_sensitivity"] == "public_market"


# --- whole turns -----------------------------------------------------------------------------------------------


def user_message(session_id: str, turn_id: str) -> dict:
    transcript = memory_db.get_session(session_id)["transcript"]
    (match,) = [m for m in transcript if m["role"] == "user" and m.get("client_turn_id") == turn_id]
    return match


def blocks_sent(client, provider: str, call: int = 0):
    """The conversation the provider's client received on its ``call``-th request."""
    if provider == "anthropic":
        return client.messages.kwargs_history[call]["messages"]
    if provider == "openai":
        return client.responses.kwargs_history[call]["input"]
    return client.models.kwargs_history[call]["contents"]


@pytest.mark.usefixtures("agent_env")
@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
def test_a_pdf_and_a_screenshot_reach_the_model_and_stay_on_the_saved_message(monkeypatch, provider):
    client = _install_rounds(monkeypatch, provider, [])
    pdf, image = stored(make_pdf(), "10-K.pdf"), stored(PNG, "screenshot.png")

    turn = _run_turn(monkeypatch, NORMAL_PROMPT, attachment_ids=[pdf.id, image.id])

    assert turn.error is None and turn.shown == ANSWER
    sent = blocks_sent(client, provider)[-1]
    content = sent["parts"] if provider == "gemini" else sent["content"]
    if provider == "anthropic":
        assert [b["type"] for b in content[:2]] == ["document", "image"]
        assert content[0]["source"]["data"] == base64.b64encode(make_pdf()).decode()
        assert content[-1]["text"] == NORMAL_PROMPT
    elif provider == "openai":
        assert [b["type"] for b in content[:2]] == ["input_file", "input_image"]
        assert content[0]["file_data"].startswith("data:application/pdf;base64,")
    else:
        assert [list(p) for p in content[:2]] == [["inline_data"], ["inline_data"]]
        assert content[0]["inline_data"]["mime_type"] == "application/pdf"
    assert content[-1]["text"] == NORMAL_PROMPT

    saved = user_message(turn.session_id, turn.turn_id)
    assert saved["content"] == NORMAL_PROMPT
    assert saved["attachments"] == [pdf.descriptor(), image.descriptor()]
    assert "base64" not in json.dumps(saved)
    assert [p["type"] for p in saved["content_parts"]] == ["text", "attachment", "attachment"]
    reloaded = memory_db.get_session(turn.session_id)["transcript"]
    assert [m["attachments"] for m in reloaded if m["role"] == "user"] == [[pdf.descriptor(), image.descriptor()]]


@pytest.mark.usefixtures("agent_env")
def test_a_follow_up_still_sees_the_file_and_a_regenerated_answer_keeps_it(monkeypatch):
    _install_rounds(monkeypatch, "anthropic", [])
    pdf = stored(make_pdf(), "10-K.pdf")
    first = _run_turn(monkeypatch, "Summarise the 10-K", attachment_ids=[pdf.id])

    follow_client = _install_rounds(monkeypatch, "anthropic", [])
    followup = _turn_in(monkeypatch, first.session_id, "What was operating margin?")
    regen_client = _install_rounds(monkeypatch, "anthropic", [])
    regenerated = _turn_in(
        monkeypatch, first.session_id, "Summarise the 10-K", regenerate_of_message_id=first.saved["id"]
    )

    assert followup.error is None and regenerated.error is None
    follow_up_sent = blocks_sent(follow_client, "anthropic")
    assert [types_of(m["content"]) for m in follow_up_sent[:2]] == [["document", "text"], ANSWER]
    assert follow_up_sent[-1]["content"][-1]["text"] == "What was operating margin?"  # the new message has no files
    regenerated_sent = blocks_sent(regen_client, "anthropic")
    assert len(regenerated_sent) == 1  # the question's own files, and nothing after it
    assert types_of(regenerated_sent[0]["content"]) == ["document", "text"]


def _turn_in(monkeypatch, session_id: str, message: str, **fields) -> _Turn:
    turn_id = f"turn-{len(memory_db.get_session(session_id)['transcript'])}-{message[:4]}"
    gen = _stream_generator(
        monkeypatch,
        AgentChatRequest(
            session_id=session_id, client_turn_id=turn_id, message=message, finalize_synchronously=True, **fields
        ),
    )
    frames, error = [], None
    try:
        frames.extend(gen)
    except Exception as exc:
        error = exc
    return _Turn(frames, session_id, turn_id, error)


@pytest.mark.usefixtures("agent_env")
def test_an_unknown_attachment_stops_the_turn_before_anything_is_stored(auth_client):
    response = auth_client.post(
        "/api/agent/chat", json={"message": "Read this", "client_turn_id": "t1", "attachment_ids": ["a" * 32]}
    )
    assert response.status_code == 422

    response = auth_client.post(
        "/api/agent/chat/async", json={"message": "Read this", "client_turn_id": "t2", "attachment_ids": ["a" * 32]}
    )
    assert response.status_code == 422


@pytest.mark.usefixtures("agent_env")
def test_the_queued_job_carries_attachment_ids_and_never_their_bytes(monkeypatch):
    pdf = stored(make_pdf(), "10-K.pdf")
    req = AgentChatRequest(session_id=None, client_turn_id="queued-1", message="Read it", attachment_ids=[pdf.id])
    captured = {}
    monkeypatch.setattr(
        "api.async_job_runner.enqueue_registered_job",
        lambda job_type, payload, **kwargs: captured.update(payload=payload) or ({"job_id": "j1"}, "created"),
    )
    monkeypatch.setattr(agent_router, "get_job", lambda _id: None)

    agent_router._enqueue_agent_chat_turn(req, admin_actor(), emit_starting_event=False)

    assert captured["payload"]["attachment_ids"] == [pdf.id]
    assert len(json.dumps(captured["payload"])) < 4_000
    stored_user = [
        m for m in memory_db.get_session(captured["payload"]["session_id"])["transcript"] if m["role"] == "user"
    ]
    assert stored_user[0]["attachments"] == [pdf.descriptor()]
