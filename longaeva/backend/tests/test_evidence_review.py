"""LON-35 browser read contracts and review-to-rule integration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from longaeva_app.db.models import DocumentText, Observation, ParameterSet, ParameterUpdate, Source

CUTOFF = "2024-07-23T20:05:38Z"


def seed_evidence(session: Session) -> list[Observation]:
    """Controlled synthetic evidence; never included in the production demo loader."""
    published = datetime(2024, 5, 2, 20, tzinfo=UTC)
    result: list[Observation] = []
    for late in (False, True):
        source = Source(
            provider="test",
            company="booking",
            doc_type="test release",
            url="https://example.test/evidence",
            publication_ts=published + timedelta(days=100 if late else 0),
            retrieval_ts=published + timedelta(days=101),
            content_hash=uuid4().hex,
            original_path="test/evidence",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 3, 31),
        )
        session.add(source)
        session.flush()
        text = (
            "Travel 😀: Room nights grew 9 percent. Cross-border travel remained resilient. <script>unsafe()</script>"
        )
        passage = DocumentText(source_id=source.id, page=1, char_start=100, char_end=100 + len(text), text=text)
        session.add(passage)
        session.flush()
        for kind in ("measured", "qualitative"):
            quote = "Room nights grew 9 percent." if kind == "measured" else "Cross-border travel remained resilient."
            start = 100 + text.index(quote)
            row = Observation(
                company="booking",
                source_id=source.id,
                document_text_id=passage.id,
                span_page=1,
                span_char_start=start,
                span_char_end=start + len(quote),
                statement_type=kind,
                activity_type="room_nights",
                geography="global",
                period_start=date(2024, 1, 1),
                period_end=date(2024, 3, 31),
                value=9 if kind == "measured" else None,
                unit="percent",
                basis="units",
                source_family="booking",
                review_status="pending",
                created_at=published,
            )
            session.add(row)
            result.append(row)
    session.commit()
    return result


@pytest.mark.db
def test_source_filter_pagination_and_tied_timestamps(client: TestClient, db_session: Session) -> None:
    rows = seed_evidence(db_session)
    expected = sorted(str(row.id) for row in rows[:2])
    query = {"source_id": str(rows[0].source_id), "company": "booking", "review_status": "pending", "limit": 1}
    first = client.get("/observations", params=query).json()
    second = client.get("/observations", params={**query, "offset": 1}).json()
    assert [first[0]["id"], second[0]["id"]] == expected
    assert client.get("/observations", params={**query, "offset": 2}).json() == []
    assert client.get("/observations", params={"offset": -1}).status_code == 422
    assert client.get("/observations", params={"source_id": "invalid"}).status_code == 422


@pytest.mark.db
def test_unicode_evidence_and_publication_cutoff(client: TestClient, db_session: Session) -> None:
    rows = seed_evidence(db_session)
    response = client.get(f"/observations/{rows[0].id}/evidence", params={"cutoff_ts": CUTOFF})
    assert response.status_code == 200
    excerpt = response.json()
    assert excerpt["quote"] == "Room nights grew 9 percent."
    assert excerpt["before"] == "Travel 😀: "
    assert excerpt["char_start"] == 110  # Python code points, not JavaScript UTF-16 units.
    assert excerpt["page"] == 1
    late = client.get(f"/observations/{rows[2].id}/evidence", params={"cutoff_ts": CUTOFF}).json()
    assert "after this cutoff" in late["unavailable_reason"]
    assert late["quote"] == ""
    search = client.get(
        "/search/passages", params={"q": "cross-border", "company": "booking", "cutoff_ts": CUTOFF}
    ).json()
    assert len(search["hits"]) == 1
    assert search["hits"][0]["source_id"] == str(rows[0].source_id)
    assert client.get(f"/observations/{uuid4()}/evidence", params={"cutoff_ts": CUTOFF}).status_code == 404
    assert client.get(f"/observations/{rows[0].id}/evidence", params={"cutoff_ts": "2024-07-23"}).status_code == 422


@pytest.mark.db
@pytest.mark.parametrize("invalid", ["missing_passage", "foreign_passage", "page", "span", "missing_source"])
def test_invalid_evidence_is_explicit(client: TestClient, db_session: Session, invalid: str) -> None:
    rows = seed_evidence(db_session)
    row = rows[0]
    if invalid == "missing_passage":
        row.document_text_id = None
    elif invalid == "foreign_passage":
        row.document_text_id = rows[2].document_text_id
    elif invalid == "page":
        row.span_page = 2
    elif invalid == "span":
        row.span_char_end = 10000
    else:
        row.statement_type = "analyst_assumption"
        row.source_id = None
    db_session.commit()
    data = client.get(f"/observations/{row.id}/evidence", params={"cutoff_ts": CUTOFF}).json()
    assert data["unavailable_reason"] and not data["quote"]


@pytest.mark.db
def test_review_preview_apply_reload_and_context(client: TestClient, db_session: Session) -> None:
    rows = seed_evidence(db_session)
    base = client.post("/workspace/origins/2024-07-23/prepare").json()
    id_ = str(rows[0].id)
    body = {"observation_ids": [id_], "decided_by": "test reviewer", "rationale": "Source checked."}
    url = f"/parameter-sets/{base['id']}"
    assert client.post(f"{url}/rule-preview", json=body).status_code == 422
    for decision, correction in [("accept", None), ("correct", {"value": 10}), ("reject", None), ("accept", None)]:
        request = {
            "observation_id": id_,
            "decision": decision,
            "decided_by": "test reviewer",
            "rationale": "Source checked.",
        }
        if correction:
            request["corrected_payload"] = correction  # type: ignore[assignment]
        assert client.post("/review-decisions", json=request).status_code == 201
        if decision == "reject":
            assert client.post(f"{url}/apply-rules", json=body).status_code == 422
    reviewed = client.get(f"/observations/{id_}/review").json()
    assert [entry["version"] for entry in reviewed["decisions"]] == [1, 2, 3, 4]
    assert reviewed["observation"]["value"] == 9
    assert reviewed["effective"]["value"] == 10
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ParameterSet)) == 1
    assert db_session.scalar(select(func.count()).select_from(ParameterUpdate)) == 0
    preview = client.post(f"{url}/rule-preview", json=body)
    assert preview.status_code == 200 and preview.json()["changed"]
    assert db_session.scalar(select(func.count()).select_from(ParameterSet)) == 1
    assert db_session.scalar(select(func.count()).select_from(ParameterUpdate)) == 0
    applied = client.post(f"{url}/apply-rules", json=body)
    assert applied.status_code == 201
    child_id = applied.json()["result_parameter_set_id"]
    assert child_id != base["id"]
    assert client.get(url).json()["values"] == base["values"]
    assert client.get(f"/parameter-sets/{child_id}/updates").json()[0]["observation_ids"] == [id_]
    assert [item["id"] for item in client.get(f"/parameter-sets/{child_id}/lineage").json()] == [base["id"], child_id]
    assert client.post(f"{url}/apply-rules", json=body).json()["result_parameter_set_id"] == child_id
    context_id = str(rows[1].id)
    assert (
        client.post(
            "/review-decisions",
            json={"observation_id": context_id, "decision": "accept", "decided_by": "test", "rationale": "Context."},
        ).status_code
        == 201
    )
    context = client.post(f"{url}/apply-rules", json={**body, "observation_ids": [context_id]}).json()
    assert not context["changed"] and not context["updates"]
    assert client.get(f"{url}/context").json()[0]["observation_id"] == context_id
    db_session.expire_all()
    assert db_session.get(ParameterSet, UUID(base["id"])).values == base["values"]  # type: ignore[union-attr]
