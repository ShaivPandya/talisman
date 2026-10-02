"""Second-wave disclosure family gate tests (LON-8 / DR-03 / FR-03)."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from longaeva_app.api.schemas import ObservationCreate
from longaeva_app.collect.second_wave import (
    MANIFEST_PATH,
    SCAN_PATH,
    SNAPSHOT_PATH,
    SOURCES_DIR,
    TIMING_PATH,
    YAML_PATH,
    build_timing_rows,
    candidates_by_id,
    finalist_ids,
    load_scan,
    load_snapshot,
    load_sources_manifest,
    load_timing,
    load_visa_origins,
    read_gzip_bytes,
    selected_ids,
    source_text,
)
from longaeva_app.collect.state_sources import locate_span
from longaeva_app.extract.booking_release import parse_percent_quote
from longaeva_app.extract.second_wave_release import (
    SecondWaveObservationFixture,
    load_fixture,
    required_fixture_paths,
    to_observation_create,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
GATE_MD = PACKAGE_ROOT / "docs" / "gates" / "second-wave.md"


@pytest.fixture(scope="module")
def yaml_manifest() -> dict[str, Any]:
    with YAML_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    return load_snapshot(SNAPSHOT_PATH)


@pytest.fixture(scope="module")
def timing() -> list[dict[str, str]]:
    return load_timing(TIMING_PATH)


@pytest.fixture(scope="module")
def scan() -> list[dict[str, str]]:
    return load_scan(SCAN_PATH)


@pytest.fixture(scope="module")
def sources_manifest() -> dict[str, Any]:
    return load_sources_manifest(MANIFEST_PATH)


@pytest.fixture(scope="module")
def fixtures() -> list[SecondWaveObservationFixture]:
    return [load_fixture(path) for path in required_fixture_paths()]


def test_yaml_one_selection_per_family_and_rejections(yaml_manifest: dict[str, Any]) -> None:
    cands = yaml_manifest["candidates"]
    assert len(cands) == 14
    selected = yaml_manifest["selected"]
    assert selected == {"airline": "united", "retailer": "costco", "processor": "paypal"}
    by_id = {c["id"]: c for c in cands}
    assert by_id["united"]["status"] == "selected"
    assert by_id["costco"]["status"] == "selected"
    assert by_id["paypal"]["status"] == "selected"
    for cand in cands:
        if cand["status"] != "selected":
            assert cand.get("reason"), f"{cand['id']} missing rejection reason"
    # Strict processor scope: networks/issuers are stretch, not selected.
    for oid in ("mastercard", "amex", "jpmorgan"):
        assert by_id[oid]["family"] == "out_of_family"
        assert by_id[oid]["status"] == "stretch_s6"
    assert yaml_manifest["decision"]["processor_scope"] == "strict_pure_processor"
    assert yaml_manifest["decision"]["rule_stance"] == "context_first"
    for family in ("airline", "retailer", "processor"):
        assert yaml_manifest["recommendation"][family]["stance"] == "context"


def test_timing_rebuild_matches_committed(snapshot: dict[str, Any], timing: list[dict[str, str]]) -> None:
    rebuilt = build_timing_rows(snapshot)
    assert len(rebuilt) == len(timing) == 14 * 19
    assert all(r["eligible"] == "true" for r in timing)
    assert [r["accession"] for r in rebuilt] == [r["accession"] for r in timing]
    assert [r["age_days"] for r in rebuilt] == [r["age_days"] for r in timing]
    assert [r["same_day"] for r in rebuilt] == [r["same_day"] for r in timing]


def test_timing_summary_matches_gate_selection(timing: list[dict[str, str]]) -> None:
    def median_age(cand: str) -> float:
        ages = sorted(float(r["age_days"]) for r in timing if r["candidate_id"] == cand)
        return ages[len(ages) // 2]

    assert median_age("united") < median_age("delta")
    assert median_age("costco") < median_age("walmart")
    assert median_age("paypal")  # exists
    paypal_same = sum(1 for r in timing if r["candidate_id"] == "paypal" and r["same_day"] == "true")
    assert paypal_same == 5
    # American can report after Visa at some origins
    american_late = [
        r
        for r in timing
        if r["candidate_id"] == "american" and r["next_after_cutoff_days"] and float(r["next_after_cutoff_days"]) <= 7
    ]
    assert len(american_late) >= 1


def test_scan_no_errors_and_finalist_coverage(scan: list[dict[str, str]], yaml_manifest: dict[str, Any]) -> None:
    assert len(scan) == 6 * 19
    assert all(not r["error"] for r in scan)
    finals = set(finalist_ids(yaml_manifest))
    assert {r["candidate_id"] for r in scan} == finals
    # Selected families have metric hits at every origin
    for cand_id in selected_ids(yaml_manifest):
        rows = [r for r in scan if r["candidate_id"] == cand_id]
        assert len(rows) == 19
        assert all(r["metric_hits"] for r in rows)


def test_sources_manifest_hashes_and_acceptance(sources_manifest: dict[str, Any], snapshot: dict[str, Any]) -> None:
    sources = cast(list[dict[str, Any]], sources_manifest["sources"])
    assert len(sources) >= 6  # at least one exhibit per retained release
    by_cand_origin: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in sources:
        assert entry["role"] == "input"
        path = SOURCES_DIR / entry["path"]
        assert path.is_file(), path
        digest = hashlib.sha256(read_gzip_bytes(path)).hexdigest()
        assert digest == entry["content_sha256"]
        assert entry["acceptance_utc"] == entry["index_page_accepted_utc"]
        assert entry["acceptance_utc"] < entry["retrieval_ts"]
        # Acceptance matches snapshot earnings row
        filings = snapshot["candidates"][entry["candidate_id"]]["filings"]
        accepted = {f["accession"]: f["accepted_utc"] for f in filings}
        assert accepted[entry["accession"]] == entry["acceptance_utc"]
        for origin in entry["origins"]:
            by_cand_origin.setdefault((entry["candidate_id"], origin), []).append(entry)
    for cand_id in selected_ids():
        for origin in ("2024-07-23", "2025-10-28"):
            assert (cand_id, origin) in by_cand_origin


def test_no_selected_accession_after_cutoff(
    sources_manifest: dict[str, Any],
    timing: list[dict[str, str]],
) -> None:
    origins = load_visa_origins()
    prospective = next(o for o in origins if o["status"] == "prospective")
    cutoff = prospective["cutoff_utc"]
    for entry in sources_manifest["sources"]:
        assert entry["acceptance_utc"] <= cutoff or entry["origins"] != [prospective["cutoff_utc"][:10]]
        # Every retained origin's accession equals timing's eligible accession
        for origin in entry["origins"]:
            trow = next(r for r in timing if r["candidate_id"] == entry["candidate_id"] and r["origin_date"] == origin)
            assert trow["accession"] == entry["accession"]
            assert trow["accepted_utc"] <= trow["cutoff_utc"]


def test_fixtures_validate_observation_create(fixtures: list[SecondWaveObservationFixture]) -> None:
    types_seen: set[str] = set()
    companies = {f.company for f in fixtures}
    assert companies == {"united", "costco", "paypal"}
    for fixture in fixtures:
        for entry in fixture.observations:
            src = next(s for s in fixture.sources if s.source_id == entry.source_id)
            created = to_observation_create(entry, src.url, company=fixture.company)
            assert isinstance(created, ObservationCreate)
            types_seen.add(entry.statement_type)
            assert entry.visa_driver
    assert "measured" in types_seen
    assert "qualitative" in types_seen


def test_spans_roundtrip_and_measured_quotes(fixtures: list[SecondWaveObservationFixture]) -> None:
    for fixture in fixtures:
        for entry in fixture.observations:
            src = next(s for s in fixture.sources if s.source_id == entry.source_id)
            text = source_text(src.accession, src.document)
            span = entry.span
            assert text[span.char_start : span.char_end] == span.quote
            start, end = locate_span(text, span.anchor, span.quote)
            assert (start, end) == (span.char_start, span.char_end)
            if entry.statement_type == "measured" and entry.value is not None:
                parsed = parse_percent_quote(span.quote.lstrip("+"))
                # Declines may store a signed value while the printed quote is unsigned.
                assert abs(parsed) == pytest.approx(abs(entry.value))


def test_period_dates_are_ordered(fixtures: list[SecondWaveObservationFixture]) -> None:
    for fixture in fixtures:
        for entry in fixture.observations:
            assert entry.period_start <= entry.period_end
            assert isinstance(entry.period_start, date)


def test_gate_doc_and_scan_counts(scan: list[dict[str, str]], yaml_manifest: dict[str, Any]) -> None:
    assert GATE_MD.is_file()
    text = GATE_MD.read_text(encoding="utf-8")
    assert "LON-8" in text
    assert "united" in text.lower() or "United" in text
    assert "Costco" in text
    assert "PayPal" in text
    assert "context" in text.lower()
    # Selected companies: metric hits at all 19 origins
    for cand_id in selected_ids(yaml_manifest):
        rows = [r for r in scan if r["candidate_id"] == cand_id]
        assert len(rows) == 19
        assert all(r["metric_hits"] for r in rows)


def test_no_users_paths_in_gate_artifacts() -> None:
    roots = [
        YAML_PATH,
        TIMING_PATH,
        SCAN_PATH,
        SNAPSHOT_PATH,
        MANIFEST_PATH,
        GATE_MD,
        *required_fixture_paths(),
    ]
    pattern = re.compile(r"/Users/[A-Za-z0-9._-]+")
    for path in roots:
        if not path.exists():
            continue
        if path.suffix == ".gz":
            continue
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), path


def test_candidates_by_id_helpers(yaml_manifest: dict[str, Any]) -> None:
    by_id = candidates_by_id(yaml_manifest)
    assert set(selected_ids(yaml_manifest)) == {"united", "costco", "paypal"}
    assert set(finalist_ids(yaml_manifest)) == {
        "united",
        "delta",
        "costco",
        "walmart",
        "paypal",
        "block",
    }
    assert by_id["fiserv"]["status"] == "rejected"
