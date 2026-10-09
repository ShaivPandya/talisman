"""Create scenarios, submit paired runs, compare saved paths, and attribute."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterEvidence, ParameterOverride, ParameterSetCreate
from longaeva_app.companies import register_default_companies
from longaeva_app.companies.visa.calibration import artifact_path
from longaeva_app.companies.visa.interventions import canonical_interventions, parse_visa_interventions
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.parameters import VISA_PARAMETERS
from longaeva_app.db.models import MappingRule, Observation, ParameterSet, ParameterUpdate, Run, Scenario
from longaeva_app.engine.attribution import (
    ATTRIBUTION_METRICS,
    ChangeContribution,
    annotate_support,
    attribute_changes,
)
from longaeva_app.engine.compare import condition_mismatches, summarize_differences
from longaeva_app.engine.outputs import load_npz_arrays
from longaeva_app.engine.replay import compare_simulation
from longaeva_app.hashing import utc_isoformat
from longaeva_app.runs.errors import RunError
from longaeva_app.runs.inputs import parameter_set_from_row, resolve_run_inputs
from longaeva_app.runs.service import submit_run
from longaeva_app.scenarios.errors import ScenarioError
from longaeva_app.scenarios.provenance import (
    ObservationView,
    ProvenanceBundle,
    RuleView,
    UpdateView,
    provenance_for_parameter,
)
from longaeva_app.storage.local import LocalArtifactStore

_EMPTY_PROVENANCE = ProvenanceBundle((), (), (), ())


def create_scenario(
    session: Session,
    *,
    company: str,
    name: str,
    parameter_set_id: uuid.UUID,
    interventions: Sequence[Mapping[str, Any]],
    pair_group_id: uuid.UUID | None,
    parameter_overrides: Mapping[str, ParameterOverride],
) -> Scenario:
    """Insert a scenario. Overrides become a child parameter set with update rows."""
    register_default_companies()
    if company != "visa":
        raise ScenarioError(f"unsupported company: {company!r}", status_code=422)
    try:
        parsed = parse_visa_interventions(list(interventions))
    except ValueError as exc:
        raise ScenarioError(str(exc), status_code=422) from exc
    base = session.get(ParameterSet, parameter_set_id)
    if base is None:
        raise ScenarioError("Parameter set not found", status_code=404)
    if base.company != company:
        raise ScenarioError(
            f"Parameter set company {base.company!r} does not match {company!r}",
            status_code=422,
        )
    parameter_set = base
    if parameter_overrides:
        parameter_set = _child_parameter_set(session, base, parameter_overrides)
    scenario = Scenario(
        company=company,
        name=name,
        parameter_set_id=parameter_set.id,
        interventions=canonical_interventions(parsed),
        pair_group_id=pair_group_id,
    )
    session.add(scenario)
    session.flush()
    return scenario


def _child_parameter_set(
    session: Session,
    base: ParameterSet,
    overrides: Mapping[str, ParameterOverride],
) -> ParameterSet:
    create = parameter_set_from_row(base)
    values = {key: float(val) for key, val in create.values.items()}
    links = dict(create.evidence_links)
    flags = dict(create.assumption_flags)
    ranges = {key: [float(pair[0]), float(pair[1])] for key, pair in create.ranges.items() if len(pair) >= 2}
    changes: list[tuple[str, float, float, str]] = []
    for name, override in overrides.items():
        if name not in values:
            raise ScenarioError(f"unknown parameter: {name}", status_code=422)
        rationale = override.rationale.strip()
        if not rationale:
            raise ScenarioError(f"parameter {name} override requires a rationale", status_code=422)
        before = float(values[name])
        after = float(override.value)
        values[name] = after
        previous = links[name]
        links[name] = ParameterEvidence(
            observation_ids=list(previous.observation_ids),
            assumption=True,
            rationale=rationale,
        )
        flags[name] = True
        changes.append((name, before, after, rationale))
    child = ParameterSetCreate(
        company=create.company,
        cutoff_ts=create.cutoff_ts,
        values=values,
        ranges=ranges,
        evidence_links=links,
        assumption_flags=flags,
        parent_id=base.id,
    )
    errors = VisaModel().validate_parameters(values)
    if errors:
        raise ScenarioError(f"parameter overrides are invalid: {errors}", status_code=422)
    digest = child.computed_content_hash()
    existing = session.execute(select(ParameterSet).where(ParameterSet.content_hash == digest)).scalar_one_or_none()
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
    present = set(
        session.scalars(
            select(ParameterUpdate.target_parameter).where(ParameterUpdate.parameter_set_id == existing.id)
        ).all()
    )
    for name, before, after, rationale in changes:
        if name in present:
            continue
        session.add(
            ParameterUpdate(
                rule_id=None,
                parameter_set_id=existing.id,
                target_parameter=name,
                before_value={"value": before},
                after_value={"value": after},
                size=after - before,
                rationale=rationale,
            )
        )
    session.flush()
    return existing


def submit_pair_runs(
    session: Session,
    *,
    scenario_ids: Sequence[uuid.UUID],
    baseline_scenario_id: uuid.UUID,
    cutoff_ts: datetime,
    seed: int,
    n_paths: int,
    n_quarters: int,
    switches: dict[str, bool],
) -> list[Run]:
    """Queue one run per scenario. Variants point at the baseline run and share its seed."""
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ScenarioError("scenario_ids must be unique", status_code=422)
    if baseline_scenario_id not in scenario_ids:
        raise ScenarioError("baseline_scenario_id must be one of scenario_ids", status_code=422)
    scenarios = []
    for scenario_id in scenario_ids:
        row = session.get(Scenario, scenario_id)
        if row is None:
            raise ScenarioError(f"Scenario {scenario_id} not found", status_code=404)
        scenarios.append(row)
    group = scenarios[0].pair_group_id
    if group is None or any(row.pair_group_id != group for row in scenarios):
        raise ScenarioError("scenarios must share a non-null pair_group_id", status_code=422)
    company = scenarios[0].company
    if any(row.company != company for row in scenarios):
        raise ScenarioError("scenarios must share a company", status_code=422)

    ordered = [baseline_scenario_id] + [item for item in scenario_ids if item != baseline_scenario_id]
    runs: list[Run] = []
    baseline_run_id: uuid.UUID | None = None
    try:
        for scenario_id in ordered:
            run = submit_run(
                session,
                scenario_id=scenario_id,
                cutoff_ts=cutoff_ts,
                seed=seed,
                n_paths=n_paths,
                n_quarters=n_quarters,
                switches=switches,
                baseline_run_id=baseline_run_id,
            )
            runs.append(run)
            if baseline_run_id is None:
                baseline_run_id = run.id
    except RunError as exc:
        raise ScenarioError(exc.message, status_code=exc.status_code) from exc
    return runs


def _cutoff_key(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return utc_isoformat(aware.astimezone(UTC))


def _load_pair(
    session: Session,
    *,
    run_id: uuid.UUID,
    baseline_run_id: uuid.UUID | None,
) -> tuple[Run, Run]:
    variant = session.get(Run, run_id)
    if variant is None:
        raise ScenarioError("Run not found", status_code=404)
    baseline_id = baseline_run_id or variant.baseline_run_id
    if baseline_id is None:
        raise ScenarioError("baseline_run_id is required when the run is not paired", status_code=422)
    if baseline_id == variant.id:
        raise ScenarioError("a run cannot be compared with itself", status_code=422)
    baseline = session.get(Run, baseline_id)
    if baseline is None:
        raise ScenarioError("Baseline run not found", status_code=404)
    for run in (variant, baseline):
        if run.status != "succeeded":
            raise ScenarioError(f"run {run.id} has status {run.status!r}", status_code=409)
        if not run.outputs_path or not run.outputs_hash:
            raise ScenarioError(f"run {run.id} is missing path outputs", status_code=409)
    mismatches = condition_mismatches(
        left_seed=variant.seed,
        right_seed=baseline.seed,
        left_paths=variant.n_paths,
        right_paths=baseline.n_paths,
        left_quarters=variant.n_quarters,
        right_quarters=baseline.n_quarters,
        left_cutoff=_cutoff_key(variant.cutoff_ts),
        right_cutoff=_cutoff_key(baseline.cutoff_ts),
        left_origin=variant.origin_label,
        right_origin=baseline.origin_label,
        left_switches=dict(variant.switches or {}),
        right_switches=dict(baseline.switches or {}),
    )
    if mismatches:
        raise ScenarioError(f"runs are not a pair: {', '.join(mismatches)}", status_code=422)
    return variant, baseline


def compare_saved_runs(
    session: Session,
    store: LocalArtifactStore,
    *,
    run_id: uuid.UUID,
    baseline_run_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Path-wise difference quantiles from the two saved ``paths.npz`` files."""
    variant, baseline = _load_pair(session, run_id=run_id, baseline_run_id=baseline_run_id)
    variant_metrics, _states, periods = _read_paths(store, variant)
    baseline_metrics, _base_states, base_periods = _read_paths(store, baseline)
    if periods != base_periods:
        raise ScenarioError("paired runs do not share period labels", status_code=422)
    try:
        items = summarize_differences(variant_metrics, baseline_metrics, periods)
    except ValueError as exc:
        raise ScenarioError(str(exc), status_code=422) from exc
    return {
        "run_id": variant.id,
        "baseline_run_id": baseline.id,
        "seed": variant.seed,
        "items": items,
    }


