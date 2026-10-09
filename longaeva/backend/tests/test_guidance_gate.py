"""Guidance availability gate tests."""

from __future__ import annotations

import csv
import json
from typing import Any, cast

import pytest

from longaeva_app.collect.edgar_index import PACKAGE_ROOT
from longaeva_app.collect.visa_ir import (
    AVAILABILITY_PATH,
    DECK_EVENT_WINDOW_SECONDS,
    FIXTURE_DIR,
    MANIFEST_PATH,
    PROBE_PATH,
    STATEMENTS_PATH,
    load_manifest,
    load_origins,
)
from longaeva_app.extract.visa_guidance import (
    CONSENSUS_UNAVAILABLE_LABEL,
    detect_outlook_slide,
    find_transcript_outlook,
    group_phrases,
    load_fixture,
    parse_guidance_phrase,
    parse_outlook_slide_words,
    required_fixture_paths,
    to_observation_create,
)

ALLOWED_CONSENSUS = CONSENSUS_UNAVAILABLE_LABEL.lower()
LON7_ARTIFACTS = [
    MANIFEST_PATH,
    AVAILABILITY_PATH,
    STATEMENTS_PATH,
    PROBE_PATH,
    PACKAGE_ROOT / "docs" / "gates" / "guidance.md",
    *required_fixture_paths(),
]


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return load_manifest()


@pytest.fixture(scope="module")
def availability() -> list[dict[str, str]]:
    assert AVAILABILITY_PATH.is_file(), "availability.csv missing; run visa_ir probe"
    with AVAILABILITY_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def statements() -> list[dict[str, str]]:
    assert STATEMENTS_PATH.is_file(), "statements.csv missing; run visa_ir probe"
    with STATEMENTS_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    assert PROBE_PATH.is_file(), "probe.json missing; run visa_ir probe"
    return cast(dict[str, Any], json.loads(PROBE_PATH.read_text(encoding="utf-8")))


def test_manifest_required_fields(manifest: dict[str, Any]) -> None:
    assert MANIFEST_PATH.is_file()
    assert manifest["decision"]["linear_id"] == "LON-7"
    assert manifest["decision"]["extension_sources"] == "decks_plus_transcripts"
    assert manifest["decision"]["retention"] == "metadata_and_short_quotes"
    assert manifest["access"]["redistribution"] == "fetch_script"
    assert manifest["access"]["ir_quarterly_html"]["status"] == "unavailable_for_automation"
    assert manifest["access"]["ir_quarterly_html"]["http_status"] == 403
    assert manifest["labels"]["estimates_unavailable"] == CONSENSUS_UNAVAILABLE_LABEL
    assert manifest["labels"]["company_guidance"] == "company guidance"
    assert "visa_site" in manifest["terms"]
    assert "factset_callstreet" in manifest["terms"]
    assert len(manifest["origins"]) == 19
    assert len(manifest["analyst_estimates_checked"]) >= 8


def test_manifest_fetch_script_policy(manifest: dict[str, Any]) -> None:
    assert manifest["access"]["redistribution"] == "fetch_script"
    assert manifest["terms"]["visa_site"]["redistribution"] == "fetch_script"
    assert manifest["terms"]["factset_callstreet"]["redistribution"] == "fetch_script"


def test_availability_covers_origins(availability: list[dict[str, str]]) -> None:
    origins = load_origins()
    expected = {f"FY{int(r['fiscal_year'])}Q{int(r['fiscal_quarter'])}" for r in origins}
    got = {r["origin_label"] for r in availability}
    assert got == expected
    assert len(availability) == 19


def test_outlook_quarter_matches_target(
    availability: list[dict[str, str]],
    statements: list[dict[str, str]],
) -> None:
    by_origin = {r["origin_label"]: r for r in availability}
    for stmt in statements:
        if stmt["period_kind"] != "next_quarter":
            continue
        if not stmt.get("range_low"):
            continue
        avail = by_origin[stmt["origin_label"]]
        assert stmt["target_fiscal_year"] == avail["target_fiscal_year"]
        assert stmt["target_fiscal_quarter"] == avail["target_fiscal_quarter"]


def test_timing_rule_for_decks(availability: list[dict[str, str]]) -> None:
    decks = [r for r in availability if r["guidance_source"] == "deck"]
    assert len(decks) == 11
    for row in decks:
        assert row["deck_within_event_window"] == "true"
        delta = int(row["deck_last_modified_delta_seconds"])
        assert abs(delta) <= DECK_EVENT_WINDOW_SECONDS
        assert row["deck_sha256"]
        assert len(row["deck_sha256"]) == 64


