"""Full-text passage search."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from longaeva_app.db.models import DocumentText, Source

pytestmark = pytest.mark.db

CUTOFF = datetime(2024, 7, 23, tzinfo=UTC)
LATER = datetime(2026, 7, 28, 20, 5, tzinfo=UTC)


def _add_source(
    session: Session,
    *,
    company: str,
    publication_ts: datetime,
    passages: list[str],
    period_start: date | None = None,
    period_end: date | None = None,
    passage_ids: list[UUID] | None = None,
) -> tuple[Source, list[DocumentText]]:
    source = Source(
        provider="fixture",
        company=company,
        doc_type="earnings_release",
        url=f"https://example.test/{uuid4().hex}",
        publication_ts=publication_ts,
        retrieval_ts=publication_ts + timedelta(minutes=1),
        period_start=period_start,
        period_end=period_end,
        content_hash=f"search-{uuid4().hex}",
        original_path=f"originals/search/{uuid4().hex}",
    )
    session.add(source)
    session.flush()
    rows: list[DocumentText] = []
    for index, body in enumerate(passages):
        row = DocumentText(
            source_id=source.id,
            page=index + 1,
            char_start=0,
            char_end=len(body),
            text=body,
        )
        if passage_ids is not None:
            row.id = passage_ids[index]
        session.add(row)
        rows.append(row)
    session.flush()
    return source, rows


def _ids(body: dict[str, object]) -> set[str]:
    hits = body["hits"]
    assert isinstance(hits, list)
    return {str(hit["document_text_id"]) for hit in hits if isinstance(hit, dict)}


def test_cutoff_excludes_later_documents_and_includes_exact(client: TestClient, db_session: Session) -> None:
    _early, early_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 4, 30, 21, 0, tzinfo=UTC),
        passages=["Cross-border volume increased in the quarter."],
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
    )
    _exact, exact_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=CUTOFF,
        passages=["Cross-border volume held steady at the cutoff."],
        period_start=date(2024, 4, 1),
        period_end=date(2024, 6, 30),
    )
    _later, later_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=LATER,
        passages=["Cross-border volume reached a new high after the cutoff."],
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
    )
    _booking, booking_rows = _add_source(
        db_session,
        company="booking",
        publication_ts=datetime(2024, 5, 2, 20, 0, tzinfo=UTC),
        passages=["Cross-border travel bookings rose before the cutoff."],
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
    )
    db_session.commit()

    response = client.get(
        "/search/passages",
        params={"q": "cross-border", "company": "visa", "cutoff_ts": "2024-07-23T00:00:00Z"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "cross-border"
    assert body["company"] == "visa"
    assert datetime.fromisoformat(body["cutoff_ts"]) == CUTOFF
    found = _ids(body)
    assert str(early_rows[0].id) in found
    assert str(exact_rows[0].id) in found
    assert str(later_rows[0].id) not in found
    assert str(booking_rows[0].id) not in found
    assert all(hit["company"] == "visa" for hit in body["hits"])
    assert all("<b>" in hit["snippet"] for hit in body["hits"])


def test_naive_and_date_only_cutoffs_are_utc(client: TestClient, db_session: Session) -> None:
    evening = datetime(2024, 7, 23, 20, 8, 25, tzinfo=UTC)
    _before, before_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 7, 22, 23, 0, tzinfo=UTC),
        passages=["Cross-border volume was published the day before."],
    )
    _at_evening, evening_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=evening,
        passages=["Cross-border volume was published that evening."],
    )
    _after, after_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=evening + timedelta(seconds=1),
        passages=["Cross-border volume was published one second later."],
    )
    db_session.commit()

    naive = client.get("/search/passages", params={"q": "cross-border", "cutoff_ts": "2024-07-23T20:08:25"})
    assert naive.status_code == 200
    naive_body = naive.json()
    assert datetime.fromisoformat(naive_body["cutoff_ts"]) == evening
    naive_ids = _ids(naive_body)
    assert str(before_rows[0].id) in naive_ids
    assert str(evening_rows[0].id) in naive_ids
    assert str(after_rows[0].id) not in naive_ids

    date_only = client.get("/search/passages", params={"q": "cross-border", "cutoff_ts": "2024-07-23"})
    assert date_only.status_code == 200
    date_body = date_only.json()
    assert datetime.fromisoformat(date_body["cutoff_ts"]) == CUTOFF
    date_ids = _ids(date_body)
    assert str(before_rows[0].id) in date_ids
    assert str(evening_rows[0].id) not in date_ids


def test_company_filter_is_exact(client: TestClient, db_session: Session) -> None:
    _visa, visa_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 7, 1, tzinfo=UTC),
        passages=["Cross-border volume for Visa."],
    )
    _booking, booking_rows = _add_source(
        db_session,
        company="booking",
        publication_ts=datetime(2024, 7, 2, tzinfo=UTC),
        passages=["Cross-border volume for Booking."],
    )
    db_session.commit()

    visa = client.get("/search/passages", params={"q": "cross-border", "company": "visa"})
    assert visa.status_code == 200
    assert _ids(visa.json()) == {str(visa_rows[0].id)}

    blank_case = client.get("/search/passages", params={"q": "cross-border", "company": "Visa"})
    assert blank_case.status_code == 200
    assert blank_case.json()["hits"] == []
    assert blank_case.json()["company"] == "Visa"

    both = client.get("/search/passages", params={"q": "cross-border"})
    assert _ids(both.json()) == {str(visa_rows[0].id), str(booking_rows[0].id)}


def test_period_overlap_drops_undated_sources_only_when_filtered(client: TestClient, db_session: Session) -> None:
    _q3, q3_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 7, 23, 20, 0, tzinfo=UTC),
        passages=["Cross-border volume in the June quarter."],
        period_start=date(2024, 4, 1),
        period_end=date(2024, 6, 30),
    )
    _q4, q4_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 10, 20, 20, 0, tzinfo=UTC),
        passages=["Cross-border volume in the September quarter."],
        period_start=date(2024, 7, 1),
        period_end=date(2024, 9, 30),
    )
    _old, old_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2023, 4, 25, 20, 0, tzinfo=UTC),
        passages=["Cross-border volume in the March quarter."],
        period_start=date(2023, 1, 1),
        period_end=date(2023, 3, 31),
    )
    _undated, undated_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 8, 1, tzinfo=UTC),
        passages=["Cross-border volume with no period."],
    )
    db_session.commit()

    overlap = client.get(
        "/search/passages",
        params={"q": "cross-border", "period_start": "2024-07-01", "period_end": "2024-09-30"},
    )
    assert overlap.status_code == 200
    assert _ids(overlap.json()) == {str(q4_rows[0].id)}

    start_only = client.get("/search/passages", params={"q": "cross-border", "period_start": "2024-06-01"})
    assert _ids(start_only.json()) == {str(q3_rows[0].id), str(q4_rows[0].id)}

    unfiltered = client.get("/search/passages", params={"q": "cross-border"})
    assert _ids(unfiltered.json()) == {
        str(q3_rows[0].id),
        str(q4_rows[0].id),
        str(old_rows[0].id),
        str(undated_rows[0].id),
    }


def test_hit_span_matches_stored_passage(client: TestClient, db_session: Session) -> None:
    body_text = "International cross-border volume grew in the quarter."
    source, rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 7, 23, 20, 8, 25, tzinfo=UTC),
        passages=[body_text],
        period_start=date(2024, 4, 1),
        period_end=date(2024, 6, 30),
    )
    db_session.commit()

    response = client.get("/search/passages", params={"q": "cross-border", "company": "visa"})
    assert response.status_code == 200
    hits = response.json()["hits"]
    assert len(hits) == 1
    hit = hits[0]
    passages = client.get(f"/sources/{source.id}/passages")
    assert passages.status_code == 200
    stored = passages.json()
    assert len(stored) == 1
    assert stored[0]["id"] == hit["document_text_id"] == str(rows[0].id)
    assert stored[0]["page"] == hit["page"]
    assert stored[0]["char_start"] == hit["char_start"]
    assert stored[0]["char_end"] == hit["char_end"]
    assert stored[0]["text"] == hit["text"] == body_text
    assert hit["text"][hit["char_start"] : hit["char_end"]] == body_text


def test_rank_publication_and_id_ordering_and_limit(client: TestClient, db_session: Session) -> None:
    dense = "cross-border cross-border cross-border cross-border"
    sparse = "alpha beta gamma delta epsilon " + ("payments volume incentives expenses " * 20) + "cross-border"
    _ranked, ranked_rows = _add_source(
        db_session,
        company="rankco",
        publication_ts=datetime(2024, 7, 1, tzinfo=UTC),
        passages=[sparse, dense],
    )
    older, _older_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 1, 1, tzinfo=UTC),
        passages=["cross-border volume tie"],
    )
    newer, _newer_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 6, 1, tzinfo=UTC),
        passages=["cross-border volume tie"],
    )
    low_id = UUID("00000000-0000-4000-8000-000000000001")
    high_id = UUID("00000000-0000-4000-8000-000000000002")
    _tied, tied_rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2023, 6, 1, tzinfo=UTC),
        passages=["cross-border volume identical", "cross-border volume identical"],
        passage_ids=[high_id, low_id],
    )
    db_session.commit()

    ranked = client.get("/search/passages", params={"q": "cross-border", "company": "rankco", "limit": 2})
    assert ranked.status_code == 200
    rank_hits = ranked.json()["hits"]
    assert [hit["document_text_id"] for hit in rank_hits] == [str(ranked_rows[1].id), str(ranked_rows[0].id)]
    assert rank_hits[0]["rank"] > rank_hits[1]["rank"]

    by_time = client.get("/search/passages", params={"q": '"cross-border volume tie"'})
    assert [hit["source_id"] for hit in by_time.json()["hits"]] == [str(newer.id), str(older.id)]
    assert by_time.json()["hits"][0]["rank"] == by_time.json()["hits"][1]["rank"]

    by_id = client.get("/search/passages", params={"q": '"cross-border volume identical"'})
    assert [hit["document_text_id"] for hit in by_id.json()["hits"]] == [str(low_id), str(high_id)]
    assert tied_rows[1].id == low_id


def test_websearch_phrase_negation_and_stopwords(client: TestClient, db_session: Session) -> None:
    _sources, rows = _add_source(
        db_session,
        company="visa",
        publication_ts=datetime(2024, 7, 23, tzinfo=UTC),
        passages=[
            "Cross-border volume grew in the quarter.",
            "Cross-border incentives exceeded volume.",
            "Payments volume grew.",
            "Client incentives reduced volume.",
        ],
    )
    db_session.commit()

    phrase = client.get("/search/passages", params={"q": '"cross-border volume"'})
    assert phrase.status_code == 200
    assert _ids(phrase.json()) == {str(rows[0].id)}

    negated = client.get("/search/passages", params={"q": "volume -incentives"})
    assert negated.status_code == 200
    found = _ids(negated.json())
    assert str(rows[0].id) in found
    assert str(rows[2].id) in found
    assert str(rows[1].id) not in found
    assert str(rows[3].id) not in found

    stop = client.get("/search/passages", params={"q": "the"})
    assert stop.status_code == 200
    assert stop.json()["query"] == "the"
    assert stop.json()["hits"] == []


def test_invalid_queries_return_422(client: TestClient) -> None:
    missing = client.get("/search/passages")
    assert missing.status_code == 422

    blank = client.get("/search/passages", params={"q": "   "})
    assert blank.status_code == 422
    assert blank.json()["detail"] == "q must not be blank"

    company = client.get("/search/passages", params={"q": "volume", "company": "  "})
    assert company.status_code == 422
    assert company.json()["detail"] == "company must not be blank"

    period = client.get(
        "/search/passages",
        params={"q": "volume", "period_start": "2024-09-30", "period_end": "2024-07-01"},
    )
    assert period.status_code == 422
    assert period.json()["detail"] == "period_start must be on or before period_end"

    assert client.get("/search/passages", params={"q": "volume", "limit": 0}).status_code == 422
    assert client.get("/search/passages", params={"q": "volume", "limit": 101}).status_code == 422


def test_filtered_search_stays_under_500ms(client: TestClient, db_session: Session) -> None:
    published = datetime(2024, 7, 23, 20, 0, tzinfo=UTC)
    source, _rows = _add_source(
        db_session,
        company="visa",
        publication_ts=published,
        passages=["Seed anchor for the latency corpus."],
        period_start=date(2024, 4, 1),
        period_end=date(2024, 6, 30),
    )
    db_session.execute(
        text(
            """
            INSERT INTO document_text (source_id, page, char_start, char_end, text)
            SELECT
                :source_id,
                g,
                0,
                char_length(body),
                body
            FROM (
                SELECT
                    g,
                    CASE
                        WHEN g % 50 = 0 THEN 'International cross-border volume observation ' || g::text
                        ELSE 'payments volume incentives expenses network item ' || g::text
                    END AS body
                FROM generate_series(2, 5000) AS g
            ) AS seeded
            """
        ),
        {"source_id": source.id},
    )
    db_session.execute(text("ANALYZE document_text"))
    db_session.execute(text("ANALYZE source"))
    db_session.commit()

    params = {
        "q": "cross-border",
        "company": "visa",
        "period_start": "2024-04-01",
        "period_end": "2024-06-30",
        "cutoff_ts": "2024-07-23T20:00:00Z",
        "limit": 20,
    }
    warm = client.get("/search/passages", params=params)
    assert warm.status_code == 200
    assert len(warm.json()["hits"]) == 20

    started = time.perf_counter()
    timed = client.get("/search/passages", params=params)
    elapsed = time.perf_counter() - started
    assert timed.status_code == 200
    assert len(timed.json()["hits"]) == 20
    assert elapsed < 0.5, f"filtered search took {elapsed:.3f}s"
