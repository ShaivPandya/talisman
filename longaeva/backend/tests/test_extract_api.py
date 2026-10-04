"""Extraction API and internal extract job (LON-16 / UF-07 / NR-02)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.config import get_settings
from longaeva_app.db.models import DocumentText, Source
from longaeva_app.extract.providers import StubProvider
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.worker.queue import claim_next_job, execute_job

PASSAGE = "Room nights grew 8% in the quarter."
QUOTE = "Room nights grew 8%"


def _clear_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()


def _source_and_passage(session: Session) -> DocumentText:
    published = datetime(2025, 10, 28, tzinfo=UTC)
    source = Source(
        provider="sec",
        company="booking",
        doc_type="8-K Ex. 99.1",
        url="https://www.sec.gov/Archives/edgar/data/1075531/example.htm",
        publication_ts=published,
        retrieval_ts=published + timedelta(hours=1),
        content_hash=uuid4().hex,
        original_path="fixtures/booking/api",
        attributes={},
    )
    session.add(source)
    session.flush()
    passage = DocumentText(
        source_id=source.id,
        page=1,
        char_start=10,
        char_end=10 + len(PASSAGE),
        text=PASSAGE,
    )
    session.add(passage)
    session.flush()
    return passage


@pytest.mark.db
def test_extraction_is_disabled_until_a_provider_is_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm(monkeypatch)
    status = client.get("/observations/extraction-status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["enabled"] is False
    assert body["disabled_reason"]
    assert "unset" in body["disabled_reason"].lower()

    refused = client.post("/observations/extract", json={"document_text_ids": [str(uuid4())]})
    assert refused.status_code == 503, refused.text

    missing_key = client.post(
        "/observations/extract",
        json={"document_text_ids": [str(uuid4())], "provider": "anthropic"},
    )
    assert missing_key.status_code == 422, missing_key.text
    assert "API key" in missing_key.json()["detail"]

    unknown_job = client.post("/jobs", json={"type": "extract", "payload": {}})
    assert unknown_job.status_code == 400, unknown_job.text


@pytest.mark.db
def test_extract_job_runs_the_stub_and_records_counts(
    client: TestClient,
    db_session: Session,
    test_engine: Engine,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm(monkeypatch)
    passage = _source_and_passage(db_session)
    db_session.commit()
    stub = StubProvider(
        responses=[
            json.dumps(
                {
                    "observations": [
                        {
                            "statement_type": "measured",
                            "activity_type": "room_nights",
                            "geography": "global",
                            "period_start": "2025-07-01",
                            "period_end": "2025-09-30",
                            "value": 8.0,
                            "range_low": None,
                            "range_high": None,
                            "unit": "percent",
                            "basis": "units",
                            "quote": QUOTE,
                        }
                    ]
                }
            )
        ]
    )

    def _injected(*_args: object, **_kwargs: object) -> StubProvider:
        return stub

    monkeypatch.setattr("longaeva_app.worker.handlers.extract.build_provider", _injected)

    created = client.post(
        "/observations/extract",
        json={"document_text_ids": [str(passage.id)], "provider": "stub"},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    claimed = claim_next_job(factory, "test-worker")
    assert claimed is not None
    assert str(claimed) == job_id
    execute_job(factory, claimed, "test-worker", artifact_store=artifact_store)

    fetched = client.get(f"/jobs/{job_id}")
    assert fetched.status_code == 200, fetched.text
    payload = fetched.json()
    assert payload["status"] == "succeeded"
    result = payload["result"]
    assert result["calls_made"] == 1
    assert result["cache_hits"] == 0
    assert result["observations_created"] == 1
    assert "cache_hit_rate" in result
    assert result["failures"]["provider_error"] == 0

    calls = client.get("/observations/extraction-calls", params={"status": "succeeded", "job_id": job_id})
    assert calls.status_code == 200, calls.text
    rows = calls.json()
    assert len(rows) == 1
    assert rows[0]["provider"] == "stub"
    assert rows[0]["parsed"]["observations"][0]["quote"] == QUOTE
    assert "confidence" not in rows[0]["parsed"]["observations"][0]

    monkeypatch.setenv("EXTRACTION_MAX_PASSAGES", "1")
    get_settings.cache_clear()
    limited = client.post(
        "/observations/extract",
        json={"document_text_ids": [str(passage.id), str(uuid4())], "provider": "stub"},
    )
    assert limited.status_code == 422, limited.text
    missing = client.post(
        "/observations/extract",
        json={"document_text_ids": [str(uuid4())], "provider": "stub"},
    )
    assert missing.status_code == 404, missing.text
