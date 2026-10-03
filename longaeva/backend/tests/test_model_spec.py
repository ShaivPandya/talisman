"""Keep ``docs/model-spec.md`` tables in sync with the Visa engine (LON-19)."""

from __future__ import annotations

import re
from pathlib import Path

from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.parameters import FREE_PARAMETER_NAMES, VISA_PARAMETERS
from longaeva_app.companies.visa.state import STATE_VARIABLES

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPEC = PACKAGE_ROOT / "docs" / "model-spec.md"

_ROW_NAME = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|", re.M)


def _section(text: str, heading: str, next_heading_prefix: str = "## ") -> str:
    assert heading in text, heading
    after = text.split(heading, 1)[1]
    # Split on the next same-level or higher heading.
    parts = re.split(rf"\n(?={re.escape(next_heading_prefix)})", after, maxsplit=1)
    return parts[0]


def test_free_parameter_count_in_mr09_range() -> None:
    assert 6 <= len(FREE_PARAMETER_NAMES) <= 8
    assert len(VISA_PARAMETERS) == 32
    assert sum(1 for p in VISA_PARAMETERS if p.role == "free") == len(FREE_PARAMETER_NAMES)


def test_model_spec_state_table_matches_code() -> None:
    text = MODEL_SPEC.read_text(encoding="utf-8")
    section = _section(text, "## 2. State variables")
    names = _ROW_NAME.findall(section)
    assert names == [spec.name for spec in STATE_VARIABLES]


def test_model_spec_parameter_table_matches_code() -> None:
    text = MODEL_SPEC.read_text(encoding="utf-8")
    section = _section(text, "## 6. Parameters")
    # Only the first markdown table in §6 is the parameter inventory (LON-20 adds more).
    table = section.split("\n\n### ", 1)[0]
    names = _ROW_NAME.findall(table)
    assert names == [spec.name for spec in VISA_PARAMETERS]


def test_model_spec_required_sections() -> None:
    text = MODEL_SPEC.read_text(encoding="utf-8")
    for heading in (
        "## 1. Overview",
        "## 2. State variables",
        "## 3. Sampler contract",
        "## 4. Transition rules",
        "## 5. Revenue rules, identities and switches",
        "## 6. Parameters",
        "## 7. Outputs",
        "## 8. Performance (NR-01)",
        "## 9. Handoffs",
    ):
        assert heading in text, heading
    model = VisaModel()
    assert model.key == "visa"
    assert "service_lag" in model.default_switches()
    assert "pool_mix" in model.default_switches()
