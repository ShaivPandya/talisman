"""Browser-ready origins and span-resolved evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from longaeva_app.api.main import app
from longaeva_app.api.workspace_schemas import EvidenceExcerpt
from longaeva_app.companies.visa.calibration import artifact_path
from longaeva_app.db.models import DocumentText, Observation, ParameterSet, Scenario, Source
from longaeva_app.evaluation.harness import load_calibration_artifact
from longaeva_app.workspace import _fill_excerpt, workspace_state


@pytest.mark.parametrize("origin", ["2024-07-23", "2025-10-28"])
def test_state_sources_are_resolved_and_as_of(origin: str) -> None:
    state = workspace_state(origin)
    assert len(state.values) == 33
    assert len(state.parameter_specs) == 32
    assert sum(spec.role == "free" for spec in state.parameter_specs) == 8
    for key, value in state.values.items():
        if value.status == "unavailable_at_cutoff":
            assert value.value is None and value.unavailable_reason
        else:
            excerpt = state.evidence[key]
            assert excerpt.quote and excerpt.unavailable_reason is None
            assert excerpt.source_id in state.sources
            assert excerpt.publication_ts is not None and excerpt.publication_ts <= state.cutoff_ts
            assert excerpt.char_start is not None and excerpt.char_end is not None
            assert excerpt.content_hash == state.sources[excerpt.source_id].content_sha256
    assert state.post_cutoff_sources
    assert all(source.acceptance_utc > state.cutoff_ts for source in state.post_cutoff_sources.values())


def test_read_routes_and_unknown_origin() -> None:
    with TestClient(app) as client:
        origins = client.get("/workspace/origins").json()
        assert [row["origin_date"] for row in origins] == ["2024-07-23", "2025-10-28"]
        assert client.get("/workspace/origins/2024-07-23").status_code == 200
        assert client.get("/workspace/origins/2026-07-28").status_code == 404


def test_span_offsets_are_applied_before_html_conversion() -> None:
    raw = "<p>Example 😀 growth: <b>12%</b> &amp; context</p>"
    start = raw.index("12%")
    result = _fill_excerpt(EvidenceExcerpt(), raw, start, start + 3, html=True, expected_quote="12%")
    assert result.quote == "12%"
    assert result.before == "Example 😀 growth:"
    assert result.after == "& context"
    assert "<" not in result.before + result.after
    assert _fill_excerpt(EvidenceExcerpt(), raw, start, start + 3, expected_quote="13%").unavailable_reason
    assert _fill_excerpt(EvidenceExcerpt(), raw, -1, 100).unavailable_reason


@pytest.mark.db
def test_prepare_is_idempotent_and_concurrent(client: TestClient, db_session: Session) -> None:
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post("/workspace/origins/2024-07-23/prepare"), range(3)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert db_session.scalar(select(func.count()).select_from(ParameterSet)) == 1
    assert db_session.scalar(select(func.count()).select_from(Scenario)) == 1
    assert responses[0].json()["cutoff_ts"].startswith("2024-07-23T20:05:38")
    assert client.post("/workspace/origins/2025-10-28/prepare").status_code == 200
    assert db_session.scalar(select(func.count()).select_from(ParameterSet)) == 2


@pytest.mark.db
def test_prepare_rejects_wrong_cutoff(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    result = load_calibration_artifact(artifact_path("2024-07-23"))
    wrong = replace(result, cutoff_ts=datetime(2025, 1, 1, tzinfo=UTC))
    monkeypatch.setattr("longaeva_app.workspace.load_calibration_artifact", lambda _: wrong)
    assert client.post("/workspace/origins/2024-07-23/prepare").status_code == 409


@pytest.mark.db
def test_parameter_evidence_uses_bundle_and_reports_assumptions(client: TestClient) -> None:
    row = client.post("/workspace/origins/2024-07-23/prepare").json()
    response = client.get(f"/parameter-sets/{row['id']}/evidence", params={"parameter": "payments_volume_growth"})
    assert response.status_code == 200
    data = response.json()
    assert data["excerpts"]
    assert any(item["quote"] and not item["unavailable_reason"] for item in data["excerpts"])
    # Some inherited image-era calibration offsets do not round-trip. Never invent a highlight.
    assert all(item["quote"] or item["unavailable_reason"] for item in data["excerpts"])
    mismatch = next(item for item in data["excerpts"] if item["unavailable_reason"])
    assert "does not match" in mismatch["unavailable_reason"]
    assert mismatch["url"] and not mismatch["quote"]
    assumption = client.get(
        f"/parameter-sets/{row['id']}/evidence", params={"parameter": "cross_border_share_at_origin"}
    ).json()
    assert assumption["evidence"]["assumption"] and assumption["evidence"]["rationale"]
    assert client.get(f"/parameter-sets/{row['id']}/evidence", params={"parameter": "unknown"}).status_code == 404


@pytest.mark.db
def test_database_evidence_wins_and_invalid_references_are_explicit(client: TestClient, db_session: Session) -> None:
    prepared = client.post("/workspace/origins/2024-07-23/prepare").json()
    parameter_set = db_session.get(ParameterSet, UUID(prepared["id"]))
    assert parameter_set is not None
    parameter = "payments_volume_growth"
    # Reuse a bundled ID to verify the database takes precedence.
    obs_id = UUID(parameter_set.evidence_links[parameter]["observation_ids"][0])
    published = datetime(2024, 5, 1, tzinfo=UTC)
    source = Source(
        provider="test",
        company="visa",
        doc_type="release",
        url="https://example.com/release",
        publication_ts=published,
        retrieval_ts=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash=uuid4().hex,
        original_path="test/release",
        attributes={},
    )
    db_session.add(source)
    db_session.flush()
    passage = DocumentText(source_id=source.id, page=1, char_start=100, char_end=119, text="Revenue grew by 12%.")
    db_session.add(passage)
    db_session.flush()
    obs = Observation(
        id=obs_id,
        company="visa",
        source_id=source.id,
        document_text_id=passage.id,
        span_page=1,
        span_char_start=116,
        span_char_end=118,
        statement_type="measured",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value=12,
        unit="percent",
        review_status="accepted",
        attributes={},
    )
    db_session.add(obs)
    missing_id = str(uuid4())
    parameter_set.evidence_links = {
        **parameter_set.evidence_links,
        parameter: {"observation_ids": [str(obs_id), missing_id], "assumption": False},
    }
    db_session.commit()
    url = f"/parameter-sets/{parameter_set.id}/evidence?parameter={parameter}"
    excerpts = client.get(url).json()["excerpts"]
    assert excerpts[0]["source_id"] == str(source.id)
    assert excerpts[0]["quote"] == "12"
    assert excerpts[1]["unavailable_reason"]
    source.publication_ts = datetime(2025, 1, 1, tzinfo=UTC)
    db_session.commit()
    assert "after this cutoff" in client.get(url).json()["excerpts"][0]["unavailable_reason"]