def test_coverage_summary(availability: list[dict[str, str]], probe: dict[str, Any]) -> None:
    covered = [r for r in availability if r["guidance_source"] in {"deck", "transcript"}]
    gaps = [r for r in availability if r["guidance_source"] == "none"]
    assert len(covered) == 16
    assert len(gaps) == 3
    assert {r["origin_label"] for r in gaps} == {"FY2022Q2", "FY2023Q3", "FY2023Q4"}
    assert probe["coverage"]["n_with_next_quarter_guidance"] == 16
    assert probe["estimates_unavailable_label"] == CONSENSUS_UNAVAILABLE_LABEL


def test_lexicon_known_phrases() -> None:
    cases = [
        ("Low double-digit", (10.0, 12.0)),
        ("low-double digits", (10.0, 12.0)),
        ("High-teens", (17.0, 19.0)),
        ("Upper mid to high single-digit", (5.0, 9.0)),
        ("High end of low double-digit", (11.0, 12.0)),
        ("Low-end of mid-teens", (14.0, 15.0)),
        ("High-single-digit to low-double-digit", (7.0, 12.0)),
        ("Mid-to high-single-digit", (4.0, 9.0)),
        ("approximately flat", (-1.0, 1.0)),
        ("high-teens to 20%", (17.0, 20.0)),
        ("~1.0%", (1.0, 1.0)),
    ]
    for raw, expected in cases:
        assert parse_guidance_phrase(raw) == expected, raw


def test_lexicon_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown guidance phrase"):
        parse_guidance_phrase("substantially higher forever")


def test_statements_phrases_parse(statements: list[dict[str, str]]) -> None:
    for stmt in statements:
        if not stmt.get("range_low"):
            # Relative opex rows are allowed without a resolved interval.
            assert "relative" in stmt["note"] or "lexicon miss" not in stmt["note"]
            continue
        low, high = parse_guidance_phrase(stmt["phrase"])
        assert float(stmt["range_low"]) == low
        assert float(stmt["range_high"]) == high


def test_layout_parser_synthetic_wrapped_cells() -> None:
    # Synthetic words mimicking the outlook slide: Q2/FY headers + glued label.
    words = [
        {"text": "Financial", "x0": 40, "x1": 80, "top": 40, "bottom": 50},
        {"text": "Outlook", "x0": 82, "x1": 120, "top": 40, "bottom": 50},
        {"text": "for", "x0": 122, "x1": 140, "top": 40, "bottom": 50},
        {"text": "Fiscal", "x0": 142, "x1": 170, "top": 40, "bottom": 50},
        {"text": "Second", "x0": 172, "x1": 210, "top": 40, "bottom": 50},
        {"text": "Quarter", "x0": 212, "x1": 250, "top": 40, "bottom": 50},
        {"text": "Q2", "x0": 300, "x1": 320, "top": 80, "bottom": 90},
        {"text": "2024", "x0": 322, "x1": 350, "top": 80, "bottom": 90},
        {"text": "Full-Year", "x0": 420, "x1": 470, "top": 80, "bottom": 90},
        {"text": "2024", "x0": 472, "x1": 500, "top": 80, "bottom": 90},
        {"text": "YoY", "x0": 40, "x1": 60, "top": 100, "bottom": 110},
        {"text": "increase", "x0": 62, "x1": 110, "top": 100, "bottom": 110},
        # Net Revenue Growth Low double-digit (glued value on same line)
        {"text": "Net", "x0": 40, "x1": 60, "top": 140, "bottom": 150},
        {"text": "Revenue", "x0": 62, "x1": 110, "top": 140, "bottom": 150},
        {"text": "Growth", "x0": 112, "x1": 150, "top": 140, "bottom": 150},
        {"text": "Low", "x0": 280, "x1": 300, "top": 140, "bottom": 150},
        {"text": "double-digit", "x0": 302, "x1": 370, "top": 140, "bottom": 150},
        {"text": "Low", "x0": 420, "x1": 440, "top": 140, "bottom": 150},
        {"text": "double-digit", "x0": 442, "x1": 510, "top": 140, "bottom": 150},
        {"text": "Operating", "x0": 40, "x1": 90, "top": 180, "bottom": 190},
        {"text": "Expense", "x0": 92, "x1": 140, "top": 180, "bottom": 190},
        {"text": "Growth", "x0": 142, "x1": 180, "top": 180, "bottom": 190},
        {"text": "High", "x0": 280, "x1": 305, "top": 180, "bottom": 190},
        {"text": "single-digit", "x0": 307, "x1": 380, "top": 180, "bottom": 190},
        {"text": "Low", "x0": 420, "x1": 440, "top": 180, "bottom": 190},
        {"text": "double-digit", "x0": 442, "x1": 510, "top": 180, "bottom": 190},
        {"text": "Diluted", "x0": 40, "x1": 80, "top": 220, "bottom": 230},
        {"text": "Class", "x0": 82, "x1": 110, "top": 220, "bottom": 230},
        {"text": "A", "x0": 112, "x1": 120, "top": 220, "bottom": 230},
        {"text": "Common", "x0": 122, "x1": 160, "top": 220, "bottom": 230},
        {"text": "Stock", "x0": 162, "x1": 190, "top": 220, "bottom": 230},
        {"text": "Earnings", "x0": 192, "x1": 240, "top": 220, "bottom": 230},
        {"text": "Per", "x0": 242, "x1": 260, "top": 220, "bottom": 230},
        {"text": "Share", "x0": 262, "x1": 295, "top": 220, "bottom": 230},
        {"text": "Growth", "x0": 297, "x1": 340, "top": 220, "bottom": 230},
        {"text": "High-teens", "x0": 350, "x1": 410, "top": 220, "bottom": 230},
        {"text": "Low-teens", "x0": 450, "x1": 510, "top": 220, "bottom": 230},
        {"text": "(1)", "x0": 40, "x1": 55, "top": 280, "bottom": 290},
        {"text": "Refer", "x0": 57, "x1": 90, "top": 280, "bottom": 290},
    ]
    parsed = parse_outlook_slide_words(words)
    assert parsed["quarter_header"] == "Q2 2024"
    assert parsed["cells"][("net_revenue", "q")] == "Low double-digit"
    assert parsed["cells"][("operating_expenses", "q")] == "High single-digit"
    assert "High-teens" in parsed["cells"][("diluted_eps", "q")]


