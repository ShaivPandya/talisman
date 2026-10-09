"""Parameter-set reads and mapping-rule application."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import (
    ContextItemRead,
    MappingRuleRead,
    ParameterSetRead,
    ParameterUpdateDetailRead,
    ProposedUpdateRead,
    RuleApplicationRead,
    RuleApplicationRequest,
)
from longaeva_app.api.workspace_schemas import ParameterEvidenceRead
from longaeva_app.db.models import (
    MappingRule,
    ParameterSet,
    ParameterSetContext,
    ParameterUpdate,
    ParameterUpdateObservation,
)
from longaeva_app.db.session import get_db
from longaeva_app.review.apply import ApplyError, RuleApplication, apply_rules, lineage, preview_rules
from longaeva_app.review.rules import RuleRegistryError, sync_registry
from longaeva_app.review.service import ReviewError
from longaeva_app.workspace import parameter_evidence

router = APIRouter(prefix="/parameter-sets", tags=["parameter-sets"])
rules_router = APIRouter(prefix="/mapping-rules", tags=["mapping-rules"])


@router.get("/{parameter_set_id}/evidence", response_model=ParameterEvidenceRead)
def get_parameter_evidence(
    parameter_set_id: uuid.UUID,
    parameter: str = Query(),
    session: Session = Depends(get_db),
) -> ParameterEvidenceRead:
    return parameter_evidence(session, parameter_set_id, parameter)


@router.get("", response_model=list[ParameterSetRead])
def list_parameter_sets(
    company: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[ParameterSet]:
    stmt = select(ParameterSet).order_by(ParameterSet.created_at.desc()).limit(limit)
    if company is not None:
        stmt = stmt.where(ParameterSet.company == company)
    return list(session.scalars(stmt).all())


@router.post("/{parameter_set_id}/rule-preview", response_model=RuleApplicationRead)
def preview_parameter_rules(
    parameter_set_id: uuid.UUID,
    body: RuleApplicationRequest,
    session: Session = Depends(get_db),
) -> RuleApplicationRead:
    try:
        result = preview_rules(
            session,
            parameter_set_id,
            body.observation_ids,
            body.families,
            decided_by=body.decided_by,
            rationale=body.rationale,
        )
        return _application_read(result)
    except (ApplyError, ReviewError) as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{parameter_set_id}/apply-rules", response_model=RuleApplicationRead)
def apply_parameter_rules(
    parameter_set_id: uuid.UUID,
    body: RuleApplicationRequest,
    response: Response,
    session: Session = Depends(get_db),
) -> RuleApplicationRead:
    try:
        result = apply_rules(
            session,
            parameter_set_id,
            body.observation_ids,
            body.families,
            decided_by=body.decided_by,
            rationale=body.rationale,
        )
        session.commit()
        response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return _application_read(result)
    except RuleRegistryError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except (ApplyError, ReviewError) as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{parameter_set_id}/updates", response_model=list[ParameterUpdateDetailRead])
def list_parameter_updates(
    parameter_set_id: uuid.UUID,
    session: Session = Depends(get_db),
) -> list[ParameterUpdateDetailRead]:
    _require_set(session, parameter_set_id)
    rows = list(
        session.scalars(
            select(ParameterUpdate)
            .where(ParameterUpdate.parameter_set_id == parameter_set_id)
            .order_by(ParameterUpdate.created_at, ParameterUpdate.target_parameter)
        ).all()
    )
    rule_ids = {row.rule_id for row in rows if row.rule_id is not None}
    rules = (
        {row.id: row for row in session.scalars(select(MappingRule).where(MappingRule.id.in_(rule_ids))).all()}
        if rule_ids
        else {}
    )
    update_ids = [row.id for row in rows]
    links = (
        list(
            session.scalars(
                select(ParameterUpdateObservation).where(ParameterUpdateObservation.parameter_update_id.in_(update_ids))
            ).all()
        )
        if update_ids
        else []
    )
    by_update: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in links:
        by_update.setdefault(link.parameter_update_id, []).append(link.observation_id)
    detailed: list[ParameterUpdateDetailRead] = []
    for row in rows:
        rule = None if row.rule_id is None else rules.get(row.rule_id)
        detailed.append(
            ParameterUpdateDetailRead(
                id=row.id,
                rule_id=row.rule_id,
                rule_key=None if rule is None else rule.rule_key,
                rule_version=None if rule is None else rule.version,
                parameter_set_id=row.parameter_set_id,
                target_parameter=row.target_parameter,
                before_value=row.before_value,
                after_value=row.after_value,
                size=row.size,
                rationale=row.rationale,
                observation_ids=by_update.get(row.id, []),
                created_at=row.created_at,
            )
        )
    return detailed


@router.get("/{parameter_set_id}/context", response_model=list[ContextItemRead])
def list_parameter_context(
    parameter_set_id: uuid.UUID,
    session: Session = Depends(get_db),
) -> list[ContextItemRead]:
    _require_set(session, parameter_set_id)
    rows = list(
        session.scalars(
            select(ParameterSetContext)
            .where(ParameterSetContext.parameter_set_id == parameter_set_id)
            .order_by(ParameterSetContext.created_at)
        ).all()
    )
    rule_ids = {row.rule_id for row in rows if row.rule_id is not None}
    rules = (
        {row.id: row for row in session.scalars(select(MappingRule).where(MappingRule.id.in_(rule_ids))).all()}
        if rule_ids
        else {}
    )
    items: list[ContextItemRead] = []
    for row in rows:
        rule = None if row.rule_id is None else rules.get(row.rule_id)
        items.append(
            ContextItemRead(
                observation_id=row.observation_id,
                reason=row.reason,
                rule_key=None if rule is None else rule.rule_key,
                rule_id=row.rule_id,
            )
        )
    return items


@router.get("/{parameter_set_id}/lineage", response_model=list[ParameterSetRead])
def get_parameter_lineage(
    parameter_set_id: uuid.UUID,
    session: Session = Depends(get_db),
) -> list[ParameterSet]:
    try:
        return lineage(session, parameter_set_id)
    except ApplyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{parameter_set_id}", response_model=ParameterSetRead)
def get_parameter_set(parameter_set_id: uuid.UUID, session: Session = Depends(get_db)) -> ParameterSet:
    return _require_set(session, parameter_set_id)


@rules_router.get("", response_model=list[MappingRuleRead])
def list_mapping_rules(session: Session = Depends(get_db)) -> list[MappingRule]:
    try:
        rows = sync_registry(session)
        session.commit()
        return rows
    except RuleRegistryError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc


@rules_router.get("/{rule_id}", response_model=MappingRuleRead)
def get_mapping_rule(rule_id: uuid.UUID, session: Session = Depends(get_db)) -> MappingRule:
    try:
        sync_registry(session)
        session.commit()
    except RuleRegistryError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    row = session.get(MappingRule, rule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping rule not found")
    return row


def _require_set(session: Session, parameter_set_id: uuid.UUID) -> ParameterSet:
    row = session.get(ParameterSet, parameter_set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parameter set not found")
    return row


def _application_read(result: RuleApplication) -> RuleApplicationRead:
    return RuleApplicationRead(
        parameter_set_id=result.parameter_set_id,
        result_parameter_set_id=result.result_parameter_set_id,
        changed=result.changed,
        created=result.created,
        updates=[
            ProposedUpdateRead(
                target_parameter=item.target_parameter,
                rule_key=item.rule_key,
                rule_version=item.rule_version,
                rule_id=item.rule_id,
                observation_id=item.observation_id,
                before_value=item.before_value,
                after_value=item.after_value,
                size=item.size,
                rationale=item.rationale,
                assumption=item.assumption,
            )
            for item in result.updates
        ],
        context=[
            ContextItemRead(
                observation_id=item.observation_id,
                reason=item.reason,
                rule_key=item.rule_key,
                rule_id=item.rule_id,
            )
            for item in result.context
        ],
    )
