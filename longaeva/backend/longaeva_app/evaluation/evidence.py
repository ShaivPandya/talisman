"""Freeze the retained reviewed corpus before evaluating any outcomes (LON-31)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.api.schemas import ObservationCreate
from longaeva_app.companies.visa.calibration import CalibrationResult
from longaeva_app.db.models import Observation, ParameterSet, Scenario, Source
from longaeva_app.evaluation.origins import EvaluationOrigin
from longaeva_app.extract.census_quarters import quarter_prints
from longaeva_app.extract.census_vintages import PARSE_STATUS_PATH, VINTAGES_PATH, VintageRow, load_parse_status
from longaeva_app.hashing import content_hash, sha256_hex, utc_isoformat
from longaeva_app.review.gate_fixtures import _upsert_observation, _upsert_source, load_gate_fixtures
from longaeva_app.review.rules import PACKAGE_ROOT, REGISTRY, registry_families
from longaeva_app.review.service import effective_observation
from longaeva_app.runs.inputs import parse_aware_utc


def observation_snapshot(session: Session, row: Observation) -> dict[str, Any]:
    source = session.get(Source, row.source_id)
    if source is None:
        raise ValueError(f"missing source for observation {row.id}")
    effective = effective_observation(session, row)
    if effective is not None:
        effective = {key: val for key, val in effective.items() if key not in {"source_id", "document_text_id"}}
    return {
        "key": str(row.attributes["fixture_observation_id"]),
        "source_hash": source.content_hash,
        "publication_ts": utc_isoformat(source.publication_ts),
        "review_status": row.review_status,
        "effective": effective,
    }


def _load_quarter(session: Session, row: VintageRow, documents: dict[str, Any]) -> Observation:
    doc = documents[row.release_id]
    if doc["integrity_flag"] != "ok" or doc["publication_ts"] != row.publication_ts:
        raise ValueError(f"Census manifest disagrees with vintage {row.release_id}")
    fixture_id = f"census-quarter:{row.release_id}:{row.period_end}:yoy_3m_pct"
    source = _upsert_source(
        session,
        provider="census_bureau",
        company="census",
        doc_type="MARTS advance release",
        url=doc["url"],
        publication_ts=parse_aware_utc(row.publication_ts),
        content_hash=doc["expected_sha256"],
        original_path="data/fixtures/census/vintages.csv.gz",
        license_note=doc["license_note"],
        attributes={"release_id": row.release_id, "integrity_flag": "ok", "vintage_row": asdict(row)},
        period_start=date.fromisoformat(row.period_start),
        period_end=date.fromisoformat(row.period_end),
    )
    if source.original_path.startswith("data/fixtures/census/vintages.csv.gz#"):
        source.original_path = "data/fixtures/census/vintages.csv.gz"
    create = ObservationCreate(
        company="census",
        source_id=source.id,
        statement_type="measured",
        activity_type="retail_food_services_total",
        geography=row.geography,
        period_start=date.fromisoformat(row.period_start),
        period_end=date.fromisoformat(row.period_end),
        value=float(row.value),
        unit=row.unit,
        basis=row.basis,
        source_family="census",
        extractor_id="census_marts_quarter",
        extractor_version="lon31-v1",
        attributes={
            "fixture_observation_id": fixture_id,
            "measure": row.measure,
            "estimate_status": row.estimate_status,
            "series_key": row.series_key,
            "release_id": row.release_id,
            "integrity_flag": row.integrity_flag,
        },
    )
    return _upsert_observation(
        session,
        source,
        create,
        fixture_observation_id=fixture_id,
        extractor_id="census_marts_quarter",
        extractor_version="lon31-v1",
        accept=True,
        acceptance_rationale="Retained LON-15 parser checklist: hash verified, release totals reconciled, "
        "unflagged finite SA three-month growth at a quarter end; suspect releases excluded.",
        acceptance_decided_by="lon31-census-parser-checklist",
    )


@dataclass
class EvidenceSnapshot:
    by_origin: dict[str, list[dict[str, Any]]]
    ids_by_origin: dict[str, list[UUID]]
    policy: dict[str, Any]

    def assert_unchanged(self, session: Session, origin_date: str) -> None:
        for relative, expected in self.policy.get("files", {}).items():
            if sha256_hex((PACKAGE_ROOT / relative).read_bytes()) != expected:
                raise ValueError("retained evidence file changed after the evaluation config was frozen")
        rules = {f"{spec.rule_key}:v{spec.version}": spec.definition_hash() for spec in REGISTRY}
        if "rules" in self.policy and rules != self.policy["rules"]:
            raise ValueError("mapping rules changed after the evaluation config was frozen")
        current = []
        for row_id in self.ids_by_origin[origin_date]:
            row = session.get(Observation, row_id)
            if row is None:
                raise ValueError("frozen observation disappeared")
            current.append(observation_snapshot(session, row))
        current.sort(key=lambda item: item["key"])
        if current != self.by_origin[origin_date]:
            raise ValueError("reviewed evidence changed after the evaluation config was frozen; rerun the suite")

    def reviewed_ids(self, origin_date: str) -> list[UUID]:
        entries = self.by_origin[origin_date]
        ids = self.ids_by_origin[origin_date]
        return [row_id for row_id, item in zip(ids, entries, strict=True) if item["effective"] is not None]


def freeze_evidence(factory: sessionmaker[Session], origins: Sequence[EvaluationOrigin]) -> EvidenceSnapshot:
    """Materialize only retained fixtures, preserve decisions, then freeze the as-of selection."""
    if not origins:
        raise ValueError("no eligible evaluation origins")
    manifest_path = PACKAGE_ROOT / "data" / "manifest" / "census.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    documents = {item["period"]["release_id"]: item for item in manifest["documents"]}
    verified = {
        item["release_id"]
        for item in load_parse_status()
        if item["status"] == "parsed" and item["hash_verified"] == "true" and item["integrity_flag"] == "ok"
    }
    by_origin: dict[str, list[dict[str, Any]]] = {}
    ids_by_origin: dict[str, list[UUID]] = {}
    with factory() as session:
        gates = load_gate_fixtures(session, accept=True, families=set(registry_families()) - {"census"})
        for origin in origins:
            selected = [
                row
                for row in gates.values()
                if (source := session.get(Source, row.source_id)) is not None
                and source.publication_ts <= origin.cutoff_ts
            ]
            quarters = [row for row in quarter_prints(origin.cutoff_ts) if row.release_id in verified]
            # The rule uses the newest complete quarter; older quarters are fitting history only.
            if quarters:
                selected.append(_load_quarter(session, quarters[-1], documents))
            selected.sort(key=lambda row: str(row.attributes["fixture_observation_id"]))
            by_origin[origin.origin_date] = [observation_snapshot(session, row) for row in selected]
            ids_by_origin[origin.origin_date] = [row.id for row in selected]
        session.commit()
    paths = [VINTAGES_PATH, PARSE_STATUS_PATH, manifest_path]
    paths.extend(sorted((PACKAGE_ROOT / "data" / "fixtures" / "observations").glob("*.json")))
    policy = {
        "method": "retained_reviewed_quarter_end_v1",
        "quarter_months": [3, 6, 9, 12],
        "allow_possibly_replaced": False,
        "files": {str(path.relative_to(PACKAGE_ROOT)): sha256_hex(path.read_bytes()) for path in paths},
        "rules": {f"{spec.rule_key}:v{spec.version}": spec.definition_hash() for spec in REGISTRY},
        "snapshots": by_origin,
        "snapshot_hash": content_hash(by_origin),
    }
    return EvidenceSnapshot(by_origin, ids_by_origin, policy)


def prepare_parameters(
    session: Session,
    calibration: CalibrationResult,
    snapshot: EvidenceSnapshot,
    origin_date: str,
    *,
    external_evidence: bool,
    sensitivity: dict[str, str],
) -> tuple[ParameterSet, Scenario, dict[str, Any]]:
    """Always rebuild from the calibrated parent; never subtract an update from a child."""
    from sqlalchemy import select

    from longaeva_app.api.schemas import ParameterSetCreate
    from longaeva_app.companies.visa.calibration import persist_calibrated
    from longaeva_app.review.apply import apply_rules

    snapshot.assert_unchanged(session, origin_date)
    root_row, _scenario = persist_calibrated(calibration, session)
    root: ParameterSet = root_row
    parent: ParameterSet | None = root
    setting: dict[str, Any] = {"profile": "central"}
    if sensitivity:
        name, endpoint = sensitivity["parameter"], sensitivity["endpoint"]
        value = float(calibration.pooled.ranges[name][0 if endpoint == "low" else 1])
        create = ParameterSetCreate(
            company=root.company,
            cutoff_ts=calibration.cutoff_ts,
            values={**root.values, name: value},
            ranges=root.ranges,
            evidence_links=calibration.pooled.evidence_links,
            assumption_flags=root.assumption_flags,
            parent_id=root.id,
        )
        digest = create.computed_content_hash()
        parent = session.scalar(select(ParameterSet).where(ParameterSet.content_hash == digest))
        if parent is None:
            parent = ParameterSet(
                company=create.company,
                cutoff_ts=create.cutoff_ts,
                values=create.values,
                ranges=create.ranges,
                evidence_links={key: link.model_dump(mode="json") for key, link in create.evidence_links.items()},
                assumption_flags=create.assumption_flags,
                parent_id=root.id,
                content_hash=digest,
            )
            session.add(parent)
            session.flush()
        setting = {"profile": f"{name}_{endpoint}", "parameter": name, "endpoint": endpoint, "value": value}
    if parent is None:
        raise RuntimeError("sensitivity parent missing")
    result: ParameterSet | None = parent
    updates: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []
    if external_evidence:
        applied = apply_rules(
            session,
            parent.id,
            observation_ids=snapshot.reviewed_ids(origin_date),
            decided_by="lon31-evaluation",
            rationale="Frozen retained evidence available at this origin cutoff; outcomes are not inputs.",
        )
        result = session.get(ParameterSet, applied.result_parameter_set_id)
        if result is None:
            raise RuntimeError("mapped parameter set missing")
        updates = applied.as_dict()["updates"]
        context = applied.as_dict()["context"]
    if result is None:
        raise RuntimeError("evaluation parameter set missing")
    name = "evaluation-reviewed" if external_evidence else "evaluation-financial-only"
    scenario = session.scalar(select(Scenario).where(Scenario.parameter_set_id == result.id, Scenario.name == name))
    if scenario is None:
        scenario = Scenario(company=result.company, parameter_set_id=result.id, name=name, interventions=[])
        session.add(scenario)
        session.flush()
    numerical_changes = {
        key: {"before": float(parent.values[key]), "after": float(result.values[key])}
        for key in parent.values
        if float(parent.values[key]) != float(result.values[key])
    }
    details = {
        "calibrated_parent_hash": root.content_hash,
        "sensitivity_parent_hash": parent.content_hash,
        "sensitivity": setting,
        "external_evidence": external_evidence,
        "external_updates": updates,
        "external_context": context,
        "external_numeric_changes": numerical_changes,
        "external_no_effect": not numerical_changes,
        "evidence_snapshot_hash": content_hash(snapshot.by_origin[origin_date]),
        "external_sources": [
            {key: item[key] for key in ("key", "source_hash", "publication_ts", "review_status")}
            for item in snapshot.by_origin[origin_date]
        ],
        "missing_external_families": sorted(
            registry_families()
            - {
                item["effective"]["source_family"]
                for item in snapshot.by_origin[origin_date]
                if item["effective"] is not None
            }
        ),
    }
    return result, scenario, details