def test_detect_outlook_and_group_phrases() -> None:
    text = "Financial Outlook for Fiscal Third Quarter and Fiscal Full-Year 2024\nYoY"
    detected = detect_outlook_slide(text)
    assert detected["outlook_type"] == "next_quarter_and_full_year"
    assert detected["guided_quarter"] == 3
    fy_only = detect_outlook_slide("Financial Outlook for Fiscal Full-Year 2024")
    assert fy_only["outlook_type"] == "full_year_only"
    phrases = group_phrases(
        [
            {"text": "Low", "x0": 10, "x1": 30, "top": 50, "bottom": 60},
            {"text": "double-digit", "x0": 32, "x1": 90, "top": 50, "bottom": 60},
            {"text": "High", "x0": 200, "x1": 230, "top": 50, "bottom": 60},
        ],
        gap=6,
    )
    assert phrases[0]["text"] == "Low double-digit"
    assert phrases[1]["text"] == "High"


def test_transcript_finder_rejects_relative_only() -> None:
    text = (
        "Second quarter net revenue growth is expected to be lower than the first quarter because of the Russia impact."
    )
    found = find_transcript_outlook(text)
    assert found["net_revenue_phrase"] is None

    text2 = (
        "third quarter net revenue growth is expected to be in the low-double digits, "
        "inclusive of an approximately 1-point drag from exchange rates. "
        "Q3 non-GAAP operating expense growth is expected to be 2 to 3 points lower "
        "than the second quarter."
    )
    found2 = find_transcript_outlook(text2)
    assert found2["net_revenue_phrase"] == "low-double digits"
    assert found2["opex_relative"] is not None
    assert found2["opex_relative"]["points_lower_low"] == 2


def test_sample_fixtures_validate_observation_create() -> None:
    paths = required_fixture_paths()
    assert len(paths) == 4
    for path in paths:
        assert path.is_file(), path.name
        fixture = load_fixture(path)
        assert fixture.labels["estimates_unavailable"] == CONSENSUS_UNAVAILABLE_LABEL
        assert fixture.labels["company_guidance"] == "company guidance"
        for obs in fixture.observations:
            assert obs.statement_type == "guidance"
            created = to_observation_create(obs, fixture.source.url)
            assert created.statement_type == "guidance"
            assert created.range_low is not None


def test_consensus_wording_rule() -> None:
    for path in LON7_ARTIFACTS:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        # Allow the exact unavailable label; forbid other uses of "consensus".
        scrubbed = lower.replace(ALLOWED_CONSENSUS, "")
        assert "consensus" not in scrubbed, f"bare consensus in {path}"


def test_no_pdfs_under_guidance_fixtures() -> None:
    assert FIXTURE_DIR.is_dir()
    for path in FIXTURE_DIR.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() != ".pdf"
            assert (
                path.name
                in {
                    "availability.csv",
                    "statements.csv",
                    "probe.json",
                }
                or path.suffix == ".json"
            )


def test_no_users_paths_in_gate_artifacts() -> None:
    for path in LON7_ARTIFACTS:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "SEC_USER_AGENT=" not in text


def test_probe_metadata_only(probe: dict[str, Any]) -> None:
    assert probe["generated_for"] == "LON-7"
    for doc in probe["documents"]:
        assert "prices" not in doc
        assert "rows" not in doc
        # No absolute cache paths leaked.
        blob = json.dumps(doc)
        assert "/Users/" not in blob
        assert "var/cache" not in blob or "cache_path" not in doc
