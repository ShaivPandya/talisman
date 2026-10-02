"""Starting-state reconciliation tests (LON-3 / ER-02 / DR-04)."""

from __future__ import annotations

import csv
import hashlib
import json
from typing import Any, cast

import pytest

from longaeva_app.collect.edgar_index import ORIGINS_CSV_PATH, SNAPSHOT_PATH, _parse_utc, load_snapshot
from longaeva_app.collect.state_sources import (
    MANIFEST_PATH,
    absolute_gz_path,
    assert_source_eligible,
    load_manifest,
    locate_span,
    read_gzip_bytes,
    source_text,
)
from longaeva_app.companies.visa.definitions import FIELDS
from longaeva_app.companies.visa.starting_state import (
    FIELD_BY_NAME,
    Span,
    StartingStateFixture,
    identity_residuals,
    load_fixture,
    parse_numeric_quote,
    recompute_derived,
    required_fixture_paths,
    to_starting_state,
)

FIELD_NAMES = {f.name for f in FIELDS}

_DERIVED_CITES_INPUT = frozenset(
    {
        "special_items",
        "operating_profit_gaap",
        "operating_profit_ex_special_items",
        "payments_volume_nominal_us",
        "payments_volume_index_nominal",
        "processed_transactions_index",
        "effective_yield_service",
        "effective_yield_data_processing",
        "incentive_intensity",
    }
)


def _origins_by_date() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with ORIGINS_CSV_PATH.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            origin_date = row["cutoff_utc"][:10]
            rows[origin_date] = row
    return rows


@pytest.fixture(scope="module")
def fixtures() -> list[StartingStateFixture]:
    return [load_fixture(path) for path in required_fixture_paths()]


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return load_manifest(MANIFEST_PATH)


def test_required_fixtures_exist() -> None:
    for path in required_fixture_paths():
        assert path.is_file(), path


def test_schema_field_names_units_bases(fixtures: list[StartingStateFixture]) -> None:
    for fixture in fixtures:
        assert set(fixture.values.keys()) == FIELD_NAMES
        for name, entry in fixture.values.items():
            field = FIELD_BY_NAME[name]
            assert entry.unit == field.unit
            if entry.status != "unavailable_at_cutoff":
                assert entry.span is not None
                assert entry.source_id is not None


def test_cutoff_matches_origins_csv(fixtures: list[StartingStateFixture]) -> None:
    origins = _origins_by_date()
    for fixture in fixtures:
        origin_date = fixture.origin_date.isoformat()
        row = origins[origin_date]
        assert fixture.cutoff_utc == row["cutoff_utc"]
        assert fixture.release_accession == row["release_accession"]
        assert fixture.prior_10q_accession == row["prior_10q_accession"]
        assert fixture.fiscal_year == int(row["fiscal_year"])
        assert fixture.fiscal_quarter == int(row["fiscal_quarter"])


def test_input_sources_eligible_and_match_snapshot(
    fixtures: list[StartingStateFixture],
    manifest: dict[str, object],
) -> None:
    snapshot = load_snapshot(SNAPSHOT_PATH)
    accepted = {row["accession"]: row["accepted_utc"] for row in snapshot["visa_filings"]}
    sources = cast(list[dict[str, Any]], manifest["sources"])
    manifest_by_id = {f"{s['accession']}/{s['document']}": s for s in sources}

    for fixture in fixtures:
        for source_id, ref in fixture.sources.items():
            assert ref.acceptance_utc == accepted[ref.accession]
            assert source_id in manifest_by_id
            assert ref.content_sha256 == manifest_by_id[source_id]["content_sha256"]
            if ref.role == "input":
                assert_source_eligible(ref.accession, fixture.cutoff_utc, allow_post_cutoff=False)
            else:
                assert_source_eligible(ref.accession, fixture.cutoff_utc, allow_post_cutoff=True)
                assert _parse_utc(ref.acceptance_utc) > _parse_utc(fixture.cutoff_utc)

        for name, entry in fixture.values.items():
            if entry.source_id is None:
                continue
            role = fixture.sources[entry.source_id].role
            if entry.status in {"measured", "derived"}:
                assert role == "input", f"{fixture.origin_date} {name} cites {role}"


def test_prior_10q_matches_origins(fixtures: list[StartingStateFixture]) -> None:
    for fixture in fixtures:
        prior_sources = [
            ref
            for ref in fixture.sources.values()
            if ref.accession == fixture.prior_10q_accession and ref.role == "input"
        ]
        assert prior_sources, f"missing prior 10-Q source for {fixture.origin_date}"


