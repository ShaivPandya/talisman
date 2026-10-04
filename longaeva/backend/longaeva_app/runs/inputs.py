"""Starting-state fixtures, document manifests, and parameter-set verification (LON-23)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.companies import register_default_companies
from longaeva_app.companies.base import FiscalPeriod, StartingState
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.parameters import VISA_PARAMETERS
from longaeva_app.companies.visa.starting_state import (
    StartingStateFixture,
    load_fixture,
    required_fixture_paths,
    to_starting_state,
)
from longaeva_app.db.models import ParameterSet, Scenario, Source
from longaeva_app.hashing import content_hash, utc_isoformat
from longaeva_app.runs.errors import RunError

DEFAULT_SCENARIO_NAME = "uncalibrated-baseline"
DEFAULT_ASSUMPTION_RATIONALE = "Uncalibrated default (LON-19); a run on defaults is not a forecast."


def parse_aware_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_origin_fixtures() -> list[StartingStateFixture]:
    return [load_fixture(path) for path in required_fixture_paths()]


def resolve_fixture(cutoff_ts: datetime) -> StartingStateFixture:
    """Pick a LON-3 fixture by exact cutoff, then UTC date, else build (LON-27)."""
    cutoff = cutoff_ts.astimezone(UTC) if cutoff_ts.tzinfo else cutoff_ts.replace(tzinfo=UTC)
    fixtures = load_origin_fixtures()
    for fixture in fixtures:
        if parse_aware_utc(fixture.cutoff_utc) == cutoff:
            return fixture
    date_matches = [fixture for fixture in fixtures if fixture.origin_date == cutoff.date()]
    if len(date_matches) == 1:
        return date_matches[0]
    from longaeva_app.companies.visa.state_builder import StateBuildError, build_fixture, buildable_origin_dates

    try:
        return build_fixture(cutoff)
    except StateBuildError as exc:
        known = ", ".join(f"{fx.origin_date.isoformat()} ({fx.cutoff_utc})" for fx in fixtures)
        buildable = ", ".join(buildable_origin_dates())
        raise RunError(
            f"No reconciled starting state for cutoff {utc_isoformat(cutoff)}. "
            f"Committed fixtures: {known}. Buildable origins: {buildable}. ({exc})",
            status_code=422,
        ) from exc


def resolve_fixture_by_origin_date(origin_date: str) -> StartingStateFixture:
    for fixture in load_origin_fixtures():
        if fixture.origin_date.isoformat() == origin_date:
            return fixture
    from longaeva_app.companies.visa.state_builder import (
        StateBuildError,
        build_fixture_for_origin_date,
        buildable_origin_dates,
    )

    try:
        return build_fixture_for_origin_date(origin_date)
    except StateBuildError as exc:
        known = [fx.origin_date.isoformat() for fx in load_origin_fixtures()]
        raise RunError(
            f"Unknown origin date {origin_date!r}. Committed fixtures: {known}. "
            f"Buildable origins: {buildable_origin_dates()}. ({exc})",
            status_code=422,
        ) from exc


def starting_state_values(fixture: StartingStateFixture) -> dict[str, float]:
    return dict(to_starting_state(fixture))


def starting_state_hash(values: StartingState) -> str:
    payload = {key: float(values[key]) for key in sorted(values)}
    return content_hash(payload)


def document_manifest_for_fixture(
    session: Session,
    fixture: StartingStateFixture,
) -> list[dict[str, Any]]:
    """Input-role documents only; ``source_id`` is omitted from the hashed payload."""
    cutoff = parse_aware_utc(fixture.cutoff_utc)
    entries: list[dict[str, Any]] = []
    for key in sorted(fixture.sources):
        ref = fixture.sources[key]
        if ref.role != "input":
            continue
        published = parse_aware_utc(ref.acceptance_utc)
        if published > cutoff:
            raise RunError(
                f"Input document {ref.source_id} was published after cutoff {fixture.cutoff_utc}",
                status_code=422,
            )
        source_id: str | None = None
        row = session.execute(select(Source).where(Source.content_hash == ref.content_sha256)).scalar_one_or_none()
        if row is not None:
            source_id = str(row.id)
        entry: dict[str, Any] = {
            "document_key": ref.source_id,
            "content_hash": ref.content_sha256,
            "publication_ts": utc_isoformat(published),
        }
        if source_id is not None:
            entry["source_id"] = source_id
        entries.append(entry)
    return entries


def manifest_hash(entries: list[dict[str, Any]]) -> str:
    hashed = [
        {
            "content_hash": item["content_hash"],
            "document_key": item["document_key"],
            "publication_ts": item["publication_ts"],
        }
        for item in entries
    ]
    hashed.sort(key=lambda item: item["document_key"])
    return content_hash(hashed)


def parameter_set_from_row(row: ParameterSet) -> ParameterSetCreate:
    links: dict[str, ParameterEvidence] = {}
    raw_links = row.evidence_links or {}
    for name, payload in raw_links.items():
        if isinstance(payload, ParameterEvidence):
            links[name] = payload
            continue
        data = dict(payload)
        obs = data.get("observation_ids") or []
        links[name] = ParameterEvidence(
            observation_ids=[UUID(str(item)) for item in obs],
            assumption=bool(data.get("assumption", False)),
            rationale=data.get("rationale"),
        )
    cutoff = row.cutoff_ts
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    return ParameterSetCreate(
        company=row.company,
        cutoff_ts=cutoff,
        values={key: float(val) for key, val in (row.values or {}).items()},
        ranges=row.ranges or {},
        evidence_links=links,
        assumption_flags=row.assumption_flags or {},
        parent_id=row.parent_id,
        content_hash=row.content_hash,
    )


def verify_parameter_set(row: ParameterSet, *, run_cutoff: datetime, company: str) -> ParameterSetCreate:
    register_default_companies()
    if row.company != company:
        raise RunError(f"Parameter set company {row.company!r} does not match scenario {company!r}", status_code=422)
    create = parameter_set_from_row(row)
    computed = create.computed_content_hash()
    if computed != row.content_hash:
        raise RunError("Parameter-set content hash does not match stored values", status_code=422)
    param_cutoff = row.cutoff_ts if row.cutoff_ts.tzinfo else row.cutoff_ts.replace(tzinfo=UTC)
    if param_cutoff > run_cutoff.astimezone(UTC):
        raise RunError("Parameter-set cutoff_ts is later than the run cutoff", status_code=422)
    model = VisaModel()
    errors = model.validate_parameters({name: float(create.values[name]) for name in create.values})
    if errors:
        raise RunError(f"Parameter set is incomplete or invalid: {errors}", status_code=422)
    return create


def parameter_set_is_all_assumption(row: ParameterSet) -> bool:
    links = row.evidence_links or {}
    if not links:
        return True
    for payload in links.values():
        if isinstance(payload, dict) and payload.get("assumption") and not payload.get("observation_ids"):
            continue
        if isinstance(payload, ParameterEvidence) and payload.assumption and not payload.observation_ids:
            continue
        return False
    return True


def default_parameter_values() -> dict[str, float]:
    return {spec.name: spec.default for spec in VISA_PARAMETERS}


def default_parameter_ranges() -> dict[str, list[float]]:
    return {spec.name: [spec.lower, spec.upper] for spec in VISA_PARAMETERS}


def ensure_default_baseline(session: Session, *, cutoff_ts: datetime, company: str = "visa") -> Scenario:
    """Create (or reuse) an all-assumption uncalibrated parameter set and baseline scenario."""
    values = default_parameter_values()
    evidence = {name: ParameterEvidence(assumption=True, rationale=DEFAULT_ASSUMPTION_RATIONALE) for name in values}
    create = ParameterSetCreate(
        company=company,
        cutoff_ts=cutoff_ts,
        values=values,
        ranges=default_parameter_ranges(),
        evidence_links=evidence,
        assumption_flags={name: True for name in values},
    )
    digest = create.computed_content_hash()
    existing = session.execute(select(ParameterSet).where(ParameterSet.content_hash == digest)).scalar_one_or_none()
    if existing is None:
        existing = ParameterSet(
            company=company,
            cutoff_ts=cutoff_ts,
            values=create.values,
            ranges=create.ranges,
            evidence_links={key: link.model_dump(mode="json") for key, link in create.evidence_links.items()},
            assumption_flags=create.assumption_flags,
            content_hash=digest,
        )
        session.add(existing)
        session.flush()
    stmt = (
        select(Scenario)
        .where(Scenario.parameter_set_id == existing.id)
        .where(Scenario.name == DEFAULT_SCENARIO_NAME)
        .where(Scenario.company == company)
    )
    scenario = session.execute(stmt).scalar_one_or_none()
    if scenario is None:
        scenario = Scenario(
            company=company,
            name=DEFAULT_SCENARIO_NAME,
            parameter_set_id=existing.id,
            interventions=[],
        )
        session.add(scenario)
        session.flush()
    if scenario.interventions:
        raise RunError("Default baseline scenario must have no interventions", status_code=422)
    return scenario


@dataclass(frozen=True, slots=True)
class ResolvedRunInputs:
    fixture: StartingStateFixture
    origin: FiscalPeriod
    origin_label: str
    starting_state: dict[str, float]
    starting_state_hash: str
    source_manifest: list[dict[str, Any]]
    source_manifest_hash: str
    parameter_set: ParameterSet
    parameter_set_hash: str
    scenario: Scenario
    switches: dict[str, bool]


def resolve_run_inputs(
    session: Session,
    *,
    scenario: Scenario,
    cutoff_ts: datetime,
    switches: dict[str, bool],
) -> ResolvedRunInputs:
    if scenario.interventions:
        raise RunError("Scenarios with interventions are not runnable until LON-22", status_code=422)
    fixture = resolve_fixture(cutoff_ts)
    origin = FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter)
    values = starting_state_values(fixture)
    param_row = session.get(ParameterSet, scenario.parameter_set_id)
    if param_row is None:
        raise RunError("Scenario parameter set not found", status_code=422)
    create = verify_parameter_set(param_row, run_cutoff=cutoff_ts, company=scenario.company)
    register_default_companies()
    model = VisaModel()
    switch_map = model.default_switches()
    switch_map.update({key: bool(val) for key, val in switches.items()})
    unknown = sorted(set(switches) - {spec.name for spec in model.switches})
    if unknown:
        raise RunError(f"unknown switches: {unknown}", status_code=422)
    manifest = document_manifest_for_fixture(session, fixture)
    return ResolvedRunInputs(
        fixture=fixture,
        origin=origin,
        origin_label=origin.label(),
        starting_state=values,
        starting_state_hash=starting_state_hash(values),
        source_manifest=manifest,
        source_manifest_hash=manifest_hash(manifest),
        parameter_set=param_row,
        parameter_set_hash=create.computed_content_hash(),
        scenario=scenario,
        switches=switch_map,
    )
