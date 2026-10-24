"""Durable name sources: lifecycle, isolation, provider grounding, and agent retrieval (TL-228)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace

import pytest

from api import agent_tools, company_research_provider, company_research_store, state_storage
from api import name_documents as docs
from api.agent_governance import classify_model_payload
from api.company_research_context import ContextEvidence
from api.company_research_evidence import (
    Fact,
    OverviewPacket,
    Section,
    Source,
    WrittenSections,
    validate_sections,
    validate_sources,
)
from api.company_research_workflow import Workflow
from api.exceptions import NotFoundError, ValidationError
from tests.test_agent_turn_terminal_state import agent_env, temp_memory_db
from tests.test_chat_attachments import make_pdf
from tests.test_company_research_workflow import claimed, mock_client, response

FACT = "The proprietary survey counted exactly 731 violet satellites."


@pytest.fixture(autouse=True)
def isolated_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "DOCUMENT_DIR", tmp_path / "documents")
    monkeypatch.setattr(company_research_store, "SQLITE_PATH", tmp_path / "runs.sqlite3")


@pytest.mark.parametrize("ticker", ["MU", "EURUSD=X", "GC=F"])
@pytest.mark.parametrize(
    "filename,payload",
    [("survey.pdf", make_pdf(FACT)), ("survey.txt", FACT.encode()), ("survey.md", f"# Survey\n{FACT}".encode())],
)
def test_uploads_list_and_download_after_reopening_without_a_holding(auth_client, ticker, filename, payload):
    uploaded = auth_client.post(f"/api/names/{ticker}/documents", files={"file": (filename, payload)})
    assert uploaded.status_code == 201, uploaded.text
    meta = uploaded.json()
    assert meta["source_kind"] == "private_upload"
    assert meta["ticker"] == ticker
    assert docs.list_documents(ticker)["documents"] == [meta]
    assert auth_client.get(f"/api/names/{ticker}/documents").json()["documents"] == [meta]
    downloaded = auth_client.get(meta["url"])
    assert downloaded.content == payload
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert FACT in docs.read_document(ticker, meta["id"])["passages"][0]["text"]


def test_individual_delete_preserves_other_files_and_other_names(auth_client):
    first = docs.upload("MU", FACT.encode(), "survey.txt")
    second = docs.upload("MU", b"A different note", "note.md")
    attached = auth_client.post(f"/api/names/MU/documents/{first['id']}/attach", json={"tickers": ["GC=F", "EURUSD=X"]})
    assert attached.status_code == 200
    assert auth_client.delete(f"/api/names/MU/documents/{first['id']}").status_code == 204
    assert [d["id"] for d in docs.list_documents("MU")["documents"]] == [second["id"]]
    assert auth_client.get(first["url"]).status_code == 404
    for ticker in ("GC=F", "EURUSD=X"):
        assert docs.get_document(ticker, first["id"])["sha256"] == first["sha256"]
        assert docs.original(ticker, first["id"]) == FACT.encode()
    assert docs.list_documents("MSFT")["count"] == 0
    with pytest.raises(NotFoundError):
        docs.read_document("MSFT", second["id"])


def test_duplicate_attachment_is_idempotent_and_destination_validation_is_atomic():
    document = docs.upload("MU", FACT.encode(), "survey.txt")
    docs.attach("MU", document["id"], ["GC=F", "GC=F"])
    docs.attach("MU", document["id"], ["GC=F"])
    assert docs.list_documents("GC=F")["count"] == 1
    with pytest.raises(ValidationError):
        docs.attach("MU", document["id"], ["MSFT", "../../invalid"])
    assert docs.list_documents("MSFT")["count"] == 0


def test_library_lists_each_file_once_with_every_name_it_is_attached_to(auth_client):
    assert auth_client.get("/api/source-files").json() == {"files": [], "count": 0}
    first = docs.upload("MU", FACT.encode(), "survey.txt")
    second = docs.upload("MSFT", b"A different note", "note.md")
    docs.attach("MU", first["id"], ["GC=F", "EURUSD=X"])
    library = auth_client.get("/api/source-files").json()
    assert library["count"] == 2
    by_hash = {file["sha256"]: file for file in library["files"]}
    survey, note = by_hash[first["sha256"]], by_hash[second["sha256"]]
    assert survey["name"] == "survey.txt"
    assert survey["size"] == len(FACT.encode())
    assert survey["created_at"] == first["created_at"]
    assert survey["tickers"] == ["EURUSD=X", "GC=F", "MU"]
    assert survey["other_names"] == []
    assert auth_client.get(survey["url"]).content == FACT.encode()
    assert (note["name"], note["tickers"]) == ("note.md", ["MSFT"])
    assert [file["sha256"] for file in library["files"]] == [second["sha256"], first["sha256"]]


def test_identical_content_uploaded_to_different_names_is_one_library_entry():
    first = docs.upload("MU", FACT.encode(), "survey.txt")
    second = docs.upload("GC=F", FACT.encode(), "Survey copy.txt")
    assert first["id"] != second["id"]
    [entry] = docs.library()["files"]
    assert entry["tickers"] == ["GC=F", "MU"]
    assert {entry["name"], *entry["other_names"]} == {"survey.txt", "Survey copy.txt"}
    assert len(entry["other_names"]) == 1


def test_library_delete_removes_the_content_from_every_name_and_leaves_other_files(auth_client):
    first = docs.upload("MU", FACT.encode(), "survey.txt")
    kept = docs.upload("MU", b"A different note", "note.md")
    twin = docs.upload("GC=F", FACT.encode(), "survey again.txt")
    docs.attach("MU", first["id"], ["EURUSD=X"])
    snapshot = docs.research_snapshot("MU")
    assert {doc["id"] for doc in snapshot} == {first["id"], kept["id"]}

    assert auth_client.delete(f"/api/source-files/{first['sha256']}").status_code == 204

    assert [doc["id"] for doc in docs.list_documents("MU")["documents"]] == [kept["id"]]
    for ticker in ("GC=F", "EURUSD=X"):
        assert docs.list_documents(ticker)["count"] == 0
    for document in (first, twin):
        assert auth_client.get(document["url"]).status_code == 404
    with pytest.raises(NotFoundError):
        docs.read_document("GC=F", twin["id"])
    passages = docs.research_passages(snapshot, "violet satellites")
    assert passages
    assert {passage["id"] for passage in passages} == {kept["id"]}
    assert [file["sha256"] for file in docs.library()["files"]] == [kept["sha256"]]
    assert docs.original("MU", kept["id"]) == b"A different note"
    assert len(list(docs.DOCUMENT_DIR.rglob("original"))) == 1
    assert len(list(docs.DOCUMENT_DIR.rglob("text.json"))) == 1


@pytest.mark.parametrize("sha256", ["a" * 64, "not-a-hash", "A" * 64, "a" * 63])
def test_library_delete_of_an_unknown_file_is_not_found(auth_client, sha256):
    kept = docs.upload("MU", FACT.encode(), "survey.txt")
    assert auth_client.delete(f"/api/source-files/{sha256}").status_code == 404
    assert docs.list_documents("MU")["count"] == 1
    assert docs.original("MU", kept["id"]) == FACT.encode()
    gone = auth_client.delete(f"/api/source-files/{kept['sha256']}")
    assert gone.status_code == 204
    assert auth_client.delete(f"/api/source-files/{kept['sha256']}").status_code == 404


def test_library_skips_incomplete_uploads_and_stray_directories():
    kept = docs.upload("MU", FACT.encode(), "survey.txt")
    (docs.DOCUMENT_DIR / "MU" / ("b" * 32)).mkdir(parents=True)
    (docs.DOCUMENT_DIR / "MU" / ("b" * 32) / "original").write_bytes(b"partial")
    stray = docs.DOCUMENT_DIR / "not a name" / ("c" * 32)
    stray.mkdir(parents=True)
    (stray / "meta.json").write_text("{}")
    assert [file["sha256"] for file in docs.library()["files"]] == [kept["sha256"]]


def test_unauthenticated_requests_cannot_read_or_delete_from_the_library(client):
    document = docs.upload("MU", FACT.encode(), "survey.txt")
    assert client.get("/api/source-files").status_code == 401
    assert client.delete(f"/api/source-files/{document['sha256']}").status_code == 401
    assert docs.list_documents("MU")["count"] == 1


def test_viewer_can_read_the_library_but_only_administrators_can_delete(auth_client):
    from api.main import app
    from api.routers.auth import require_actor
    from ontology.policy import user_actor

    document = docs.upload("MU", FACT.encode(), "survey.txt")
    app.dependency_overrides[require_actor] = lambda: user_actor("viewer", ("viewer",))
    try:
        assert auth_client.get("/api/source-files").json()["count"] == 1
        assert auth_client.delete(f"/api/source-files/{document['sha256']}").status_code == 403
    finally:
        app.dependency_overrides.pop(require_actor)
    assert docs.list_documents("MU")["count"] == 1


@pytest.mark.parametrize(
    "filename,payload",
    [
        ("empty.txt", b""),
        ("blank.txt", b" \n\t"),
        ("binary.md", b"MZ\x00binary"),
        ("bad.pdf", b"%PDF-broken"),
        ("fake.pdf", b"not a PDF"),
        ("unsupported.exe", b"hello"),
        ("image.png", b"\x89PNG"),
    ],
)
def test_unreadable_uploads_are_rejected_without_storing_files(auth_client, filename, payload):
    result = auth_client.post("/api/names/MU/documents", files={"file": (filename, payload)})
    assert result.status_code == 422
    assert docs.list_documents("MU")["count"] == 0


def test_scanned_pdf_size_limit_and_path_validation(auth_client, monkeypatch):
    response = auth_client.post("/api/names/MU/documents", files={"file": ("scan.pdf", make_pdf(""))})
    assert response.status_code == 422
    assert "OCR" in response.text
    monkeypatch.setattr(docs, "MAX_UPLOAD_BYTES", 10)
    assert auth_client.post("/api/names/MU/documents", files={"file": ("large.txt", FACT.encode())}).status_code == 413
    with pytest.raises(ValidationError):
        docs.list_documents("../../etc/passwd")
    with pytest.raises(NotFoundError):
        docs.original("MU", "../../etc/passwd")
    assert docs.normalize_name(" eur/usd ") == "EURUSD=X"


def test_filename_is_safe_and_utf16_text_is_readable():
    document = docs.upload("MU", FACT.encode("utf-16"), "../../private\\survey\x07.txt")
    assert document["name"] == "survey.txt"
    assert FACT in docs.read_document("MU", document["id"])["passages"][0]["text"]


def test_unauthenticated_requests_cannot_read_or_write(client):
    document = docs.upload("MU", FACT.encode(), "survey.txt")
    assert client.get("/api/names/MU/documents").status_code == 401
    assert client.get(document["url"]).status_code == 401
    assert client.post("/api/names/MU/documents", files={"file": ("x.txt", b"text")}).status_code == 401
    assert client.delete(f"/api/names/MU/documents/{document['id']}").status_code == 401


def test_viewer_can_read_workspace_sources_but_cannot_change_them(auth_client):
    from api.main import app
    from api.routers.auth import require_actor
    from ontology.policy import user_actor

    document = docs.upload("MU", FACT.encode(), "survey.txt")
    app.dependency_overrides[require_actor] = lambda: user_actor("viewer", ("viewer",))
    try:
        assert auth_client.get(document["url"]).status_code == 200
        assert auth_client.post("/api/names/MU/documents", files={"file": ("x.txt", b"text")}).status_code == 403
        assert auth_client.delete(f"/api/names/MU/documents/{document['id']}").status_code == 403
        assert (
            auth_client.post(f"/api/names/MU/documents/{document['id']}/attach", json={"tickers": ["MSFT"]}).status_code
            == 403
        )
    finally:
        app.dependency_overrides.pop(require_actor)


def test_storage_failure_leaves_no_visible_orphan(monkeypatch):
    write = state_storage.write_text

    def fail_metadata(path, key, value, **kwargs):
        if key.endswith("meta.json"):
            raise OSError("Storage unavailable")
        return write(path, key, value, **kwargs)

    monkeypatch.setattr(state_storage, "write_text", fail_metadata)
    with pytest.raises(OSError):
        docs.upload("MU", FACT.encode(), "survey.txt")
    assert docs.list_documents("MU")["count"] == 0
    assert not list(docs.DOCUMENT_DIR.rglob("original"))


def test_concurrent_uploads_do_not_overwrite_a_shared_index():
    with ThreadPoolExecutor(max_workers=5) as pool:
        uploaded = list(pool.map(lambda index: docs.upload("MU", str(index).encode(), "note.txt"), range(10)))
    assert {d["id"] for d in docs.list_documents("MU")["documents"]} == {d["id"] for d in uploaded}


def test_gcs_storage_survives_listing_and_deleting_without_local_files(monkeypatch):
    objects: dict[str, bytes] = {}

    class Blob:
        def __init__(self, name):
            self.name = name

        def exists(self):
            return self.name in objects

        def upload_from_string(self, data, **_kwargs):
            objects[self.name] = data.encode() if isinstance(data, str) else data

        def download_as_text(self, encoding="utf-8"):
            return objects[self.name].decode(encoding)

        def download_as_bytes(self):
            return objects[self.name]

        def delete(self):
            del objects[self.name]

    bucket = SimpleNamespace(
        blob=Blob, list_blobs=lambda prefix: [Blob(key) for key in objects if key.startswith(prefix)]
    )
    monkeypatch.setattr(state_storage, "_bucket", lambda: bucket)
    monkeypatch.setenv("STATE_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("GCS_STATE_BUCKET", "private-workspace-test")
    document = docs.upload("GC=F", FACT.encode(), "survey.txt")
    assert docs.list_documents("GC=F")["documents"] == [document]
    assert docs.original("GC=F", document["id"]) == FACT.encode()
    assert not docs.DOCUMENT_DIR.exists()
    docs.delete("GC=F", document["id"])
    assert not objects
    shared = docs.upload("GC=F", FACT.encode(), "survey.txt")
    docs.attach("GC=F", shared["id"], ["MU"])
    assert [file["tickers"] for file in docs.library()["files"]] == [["GC=F", "MU"]]
    docs.delete_everywhere(shared["sha256"])
    assert not objects
    assert docs.library()["count"] == 0


def test_fresh_agent_tools_retrieve_private_fact_only_for_its_name():
    doc = docs.upload("EURUSD=X", ("Context\n" * 5000 + FACT).encode(), "survey.txt")
    listing = json.loads(agent_tools.execute_tool("list_name_documents", {"ticker": "EURUSD=X"}))
    assert listing["documents"][0]["id"] == doc["id"]
    start, text = 0, ""
    while True:
        result = json.loads(
            agent_tools.execute_tool(
                "read_name_document", {"ticker": "EURUSD=X", "document_id": doc["id"], "start": start}
            )
        )
        text += "".join(p["text"] for p in result["passages"])
        assert result["sources"][0]["title"] == "Private upload: survey.txt"
        if result["next_start"] is None:
            break
        start = result["next_start"]
    assert FACT in text
    unrelated = json.loads(agent_tools.execute_tool("list_name_documents", {"ticker": "MU"}))
    assert unrelated["documents"] == []
    wrong = json.loads(agent_tools.execute_tool("read_name_document", {"ticker": "MU", "document_id": doc["id"]}))
    assert "error" in wrong
    assert classify_model_payload({"conversation": result}) in {"research_private", "portfolio_private"}


def test_research_snapshot_excludes_unrelated_later_and_deleted_files():
    included = docs.upload("MU", FACT.encode(), "survey.txt")
    docs.upload("MSFT", b"Unrelated secret", "other.txt")
    snapshot = docs.research_snapshot("MU")
    docs.upload("MU", b"Later upload", "later.txt")
    passages = docs.research_passages(snapshot, "survey")
    assert [p["id"] for p in passages] == [included["id"]]
    assert FACT in passages[0]["text"]
    assert docs.research_passages(snapshot, "survey", max_bytes=10) == []
    docs.delete("MU", included["id"])
    assert docs.research_passages(snapshot, "survey") == []


def private_packet(document):
    return OverviewPacket(
        facts=[
            Fact(
                record_id="survey",
                section="Business",
                claim=FACT,
                sources=[
                    Source(
                        url=document["url"],
                        title="Private upload: survey.txt",
                        published_on=None,
                        passage=FACT,
                        location="lines 1-1",
                    )
                ],
            )
        ],
        searched_sources=[],
        gaps=[],
    )


def test_research_uses_upload_only_fact_without_sending_it_to_public_web_search(monkeypatch):
    doc = docs.upload("EL", FACT.encode(), "survey.txt")
    docs.upload("MSFT", b"Unrelated secret", "other.txt")
    run_id = claimed()
    company_research_store.mutate_run(
        run_id, lambda s: s["snapshot"].update(private_documents=docs.research_snapshot("EL"))
    )
    packet = private_packet(doc)
    client = mock_client(
        monkeypatch,
        [
            response({"reads": []}, web=False),
            response({"facts": packet.model_dump(mode="json")["facts"], "commitments": [], "gaps": []}, web=False),
            response({"facts": [], "searched_sources": [], "gaps": []}),
        ],
    )
    workflow = Workflow(run_id, "worker")
    workflow.talisman.collect("EL")
    result = workflow.talisman.evidence("overview", ["Business"], [])
    workflow.provider.request(
        "overview/business",
        OverviewPacket,
        prompt="Research the public business",
        instructions="Use evidence",
        web=True,
    )
    assert result.facts[0].claim == FACT
    private_requests = [call.kwargs for call in client.responses.create.call_args_list if not call.kwargs.get("tools")]
    assert private_requests and all(FACT in request["input"] for request in private_requests)
    assert all("Unrelated secret" not in request["input"] for request in private_requests)
    public_request = client.responses.create.call_args.kwargs
    assert public_request["tools"][0]["type"] == "web_search" and public_request["tool_choice"] == "required"
    assert FACT not in public_request["input"] and doc["url"] not in public_request["input"]
    assert client.responses.create.call_count == 3


def test_invented_private_passages_and_wrong_name_citations_fail(monkeypatch):
    doc = docs.upload("EL", FACT.encode(), "survey.txt")
    run_id = claimed()
    company_research_store.mutate_run(
        run_id, lambda s: s["snapshot"].update(private_documents=docs.research_snapshot("EL"))
    )
    packet = private_packet(doc)
    packet.facts[0].sources[0].passage = "An invented private fact"
    mock_client(monkeypatch, [])
    workflow = Workflow(run_id, "worker")
    workflow.talisman.collect_uploads()
    with pytest.raises(ValueError, match="supplied upload passage"):
        workflow.talisman.validate_sources(packet)
    supplied = docs.research_passages(docs.research_snapshot("EL"), "survey")
    packet.facts[0].sources[0].passage = FACT
    packet.facts[0].sources[0].url = docs.citation_url("MSFT", doc["id"])
    with pytest.raises(ValueError, match="supplied upload passage"):
        docs.validate_private_sources(packet.model_dump(mode="json"), supplied)


def test_public_research_cannot_introduce_an_upload_citation(monkeypatch):
    doc = docs.upload("EL", FACT.encode(), "survey.txt")
    run_id = claimed()
    mock_client(monkeypatch, [response(private_packet(doc).model_dump(mode="json"))])
    with pytest.raises(RuntimeError, match="cannot introduce private"):
        company_research_provider.ResearchProvider(run_id, "worker").request(
            "public",
            OverviewPacket,
            prompt="Public research",
            instructions="Evidence",
            web=True,
            attempts=1,
        )


def test_private_citations_survive_section_validation_and_report_archive(monkeypatch):
    doc = docs.upload("EL", FACT.encode(), "survey.txt")
    run_id = claimed()
    company_research_store.mutate_run(
        run_id, lambda s: s["snapshot"].update(private_documents=docs.research_snapshot("EL"))
    )
    mock_client(monkeypatch, [])
    packet = private_packet(doc)
    validate_sources(packet, as_of=date(2026, 10, 24))
    section = WrittenSections(
        sections=[
            Section(
                title="Business", markdown=f"{FACT} [Private upload: survey.txt]({doc['url']})", evidence_ids=["survey"]
            )
        ]
    )
    validate_sections(section, ["Business"], {"survey"}, {doc["url"]})
    saved = []
    monkeypatch.setattr("api.company_research_workflow.legacy._write_json", lambda key, value: saved.append(value))
    monkeypatch.setattr("api.company_research_workflow.legacy._read_json", lambda key: None)
    workflow = Workflow(run_id, "worker")
    workflow.talisman.collect_uploads()
    report = workflow.archive("overview", section.sections[0].markdown, packet, complete=True)
    assert report["sources"] == [
        {"url": doc["url"], "title": "Private upload: survey.txt", "source_kind": "private_upload"}
    ]
    assert doc["url"] in report["content"]


@pytest.mark.usefixtures("agent_env")
def test_new_chat_reads_the_durable_file_and_saves_its_fact_and_citation(monkeypatch):
    from tests.test_agent_stream_retry import _run_turn
    from tests.test_agent_streaming import _event_text_delta, _event_tool_use_start, _install_fake_anthropic

    document = docs.upload("MU", FACT.encode(), "survey.txt")
    streams = []
    for index, (name, arguments) in enumerate(
        [
            ("list_name_documents", {"ticker": "MU"}),
            ("read_name_document", {"ticker": "MU", "document_id": document["id"]}),
        ]
    ):
        call_id = f"document-{index}"
        streams.append(
            (
                [_event_tool_use_start(name, call_id)],
                SimpleNamespace(
                    content=[{"type": "tool_use", "name": name, "id": call_id, "input": arguments}],
                    stop_reason="tool_use",
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                ),
            )
        )
    answer = f"{FACT} [Private upload: survey.txt]({document['url']})"
    streams.append(
        (
            [_event_text_delta(answer)],
            SimpleNamespace(
                content=[{"type": "text", "text": answer}],
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            ),
        )
    )
    client = _install_fake_anthropic(monkeypatch, streams)
    turn = _run_turn(monkeypatch, "What does the uploaded survey for MU report?")
    assert turn.error is None
    assert FACT in turn.shown and FACT in turn.saved["content"]
    assert any(source["url"] == document["url"] for source in turn.saved["sources"])
    assert FACT in json.dumps(client.messages.kwargs_history[-1]["messages"])


def test_research_start_captures_only_the_named_sources(auth_client, monkeypatch):
    from api import company_research as legacy
    from api.routers import company_research as router

    docs.upload("MU", FACT.encode(), "survey.txt")
    docs.upload("MSFT", b"An unrelated secret", "other.txt")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(router, "enqueue_registered_job", lambda *args, **kwargs: ({"job_id": "test-job"}, False))
    result = auth_client.post("/api/company-research/MU", json={"kinds": ["overview"]})
    assert result.status_code == 202
    run = company_research_store.get_run(result.json()["reports"]["overview"]["run_id"])
    assert run["snapshot"]["private_documents"] == docs.research_snapshot("MU")
    assert "An unrelated secret" not in json.dumps(run)


def test_complete_research_workflow_retains_upload_fact_and_private_attribution(monkeypatch, tmp_path):
    from api import company_research as legacy
    from api import company_research_workflow as workflow
    from api.company_research_evidence import EvidenceDecisions
    from tests.test_company_research_workflow import FakeProvider, create_run, source

    document = docs.upload("EL", FACT.encode(), "survey.txt")

    class UploadProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is ContextEvidence:
                assert kwargs["private"] and not kwargs.get("web")
                assert FACT in kwargs["prompt"]
                result = ContextEvidence(facts=private_packet(document).facts, commitments=[], gaps=[])
            elif model is WrittenSections:
                titles = json.loads(
                    kwargs["prompt"].split("preserving exact titles and order: ")[1].split(". Use the supplied")[0]
                )
                records = json.loads(kwargs["prompt"].split("\nEvidence:\n")[1].split("\nGaps:\n")[0])["records"]
                result = WrittenSections(
                    sections=[
                        Section(
                            title=title,
                            markdown=f"{FACT} [Private upload: survey.txt]({document['url']})",
                            evidence_ids=[record["record_id"] for record in records],
                        )
                        for title in titles
                    ]
                )
            elif model is workflow.SheetSummary:
                result = workflow.SheetSummary(
                    markdown=f"# EL\n\n## Financials\n\n{FACT} [Private upload: survey.txt]({document['url']})\n\n## Sensitivity to Extrinsic Factors\n\nInsufficient evidence.\n\n## Industry\n\nPrivate survey."
                )
            else:
                if kwargs.get("web"):
                    assert FACT not in kwargs["prompt"] and document["url"] not in kwargs["prompt"]
                return super().request(step, model, **kwargs)
            if kwargs.get("validate"):
                kwargs["validate"](result)
            return result

    monkeypatch.setattr(legacy, "LOCAL_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(workflow, "ResearchProvider", UploadProvider)
    state = create_run(apply=True)
    company_research_store.mutate_run(
        state["run_id"],
        lambda s: (
            s["snapshot"].update(kinds=["overview"], private_documents=docs.research_snapshot("EL")),
            s["reports"].pop("management_quality"),
        ),
    )
    saves = []
    monkeypatch.setattr(
        legacy,
        "stage_api_action",
        lambda action, payload, **kwargs: saves.append(payload) or {"application_status": "applied"},
    )
    completed = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="upload-test"
    )
    assert completed["status"] == "done"
    report = legacy.read_research_report("EL", "overview", state["run_id"])
    assert FACT in report["content"] and document["url"] in report["content"]
    assert report["sources"][0]["source_kind"] == "private_upload"
    assert FACT in saves[0]["content"] and document["url"] in saves[0]["content"]
