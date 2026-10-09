"""Pydantic schemas for passage-only LLM extraction.

Schema converters follow the JSON-schema shaping in Talisman's ``llm_utils.py``.
They are copied here and are not imported from Talisman.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ExtractStatementType = Literal["measured", "guidance", "qualitative"]

_DROP_KEYS = {"$defs", "$schema", "default", "examples", "title", "format"}


class ExtractedObservation(BaseModel):
    """One observation the model claims is stated in the supplied passage."""

    model_config = ConfigDict(extra="forbid")

    statement_type: ExtractStatementType = Field(
        description="measured (a reported result), guidance (a company outlook), or qualitative (no number)."
    )
    activity_type: str | None = Field(
        default=None,
        description="Short snake_case label, such as room_nights or gross_travel_bookings. Null if unclear.",
    )
    geography: str | None = Field(default=None, description="Geography as stated, or null.")
    period_start: date = Field(description="ISO date YYYY-MM-DD. Start of the period the statement is about.")
    period_end: date = Field(description="ISO date YYYY-MM-DD. End of the period the statement is about.")
    value: float | None = Field(
        default=None,
        description="Point value as stated. For a percent, use the stated number (8 for 8%), not a fraction. Null for a range or qualitative statement.",
    )
    range_low: float | None = Field(default=None, description="Inclusive range low, or null.")
    range_high: float | None = Field(default=None, description="Inclusive range high, or null.")
    unit: str = Field(
        min_length=1,
        description="percent for percentages, the stated unit otherwise. Use text for a qualitative statement.",
    )
    basis: str | None = Field(
        default=None,
        description="units, as_reported, or constant_currency when the passage says so. Null if not stated.",
    )
    quote: str = Field(
        min_length=1,
        description="Verbatim substring of the passage that states this observation, including the number when there is one.",
    )

    @model_validator(mode="after")
    def _statement_rules(self) -> ExtractedObservation:
        if self.range_low is None and self.range_high is not None:
            raise ValueError("range_high requires range_low")
        if self.range_low is not None and self.range_high is not None and self.range_low > self.range_high:
            raise ValueError("range_low must be <= range_high")
        has_number = self.value is not None or self.range_low is not None or self.range_high is not None
        if self.statement_type == "qualitative":
            if has_number:
                raise ValueError("qualitative observations cannot carry a value or a range")
        elif self.value is None and self.range_low is None:
            raise ValueError("measured and guidance observations need a value or a range")
        return self


class ExtractionResponse(BaseModel):
    """Top-level tool / JSON-schema payload. An empty list is valid."""

    model_config = ConfigDict(extra="forbid")

    observations: list[ExtractedObservation] = Field(
        description="Observations stated in the passage. Empty when the passage states none."
    )


def extraction_json_schema() -> dict[str, Any]:
    """Canonical JSON schema hashed into the cache key and sent to providers."""
    return _inline_refs(ExtractionResponse.model_json_schema())


def openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON Schema for OpenAI strict structured outputs and Anthropic tools."""

    def convert(value: Any) -> Any:
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"default", "format", "$schema", "$defs"}:
                continue
            converted[key] = convert(item)
        properties = converted.get("properties")
        is_object = converted.get("type") == "object" or isinstance(properties, dict)
        if is_object:
            converted["additionalProperties"] = False
            if isinstance(properties, dict):
                converted["required"] = list(properties.keys())
        return converted

    converted = convert(_inline_refs(schema))
    return converted if isinstance(converted, dict) else {}


def gemini_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON Schema into the subset Gemini response schemas accept."""

    def convert(value: Any) -> Any:
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        converted: dict[str, Any] = {}
        nullable = False
        for key, item in value.items():
            if key in _DROP_KEYS:
                continue
            if key in {"anyOf", "oneOf"} and isinstance(item, list):
                non_null = [
                    candidate
                    for candidate in item
                    if not (isinstance(candidate, dict) and candidate.get("type") == "null")
                ]
                if len(non_null) == 1 and len(non_null) != len(item):
                    nested = convert(non_null[0])
                    if isinstance(nested, dict):
                        converted.update(nested)
                        nullable = True
                    continue
            if key == "type" and isinstance(item, list):
                non_null_types = [type_name for type_name in item if type_name != "null"]
                if len(non_null_types) == 1:
                    converted[key] = non_null_types[0]
                    nullable = True
                    continue
            converted[key] = convert(item)
        properties = converted.get("properties")
        if converted.get("type") == "object" or isinstance(properties, dict):
            converted.pop("additionalProperties", None)
        if nullable:
            converted["nullable"] = True
        return converted

    converted = convert(_inline_refs(schema))
    return converted if isinstance(converted, dict) else {}


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs")
    root_defs: dict[str, Any] = defs if isinstance(defs, dict) else {}

    def resolve(value: Any) -> Any:
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, dict):
            return value
        ref = value.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            target = root_defs.get(name)
            if isinstance(target, dict):
                merged = resolve(copy.deepcopy(target))
                siblings = {key: resolve(item) for key, item in value.items() if key != "$ref"}
                if isinstance(merged, dict):
                    merged.update(siblings)
                    return merged
        return {key: resolve(item) for key, item in value.items() if key not in {"$defs", "$schema"}}

    resolved = resolve(schema)
    return resolved if isinstance(resolved, dict) else {}
