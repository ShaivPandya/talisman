"""Apply reviewed observations to a Visa parameter set through the mapping-rule registry.

Preview computes the child set and writes nothing. Apply persists a child parameter
set (or reuses one with the same content hash), ``parameter_update`` rows, and
context rows for observations that do not change a parameter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.db.models import (
    MappingRule,
    Observation,
    ParameterSet,
    ParameterSetContext,
    ParameterUpdate,
    ParameterUpdateObservation,
    Source,
)
from longaeva_app.review.rules import (
    REGISTRY,
    RuleSpec,
    aligned_pairs,
    apply_transform,
    booking_guidance_covers_target,
    registry_families,
    registry_index,
    rule_matches,
    sync_registry,
)
from longaeva_app.review.service import REVIEWED_STATUSES, effective_observation, require_reviewed
from longaeva_app.runs.inputs import parameter_set_from_row

_PERCENT_UNITS = frozenset({"percent", "pct"})


class ApplyError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ProposedUpdate:
    target_parameter: str
    rule_key: str
    rule_version: int
    rule_id: UUID | None
    observation_id: UUID
    before_value: dict[str, Any]
    after_value: dict[str, Any]
    size: float
    rationale: str
    assumption: bool


@dataclass(frozen=True, slots=True)
class ContextItem:
    observation_id: UUID
    reason: str
    rule_key: str | None = None
    rule_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RuleApplication:
    parameter_set_id: UUID
    result_parameter_set_id: UUID | None
    changed: bool
    created: bool
    updates: tuple[ProposedUpdate, ...]
    context: tuple[ContextItem, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "parameter_set_id": str(self.parameter_set_id),
            "result_parameter_set_id": None
            if self.result_parameter_set_id is None
            else str(self.result_parameter_set_id),
            "changed": self.changed,
            "created": self.created,
            "updates": [
                {
                    "target_parameter": item.target_parameter,
                    "rule_key": item.rule_key,
                    "rule_version": item.rule_version,
                    "rule_id": None if item.rule_id is None else str(item.rule_id),
                    "observation_id": str(item.observation_id),
                    "before_value": item.before_value,
                    "after_value": item.after_value,
                    "size": item.size,
                    "rationale": item.rationale,
                    "assumption": item.assumption,
                }
                for item in self.updates
            ],
            "context": [
                {
                    "observation_id": str(item.observation_id),
                    "reason": item.reason,
                    "rule_key": item.rule_key,
                    "rule_id": None if item.rule_id is None else str(item.rule_id),
                }
                for item in self.context
            ],
        }


@dataclass(frozen=True, slots=True)
class _Winner:
    spec: RuleSpec
    observation: Observation
    effective: Mapping[str, Any]


def preview_rules(
    session: Session,
    parameter_set_id: UUID,
    observation_ids: Sequence[UUID] | None = None,
    families: Sequence[str] | None = None,
    *,
    decided_by: str = "preview",
    rationale: str = "preview",
) -> RuleApplication:
    """Compute the application. Does not sync the registry and does not write."""
    return _apply(
        session,
        parameter_set_id,
        observation_ids,
        families,
        decided_by=decided_by,
        rationale=rationale,
        persist=False,
    )


def apply_rules(
    session: Session,
    parameter_set_id: UUID,
    observation_ids: Sequence[UUID] | None = None,
    families: Sequence[str] | None = None,
    *,
    decided_by: str,
    rationale: str,
) -> RuleApplication:
    """Sync the registry, then persist the child set, updates, and context rows."""
    if not decided_by.strip() or not rationale.strip():
        raise ApplyError("decided_by and rationale are required", status_code=422)
    sync_registry(session)
    return _apply(
        session,
        parameter_set_id,
        observation_ids,
        families,
        decided_by=decided_by,
        rationale=rationale,
        persist=True,
    )


def lineage(session: Session, parameter_set_id: UUID) -> list[ParameterSet]:
    """Walk ``parent_id`` from the set back to the root. The root is first."""
    chain: list[ParameterSet] = []
    current = session.get(ParameterSet, parameter_set_id)
    if current is None:
        raise ApplyError(f"Parameter set {parameter_set_id} not found", status_code=404)
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        if current.parent_id is None:
            break
        current = session.get(ParameterSet, current.parent_id)
    chain.reverse()
    return chain


def _apply(
    session: Session,
    parameter_set_id: UUID,
    observation_ids: Sequence[UUID] | None,
    families: Sequence[str] | None,
    *,
    decided_by: str,
    rationale: str,
    persist: bool,
) -> RuleApplication:
    base = session.get(ParameterSet, parameter_set_id)
    if base is None:
        raise ApplyError(f"Parameter set {parameter_set_id} not found", status_code=404)
    if base.company != "visa":
        raise ApplyError("mapping rules apply only to a visa parameter set", status_code=422)
    family_filter = _family_filter(families)
    observations = _select_observations(session, base, observation_ids, family_filter)
    updates, context, child = _plan(session, base, observations, decided_by=decided_by, reviewer_rationale=rationale)
    comparable = ParameterSetCreate(
        company=child.company,
        cutoff_ts=child.cutoff_ts,
        values=child.values,
        ranges=child.ranges,
        evidence_links=child.evidence_links,
        assumption_flags=child.assumption_flags,
        parent_id=base.parent_id,
    )
    changed = comparable.computed_content_hash() != base.content_hash
    digest = child.computed_content_hash()
    if not changed:
        if persist:
            _persist_context(session, base.id, context)
            session.flush()
        return RuleApplication(
            parameter_set_id=base.id,
            result_parameter_set_id=base.id,
            changed=False,
            created=False,
            updates=(),
            context=tuple(context),
        )
    existing = session.execute(select(ParameterSet).where(ParameterSet.content_hash == digest)).scalar_one_or_none()
    created = False
    if persist:
        if existing is None:
            existing = ParameterSet(
                company=child.company,
                cutoff_ts=child.cutoff_ts,
                values=child.values,
                ranges=child.ranges,
                evidence_links={key: link.model_dump(mode="json") for key, link in child.evidence_links.items()},
                assumption_flags=child.assumption_flags,
                content_hash=digest,
                parent_id=base.id,
            )
            session.add(existing)
            session.flush()
            created = True
        _persist_updates(session, existing.id, updates)
        _persist_context(session, existing.id, context)
        session.flush()
        result_id: UUID | None = existing.id
    else:
        result_id = None if existing is None else existing.id
    return RuleApplication(
        parameter_set_id=base.id,
        result_parameter_set_id=result_id,
        changed=True,
        created=created,
        updates=tuple(updates),
        context=tuple(context),
    )


def _family_filter(families: Sequence[str] | None) -> set[str] | None:
    if families is None:
        return None
    return {item.strip().lower() for item in families}


def _select_observations(
    session: Session,
    base: ParameterSet,
    observation_ids: Sequence[UUID] | None,
    families: set[str] | None,
) -> list[Observation]:
    cutoff = _as_utc(base.cutoff_ts)
    if observation_ids is not None:
        rows = require_reviewed(session, list(observation_ids))
        by_id = {row.id: row for row in rows}
        ordered = [by_id[item] for item in observation_ids]
        allowed = registry_families() if families is None else families
        for row in ordered:
            family = row.source_family or ""
            if family not in allowed:
                raise ApplyError(
                    f"Observation {row.id} family {family!r} is outside the requested families",
                    status_code=422,
                )
            _require_published_by_cutoff(session, row, cutoff)
        return ordered
    selected = registry_families() if families is None else families
    if not selected:
        return []
    stmt = (
        select(Observation)
        .join(Source, Observation.source_id == Source.id)
        .where(Observation.review_status.in_(tuple(REVIEWED_STATUSES)))
        .where(Observation.source_family.in_(tuple(selected)))
        .where(Source.publication_ts <= cutoff)
        .order_by(Source.publication_ts, Observation.period_end, Observation.id)
    )
    return list(session.scalars(stmt).all())


def _require_published_by_cutoff(session: Session, observation: Observation, cutoff: datetime) -> None:
    if observation.source_id is None:
        raise ApplyError(f"Observation {observation.id} has no source", status_code=422)
    source = session.get(Source, observation.source_id)
    if source is None:
        raise ApplyError(f"Observation {observation.id} source is missing", status_code=422)
    if _as_utc(source.publication_ts) > cutoff:
        raise ApplyError(
            f"Observation {observation.id} was published after the parameter-set cutoff {cutoff.isoformat()}",
            status_code=422,
        )


def _plan(
    session: Session,
    base: ParameterSet,
    observations: Sequence[Observation],
    *,
    decided_by: str,
    reviewer_rationale: str,
) -> tuple[list[ProposedUpdate], list[ContextItem], ParameterSetCreate]:
    create = parameter_set_from_row(base)
    covers = booking_guidance_covers_target(_as_utc(base.cutoff_ts))
    rule_ids = _stored_rule_ids(session)
    candidates: list[_Winner] = []
    context: list[ContextItem] = []
    for observation in observations:
        effective = effective_observation(session, observation)
        if effective is None:
            raise ApplyError(f"Observation {observation.id} is not reviewed", status_code=422)
        matches = [
            spec
            for spec in REGISTRY
            if rule_matches(
                spec,
                source_family=effective.get("source_family") or observation.source_family,
                statement_type=str(effective["statement_type"]),
                activity_type=effective.get("activity_type"),
                basis=effective.get("basis"),
                unit=str(effective.get("unit") or ""),
                attributes=_attributes(effective),
                guidance_covers_target=covers,
            )
        ]
        transforming = [spec for spec in matches if spec.kind != "context"]
        context_rules = [spec for spec in matches if spec.kind == "context"]
        if transforming:
            for spec in transforming:
                candidates.append(_Winner(spec=spec, observation=observation, effective=effective))
            continue
        if context_rules:
            spec = context_rules[0]
            context.append(
                ContextItem(
                    observation_id=observation.id,
                    reason="context_only",
                    rule_key=spec.rule_key,
                    rule_id=rule_ids.get((spec.rule_key, spec.version)),
                )
            )
            continue
        context.append(ContextItem(observation_id=observation.id, reason="no_adopted_rule"))

    winners, superseded = _winners(candidates, rule_ids)
    context.extend(superseded)
    updates, values, ranges, links, flags = _chain(base, create, winners, rule_ids, decided_by, reviewer_rationale)
    child = ParameterSetCreate(
        company=create.company,
        cutoff_ts=create.cutoff_ts,
        values=values,
        ranges=ranges,
        evidence_links=links,
        assumption_flags=flags,
        parent_id=base.id,
    )
    errors = VisaModel().validate_parameters({name: float(val) for name, val in values.items()})
    if errors:
        raise ApplyError(f"mapped parameters are invalid: {errors}", status_code=422)
    return updates, context, child


def _winners(
    candidates: Sequence[_Winner],
    rule_ids: Mapping[tuple[str, int], UUID],
) -> tuple[list[_Winner], list[ContextItem]]:
    grouped: dict[tuple[str, str], list[_Winner]] = {}
    for item in candidates:
        target = item.spec.target_parameter
        if target is None:
            continue
        grouped.setdefault((item.spec.source_family, target), []).append(item)
    winners: list[_Winner] = []
    context: list[ContextItem] = []
    for group in grouped.values():
        ordered = sorted(group, key=_winner_key, reverse=True)
        kept = ordered[0]
        winners.append(kept)
        for loser in ordered[1:]:
            if loser.observation.id == kept.observation.id and loser.spec.rule_key == kept.spec.rule_key:
                continue
            context.append(
                ContextItem(
                    observation_id=loser.observation.id,
                    reason="superseded",
                    rule_key=loser.spec.rule_key,
                    rule_id=rule_ids.get((loser.spec.rule_key, loser.spec.version)),
                )
            )
    winners.sort(key=lambda item: (registry_index(item.spec), item.spec.rule_key))
    return winners, _dedupe_context(context)


def _winner_key(item: _Winner) -> tuple[int, date, str]:
    period = _period_end(item.effective)
    return (item.spec.priority, period, item.spec.rule_key)


def _chain(
    base: ParameterSet,
    create: ParameterSetCreate,
    winners: Sequence[_Winner],
    rule_ids: Mapping[tuple[str, int], UUID],
    decided_by: str,
    reviewer_rationale: str,
) -> tuple[
    list[ProposedUpdate],
    dict[str, float],
    dict[str, list[float]],
    dict[str, ParameterEvidence],
    dict[str, Any],
]:
    values = {key: float(val) for key, val in create.values.items()}
    ranges = {key: [float(pair[0]), float(pair[1])] for key, pair in create.ranges.items() if len(pair) >= 2}
    links = dict(create.evidence_links)
    flags = dict(create.assumption_flags)
    cutoff = _as_utc(base.cutoff_ts)
    history_cache: dict[tuple[str, int], list[tuple[float, float]]] = {}
    updates: list[ProposedUpdate] = []
    for winner in winners:
        spec = winner.spec
        name = spec.target_parameter
        if name is None or name not in values or name not in ranges:
            raise ApplyError(f"parameter {name!r} is not on the set", status_code=422)
        observed, half_width = _observed_ratio(winner.effective)
        pairs = history_cache.get((spec.rule_key, spec.version))
        if spec.kind == "estimated" and pairs is None:
            pairs = aligned_pairs(spec, cutoff)
            history_cache[(spec.rule_key, spec.version)] = pairs
        before = values[name]
        low, high = ranges[name]
        transformed = apply_transform(
            spec,
            before=before,
            range_low=low,
            range_high=high,
            observed=observed,
            half_width=half_width,
            pairs=pairs,
            cutoff=cutoff,
        )
        values[name] = transformed.value
        ranges[name] = [transformed.stored_range[0], transformed.stored_range[1]]
        previous = links[name]
        observation_ids = list(dict.fromkeys([*previous.observation_ids, winner.observation.id]))
        links[name] = ParameterEvidence(
            observation_ids=observation_ids,
            assumption=transformed.assumption,
            rationale=spec.rationale if transformed.assumption else None,
        )
        flags[name] = transformed.assumption
        stored_rationale = f"{spec.rationale} Applied by {decided_by}: {reviewer_rationale}"
        updates.append(
            ProposedUpdate(
                target_parameter=name,
                rule_key=spec.rule_key,
                rule_version=spec.version,
                rule_id=rule_ids.get((spec.rule_key, spec.version)),
                observation_id=winner.observation.id,
                before_value={"value": before},
                after_value=transformed.after_value,
                size=transformed.size,
                rationale=stored_rationale,
                assumption=transformed.assumption,
            )
        )
    return updates, values, ranges, links, flags


def _persist_updates(session: Session, parameter_set_id: UUID, updates: Sequence[ProposedUpdate]) -> None:
    for item in updates:
        if item.rule_id is None:
            raise ApplyError(f"mapping rule {item.rule_key} v{item.rule_version} is not synced", status_code=422)
        existing = session.scalars(
            select(ParameterUpdate).where(
                ParameterUpdate.parameter_set_id == parameter_set_id,
                ParameterUpdate.target_parameter == item.target_parameter,
                ParameterUpdate.rule_id == item.rule_id,
            )
        ).first()
        if existing is not None:
            continue
        row = ParameterUpdate(
            rule_id=item.rule_id,
            parameter_set_id=parameter_set_id,
            target_parameter=item.target_parameter,
            before_value=item.before_value,
            after_value=item.after_value,
            size=item.size,
            rationale=item.rationale,
        )
        session.add(row)
        session.flush()
        session.add(ParameterUpdateObservation(parameter_update_id=row.id, observation_id=item.observation_id))


def _persist_context(session: Session, parameter_set_id: UUID, context: Sequence[ContextItem]) -> None:
    for item in _dedupe_context(context):
        existing = session.scalars(
            select(ParameterSetContext).where(
                ParameterSetContext.parameter_set_id == parameter_set_id,
                ParameterSetContext.observation_id == item.observation_id,
            )
        ).first()
        if existing is not None:
            continue
        session.add(
            ParameterSetContext(
                parameter_set_id=parameter_set_id,
                observation_id=item.observation_id,
                reason=item.reason,
                rule_id=item.rule_id,
            )
        )


def _dedupe_context(items: Sequence[ContextItem]) -> list[ContextItem]:
    seen: set[UUID] = set()
    kept: list[ContextItem] = []
    for item in items:
        if item.observation_id in seen:
            continue
        seen.add(item.observation_id)
        kept.append(item)
    return kept


def _stored_rule_ids(session: Session) -> dict[tuple[str, int], UUID]:
    rows = session.scalars(select(MappingRule)).all()
    return {(row.rule_key, row.version): row.id for row in rows}


def _observed_ratio(effective: Mapping[str, Any]) -> tuple[float, float]:
    unit = str(effective.get("unit") or "")
    low = effective.get("range_low")
    high = effective.get("range_high")
    if low is not None and high is not None:
        point = (float(low) + float(high)) / 2.0
        half = abs(float(high) - float(low)) / 2.0
        return _to_ratio(point, unit), _to_ratio(half, unit)
    value = effective.get("value")
    if value is None:
        raise ApplyError("observation has no numeric value", status_code=422)
    return _to_ratio(float(value), unit), 0.0


def _to_ratio(value: float, unit: str) -> float:
    if unit in _PERCENT_UNITS:
        return value / 100.0
    if unit == "ratio":
        return value
    raise ApplyError(f"unsupported observation unit {unit!r}", status_code=422)


def _attributes(effective: Mapping[str, Any]) -> dict[str, Any]:
    raw = effective.get("attributes")
    if isinstance(raw, dict):
        return raw
    return {}


def _period_end(effective: Mapping[str, Any]) -> date:
    raw = effective.get("period_end")
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        return date.fromisoformat(raw[:10])
    return date.min


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "ApplyError",
    "ContextItem",
    "ProposedUpdate",
    "RuleApplication",
    "apply_rules",
    "lineage",
    "preview_rules",
]