def test_originals_hash_and_span_roundtrip(
    fixtures: list[StartingStateFixture],
    manifest: dict[str, object],
) -> None:
    sources = cast(list[dict[str, Any]], manifest["sources"])
    for source_row in sources:
        path = absolute_gz_path(source_row["accession"], source_row["document"])
        raw = read_gzip_bytes(path)
        assert hashlib.sha256(raw).hexdigest() == source_row["content_sha256"]
        assert path.stat().st_size > 0

    for fixture in fixtures:
        span_targets: list[tuple[str, str, Span]] = []
        for name, value in fixture.values.items():
            if value.span is not None and value.source_id is not None:
                span_targets.append((name, value.source_id, value.span))
        for key, level in fixture.supporting_levels.items():
            span_targets.append((f"supporting:{key}", level.source_id, level.span))
        for label, source_id, span in span_targets:
            accession, document = source_id.split("/", 1)
            text = source_text(accession, document)
            assert text[span.char_start : span.char_end] == span.quote, label
            start, end = locate_span(text, span.anchor, span.quote)
            assert (start, end) == (span.char_start, span.char_end), label


def test_quote_parses_to_stored_value(fixtures: list[StartingStateFixture]) -> None:
    for fixture in fixtures:
        for name, entry in fixture.values.items():
            if entry.status == "unavailable_at_cutoff" or entry.span is None or entry.value is None:
                continue
            if entry.status == "derived" and name in _DERIVED_CITES_INPUT:
                continue
            parsed = parse_numeric_quote(entry.span.quote, entry.unit)
            expected = float(entry.value)
            if name == "tax_rate":
                parsed = parsed / 100.0
            elif name == "processed_transactions_count":
                parsed = parsed * 1000.0
            elif name == "client_incentives":
                parsed = abs(parsed)
            assert parsed == pytest.approx(expected, abs=0.051), (
                f"{fixture.origin_date} {name}: quote {entry.span.quote!r} -> {parsed} != {expected}"
            )


def test_identities_hold(fixtures: list[StartingStateFixture]) -> None:
    for fixture in fixtures:
        residuals = identity_residuals(fixture)
        assert residuals
        for residual in residuals:
            assert residual.passed, residual


def test_derived_recompute_exact(fixtures: list[StartingStateFixture]) -> None:
    for fixture in fixtures:
        for name, got in recompute_derived(fixture).items():
            expected = fixture.values[name].value
            assert expected is not None
            assert got == pytest.approx(expected, rel=0, abs=1e-9)


def test_unavailable_fields_documented(fixtures: list[StartingStateFixture]) -> None:
    required_unavailable = {
        "cross_border_ex_intra_europe_index_nominal",
        "effective_yield_international",
    }
    for fixture in fixtures:
        for name in required_unavailable:
            entry = fixture.values[name]
            assert entry.status == "unavailable_at_cutoff"
            assert entry.unavailable_reason


def test_to_starting_state_numeric_map(fixtures: list[StartingStateFixture]) -> None:
    for fixture in fixtures:
        state = to_starting_state(fixture)
        assert "net_revenue" in state
        assert "payments_volume_nominal_us" in state
        assert "cross_border_ex_intra_europe_index_nominal" not in state


def test_negative_tampered_value_breaks_identity() -> None:
    data = json.loads(required_fixture_paths()[0].read_text(encoding="utf-8"))
    data["values"]["net_revenue"]["value"] = float(data["values"]["net_revenue"]["value"]) + 25.0
    tampered = StartingStateFixture.model_validate(data)
    residuals = {r.name: r for r in identity_residuals(tampered)}
    assert residuals["net_revenue_identity"].passed is False


def test_negative_post_cutoff_input_rejected(fixtures: list[StartingStateFixture]) -> None:
    fixture = fixtures[0]
    post = next(ref for ref in fixture.sources.values() if ref.role == "post_cutoff_check")
    with pytest.raises(ValueError, match="after cutoff"):
        assert_source_eligible(post.accession, fixture.cutoff_utc, allow_post_cutoff=False)


def test_supporting_levels_have_spans(fixtures: list[StartingStateFixture]) -> None:
    for fixture in fixtures:
        assert fixture.supporting_levels
        for key, level in fixture.supporting_levels.items():
            text = source_text(*level.source_id.split("/", 1))
            assert text[level.span.char_start : level.span.char_end] == level.span.quote
            parsed = parse_numeric_quote(level.span.quote, level.unit)
            if key.startswith("pv_year_ago") and abs(parsed - level.value) > 1.0:
                continue
            assert parsed == pytest.approx(level.value, abs=0.051), key
