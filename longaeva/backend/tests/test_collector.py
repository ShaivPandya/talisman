"""Collector integration tests against three cached fixtures."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from longaeva_app.collect.collector import canonical_passage, collect
from longaeva_app.collect.http import PoliteClient
from longaeva_app.collect.manifest import DocumentEntry, Period
from longaeva_app.db.models import DocumentText, Source, SourceRetrieval
from longaeva_app.hashing import sha256_hex
from longaeva_app.storage.local import LocalArtifactStore

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PACKAGE_ROOT / "data" / "fixtures"

VISA_ACC = "0001403161-24-000040"
VISA_DOC = "q32024earningsrelease.htm"
VISA_TS = "2024-07-23T20:05:38Z"
VISA_URL = f"https://www.sec.gov/Archives/edgar/data/1403161/{VISA_ACC.replace('-', '')}/{VISA_DOC}"
VISA_INDEX = f"https://www.sec.gov/Archives/edgar/data/1403161/{VISA_ACC.replace('-', '')}/{VISA_ACC}-index.htm"

BOOKING_ACC = "0001075531-24-000026"
BOOKING_DOC = "ex99133124.htm"
BOOKING_TS = "2024-05-02T20:02:05Z"
BOOKING_URL = f"https://www.sec.gov/Archives/edgar/data/1075531/{BOOKING_ACC.replace('-', '')}/{BOOKING_DOC}"
BOOKING_INDEX = (
    f"https://www.sec.gov/Archives/edgar/data/1075531/{BOOKING_ACC.replace('-', '')}/{BOOKING_ACC}-index.htm"
)

CENSUS_URL = "https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf"
CENSUS_TS = "2024-07-16T12:30:00Z"


def _read_gz(path: Path) -> bytes:
    with gzip.open(path, "rb") as handle:
        return handle.read()


def _fixture_bytes() -> dict[str, bytes]:
    return {
        "visa": _read_gz(FIXTURES / "states" / "sources" / VISA_ACC / f"{VISA_DOC}.gz"),
        "booking": _read_gz(FIXTURES / "booking" / "sources" / BOOKING_ACC / f"{BOOKING_DOC}.gz"),
        "census": (FIXTURES / "census" / "sources" / "adv2406.pdf").read_bytes(),
    }


def _index_html(accepted_et: str, document: str, exhibit: str = "EX-99.1") -> bytes:
    # Accepted is Eastern wall-clock without zone, matching EDGAR index pages.
    return (
        f"<html><body><div>Accepted</div><div>{accepted_et}</div>"
        f'<table><tr><td><a href="{document}">{document}</a></td><td>{exhibit}</td></tr></table>'
        f"</body></html>"
    ).encode()


def _entries() -> list[DocumentEntry]:
    blobs = _fixture_bytes()
    return [
        DocumentEntry(
            key="visa:release:FY2024Q3",
            provider="sec_edgar",
            company="visa",
            doc_type="earnings_release",
            cik="0001403161",
            accession=VISA_ACC,
            document=VISA_DOC,
            exhibit="EX-99.1",
            publication_ts=datetime.fromisoformat(VISA_TS.replace("Z", "+00:00")),
            publication_ts_source="edgar_acceptance",
            period=Period(fiscal_year=2024, fiscal_quarter=3),
            expected_sha256=sha256_hex(blobs["visa"]),
            license_note="SEC public domain",
        ),
        DocumentEntry(
            key="census:marts:adv2406",
            provider="census",
            company="census",
            doc_type="marts_advance",
            url=CENSUS_URL,
            publication_ts=datetime.fromisoformat(CENSUS_TS.replace("Z", "+00:00")),
            publication_ts_source="census_release_line",
            period=Period(release_id="adv2406", reference_month="2024-06"),
            expected_sha256=sha256_hex(blobs["census"]),
            license_note="Census public domain",
        ),
        DocumentEntry(
            key="booking:release:FY2024Q1",
            provider="sec_edgar",
            company="booking",
            doc_type="earnings_release",
            cik="0001075531",
            accession=BOOKING_ACC,
            document=BOOKING_DOC,
            exhibit="EX-99.1",
            publication_ts=datetime.fromisoformat(BOOKING_TS.replace("Z", "+00:00")),
            publication_ts_source="edgar_acceptance",
            expected_sha256=sha256_hex(blobs["booking"]),
            license_note="SEC public domain",
        ),
    ]


def _transport(blobs: dict[str, bytes], *, mutate_visa: bool = False) -> httpx.MockTransport:
    visa_body = blobs["visa"] + (b"\n<!--mut-->" if mutate_visa else b"")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == VISA_INDEX:
            return httpx.Response(200, content=_index_html("2024-07-23 16:05:38", VISA_DOC))
        if url == VISA_URL:
            return httpx.Response(200, content=visa_body, headers={"content-type": "text/html"})
        if url == BOOKING_INDEX:
            return httpx.Response(200, content=_index_html("2024-05-02 16:02:05", BOOKING_DOC))
        if url == BOOKING_URL:
            return httpx.Response(200, content=blobs["booking"], headers={"content-type": "text/html"})
        if url == CENSUS_URL:
            return httpx.Response(200, content=blobs["census"], headers={"content-type": "application/pdf"})
        if "forbidden" in url:
            return httpx.Response(403, content=b"nope")
        return httpx.Response(404, content=b"missing")

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport) -> PoliteClient:
    return PoliteClient(
        user_agent="LongaevaTest/0.1 (test@example.com)",
        transport=transport,
        host_intervals={
            "www.sec.gov": 0.0,
            "www2.census.gov": 0.0,
            "example.com": 0.0,
        },
        default_interval=0.0,
        sleep=lambda _s: None,
    )


@pytest.mark.db
def test_collect_three_fixtures_and_dedup(db_session: Session, tmp_path: Path) -> None:
    blobs = _fixture_bytes()
    store = LocalArtifactStore(tmp_path)
    entries = _entries()
    client = _client(_transport(blobs))

    report = collect(
        session=db_session,
        store=store,
        client=client,
        entries=entries,
        refresh=False,
    )
    db_session.commit()
    assert report.failed_count == 0
    assert all(e.status == "collected" for e in report.entries)

    sources = db_session.execute(select(Source)).scalars().all()
    assert len(sources) == 3
    for source in sources:
        assert source.publication_ts < source.retrieval_ts
        assert store.exists(source.original_path)

    # Re-run: cached, no new sources.
    report2 = collect(session=db_session, store=store, client=client, entries=entries)
    db_session.commit()
    assert all(e.status == "cached" for e in report2.entries)
    assert db_session.execute(select(func.count()).select_from(Source)).scalar_one() == 3

    # --refresh with same bytes: one source, two retrievals for visa.
    report3 = collect(session=db_session, store=store, client=client, entries=entries[:1], refresh=True)
    db_session.commit()
    assert report3.entries[0].status in {"refreshed", "cached"}
    visa = db_session.execute(select(Source).where(Source.company == "visa")).scalar_one()
    retrievals = db_session.execute(
        select(func.count()).select_from(SourceRetrieval).where(SourceRetrieval.source_id == visa.id)
    ).scalar_one()
    assert retrievals == 2
    assert db_session.execute(select(func.count()).select_from(Source)).scalar_one() == 3


@pytest.mark.db
def test_refresh_changed_bytes_supersedes(db_session: Session, tmp_path: Path) -> None:
    blobs = _fixture_bytes()
    store = LocalArtifactStore(tmp_path)
    entries = _entries()[:1]
    collect(session=db_session, store=store, client=_client(_transport(blobs)), entries=entries)
    db_session.commit()
    original = db_session.execute(select(Source)).scalar_one()

    report = collect(
        session=db_session,
        store=store,
        client=_client(_transport(blobs, mutate_visa=True)),
        entries=entries,
        refresh=True,
    )
    db_session.commit()
    assert report.entries[0].status == "superseded"
    sources = db_session.execute(select(Source).order_by(Source.retrieval_ts)).scalars().all()
    assert len(sources) == 2
    newer = sources[-1]
    assert newer.supersedes_id == original.id
    assert newer.content_hash != original.content_hash


@pytest.mark.db
def test_passage_dedup_links_earliest_published(db_session: Session, tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    shared = b"<html><body><p>Identical shared paragraph for DR-08.</p></body></html>"
    early_ts = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
    late_ts = datetime(2021, 1, 1, 12, 0, tzinfo=UTC)
    late_body = shared.replace(b"</body>", b"<p>trailer</p></body>")

    def handler2(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("a.htm"):
            return httpx.Response(200, content=shared)
        if url.endswith("b.htm"):
            return httpx.Response(200, content=late_body)
        return httpx.Response(404, content=b"x")

    entries = [
        DocumentEntry(
            key="dedup:early",
            provider="sec_edgar",
            company="visa",
            doc_type="test",
            url="https://www.sec.gov/Archives/edgar/data/1/20200101/a.htm",
            publication_ts=early_ts,
            publication_ts_source="manifest",
        ),
        DocumentEntry(
            key="dedup:late",
            provider="sec_edgar",
            company="visa",
            doc_type="test",
            url="https://www.sec.gov/Archives/edgar/data/1/20210101/b.htm",
            publication_ts=late_ts,
            publication_ts_source="manifest",
        ),
    ]

    client = _client(httpx.MockTransport(handler2))
    collect(session=db_session, store=store, client=client, entries=entries)
    db_session.commit()

    passages = db_session.execute(select(DocumentText)).scalars().all()
    shared_passages = [p for p in passages if "Identical shared paragraph" in p.text]
    assert len(shared_passages) == 2
    assert shared_passages[0].text_hash == shared_passages[1].text_hash
    assert shared_passages[0].text_hash is not None
    canon = canonical_passage(db_session, shared_passages[0].text_hash or "")
    assert canon is not None
    early_source = db_session.execute(
        select(Source).where(Source.attributes.contains({"manifest_key": "dedup:early"}))
    ).scalar_one()
    assert canon.source_id == early_source.id


@pytest.mark.db
def test_403_reported_without_insert(db_session: Session, tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    entry = DocumentEntry(
        key="blocked:ir",
        provider="visa_ir",
        company="visa",
        doc_type="ir_deck",
        url="https://example.com/forbidden.pdf",
        publication_ts_source="http_last_modified",
    )
    report = collect(
        session=db_session,
        store=store,
        client=_client(_transport(_fixture_bytes())),
        entries=[entry],
    )
    assert report.entries[0].status == "unavailable"
    assert db_session.execute(select(func.count()).select_from(Source)).scalar_one() == 0


@pytest.mark.db
def test_acceptance_mismatch_fails(db_session: Session, tmp_path: Path) -> None:
    blobs = _fixture_bytes()
    store = LocalArtifactStore(tmp_path)
    entry = _entries()[0].model_copy(update={"publication_ts": datetime.now(UTC) - timedelta(days=1)})
    report = collect(
        session=db_session,
        store=store,
        client=_client(_transport(blobs)),
        entries=[entry],
    )
    assert report.entries[0].status == "failed"
    assert "publication_ts mismatch" in (report.entries[0].message or "")
    assert db_session.execute(select(func.count()).select_from(Source)).scalar_one() == 0


@pytest.mark.db
def test_unavailable_manifest_entry_skipped(db_session: Session, tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    entry = DocumentEntry(
        key="visa_ir:quarterly_html",
        provider="visa_ir",
        company="visa",
        doc_type="ir_quarterly_html",
        url="https://investor.visa.com/news/",
        availability="unavailable_for_automation",
        unavailable_reason="Cloudflare JS challenge",
        attributes={"http_status": 403},
    )
    report = collect(session=db_session, store=store, client=_client(_transport(_fixture_bytes())), entries=[entry])
    assert report.entries[0].status == "unavailable"
    assert report.unavailable_count == 1
