"""Research lifecycle and fidelity gates, with real PDF parsing and ontology schemas."""

import copy
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from api import research, retrieval
from api import research_processing as processing
from api import research_store as store
from api.exceptions import NotFoundError, ValidationError
from ontology.object_service import OntologyObjectService
from tests.test_chat_attachments import make_pdf

TITLE = "Economic Outlook: November 2026"
FACT = "GDP is forecast to grow 2.3% in 2027, assuming oil remains at $75 per barrel."
ACTOR = {"actor_type": "user", "actor_id": "admin", "roles": ["admin"]}


class Repository:
    def __init__(self):
        self.rows = {}

    @contextmanager
    def _connect(self):
        yield None

    def get_object(self, key, **kwargs):
        return copy.deepcopy(self.rows.get(key))

    def query_objects(self, kind, filters=None, limit=100, offset=0, **kwargs):
        rows = [
            row
            for row in self.rows.values()
            if row["object_type"] == kind
            and all(row["properties_json"].get(k) == v for k, v in (filters or {}).items())
        ]
        return copy.deepcopy(rows[offset : offset + limit])

    def write_object_version(self, write):
        row = {
            "version_id": str(uuid4()),
            "object_uid": write.object_uid,
            "object_type": write.object_type,
            "business_key": write.business_key,
            "schema_name": write.schema_name,
            "schema_version": write.schema_version,
            "properties_json": copy.deepcopy(write.properties),
            "valid_from": write.valid_from,
            "valid_to": None,
            "tx_from": datetime.now(UTC),
            "tx_to": None,
            "temporal_confidence": "native",
        }
        self.rows[write.object_uid] = row
        return row


@pytest.fixture
def env(tmp_path, monkeypatch):
    service = OntologyObjectService(Repository())
    lock = threading.RLock()

    @contextmanager
    def locked(_):
        with lock:
            yield service

    monkeypatch.setattr(store, "locked", locked)
    monkeypatch.setattr(store, "OntologyObjectService", lambda: service)
    monkeypatch.setattr(store, "PROJECT_ROOT", tmp_path)
    import paths

    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    jobs = []

    def enqueue(kind, payload, **kwargs):
        job = {"job_id": uuid4().hex, "kind": kind, "payload": payload, "status": "queued"}
        jobs.append(job)
        return job, "created"

    monkeypatch.setattr(research, "enqueue_registered_job", enqueue)
    monkeypatch.setattr(research, "get_job", lambda key: next((j for j in jobs if j["job_id"] == key), None))
    index = {}

    def index_document(kind, content, **kwargs):
        index[kwargs["doc_id"]] = {"doc_type": kind, "content": content, **kwargs}

    monkeypatch.setattr(retrieval, "index_document", index_document)
    monkeypatch.setattr(retrieval, "delete_document", lambda key, **kwargs: index.pop(key, None))
    monkeypatch.setattr(
        retrieval,
        "search",
        lambda query, **kwargs: [v for v in index.values() if query.casefold() in v["content"].casefold()],
    )
    monkeypatch.setattr(processing, "selected_provider_for_tier", lambda _: "anthropic")
    monkeypatch.setattr(processing, "model_for_tier", lambda *a, **kw: "test-model")
    return SimpleNamespace(service=service, jobs=jobs, index=index)


def source_blocks():
    return [
        processing.Block(kind="heading", page=1, text="Growth outlook", level=2),
        processing.Block(kind="text", page=1, text=FACT),
        processing.Block(
            kind="visual",
            page=1,
            caption="Figure 1: Growth",
            text="2026: 2.0%; 2027 forecast: 2.3%. Source: Research Desk.",
        ),
        processing.Block(kind="heading", page=1, text="Risks & disclosures", level=3),
        processing.Block(kind="text", page=1, text="Forecasts depend on oil prices. Redistribution is restricted."),
    ]


def model(monkeypatch, *, category="economic", issues=None, missing_title=False, verify_issues=None, on_metadata=None):
    calls = []

    def ask(self, instruction, schema, pdf=None):
        calls.append(schema)
        if schema is processing.PageExtraction:
            return processing.PageExtraction(
                pages_read=[1], metadata_evidence=TITLE, blocks=source_blocks(), issues=issues or []
            )
        if schema is processing.Metadata:
            if on_metadata:
                on_metadata()
            return processing.Metadata(
                title=None if missing_title else TITLE,
                subtitle="The next year",
                institution="Research Desk",
                publication_date="November 2, 2026",
                authors=["A. Analyst", "B. Analyst"],
                category=category,
                category_uncertain=False,
            )
        if schema is processing.SectionOutput:
            if "Growth outlook" in instruction:
                return processing.SectionOutput(
                    paragraph=FACT,
                    visuals=[
                        "Figure 1: Growth. Growth rises from 2.0% in 2026 to a forecast 2.3% in 2027. Source: Research Desk."
                    ],
                )
            return processing.SectionOutput(
                paragraph="Forecasts depend on oil prices. Redistribution is restricted.", visuals=[]
            )
        if schema is processing.Check:
            return processing.Check(pages_checked=[1], issues=verify_issues or [])
        raise AssertionError(schema)

    monkeypatch.setattr(processing.Converter, "ask", ask)
    return calls


