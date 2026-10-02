"""Booking Holdings family-gate tests (LON-4 / DR-03 / DR-04 / FR-03)."""

from __future__ import annotations

import csv
import hashlib
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from longaeva_app.api.schemas import ObservationCreate
from longaeva_app.collect.booking_sources import (
    CALENDAR_ACCESSIONS,
    CALENDAR_PATH,
    MANIFEST_PATH,
    RETAINED_SPECS,
    absolute_gz_path,
    load_calendar,
    load_manifest,
    read_gzip_bytes,
    source_text,
)
from longaeva_app.collect.edgar_index import (
    ORIGINS_CSV_PATH,
    SNAPSHOT_PATH,
    _parse_utc,
    build_origins,
    load_snapshot,
)
from longaeva_app.collect.state_sources import locate_span
from longaeva_app.extract.booking_release import (
    BookingObservationFixture,
    detect_guidance,
    guidance_covers_target,
    load_fixture,
    parse_percent_quote,
    parse_percent_range_quote,
    required_fixture_paths,
    to_observation_create,
    visa_target_to_calendar_quarter,
)


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return load_manifest(MANIFEST_PATH)


@pytest.fixture(scope="module")
def calendar() -> list[dict[str, str]]:
    return load_calendar(CALENDAR_PATH)


@pytest.fixture(scope="module")
def fixtures() -> list[BookingObservationFixture]:
    return [load_fixture(path) for path in required_fixture_paths()]


def test_manifest_hashes_roles_and_acceptance(manifest: dict[str, Any]) -> None:
    sources = cast(list[dict[str, Any]], manifest["sources"])
    assert len(sources) == 3
    by_acc = {s["accession"]: s for s in sources}
    snapshot = load_snapshot(SNAPSHOT_PATH)
    accepted = {row["accession"]: row["accepted_utc"] for row in snapshot["booking_filings"]}

    for spec in RETAINED_SPECS:
        entry = by_acc[spec.accession]
        path = absolute_gz_path(spec.accession, spec.document)
        assert path.is_file(), path
        digest = hashlib.sha256(read_gzip_bytes(path)).hexdigest()
        assert digest == entry["content_sha256"]
        assert entry["role"] == spec.role
        assert entry["acceptance_utc"] == accepted[spec.accession]
        assert entry["index_page_accepted_utc"] == entry["acceptance_utc"]
        assert entry["acceptance_utc"] < entry["retrieval_ts"]


def test_fixtures_validate_as_observation_create(fixtures: list[BookingObservationFixture]) -> None:
    types_seen: set[str] = set()
    for fixture in fixtures:
        for entry in fixture.observations:
            created = to_observation_create(entry, fixture.source.url)
            assert isinstance(created, ObservationCreate)
            types_seen.add(entry.statement_type)
    assert {"measured", "guidance", "qualitative"} <= types_seen


def test_spans_roundtrip_and_quotes_parse(fixtures: list[BookingObservationFixture]) -> None:
    for fixture in fixtures:
        text = source_text(fixture.source.accession, fixture.source.document)
        for entry in fixture.observations:
            span = entry.span
            assert text[span.char_start : span.char_end] == span.quote
            start, end = locate_span(text, span.anchor, span.quote)
            assert (start, end) == (span.char_start, span.char_end)
            if entry.statement_type == "measured":
                assert entry.value is not None
                assert parse_percent_quote(span.quote) == pytest.approx(entry.value)
            elif entry.statement_type == "guidance":
                assert entry.range_low is not None and entry.range_high is not None
                low, high = parse_percent_range_quote(span.quote)
                assert low == pytest.approx(entry.range_low)
                assert high == pytest.approx(entry.range_high)


def test_origin_timing_matches_origins_csv(fixtures: list[BookingObservationFixture]) -> None:
    origins = {row["cutoff_utc"][:10]: row for row in csv.DictReader(ORIGINS_CSV_PATH.open(encoding="utf-8"))}
    by_date = {f.release_date: f for f in fixtures}

    origin_a = by_date["2024-05-02"]
    timing_a = origin_a.visa_origins[0]
    assert timing_a.origin_date == "2024-07-23"
    assert timing_a.age_weeks == pytest.approx(11.7146, abs=0.001)
    assert timing_a.same_day is False
    assert timing_a.guidance_covers_target == "false"
    row_a = origins["2024-07-23"]
    assert row_a["booking_accession"] == origin_a.source.accession
    assert float(row_a["booking_age_weeks"]) == pytest.approx(timing_a.age_weeks, abs=0.001)

    origin_b = by_date["2025-10-28"]
    timing_b = next(t for t in origin_b.visa_origins if t.origin_date == "2025-10-28")
    assert timing_b.age_seconds == 224
    assert timing_b.same_day is True
    assert timing_b.margin_seconds == 224
    assert timing_b.guidance_covers_target == "true"
    row_b = origins["2025-10-28"]
    assert row_b["booking_accession"] == origin_b.source.accession
    assert row_b["booking_margin_seconds"] == "224"
    assert row_b["booking_guidance_covers_target"] == "true"
    assert row_b["booking_fallback_accession"] == "0001075531-25-000035"