def _read_paths(store: LocalArtifactStore, run: Run) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    path = run.outputs_path or ""
    if not store.exists(path):
        raise ScenarioError(f"artifact for run {run.id} is missing", status_code=409)
    return load_npz_arrays(store.read_bytes(path))


def attribute_saved_runs(
    session: Session,
    store: LocalArtifactStore,
    *,
    run_id: uuid.UUID,
    baseline_run_id: uuid.UUID | None,
    metric: str | None,
) -> dict[str, Any]:
    """Re-simulate the pair, verify hashes, then attribute. Nothing new is stored."""
    variant, baseline = _load_pair(session, run_id=run_id, baseline_run_id=baseline_run_id)
    metrics = _selected_metrics(metric)
    try:
        variant_inputs = resolve_run_inputs(
            session,
            scenario=_require_scenario(session, variant.scenario_id),
            cutoff_ts=_aware(variant.cutoff_ts),
            switches=dict(variant.switches or {}),
        )
        baseline_inputs = resolve_run_inputs(
            session,
            scenario=_require_scenario(session, baseline.scenario_id),
            cutoff_ts=_aware(baseline.cutoff_ts),
            switches=dict(baseline.switches or {}),
        )
    except RunError as exc:
        raise ScenarioError(exc.message, status_code=exc.status_code) from exc
    _require_pinned(variant, variant_inputs.parameter_set_hash, variant_inputs.interventions_hash)
    _require_pinned(baseline, baseline_inputs.parameter_set_hash, baseline_inputs.interventions_hash)

    try:
        result = attribute_changes(
            VisaModel(),
            variant_inputs.starting_state,
            baseline_params=baseline_inputs.parameter_set.values,
            variant_params=variant_inputs.parameter_set.values,
            baseline_interventions=baseline_inputs.interventions_payload,
            variant_interventions=variant_inputs.interventions_payload,
            origin=variant_inputs.origin,
            seed=variant.seed,
            n_paths=variant.n_paths,
            n_quarters=variant.n_quarters,
            switches=dict(variant.switches or {}),
            metrics=metrics,
            ranges=_ranges_of(variant_inputs.parameter_set),
        )
    except ValueError as exc:
        raise ScenarioError(str(exc), status_code=422) from exc

    verification = [
        _verify_hash(result.variant, variant, store),
        _verify_hash(result.baseline, baseline, store),
    ]
    bundles = _provenance_bundles(
        session,
        parameter_set=variant_inputs.parameter_set,
        origin_date=variant_inputs.fixture.origin_date.isoformat(),
    )
    evidence = _evidence_table(variant_inputs.parameter_set)
    review_statuses = {obs_id: view.review_status for obs_id, view in _observation_views(session, evidence).items()}
    ranked = annotate_support(result.sensitivity, evidence=evidence, review_statuses=review_statuses)
    return {
        "run_id": variant.id,
        "baseline_run_id": baseline.id,
        "conditional_on_model": True,
        "order_note": result.order_note,
        "sequential_order": list(result.sequential_order),
        "metrics": [
            {
                "metric": name,
                "total": [_effect_dict(item) for item in result.totals[name]],
                "horizon_total": result.horizon_totals[name],
                "joint_residual": [_effect_dict(item) for item in result.joint_residual[name]],
                "joint_residual_horizon": result.joint_residual_horizon[name],
            }
            for name in metrics
        ],
        "contributions": [_contribution_dict(item, bundles) for item in result.contributions],
        "sensitivity": [
            {
                "parameter": item.parameter,
                "range_low": item.range_low,
                "range_high": item.range_high,
                "low_mean": item.low_mean,
                "high_mean": item.high_mean,
                "swing": item.swing,
                "normalized_sensitivity": item.normalized_sensitivity,
                "support_score": item.support_score,
                "flag": item.flag,
                **_id_fields(bundles.get(item.parameter, _EMPTY_PROVENANCE)),
            }
            for item in ranked
        ],
        "sensitivity_metric": result.sensitivity_metric,
        "verification": verification,
    }