def uploaded(category=None):
    result = research.upload(make_pdf(FACT), "wrong filename.pdf", category, ACTOR)
    return store.get(result["report"]["id"])


def process(state):
    return processing.run_research_job(
        processing.ResearchJobRequest(report_id=state["id"], token=state["token"], actor=ACTOR), job_id=state["job_id"]
    )


@pytest.mark.parametrize("category", list(store.CATEGORIES))
def test_complete_pdf_preserves_structure_numbers_metadata_and_indexes(env, monkeypatch, category):
    calls = model(monkeypatch, category=category)
    state = uploaded()
    assert process(state)["status"] == "ready"
    done = research.detail(state["id"])
    assert done["category"] == category
    assert done["title"] == TITLE and done["authors"] == ["A. Analyst", "B. Analyst"]
    content, filename = research.markdown_download(state["id"])
    assert filename == "Economic Outlook_ November 2026.md"
    text = content.decode()
    assert text.startswith("# " + TITLE)
    assert "wrong filename" not in text
    assert text.index("## Growth outlook") < text.index("Figure 1: Growth") < text.index("### Risks & disclosures")
    assert FACT in text and "Redistribution is restricted" in text
    assert processing.Check in calls
    job = next(j for j in env.jobs if j["kind"] == "research_index")
    research.run_index_job(processing.ResearchJobRequest(**job["payload"]))
    hits = research.search_research("2.3%")
    assert len(hits["results"]) == 2
    assert all(h["title"] == TITLE and h["citation_url"] for h in hits["results"])
    assert research.read_report(state["id"])["sections"][0]["heading"] == "Growth outlook"


def test_manual_category_wins_even_when_changed_during_processing(env, monkeypatch):
    state = uploaded("credit_strategy")
    model(monkeypatch, on_metadata=lambda: research.change_category(state["id"], "industry_thematic", ACTOR))
    process(state)
    done = store.get(state["id"])
    assert done["category"] == "industry_thematic" and done["category_source"] == "manual"


def test_duplicate_upload_is_idempotent_and_does_not_override_category(env):
    state = uploaded("credit_strategy")
    again = research.upload(make_pdf(FACT), "copy.pdf", "economic", ACTOR)
    assert again["duplicate"] and again["report"]["id"] == state["id"]
    assert again["report"]["category"] == "credit_strategy"
    assert len(env.jobs) == 1


def test_missing_title_uses_neutral_fallback_without_blocking(env, monkeypatch):
    model(monkeypatch, missing_title=True)
    state = uploaded()
    assert process(state)["status"] == "ready"
    assert research.detail(state["id"])["title"] == "Untitled research report"
    assert research.markdown_download(state["id"])[0]


def test_extraction_limitations_do_not_block_download_or_index(env, monkeypatch):
    model(monkeypatch, issues=["Page 1 chart has no exact numerical labels"])
    state = uploaded()
    assert process(state)["status"] == "ready"
    assert research.markdown_download(state["id"])[0]
    assert env.jobs[-1]["kind"] == "research_index"


@pytest.mark.parametrize("located", [True, False])
def test_unresolved_defects_retain_source_instead_of_blocking(env, monkeypatch, located):
    model(monkeypatch, verify_issues=["Page 1 " + ("section-1 " if located else "") + "incorrect forecast"])
    state = uploaded()
    assert process(state)["status"] == "ready"
    detail = research.detail(state["id"])
    assert detail["sections"][0]["source_retained"]
    assert "2.3%" in detail["sections"][0]["output"]["paragraph"]
    assert detail["sections"][0]["output"]["visuals"]


def test_empty_summary_retains_text_and_model_errors_fall_back(env, monkeypatch):
    section = processing.sections_from_blocks(source_blocks())[0]
    converter = SimpleNamespace(ask=lambda *args: processing.SectionOutput(paragraph="", visuals=[]))
    text_only = {**section, "blocks": [b for b in section["blocks"] if b["kind"] == "text"]}
    assert "2.3%" in processing.condense(converter, text_only).paragraph
    result = processing.best_effort_section(converter, section)
    assert result.paragraph and result.visuals and section["source_retained"]


