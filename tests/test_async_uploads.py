"""Upload processing must leave the request event loop available to other requests."""

from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar
from importlib import import_module
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from api import document_generation_jobs as jobs
from api.exceptions import ValidationError
from api.routers.auth import require_actor
from ontology.policy import Actor

ACTOR = Actor(actor_id="upload-test", actor_type="user", roles=("admin",))
REQUEST_CONTEXT = ContextVar("upload_test_request", default="missing")
UPLOAD_CASES = [
    ("thesis", "/thesis/generate", "document.md", "text/markdown", 30 * 1024 * 1024),
    ("overview", "/overview/generate", "document.md", "text/markdown", 30 * 1024 * 1024),
    ("management_quality", "/management-quality/generate", "document.md", "text/markdown", 30 * 1024 * 1024),
    ("source_ingestion", "/source-ingestion/uploads", "source.md", "text/markdown", 30 * 1024 * 1024),
    ("portfolio_edit", "/portfolio-positions/import/ibkr-flex", "positions.xml", "application/xml", 1024),
    ("economic_growth", "/economic-growth/crb-file", "crb.xlsx", "application/vnd.ms-excel", 1024),
    ("portfolio_news", "/portfolio-news", "digest.md", "text/markdown", 10 * 1024 * 1024),
]


@pytest.mark.parametrize("module_name,path,filename,content_type,size", UPLOAD_CASES)
def test_upload_processing_allows_concurrent_request(monkeypatch, module_name, path, filename, content_type, size):
    router = import_module(f"api.routers.{module_name}")
    started = threading.Event()
    release = threading.Event()
    worker_calls = []
    loop_thread = threading.get_ident()

    def check_worker():
        worker_calls.append(threading.get_ident())
        assert threading.get_ident() != loop_thread
        assert REQUEST_CONTEXT.get() == "upload-request"

    def block(*_args, **_kwargs):
        started.set()
        check_worker()
        assert release.wait(5), "concurrent request did not finish while upload processing was blocked"

    if module_name in {"thesis", "overview", "management_quality"}:
        monkeypatch.setattr(jobs, "write_bytes", block)

        def enqueue(*_args, **_kwargs):
            check_worker()
            return {"job_id": "upload-job"}, "created"

        monkeypatch.setattr(jobs, "enqueue_registered_job", enqueue)
        monkeypatch.setattr(
            jobs, "enqueue_response", lambda *_args: JSONResponse({"status": "queued"}, status_code=202)
        )
    elif module_name == "source_ingestion":
        monkeypatch.setattr(router, "require_multimodal_ingestion_enabled", lambda: None)

        def upload(req):
            assert len(req.content) == size
            assert req.manifest_id == "test-manifest"
            assert req.actor["actor_id"] == ACTOR.actor_id
            block()
            return {"status": "ok"}

        def service():
            check_worker()  # Constructors can open database connections, too.
            return SimpleNamespace(upload_artifact=upload)

        monkeypatch.setattr(router, "SourceIngestionService", service)
    elif module_name == "portfolio_edit":

        def parse(payload):
            assert len(payload) == size
            block()
            return []

        def service():
            check_worker()
            return SimpleNamespace(positions=lambda **_kwargs: [])

        monkeypatch.setattr(router, "parse_ibkr_flex_open_positions_xml", parse)
        monkeypatch.setattr(router, "OntologyRuntimeReadService", service)
        monkeypatch.setattr(router, "stage_api_action", lambda *_args, **_kwargs: {"status": "ok"})
    elif module_name == "economic_growth":

        def metadata(payload, uploaded_filename):
            assert len(payload) == size
            assert uploaded_filename == filename
            block()
            return {"filename": uploaded_filename}

        monkeypatch.setattr(router, "_crb_metadata_from_upload", metadata)
        monkeypatch.setattr(router, "_write_managed_crb", lambda *_args: check_worker())
        monkeypatch.setattr(router, "delete_cached", lambda *_args: check_worker())
        monkeypatch.setattr(router, "delete_snapshot", lambda *_args: check_worker())
    else:
        monkeypatch.setattr(router, "stage_api_action", lambda *_args, **_kwargs: block() or {"status": "ok"})

    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[require_actor] = lambda: ACTOR

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            token = REQUEST_CONTEXT.set("upload-request")
            try:
                upload = asyncio.create_task(
                    client.post(
                        path,
                        data={"ticker": "AAPL", "manifest_id": "test-manifest"},
                        files={"file": (filename, b"x" * size, content_type)},
                    )
                )
                try:
                    assert await asyncio.to_thread(started.wait, 5)
                    assert not upload.done(), "upload processing blocked the event loop"
                    response = await asyncio.wait_for(client.get("/probe"), timeout=2)
                    assert response.json() == {"ok": True}
                    assert not upload.done()
                finally:
                    release.set()
                    result = await upload
                assert result.status_code == (
                    202 if module_name in {"thesis", "overview", "management_quality"} else 200
                )
                assert worker_calls
            finally:
                REQUEST_CONTEXT.reset(token)

    asyncio.run(run())


@pytest.mark.parametrize("failure_point", ["storage", "enqueue"])
def test_document_upload_failure_cleans_up_in_worker(monkeypatch, failure_point):
    loop_thread = threading.get_ident()
    calls = []
    failure = RuntimeError("upload processing failed")

    def record(stage):
        assert threading.get_ident() != loop_thread
        calls.append(stage)
        if stage == failure_point:
            raise failure

    monkeypatch.setattr(jobs, "write_bytes", lambda *_args, **_kwargs: record("storage"))
    monkeypatch.setattr(jobs, "enqueue_registered_job", lambda *_args, **_kwargs: record("enqueue"))
    monkeypatch.setattr(jobs, "delete_file", lambda *_args, **_kwargs: record("cleanup"))
    file = UploadFile(
        BytesIO(b"# document"), filename="document.md", headers=Headers({"content-type": "text/markdown"})
    )

    with pytest.raises(RuntimeError) as error:
        asyncio.run(jobs.enqueue_document_generation_upload(kind="thesis", ticker="AAPL", file=file))

    assert error.value is failure
    assert calls == (["storage", "cleanup"] if failure_point == "storage" else ["storage", "enqueue", "cleanup"])


@pytest.mark.parametrize("payload,filename", [(b"", "empty.md"), (b"not a PDF", "document.pdf")])
def test_invalid_document_upload_never_writes_or_enqueues(monkeypatch, payload, filename):
    def unexpected(*_args, **_kwargs):
        pytest.fail("invalid upload reached storage or job enqueue")

    monkeypatch.setattr(jobs, "write_bytes", unexpected)
    monkeypatch.setattr(jobs, "enqueue_registered_job", unexpected)
    file = UploadFile(BytesIO(payload), filename=filename)

    with pytest.raises(ValidationError):
        asyncio.run(jobs.enqueue_document_generation_upload(kind="thesis", ticker="AAPL", file=file))