def _selected_metrics(metric: str | None) -> tuple[str, ...]:
    if metric is None:
        return ATTRIBUTION_METRICS
    if metric not in ATTRIBUTION_METRICS:
        allowed = ", ".join(ATTRIBUTION_METRICS)
        raise ScenarioError(f"metric must be one of {allowed}", status_code=422)
    return (metric,)


def _require_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    row = session.get(Scenario, scenario_id)
    if row is None:
        raise ScenarioError("Scenario not found", status_code=422)
    return row


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _require_pinned(run: Run, parameter_hash: str, interventions_hash: str) -> None:
    if run.parameter_set_hash != parameter_hash or run.interventions_hash != interventions_hash:
        raise ScenarioError(f"pinned inputs for run {run.id} no longer match the scenario", status_code=409)


def _ranges_of(row: ParameterSet) -> dict[str, list[float]]:
    ranges: dict[str, list[float]] = {}
    for name, raw in (row.ranges or {}).items():
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            ranges[str(name)] = [float(raw[0]), float(raw[1])]
    return ranges


def _verify_hash(result: Any, run: Run, store: LocalArtifactStore) -> str:
    recorded_metrics, recorded_states, _periods = _read_paths(store, run)
    comparison = compare_simulation(
        result,
        recorded_hash=run.outputs_hash or "",
        recorded_metrics=recorded_metrics,
        recorded_states=recorded_states,
    )
    if comparison.status not in {"exact_match", "numerically_equivalent"}:
        raise ScenarioError(
            f"recomputed outputs do not match run {run.id} ({comparison.status})",
            status_code=409,
        )
    return comparison.status