def test_verifier_failure_preserves_report_and_never_claims_verified_pages(env, monkeypatch):
    model(monkeypatch)
    monkeypatch.setattr(processing, "verify", lambda *a: (_ for _ in ()).throw(ValueError("Bad model JSON")))
    state = uploaded()
    assert process(state)["status"] == "ready"
    assert all(s["source_retained"] for s in research.detail(state["id"])["sections"])
    validation = json.loads(store.read_blob(state["id"], state["token"] + "-validation.json"))
    assert validation["pages_checked"] is None and not validation["verification_complete"]


def test_previous_successful_revision_survives_failed_reprocessing(env, monkeypatch):
    model(monkeypatch)
    state = uploaded()
    process(state)
    old_bytes = research.markdown_download(state["id"])[0]
    research.retry(state["id"], ACTOR)
    monkeypatch.setattr(
        processing, "extract_batch", lambda *a: (_ for _ in ()).throw(RuntimeError("PDF reading unavailable"))
    )
    with pytest.raises(RuntimeError):
        process(store.get(state["id"]))
    assert store.get(state["id"])["status"] == "failed"
    assert research.markdown_download(state["id"])[0] == old_bytes
    assert research.detail(state["id"])["title"] == TITLE


def test_delete_storage_failure_cannot_restore_report_and_cleanup_can_retry(env, monkeypatch):
    model(monkeypatch)
    state = uploaded()
    process(state)
    research.run_index_job(processing.ResearchJobRequest(**env.jobs[-1]["payload"]))
    original_delete = store.storage.delete_file

    def fail(*args):
        raise OSError("Storage unavailable")

    monkeypatch.setattr(store.storage, "delete_file", fail)
    with pytest.raises(OSError):
        research.delete(state["id"], ACTOR)
    with pytest.raises(NotFoundError):
        store.get(state["id"])
    assert not env.index
    monkeypatch.setattr(store.storage, "delete_file", original_delete)
    research.delete(state["id"], ACTOR)
    assert not list(store.PROJECT_ROOT.rglob("*.pdf"))


def test_delete_removes_search_and_files_and_fences_late_worker(env, monkeypatch):
    model(monkeypatch)
    state = uploaded()
    process(state)
    research.run_index_job(processing.ResearchJobRequest(**env.jobs[-1]["payload"]))
    research.delete(state["id"], ACTOR)
    assert not research.search_research("2.3%")["results"]
    with pytest.raises(NotFoundError):
        research.detail(state["id"])
    with pytest.raises(store.SupersededResearch):
        store.save_artifact(state["id"], state["token"], "late.md", b"late", "text/markdown")
    assert process(state)["status"] == "superseded"
    assert not list(store.PROJECT_ROOT.rglob("*.pdf"))


def test_interrupted_job_can_retry_and_old_attempt_cannot_publish(env):
    state = uploaded()
    env.jobs[0]["status"] = "failed"
    report = research.detail(state["id"])
    assert report["status"] == "failed"
    research.retry(state["id"], ACTOR)
    assert store.get(state["id"])["token"] != state["token"]
    with pytest.raises(store.SupersededResearch):
        store.mutate(state["id"], lambda s: s.update(status="ready"), token=state["token"])


