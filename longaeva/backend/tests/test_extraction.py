"""Passage extraction, cache, and span checks against Booking Q3 2025."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from longaeva_app.collect.booking_sources import source_text
from longaeva_app.collect.text import extract_html_passages
from longaeva_app.config import Settings
from longaeva_app.db.models import DocumentText, ExtractionCall, Observation, ParameterSet, ParameterUpdate, Source
from longaeva_app.extract.llm import ExtractionError, load_passages, run_extraction
from longaeva_app.extract.providers import StubProvider
from longaeva_app.storage.local import LocalArtifactStore

ACCESSION = "0001075531-25-000050"
PUBLICATION = datetime(1999, 1, 2, tzinfo=UTC)
DECOY = "DECOY-PASSAGE-NOT-SELECTED"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_provider": "stub",
        "llm_model": "",
        "llm_base_url": "",
        "anthropic_api_key": SecretStr(""),
        "openai_api_key": SecretStr(""),
        "gemini_api_key": SecretStr(""),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _source(session: Session, *, content_hash: str, text_period: bool = False) -> Source:
    row = Source(
        provider="sec",
        company="booking",
        doc_type="8-K Ex. 99.1",
        url="https://www.sec.gov/Archives/edgar/data/1075531/example.htm",
        publication_ts=PUBLICATION,
        retrieval_ts=PUBLICATION + timedelta(days=1),
        period_start=date(2025, 7, 1) if text_period else None,
        period_end=date(2025, 9, 30) if text_period else None,
        content_hash=content_hash,
        original_path=f"fixtures/booking/{content_hash}",
        attributes={},
    )
    session.add(row)
    session.flush()
    return row


def _passage(session: Session, source: Source, *, page: int, char_start: int, text: str) -> DocumentText:
    row = DocumentText(
        source_id=source.id,
        page=page,
        char_start=char_start,
        char_end=char_start + len(text),
        text=text,
    )
    session.add(row)
    session.flush()
    return row


def _booking_room_nights() -> tuple[int, int, str, str]:
    html = source_text(ACCESSION, "q3-25bkngearningsrelease.htm")
    passages = extract_html_passages(html.encode("utf-8"))
    target = next(item for item in passages if "Room nights grew" in item.text)
    start = target.text.find("Room nights grew")
    window = target.text[start : start + 80]
    match = re.search(r"8\s*%", window)
    assert match is not None, window
    quote = window[: match.end()]
    return target.page, target.char_start, target.text, quote


def _payload(quote: str, *, value: float = 8.0) -> str:
    return json.dumps(
        {
            "observations": [
                {
                    "statement_type": "measured",
                    "activity_type": "room_nights",
                    "geography": "global",
                    "period_start": "2025-07-01",
                    "period_end": "2025-09-30",
                    "value": value,
                    "range_low": None,
                    "range_high": None,
                    "unit": "percent",
                    "basis": "units",
                    "quote": quote,
                }
            ]
        }
    )


@pytest.mark.db
def test_booking_passage_extracts_a_pending_observation_and_caches(
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    page, char_start, text, quote = _booking_room_nights()
    source = _source(db_session, content_hash=uuid4().hex, text_period=True)
    passage = _passage(db_session, source, page=page, char_start=char_start, text=text)
    decoy = _passage(db_session, source, page=2, char_start=0, text=DECOY + " " + "x" * 40)
    before_sets = db_session.scalar(select(func.count()).select_from(ParameterSet))
    before_updates = db_session.scalar(select(func.count()).select_from(ParameterUpdate))

    stub = StubProvider(responses=[_payload(quote)])
    report = run_extraction(
        db_session,
        [passage],
        provider=stub,
        settings=_settings(),
        store=artifact_store,
    )
    assert report.calls_made == 1
    assert report.cache_hits == 0
    assert report.observations_created == 1
    assert report.report_path is not None
    body = json.loads(artifact_store.read_bytes(report.report_path))
    assert body["observations_created"] == 1
    assert body["cache_hit_rate"] == 0.0

    system, user = stub.seen[0]
    assert text in user
    assert decoy.text not in user
    assert decoy.text not in system
    assert "1999-01-02" not in user
    assert "1999-01-02" not in system
    assert "Reporting period: 2025-07-01 to 2025-09-30" in user

    observation = db_session.scalars(select(Observation)).one()
    assert observation.review_status == "pending"
    assert observation.extractor_id == "llm_extract"
    assert observation.statement_type == "measured"
    assert observation.activity_type == "room_nights"
    assert observation.value == 8.0
    assert observation.unit == "percent"
    assert observation.basis == "units"
    assert observation.period_start == date(2025, 7, 1)
    assert observation.period_end == date(2025, 9, 30)
    assert observation.span_page == page
    assert observation.span_char_start is not None
    assert observation.span_char_end is not None
    local_start = observation.span_char_start - passage.char_start
    local_end = observation.span_char_end - passage.char_start
    assert passage.text[local_start:local_end] == quote
    assert observation.attributes["number_not_in_quote"] is False
    assert "confidence" not in observation.attributes

    again = run_extraction(db_session, [passage], provider=stub, settings=_settings(), store=artifact_store)
    assert stub.calls == 1
    assert again.calls_made == 0
    assert again.cache_hits == 1
    assert again.observations_created == 0
    assert db_session.scalar(select(func.count()).select_from(Observation)) == 1
    assert db_session.scalar(select(func.count()).select_from(ParameterSet)) == before_sets
    assert db_session.scalar(select(func.count()).select_from(ParameterUpdate)) == before_updates


@pytest.mark.db
def test_invalid_json_and_missing_quote_are_recorded(db_session: Session) -> None:
    source = _source(db_session, content_hash=uuid4().hex)
    bad = _passage(db_session, source, page=1, char_start=0, text="Revenue grew 13% in the quarter.")
    missing = _passage(db_session, source, page=1, char_start=80, text="Gross bookings grew 14% year over year.")
    flagged = _passage(db_session, source, page=1, char_start=160, text="Room nights grew 8% compared with last year.")

    invalid = StubProvider(responses=['{"observations": [{"confidence": 0.9}]}'])
    invalid_report = run_extraction(db_session, [bad], provider=invalid, settings=_settings())
    assert invalid_report.calls_made == 1
    assert invalid_report.failures["invalid_response"] == 1
    assert invalid_report.observations_created == 0
    invalid_row = db_session.scalars(select(ExtractionCall).where(ExtractionCall.document_text_id == bad.id)).one()
    assert invalid_row.status == "invalid_response"
    assert invalid_row.parsed is None
    assert invalid_row.response_text is not None
    assert "confidence" in invalid_row.response_text

    absent = StubProvider(responses=[_payload("this quote is not in the passage")])
    absent_report = run_extraction(db_session, [missing], provider=absent, settings=_settings())
    assert absent_report.failures["quote_not_found"] == 1
    assert absent_report.observations_created == 0
    absent_row = db_session.scalars(select(ExtractionCall).where(ExtractionCall.document_text_id == missing.id)).one()
    assert absent_row.status == "succeeded"
    assert absent_row.item_errors[0]["code"] == "quote_not_found"

    flagged_quote = "Room nights grew"
    flagged_report = run_extraction(
        db_session,
        [flagged],
        provider=StubProvider(responses=[_payload(flagged_quote, value=99.0)]),
        settings=_settings(),
    )
    assert flagged_report.observations_created == 1
    observation = db_session.scalars(select(Observation)).one()
    assert observation.attributes["number_not_in_quote"] is True
    assert observation.value == 99.0


@pytest.mark.db
def test_limits_reject_before_a_provider_call(db_session: Session) -> None:
    source = _source(db_session, content_hash=uuid4().hex)
    passage = _passage(db_session, source, page=1, char_start=0, text="Room nights grew 8% in the quarter.")
    stub = StubProvider()
    with pytest.raises(ExtractionError, match="At most 1"):
        load_passages(db_session, [passage.id, uuid4()], settings=_settings(extraction_max_passages=1))
    with pytest.raises(ExtractionError, match="characters"):
        load_passages(db_session, [passage.id], settings=_settings(extraction_max_passage_chars=10))
    with pytest.raises(ExtractionError, match="Unknown passages"):
        load_passages(db_session, [uuid4()], settings=_settings())
    assert stub.calls == 0
