"""Tests for Visa definitions (LON-2)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from longaeva_app.collect.edgar_index import SNAPSHOT_PATH, load_snapshot
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import (
    BASIS_VOCABULARY,
    CHANGES,
    FIELDS,
    MODEL_ROLE_VOCABULARY,
    PERIOD_RULE_VOCABULARY,
    SOURCE_VOCABULARY,
    UNIT_VOCABULARY,
    VISA_FISCAL_CALENDAR,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS_MD = PACKAGE_ROOT / "docs" / "definitions.md"
SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
PERIOD_RE = re.compile(r"^FY(20\d{2})Q([1-4])$")

# Teaching-fee patterns from the Stage 1 proposal. Allowed only in the dedicated
# "not an input" section of definitions.md.
TEACHING_PATTERNS = (
    re.compile(r"\$1\s+for\s+every\s+\$100", re.I),
    re.compile(r"\$3\s+for\s+every\s+\$100", re.I),
    re.compile(r"earns\s+\$1\b", re.I),
    re.compile(r"earns\s+\$3\b", re.I),
)

SCAN_ROOTS = (
    PACKAGE_ROOT / "backend",
    PACKAGE_ROOT / "data",
    PACKAGE_ROOT / "docs",
)

SCAN_SUFFIXES = {".py", ".md", ".csv", ".json", ".yaml", ".yml", ".txt", ".toml"}


def _period_key(label: str) -> tuple[int, int]:
    match = PERIOD_RE.match(label)
    assert match, f"bad period label: {label}"
    return int(match.group(1)), int(match.group(2))


def test_field_names_unique_snake_case() -> None:
    names = [field.name for field in FIELDS]
    assert len(names) == len(set(names))
    for name in names:
        assert SNAKE_RE.match(name), name


def test_field_vocabularies_and_citations() -> None:
    for field in FIELDS:
        assert field.unit in UNIT_VOCABULARY, field.name
        assert field.basis in BASIS_VOCABULARY, field.name
        assert field.period_rule in PERIOD_RULE_VOCABULARY, field.name
        assert field.source in SOURCE_VOCABULARY, field.name
        assert field.model_role in MODEL_ROLE_VOCABULARY, field.name
        assert _period_key(field.first_period) <= _period_key(field.last_period), field.name
        assert len(field.citations) >= 1, field.name
        for citation in field.citations:
            assert citation.accession
            assert citation.primary_document
            assert citation.quote
            assert citation.url().startswith("https://www.sec.gov/Archives/edgar/data/1403161/")


def test_cited_accessions_exist_in_snapshot() -> None:
    snapshot = load_snapshot(SNAPSHOT_PATH)
    known = {row["accession"] for row in snapshot["visa_filings"]}
    missing: list[str] = []
    for field in FIELDS:
        for citation in field.citations:
            if citation.accession not in known:
                missing.append(f"{field.name}:{citation.accession}")
    for change in CHANGES:
        for citation in change.citations:
            if citation.accession not in known:
                missing.append(f"change:{change.effective_period}:{citation.accession}")
    assert not missing, f"accessions not in LON-1 snapshot: {missing}"


def test_definitions_md_field_table_matches_fields() -> None:
    text = DEFINITIONS_MD.read_text(encoding="utf-8")
    assert "## 12. Field table" in text
    # Collect backtick-wrapped field names from the field-table section only.
    table_section = text.split("## 12. Field table", 1)[1].split("## 13.", 1)[0]
    table_names = re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", table_section, flags=re.M)
    field_names = [field.name for field in FIELDS]
    assert table_names == field_names, (
        f"doc table and FIELDS diverge.\n"
        f"only_in_doc={sorted(set(table_names) - set(field_names))}\n"
        f"only_in_fields={sorted(set(field_names) - set(table_names))}\n"
        f"order_mismatch={table_names != field_names}"
    )


def test_teaching_fees_only_in_not_an_input_section() -> None:
    doc = DEFINITIONS_MD.read_text(encoding="utf-8")
    assert "## 8. Teaching fees — not an input" in doc
    # Split: everything outside section 8 must be clean; section 8 may mention the example.
    before, rest = doc.split("## 8. Teaching fees — not an input", 1)
    section8, after = rest.split("## 9.", 1)
    for pattern in TEACHING_PATTERNS:
        assert not pattern.search(before), f"teaching pattern outside §8 (before): {pattern.pattern}"
        assert not pattern.search(after), f"teaching pattern outside §8 (after): {pattern.pattern}"
        assert pattern.search(section8) or "teaching" in section8.lower()

    # Package scan: no teaching patterns outside definitions.md section 8.
    # We allow the string "teaching" as a label, but not the $1/$3 constants.
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            # Skip the OpenAPI snapshot (huge, unrelated) and the definitions doc itself
            # (checked above with section gating).
            if path.name == "openapi.json":
                continue
            if path.resolve() == DEFINITIONS_MD.resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in TEACHING_PATTERNS:
                if pattern.search(text):
                    offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{pattern.pattern}")
    assert not offenders, f"teaching-fee constants found outside §8: {offenders}"


def test_visa_fiscal_calendar_q3_fy2026() -> None:
    period = FiscalPeriod(2026, 3)
    assert VISA_FISCAL_CALENDAR.fiscal_year_end_month == 9
    assert VISA_FISCAL_CALENDAR.period_end(period) == date(2026, 6, 30)
    assert VISA_FISCAL_CALENDAR.period_start(period) == date(2026, 4, 1)
    assert VISA_FISCAL_CALENDAR.period_containing(date(2026, 5, 15)) == period
    # Q1 spans the prior calendar year
    q1 = FiscalPeriod(2026, 1)
    assert VISA_FISCAL_CALENDAR.period_end(q1) == date(2025, 12, 31)
    assert VISA_FISCAL_CALENDAR.period_start(q1) == date(2025, 10, 1)


def test_changes_kinds_and_periods() -> None:
    allowed = {"label_change", "format_change", "new_series", "comparability_break"}
    assert CHANGES
    for change in CHANGES:
        assert change.kind in allowed, change.kind
        assert PERIOD_RE.match(change.effective_period), change.effective_period
        assert change.summary
        assert change.citations


def test_definitions_md_required_sections() -> None:
    text = DEFINITIONS_MD.read_text(encoding="utf-8")
    for heading in (
        "## 1. Fiscal calendar",
        "## 2. Activity metrics",
        "## 3. Cross-border volume",
        "## 4. Revenue categories",
        "## 5. Nominal versus constant-dollar",
        "## 6. GAAP versus identified special items",
        "## 7. Yields",
        "## 8. Teaching fees — not an input",
        "## 9. Observation basis vocabulary",
        "## 10. Disclosure change log",
        "## 11. Stability verdict",
        "## 12. Field table",
    ):
        assert heading in text, heading
    # Eligibility counts stated exactly
    assert "**18**" in text
    assert "**28**" in text
    assert "**39**" in text
    assert "**1**" in text
    assert "Origins excluded by LON-2 definition instability | **0**" in text