def test_post_cutoff_release_never_selected(manifest: dict[str, Any]) -> None:
    post = next(s for s in cast(list[dict[str, Any]], manifest["sources"]) if s["role"] == "post_cutoff_check")
    assert post["accession"] == "0001075531-26-000036"
    prospective_cutoff = "2026-07-28T20:05:26Z"
    assert _parse_utc(post["acceptance_utc"]) > _parse_utc(prospective_cutoff)

    rows = list(csv.DictReader(ORIGINS_CSV_PATH.open(encoding="utf-8")))
    for row in rows:
        assert row["booking_accession"] != "0001075531-26-000036"
    prospective = next(r for r in rows if r["status"] == "prospective")
    assert prospective["booking_accession"] == "0001075531-26-000024"
    assert float(prospective["booking_age_weeks"]) == pytest.approx(13.0002, abs=0.001)


def test_calendar_guidance_switch_and_coverage(calendar: list[dict[str, str]]) -> None:
    assert len(calendar) == 20
    assert len(CALENDAR_ACCESSIONS) == 20
    assert all(not row["error"] for row in calendar)
    assert [row["accession"] for row in calendar] == list(CALENDAR_ACCESSIONS)

    by_acc = {row["accession"]: row for row in calendar}
    # Guidance tables begin at 2025-07-29.
    assert by_acc["0001075531-25-000021"]["guidance_table"] == "false"
    assert by_acc["0001075531-25-000035"]["guidance_table"] == "true"
    assert by_acc["0001075531-25-000035"]["guidance_quarter"] == "2025Q3"
    assert by_acc["0001075531-25-000050"]["guidance_quarter"] == "2025Q4"
    assert by_acc["0001075531-26-000024"]["guidance_quarter"] == "2026Q2"
    assert by_acc["0001075531-26-000036"]["guidance_quarter"] == "2026Q3"

    rows = build_origins(load_snapshot(), booking_calendar=calendar)
    guided = [r for r in rows if r["booking_guidance_covers_target"] == "true"]
    assert {(int(r["fiscal_year"]), int(r["fiscal_quarter"])) for r in guided} == {
        (2025, 3),
        (2025, 4),
        (2026, 2),
    }
    same_day = [r for r in rows if r["booking_same_day"] == "true"]
    assert len(same_day) == 4
    assert all(r["booking_fallback_accession"] for r in same_day)
    assert all(r["booking_margin_seconds"] for r in same_day)


def test_visa_target_calendar_mapping_and_detect_guidance() -> None:
    assert visa_target_to_calendar_quarter(2026, 1) == "2025Q4"
    assert visa_target_to_calendar_quarter(2025, 3) == "2025Q2"
    assert guidance_covers_target("2025Q4", 2026, 1) == "true"
    assert guidance_covers_target("2025Q3", 2026, 1) == "false"
    assert guidance_covers_target("", 2026, 1) == "false"

    text = source_text("0001075531-25-000050", "q3-25bkngearningsrelease.htm")
    detected = detect_guidance(text)
    assert detected["guidance_table"] == "true"
    assert detected["guidance_quarter"] == "2025Q4"

    no_guide = source_text("0001075531-24-000026", "ex99133124.htm")
    assert detect_guidance(no_guide)["guidance_table"] == "false"


def test_quote_parsers_unit_cases() -> None:
    assert parse_percent_quote("8%") == 8.0
    assert parse_percent_quote("9") == 9.0
    assert parse_percent_range_quote("4% - 6%") == (4.0, 6.0)
    assert parse_percent_range_quote("6%-8%") == (6.0, 8.0)
    with pytest.raises(ValueError):
        parse_percent_range_quote("not-a-range")


def test_origins_csv_rebuild_includes_booking_columns(calendar: list[dict[str, str]]) -> None:
    assert SNAPSHOT_PATH.exists()
    rows = build_origins(load_snapshot(), booking_calendar=calendar)
    committed = list(csv.DictReader(ORIGINS_CSV_PATH.open(encoding="utf-8")))
    assert [r["booking_accession"] for r in committed] == [r["booking_accession"] for r in rows]
    assert [r["booking_guidance_covers_target"] for r in committed] == [
        r["booking_guidance_covers_target"] for r in rows
    ]
    assert [r["booking_same_day"] for r in committed] == [r["booking_same_day"] for r in rows]
    gate = Path(__file__).resolve().parents[2] / "docs" / "gates" / "booking.md"
    assert gate.is_file()
    for path in required_fixture_paths():
        assert path.is_file()
        assert load_fixture(path).observations


def test_period_dates_are_calendar_quarters(fixtures: list[BookingObservationFixture]) -> None:
    for fixture in fixtures:
        for entry in fixture.observations:
            assert entry.period_start <= entry.period_end
            assert isinstance(entry.period_start, date)