def test_index_failure_is_separate_from_conversion_and_retryable(env, monkeypatch):
    model(monkeypatch)
    state = uploaded()
    process(state)
    monkeypatch.setattr(retrieval, "index_document", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        research.run_index_job(processing.ResearchJobRequest(**env.jobs[-1]["payload"]))
    assert store.get(state["id"])["status"] == "ready"
    assert store.get(state["id"])["index_status"] == "failed"
    assert research.markdown_download(state["id"])[0]


def test_auth_upload_download_and_category_validation(env, auth_client, monkeypatch):
    invalid = auth_client.post("/api/research/reports", files={"file": ("bad.pdf", b"not pdf")})
    assert invalid.status_code == 422
    response = auth_client.post(
        "/api/research/reports",
        files={"file": ("upload.pdf", make_pdf(FACT), "application/pdf")},
        data={"category": "credit_strategy"},
    )
    assert response.status_code == 202, response.text
    state = store.get(response.json()["report"]["id"])
    model(monkeypatch)
    process(state)
    url = f"/api/research/reports/{state['id']}"
    assert auth_client.get(url + "/original").content == make_pdf(FACT)
    download = auth_client.get(url + "/markdown")
    assert download.status_code == 200 and download.headers["content-type"].startswith("text/markdown")
    assert "attachment" in download.headers["content-disposition"] and ".md" in download.headers["content-disposition"]
    assert auth_client.patch(url, json={"category": "invalid"}).status_code == 422
    assert auth_client.get("/api/research/reports?category=credit_strategy").json()["total"] == 1


def test_viewer_cannot_mutate_research(env, auth_client):
    from api.main import app
    from api.routers.auth import require_actor
    from ontology.policy import Actor

    state = uploaded()
    app.dependency_overrides[require_actor] = lambda: Actor(actor_type="user", actor_id="reader", roles=("viewer",))
    try:
        assert auth_client.get("/api/research/reports").json()["can_manage"] is False
        path = f"/api/research/reports/{state['id']}"
        assert auth_client.delete(path).status_code == 403
        assert auth_client.patch(path, json={"category": "economic"}).status_code == 403
        assert auth_client.post(path + "/retry").status_code == 403
    finally:
        app.dependency_overrides.pop(require_actor, None)


def test_research_responses_do_not_cache_missing_or_reuploaded_documents(env, auth_client):
    import hashlib

    data = make_pdf(FACT)
    path = "/api/research/reports/" + hashlib.sha256(data).hexdigest()
    missing = auth_client.get(path)
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "private, no-store"
    state = uploaded()
    assert auth_client.get(path).status_code == 200
    research.delete(state["id"], ACTOR)
    assert auth_client.get(path).status_code == 404
    uploaded()
    restored = auth_client.get(path)
    assert restored.status_code == 200
    assert restored.headers["cache-control"] == "private, no-store"


def test_deterministic_visual_and_markdown_checks():
    assert (
        processing.clean_markdown("```markdown\n## Outlook\nGrowth is **2.3%**.\n```") == "Outlook\nGrowth is **2.3%**."
    )
    assert processing.clean_markdown("<p>Growth <b>2.3%</b></p><script>alert(1)</script>") == "Growth  2.3%"
    assert processing.clean_markdown("![Chart: growth rises](chart.png)") == "Chart: growth rises"
    assert processing.clean_markdown("Inflation < 3% and growth > 2%") == "Inflation < 3% and growth > 2%"


def test_truncated_provider_json_is_rejected(monkeypatch):
    monkeypatch.setattr(
        processing,
        "call_llm_text",
        lambda **kwargs: (json.dumps({"pages_checked": [1], "issues": []}), [], {"status": "incomplete"}),
    )
    with pytest.raises(ValueError, match="truncated"):
        processing.Converter("openai", "test").ask("Check", processing.Check)


def test_unauthenticated_research_is_private(env, client):
    assert client.get("/api/research/reports").status_code == 401


def test_explicit_page_images_and_page_coverage_retry():
    import io

    import pypdfium2 as pdfium

    with pdfium.PdfDocument(make_pdf(FACT)) as single, pdfium.PdfDocument.new() as combined:
        combined.import_pages(single)
        combined.import_pages(single)
        buffer = io.BytesIO()
        combined.save(buffer)
    data = buffer.getvalue()
    images = processing.render_page_images(data)
    assert len(images) == 2 and all(image.startswith(b"\xff\xd8") for image in images)
    responses = iter([[1], [1], [2]])
    converter = SimpleNamespace(ask=lambda *args: processing.Check(pages_checked=next(responses), issues=[]))
    metadata = processing.Metadata(
        title=TITLE,
        subtitle=None,
        institution=None,
        publication_date=None,
        authors=[],
        category="economic",
        category_uncertain=False,
    )
    assert processing.verify(converter, data, 2, metadata, [], lambda *args: None) == []


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_pdf_provider_receives_explicit_images(monkeypatch, provider):
    import llm_utils

    captured = {}

    def call(**kwargs):
        captured.update(kwargs)
        return {}

    for name in ("_call_openai_response", "_call_anthropic_messages", "_call_gemini_generate_content"):
        monkeypatch.setattr(llm_utils, name, call)
    monkeypatch.setattr(llm_utils, "extract_text", lambda response: "{}")
    monkeypatch.setattr(llm_utils, "extract_citations", lambda response: [])
    llm_utils.call_llm_pdf_text(
        pdf_bytes=b"%PDF-test",
        prompt="Inspect pages",
        model="test-model",
        provider=provider,
        page_images=[b"jpeg-page"],
    )
    encoded = "anBlZy1wYWdl"
    payload = json.dumps(captured)
    assert encoded in payload and "image/jpeg" in payload
    assert "Inspect pages" in payload