def _effect_dict(item: Any) -> dict[str, Any]:
    return {
        "quarter_index": item.quarter_index,
        "period_label": item.period_label,
        "mean_difference": item.mean_difference,
    }


def _id_fields(bundle: ProvenanceBundle) -> dict[str, list[str]]:
    return {
        "rule_ids": list(bundle.rule_ids),
        "source_ids": list(bundle.source_ids),
        "observation_ids": list(bundle.observation_ids),
    }


def _contribution_dict(item: ChangeContribution, bundles: Mapping[str, ProvenanceBundle]) -> dict[str, Any]:
    bundle = bundles.get(item.name, _EMPTY_PROVENANCE) if item.kind == "parameter" else _EMPTY_PROVENANCE
    by_metric = {
        name: {
            "one_at_a_time": [_effect_dict(effect) for effect in metric_effects.one_at_a_time],
            "sequential": [_effect_dict(effect) for effect in metric_effects.sequential],
            "one_at_a_time_horizon": metric_effects.one_at_a_time_horizon,
            "sequential_horizon": metric_effects.sequential_horizon,
        }
        for name, metric_effects in item.effects.items()
    }
    return {
        "kind": item.kind,
        "name": item.name,
        "key": item.key,
        "label": item.label,
        "before": item.before,
        "after": item.after,
        "size": item.size,
        "intervention": item.intervention,
        "by_metric": by_metric,
        **_id_fields(bundle),
    }


