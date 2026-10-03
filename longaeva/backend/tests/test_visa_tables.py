"""Visa structured table parser tests (LON-14)."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from longaeva_app.collect.edgar_index import ORIGINS_CSV_PATH
from longaeva_app.collect.visa_filings import load_manifest, source_text, verify_source_hash
from longaeva_app.companies.visa.starting_state import (
    SupportingLevel,
    load_fixture,
    recompute_derived,
    required_fixture_paths,
)
from longaeva_app.extract.html_offsets import parse_html
from longaeva_app.extract.visa_tables import (
    EXTRACTOR_ID,
    PACKAGE_ROOT,
    ParseResult,
    detect_format,
    parse_form_accession,
    parse_release,
    parse_release_accession,
    reject_after_cutoff,
    to_observation_create,
)

RELEASES_DIR = PACKAGE_ROOT / "data" / "fixtures" / "visa_releases"
STATUS_CSV = RELEASES_DIR / "parse_status.csv"
OBS_CSV = RELEASES_DIR / "observations.csv"


def _origins() -> list[dict[str, str]]:
    with ORIGINS_CSV_PATH.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def fy2024_2026_releases() -> list[tuple[dict[str, str], ParseResult]]:
    out: list[tuple[dict[str, str], ParseResult]] = []
    for row in _origins():
        fy, fq = int(row["fiscal_year"]), int(row["fiscal_quarter"])
        if fy < 2024:
            continue
        parsed = parse_release_accession(row["release_accession"], fy=fy, fq=fq)
        out.append((row, parsed))
    return out


def test_fy2024_2026_releases_parsed(fy2024_2026_releases: list[tuple[dict[str, str], ParseResult]]) -> None:
    assert len(fy2024_2026_releases) == 11
    for row, parsed in fy2024_2026_releases:
        assert parsed.status == "parsed", (row["fiscal_year"], row["fiscal_quarter"], parsed.missing, parsed.notes)
        assert parsed.missing == []
        assert all(check.passed for check in parsed.identities)
        form = parse_form_accession(row["prior_10q_accession"], form=row["prior_10q_form"])
        assert form.status == "parsed", (row["prior_10q_accession"], form.missing, form.notes)
        assert all(check.passed for check in form.identities)


def test_parse_status_covers_39_quarters() -> None:
    with STATUS_CSV.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 39
    periods = [r["period"] for r in rows]
    assert periods[0] == "FY2017Q1"
    assert periods[-1] == "FY2026Q3"
    modern = [r for r in rows if r["era"] == "table_modern"]
    assert len(modern) == 21
    assert all(r["status"] == "parsed" for r in modern)
    for row in rows:
        assert row["status"] in {"parsed", "partial", "failed"}
        if row["status"] != "parsed":
            assert row["missing_fields"] or row["notes"] or int(row["identities_failed"]) > 0


def test_golden_csvs_regenerate(tmp_path: Path) -> None:
    from longaeva_app.extract.visa_tables import iter_origin_parses, write_outputs

    status_rows, obs_rows = iter_origin_parses()
    write_outputs(status_rows, obs_rows, out_dir=tmp_path)
    assert (tmp_path / "parse_status.csv").read_bytes() == STATUS_CSV.read_bytes()
    assert (tmp_path / "observations.csv").read_bytes() == OBS_CSV.read_bytes()


def test_span_invariants_and_observation_create(
    fy2024_2026_releases: list[tuple[dict[str, str], ParseResult]],
) -> None:
    for _row, parsed in fy2024_2026_releases:
        html = source_text(parsed.accession, parsed.document)
        for obs in parsed.observations:
            assert html[obs.span.char_start : obs.span.char_end] == obs.span.quote
            to_observation_create(obs)
            assert obs.source_id == f"{parsed.accession}/{parsed.document}"


def test_format_detection_one_per_era() -> None:
    samples = {
        "table_2017": ("0001403161-17-000010", 2017, 1),
        "image_text_layer": ("0001403161-19-000026", 2019, 3),
        "table_modern": ("0001403161-24-000040", 2024, 3),
    }
    for era, (accession, fy, fq) in samples.items():
        parsed = parse_release_accession(accession, fy=fy, fq=fq)
        html = source_text(parsed.accession, parsed.document)
        layout = parse_html(html)
        assert detect_format(layout, fy) == era
        assert parsed.era == era


def test_manifest_sha256_matches_files() -> None:
    data = load_manifest()
    assert data["generated_for"] == "LON-14"
    assert len(data["sources"]) == 78
    for row in data["sources"]:
        raw = verify_source_hash(row["accession"], row["document"], expected=row["content_sha256"])
        assert hashlib.sha256(raw).hexdigest() == row["content_sha256"]


def test_tampered_category_fails_identity() -> None:
    parsed = parse_release_accession("0001403161-24-000040", fy=2024, fq=3)
    html = source_text(parsed.accession, parsed.document)
    tampered = html.replace("3,967", "9,999", 1)
    result = parse_release(
        tampered,
        accession=parsed.accession,
        document=parsed.document,
        fiscal_year=2024,
        fiscal_quarter=3,
    )
    assert any(not check.passed for check in result.identities if check.name == "net_revenue_identity")
    assert result.status == "partial"


def test_removed_drivers_table_does_not_fabricate() -> None:
    parsed = parse_release_accession("0001403161-24-000040", fy=2024, fq=3)
    html = source_text(parsed.accession, parsed.document)
    cut = html.find("KEY BUSINESS DRIVERS")
    assert cut > 0
    stripped = html[:cut] + html[cut:].replace("Payments volume", "Volume (removed)", 1)
    result = parse_release(
        stripped,
        accession=parsed.accession,
        document=parsed.document,
        fiscal_year=2024,
        fiscal_quarter=3,
    )
    fields = {obs.field for obs in result.observations if obs.location == "primary"}
    assert "payments_volume_growth_constant" not in fields
    assert "payments_volume_growth_nominal" not in fields
    assert any(name == "payments_volume_growth_constant" for name, _reason in result.missing)


def test_document_after_cutoff_rejected() -> None:
    # Origin A cutoff is the FY2024Q3 8-K; the same-quarter 10-Q is ~2 hours later.
    with pytest.raises(ValueError, match="after cutoff"):
        reject_after_cutoff("2024-07-23T22:12:59Z", "2024-07-23T20:05:38Z", accession="0001403161-24-000041")


@pytest.mark.parametrize("path", required_fixture_paths())
def test_lon3_fixture_parity(path: Path) -> None:
    fixture = load_fixture(path)
    release = parse_release_accession(fixture.release_accession, fy=fixture.fiscal_year, fq=fixture.fiscal_quarter)
    by_field = {obs.field: obs for obs in release.observations if obs.location == "primary"}
    html = source_text(release.accession, release.document)

    for name, val in fixture.values.items():
        if val.status != "measured":
            continue
        if val.source_id and val.source_id.startswith(fixture.release_accession):
            obs = by_field.get(name)
            assert obs is not None, name
            assert obs.value == pytest.approx(val.value, abs=1e-9), name
            assert obs.unit == val.unit
            assert obs.basis == val.basis
            assert obs.period_label == val.period_label
            assert obs.source_id == val.source_id
            assert val.span is not None
            assert obs.span.quote == val.span.quote
            assert (obs.span.char_start, obs.span.char_end) == (val.span.char_start, val.span.char_end)
            assert html[obs.span.char_start : obs.span.char_end] == obs.span.quote

    # 10-Q measured volume levels (direct spans).
    form_acc = fixture.prior_10q_accession
    form = parse_form_accession(form_acc, form="10-Q" if "10-Q" in str(fixture.sources) else "10-Q")
    form_obs = [
        obs
        for obs in form.observations
        if obs.location == "primary" and obs.attributes.get("vintage_role", "current") == "current"
    ]

    for name, val in fixture.values.items():
        if val.status != "measured":
            continue
        if not val.source_id or form_acc not in val.source_id:
            continue
        assert val.value is not None and val.span is not None
        hit = next((obs for obs in form_obs if obs.field == name and obs.value == val.value), None)
        assert hit is not None, name
        assert hit.span.quote == val.span.quote
        assert (hit.span.char_start, hit.span.char_end) == (val.span.char_start, val.span.char_end)

    # Residual supporting TTM − 9M: parser windows reproduce the fixture residual.
    levels = fixture.supporting_levels
    ttm_keys = [k for k in levels if "ttm" in k]
    nine_keys = [k for k in levels if "nine" in k]
    if ttm_keys and nine_keys:
        ttm = levels[ttm_keys[0]]
        nine = levels[nine_keys[0]]
        from longaeva_app.extract.visa_tables import parse_form_financials

        def _level_from_source(level: SupportingLevel) -> float:
            acc, doc = level.source_id.split("/", 1)
            html_l = source_text(acc, doc)
            parsed_l = parse_form_financials(html_l, accession=acc, document=doc, form="10-Q")
            hits = [
                obs
                for obs in parsed_l.observations
                if obs.field == "payments_volume_nominal_us"
                and obs.geography == "global"
                and obs.attributes.get("vintage_role") == "current"
                and obs.span.char_start == level.span.char_start
            ]
            assert hits, level.key
            return hits[0].value

        parser_ttm = _level_from_source(ttm)
        parser_nine = _level_from_source(nine)
        assert parser_ttm - parser_nine == pytest.approx(ttm.value - nine.value, abs=1e-9)

    recomputed = recompute_derived(fixture)
    for name, val in fixture.values.items():
        if val.status != "derived":
            continue
        assert recomputed[name] == pytest.approx(val.value, abs=1e-9), name

    assert EXTRACTOR_ID == "visa_tables"
