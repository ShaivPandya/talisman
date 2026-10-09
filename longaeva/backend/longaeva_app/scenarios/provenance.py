"""Rule, observation, and source references for an attribution row."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ObservationView:
    observation_id: str
    source_id: str | None
    document_text_id: str | None
    span_page: int | None
    span_char_start: int | None
    span_char_end: int | None
    review_status: str


@dataclass(frozen=True, slots=True)
class UpdateView:
    target_parameter: str
    rule_id: str | None


@dataclass(frozen=True, slots=True)
class RuleView:
    rule_id: str
    rule_key: str
    version: int


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    observation_id: str | None = None
    source_id: str | None = None
    document_text_id: str | None = None
    span_page: int | None = None
    span_char_start: int | None = None
    span_char_end: int | None = None
    rule_id: str | None = None
    rule_key: str | None = None
    rule_version: int | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceBundle:
    observation_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    rule_ids: tuple[str, ...]
    refs: tuple[ProvenanceRef, ...]


def _unique(values: Sequence[str | None]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return tuple(seen)


def provenance_for_parameter(
    parameter: str,
    observation_ids: Sequence[str],
    *,
    observations: Mapping[str, ObservationView],
    evidence_index: Mapping[str, Mapping[str, Any]],
    updates: Sequence[UpdateView],
    rules: Mapping[str, RuleView],
) -> ProvenanceBundle:
    """Resolve ids for one parameter.

    Database rows win. A calibration UUID that is not a database row falls back
    to ``evidence_index`` (document key and character span).
    """
    refs: list[ProvenanceRef] = []
    for raw_id in observation_ids:
        obs_id = str(raw_id)
        row = observations.get(obs_id)
        if row is not None:
            refs.append(
                ProvenanceRef(
                    observation_id=row.observation_id,
                    source_id=row.source_id,
                    document_text_id=row.document_text_id,
                    span_page=row.span_page,
                    span_char_start=row.span_char_start,
                    span_char_end=row.span_char_end,
                )
            )
            continue
        indexed = evidence_index.get(obs_id)
        if isinstance(indexed, Mapping):
            source = indexed.get("source_id")
            start = indexed.get("char_start")
            end = indexed.get("char_end")
            refs.append(
                ProvenanceRef(
                    observation_id=obs_id,
                    source_id=str(source) if source else None,
                    span_char_start=int(start) if isinstance(start, int) else None,
                    span_char_end=int(end) if isinstance(end, int) else None,
                )
            )
            continue
        refs.append(ProvenanceRef(observation_id=obs_id))

    rule_ids: list[str] = []
    for update in updates:
        if update.target_parameter != parameter or not update.rule_id:
            continue
        if update.rule_id in rule_ids:
            continue
        rule_ids.append(update.rule_id)
        rule = rules.get(update.rule_id)
        refs.append(
            ProvenanceRef(
                rule_id=update.rule_id,
                rule_key=None if rule is None else rule.rule_key,
                rule_version=None if rule is None else rule.version,
            )
        )

    return ProvenanceBundle(
        observation_ids=_unique([ref.observation_id for ref in refs]),
        source_ids=_unique([ref.source_id for ref in refs]),
        rule_ids=tuple(rule_ids),
        refs=tuple(refs),
    )


__all__ = [
    "ObservationView",
    "ProvenanceBundle",
    "ProvenanceRef",
    "RuleView",
    "UpdateView",
    "provenance_for_parameter",
]