def _evidence_table(row: ParameterSet) -> dict[str, tuple[list[str], bool]]:
    links = row.evidence_links or {}
    flags = row.assumption_flags or {}
    table: dict[str, tuple[list[str], bool]] = {}
    for spec in VISA_PARAMETERS:
        raw = links.get(spec.name) or {}
        if not isinstance(raw, dict):
            table[spec.name] = ([], bool(flags.get(spec.name)))
            continue
        ids = [str(item) for item in (raw.get("observation_ids") or [])]
        assumption = bool(raw.get("assumption") or flags.get(spec.name))
        table[spec.name] = (ids, assumption)
    return table


def _observation_views(session: Session, evidence: Mapping[str, tuple[list[str], bool]]) -> dict[str, ObservationView]:
    raw_ids: list[uuid.UUID] = []
    for ids, _assumption in evidence.values():
        for item in ids:
            try:
                raw_ids.append(uuid.UUID(item))
            except ValueError:
                continue
    if not raw_ids:
        return {}
    rows = session.scalars(select(Observation).where(Observation.id.in_(raw_ids))).all()
    return {
        str(row.id): ObservationView(
            observation_id=str(row.id),
            source_id=None if row.source_id is None else str(row.source_id),
            document_text_id=None if row.document_text_id is None else str(row.document_text_id),
            span_page=row.span_page,
            span_char_start=row.span_char_start,
            span_char_end=row.span_char_end,
            review_status=row.review_status,
        )
        for row in rows
    }


def _load_evidence_index(origin_date: str) -> dict[str, dict[str, Any]]:
    path = artifact_path(origin_date)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    index = payload.get("evidence_index") or {}
    return index if isinstance(index, dict) else {}


def _provenance_bundles(
    session: Session,
    *,
    parameter_set: ParameterSet,
    origin_date: str,
) -> dict[str, ProvenanceBundle]:
    evidence = _evidence_table(parameter_set)
    observations = _observation_views(session, evidence)
    updates = [
        UpdateView(target_parameter=row.target_parameter, rule_id=None if row.rule_id is None else str(row.rule_id))
        for row in session.scalars(
            select(ParameterUpdate).where(ParameterUpdate.parameter_set_id == parameter_set.id)
        ).all()
    ]
    rule_ids = [uuid.UUID(item.rule_id) for item in updates if item.rule_id]
    rules: dict[str, RuleView] = {}
    if rule_ids:
        for rule in session.scalars(select(MappingRule).where(MappingRule.id.in_(rule_ids))).all():
            rules[str(rule.id)] = RuleView(rule_id=str(rule.id), rule_key=rule.rule_key, version=rule.version)
    index = _load_evidence_index(origin_date)
    return {
        name: provenance_for_parameter(
            name,
            ids,
            observations=observations,
            evidence_index=index,
            updates=updates,
            rules=rules,
        )
        for name, (ids, _assumption) in evidence.items()
    }


__all__ = [
    "attribute_saved_runs",
    "compare_saved_runs",
    "create_scenario",
    "submit_pair_runs",
]
