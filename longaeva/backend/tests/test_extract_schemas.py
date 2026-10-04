"""Extraction item rules, schema conversion, and quote location (LON-16)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from longaeva_app.extract.cache import prompt_hash
from longaeva_app.extract.llm import locate_quote
from longaeva_app.extract.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from longaeva_app.extract.schemas import (
    ExtractedObservation,
    extraction_json_schema,
    gemini_response_schema,
    openai_strict_schema,
)


def _item(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "statement_type": "measured",
        "activity_type": "room_nights",
        "geography": "global",
        "period_start": "2025-07-01",
        "period_end": "2025-09-30",
        "value": 8.0,
        "range_low": None,
        "range_high": None,
        "unit": "percent",
        "basis": "units",
        "quote": "Room nights grew 8%",
    }
    payload.update(overrides)
    return payload


def test_measured_item_accepts_a_stated_value() -> None:
    item = ExtractedObservation.model_validate(_item())
    assert item.value == 8.0
    assert item.period_start == date(2025, 7, 1)
    assert item.unit == "percent"


def test_measured_and_guidance_need_a_number() -> None:
    with pytest.raises(ValidationError, match="value or a range"):
        ExtractedObservation.model_validate(_item(value=None, range_low=None, range_high=None))
    with pytest.raises(ValidationError, match="value or a range"):
        ExtractedObservation.model_validate(
            _item(statement_type="guidance", value=None, range_low=None, range_high=None)
        )


def test_qualitative_rejects_numbers() -> None:
    with pytest.raises(ValidationError, match="qualitative"):
        ExtractedObservation.model_validate(_item(statement_type="qualitative", unit="text", value=8.0))
    item = ExtractedObservation.model_validate(
        _item(statement_type="qualitative", unit="text", value=None, range_low=None, range_high=None)
    )
    assert item.value is None


def test_range_bounds_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="range_low"):
        ExtractedObservation.model_validate(_item(value=None, range_low=12.0, range_high=4.0))
    with pytest.raises(ValidationError, match="range_high requires range_low"):
        ExtractedObservation.model_validate(_item(value=None, range_low=None, range_high=4.0))


def test_confidence_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedObservation.model_validate(_item(confidence=0.9))


def test_schema_converters_drop_defaults_and_inline_refs() -> None:
    schema = extraction_json_schema()
    assert "$defs" not in schema
    assert "$ref" not in str(schema)
    strict = openai_strict_schema(schema)
    observations = strict["properties"]["observations"]
    item = observations["items"]
    assert item["additionalProperties"] is False
    assert "quote" in item["required"]
    assert "value" in item["required"]
    assert "default" not in str(strict)
    gemini = gemini_response_schema(schema)
    activity = gemini["properties"]["observations"]["items"]["properties"]["activity_type"]
    assert activity.get("nullable") is True
    assert "additionalProperties" not in activity


def test_prompt_hash_is_stable() -> None:
    schema = extraction_json_schema()
    first = prompt_hash(
        prompt_version=PROMPT_VERSION, system=SYSTEM_PROMPT, user="Passage:\nRoom nights", schema=schema
    )
    reordered = {key: schema[key] for key in reversed(list(schema))}
    second = prompt_hash(
        prompt_version=PROMPT_VERSION, system=SYSTEM_PROMPT, user="Passage:\nRoom nights", schema=reordered
    )
    assert first == second
    changed = prompt_hash(prompt_version=PROMPT_VERSION, system=SYSTEM_PROMPT, user="other", schema=schema)
    assert changed != first


def test_locate_quote_tolerates_whitespace() -> None:
    passage = "Room nights grew\n8% compared to last year."
    located = locate_quote(passage, "Room nights grew 8%")
    assert located is not None
    start, end = located
    assert "8%" in passage[start:end]
    assert locate_quote(passage, "not in the passage") is None
