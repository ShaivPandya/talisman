"""Curator-only demo generation in an empty, migrated disposable database."""

from __future__ import annotations

import gzip
import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.collect.text import extract_passages
from longaeva_app.companies.visa.calibration import artifact_path
from longaeva_app.config import PACKAGE_ROOT
from longaeva_app.db import models as m
from longaeva_app.db.base import Base
from longaeva_app.demo import TABLES, VERSION, DemoError, _decoded_row, load_bundle, row_payload
from longaeva_app.evaluation.evidence import freeze_evidence, prepare_parameters
from longaeva_app.evaluation.harness import load_calibration_artifact
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.hashing import content_hash, sha256_hex
from longaeva_app.runs.forecasts import archive_forecasts
from longaeva_app.runs.inputs import load_origin_fixtures, parse_aware_utc, resolve_fixture_by_origin_date
from longaeva_app.runs.prospective import load_registration
from longaeva_app.runs.service import execute_run, replay_run, submit_run
from longaeva_app.scenarios.service import create_scenario
from longaeva_app.storage.local import LocalArtifactStore

ORIGINS = ("2024-07-23", "2025-10-28")
NAMESPACE = uuid.UUID("c7752674-7d08-570b-a045-8a9da7950b37")
DEMO_DIR = PACKAGE_ROOT / "data/demo"


def _stable_id(_mapper: Any, _connection: Any, row: Base) -> None:
    if hasattr(row, "id") and row.id is None:
        payload = {
            col.name: str(getattr(row, col.name))
            for col in row.__table__.columns
            if col.computed is None and col.name not in {"id", "created_at", "retrieval_ts", "decided_at", "job_id"}
        }
        row.id = uuid.uuid5(NAMESPACE, f"{row.__tablename__}:{content_hash(payload)}")


def _original_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for manifest in (PACKAGE_ROOT / "data/fixtures").glob("*/sources/manifest.json"):
        for entry in json.loads(manifest.read_text()).get("sources", []):
            relative = entry.get("path")
            if relative:
                path = PACKAGE_ROOT / relative
                if not path.is_file():
                    path = manifest.parent / relative
                if path.is_file() and entry.get("content_sha256"):
                    index[entry["content_sha256"]] = path
    for directory in (
        PACKAGE_ROOT / "data/fixtures/census/sources",
        PACKAGE_ROOT / "data/demo/originals",
        PACKAGE_ROOT / "var/cache/census",
    ):
        for path in directory.glob("adv*.pdf"):
            index.setdefault(sha256_hex(path.read_bytes()), path)
    return index


def _attach_sources(session: Session, store: LocalArtifactStore, prospective_origin: str) -> None:
    index = _original_index()
    # Also retain every starting-state document needed by saved-run manifests.
    for fixture in [*load_origin_fixtures(), resolve_fixture_by_origin_date(prospective_origin)]:
        for ref in fixture.sources.values():
            if ref.role != "input":
                continue
            existing = session.scalar(select(m.Source).where(m.Source.content_hash == ref.content_sha256))
            if existing is None:
                published = parse_aware_utc(ref.acceptance_utc)
                session.add(
                    m.Source(
                        provider="sec",
                        company="visa",
                        doc_type=ref.form,
                        url=ref.url,
                        publication_ts=published,
                        retrieval_ts=datetime.now(UTC),
                        content_hash=ref.content_sha256,
                        original_path="pending",
                        license_note="Public SEC filing retained under the existing source gate; issuer authorship retained.",
                        attributes={"document_key": ref.source_id},
                    )
                )
                session.flush()
    session.flush()
    for source in session.scalars(select(m.Source)).all():
        path = index.get(source.content_hash)
        if path is None:
            raise DemoError(f"Retained original missing for {source.company} {source.content_hash}")
        if not path.is_relative_to(PACKAGE_ROOT / "data"):
            destination = DEMO_DIR / "originals" / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            path = destination
        source.original_path = str(path.relative_to(PACKAGE_ROOT))
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
        if sha256_hex(raw) != source.content_hash:
            raise DemoError("Retained original does not match source hash")
        store.put_original(raw)
        if not session.scalar(select(m.DocumentText.id).where(m.DocumentText.source_id == source.id)):
            for extracted in extract_passages(raw, filename=path.name.removesuffix(".gz")):
                session.add(m.DocumentText(source_id=source.id, **vars(extracted)))
        session.flush()
        # Gate spans use original HTML code-point offsets. Retain exact quote spans
        # on page 0 separately from normalized HTML pages (which start at page 1).
        for observation in session.scalars(select(m.Observation).where(m.Observation.source_id == source.id)):
            if observation.document_text_id is not None:
                continue
            if observation.span_char_start is None:
                if observation.extractor_id != "census_marts_quarter":
                    raise DemoError("Observation has no retained evidence span")
                passage = session.scalar(
                    select(m.DocumentText).where(m.DocumentText.source_id == source.id, m.DocumentText.page == 1)
                )
                match = re.search(r"Total sales\s+for.*?year\s+ago\.", passage.text, re.DOTALL) if passage else None
                if (
                    passage is None
                    or match is None
                    or not re.search(rf"up\s+{re.escape(f'{observation.value:g}')}\s+percent", match.group())
                ):
                    raise DemoError("Census quarterly value has no matching retained release sentence")
                observation.document_text_id = passage.id
                observation.span_page = passage.page
                observation.span_char_start = passage.char_start + match.start()
                observation.span_char_end = passage.char_start + match.end()
                continue
            original = raw.decode("utf-8", errors="replace")
            start, end = observation.span_char_start, observation.span_char_end
            if end is None or not 0 <= start < end <= len(original):
                raise DemoError("Gate observation has an invalid original span")
            quote = original[start:end]
            if observation.attributes.get("quote") and quote != observation.attributes["quote"]:
                raise DemoError("Gate quote differs from retained original")
            passage = session.scalar(
                select(m.DocumentText).where(
                    m.DocumentText.source_id == source.id,
                    m.DocumentText.page == 0,
                    m.DocumentText.char_start == start,
                )
            )
            if passage is None:
                passage = m.DocumentText(source_id=source.id, page=0, char_start=start, char_end=end, text=quote)
                session.add(passage)
                session.flush()
            observation.document_text_id = passage.id
            observation.span_page = 0
    session.commit()


def _parameter_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    pending = list(rows)
    seen: set[str] = set()
    while pending:
        ready = [row for row in pending if row["parent_id"] is None or row["parent_id"] in seen]
        if not ready:
            raise DemoError("Cyclic or incomplete demo parameter lineage")
        for row in sorted(ready, key=lambda r: r["id"]):
            ordered.append(row)
            seen.add(row["id"])
            pending.remove(row)
    return ordered


def _saved_evaluations(session: Session) -> None:
    cutoffs = {origin.origin_date: origin.cutoff_ts for origin in load_evaluation_origins(origin_dates=list(ORIGINS))}
    for path in sorted((PACKAGE_ROOT / "data/evaluation").glob("visa_*.json")):
        report = json.loads(path.read_text())
        if "origins" not in report or "config_hash" not in report:
            continue
        config = report["config"]
        for origin in report["origins"]:
            if origin["origin_date"] not in ORIGINS or "scores" not in origin:
                continue
            for metric, value in origin["scores"].items():
                session.add(
                    m.EvaluationResult(
                        suite_version=config["suite_version"],
                        origin_ts=cutoffs[origin["origin_date"]],
                        model_variant=config["model_variant"],
                        metric=metric,
                        value=float(value),
                        config_hash=report["config_hash"],
                        details={
                            "saved_report": str(path.relative_to(PACKAGE_ROOT)),
                            "label": origin["label"],
                            "original_run_id": origin["run_id"],
                            "historical_snapshot": True,
                        },
                    )
                )


def build_demo(factory: sessionmaker[Session], store: LocalArtifactStore, registration_records: Path) -> Path:
    """Refuse a nonempty database. Generation never runs during startup."""
    with factory() as session:
        if any(session.scalar(select(func.count()).select_from(cls)) for cls in TABLES.values()):
            raise DemoError("Demo generation requires an empty migrated disposable database")
    for cls in TABLES.values():
        event.listen(cls, "before_insert", _stable_id)
    try:
        return _build(factory, store, registration_records)
    finally:
        for cls in TABLES.values():
            event.remove(cls, "before_insert", _stable_id)


def _build(factory: sessionmaker[Session], store: LocalArtifactStore, registration_records: Path) -> Path:
    registration = load_registration(DEMO_DIR / "forecasts/prospective_fy2026q4.json")
    records = json.loads(registration_records.read_text())
    with factory.begin() as session:
        for table in TABLES:
            for row in records[table]:
                session.add(TABLES[table](**_decoded_row(table, row)))
                session.flush()
    prospective_run = records["run"][0]
    store.write_bytes(prospective_run["outputs_path"], (DEMO_DIR / "forecasts" / registration.paths_file).read_bytes())
    origins = load_evaluation_origins(origin_dates=list(ORIGINS))
    freeze_evidence(factory, origins)
    with factory() as session:
        _attach_sources(session, store, prospective_run["cutoff_ts"][:10])
    snapshot = freeze_evidence(factory, origins)
    links: list[dict[str, str]] = []
    for origin in origins:
        calibration = load_calibration_artifact(artifact_path(origin.origin_date))
        with factory.begin() as session:
            parameters, _, _ = prepare_parameters(
                session,
                calibration,
                snapshot,
                origin.origin_date,
                external_evidence=True,
                sensitivity={},
            )
            group = uuid.uuid5(NAMESPACE, f"pair:{origin.origin_date}")
            baseline = create_scenario(
                session,
                company="visa",
                name=f"Demo {origin.origin_date} baseline",
                parameter_set_id=parameters.id,
                interventions=[],
                pair_group_id=group,
                parameter_overrides={},
            )
            baseline_run = submit_run(
                session,
                scenario_id=baseline.id,
                cutoff_ts=origin.cutoff_ts,
                seed=22,
                n_paths=5000,
                n_quarters=4,
                switches={},
            )
            baseline_id, job_id = baseline_run.id, baseline_run.job_id
        assert job_id is not None
        execute_run(factory, baseline_id, job_id=job_id, artifact_store=store)
        with factory.begin() as session:
            archive_forecasts(session, baseline_id, kind="retrospective")
        for name, intervention in (
            ("mix shift", {"type": "mix_shift_conserving_total", "cross_border_change": -0.10}),
            ("spending reduction", {"type": "total_spend_reduction", "reduction": 0.05}),
        ):
            with factory.begin() as session:
                scenario = create_scenario(
                    session,
                    company="visa",
                    name=f"Demo {origin.origin_date} {name}",
                    parameter_set_id=parameters.id,
                    interventions=[intervention],
                    pair_group_id=group,
                    parameter_overrides={},
                )
                variant = submit_run(
                    session,
                    scenario_id=scenario.id,
                    cutoff_ts=origin.cutoff_ts,
                    seed=22,
                    n_paths=5000,
                    n_quarters=4,
                    switches={},
                    baseline_run_id=baseline_id,
                )
                variant_id, job_id = variant.id, variant.job_id
            assert job_id is not None
            execute_run(factory, variant_id, job_id=job_id, artifact_store=store)
            links.append(
                {
                    "label": f"{origin.origin_date}: {name}",
                    "path": f"/scenarios?origin={origin.origin_date}&baseline_run_id={baseline_id}&run_id={variant_id}",
                }
            )
    with factory.begin() as session:
        _saved_evaluations(session)
    files: dict[str, dict[str, str]] = {}
    tables: dict[str, list[dict[str, Any]]] = {}
    with factory() as session:
        for table, cls in TABLES.items():
            tables[table] = sorted([row_payload(row) for row in session.scalars(select(cls))], key=content_hash)
        tables["parameter_set"] = _parameter_order(tables["parameter_set"])
        tables["run"].sort(key=lambda row: bool(row["baseline_run_id"]))
        for row in tables["run"]:
            report = replay_run(session, uuid.UUID(row["id"]), artifact_store=store)
            allowed = {"exact_match"}
            if row["id"] == registration.run["id"]:
                # The archive belongs to its original runtime. Never regenerate
                # it to erase floating-point differences on another platform.
                allowed.add("numerically_equivalent")
            if report["status"] not in allowed:
                raise DemoError(f"Generated run does not replay exactly: {row['id']}")
            row["job_id"] = None
            if row["id"] == registration.run["id"]:
                path = DEMO_DIR / "forecasts" / registration.paths_file
            else:
                path = DEMO_DIR / "runs" / row["id"] / "paths.npz"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(store.read_bytes(row["outputs_path"]))
            relative = str(path.relative_to(PACKAGE_ROOT))
            files[relative] = {
                "path": relative,
                "sha256": sha256_hex(path.read_bytes()),
                "artifact_key": row["outputs_path"],
            }
        for source in tables["source"]:
            relative = source["original_path"]
            digest = source["content_hash"]
            source["original_path"] = f"originals/{digest[:2]}/{digest}"
            entry = {
                "path": relative,
                "sha256": sha256_hex((PACKAGE_ROOT / relative).read_bytes()),
                "artifact_key": source["original_path"],
                "artifact_sha256": digest,
            }
            if relative.endswith(".gz"):
                entry["encoding"] = "gzip"
            files[relative] = entry
    # Pin all demo dependencies (including reports and calibration) without copying.
    for directory in ("data/calibration", "data/evaluation", "data/fixtures", "data/demo/forecasts", "config"):
        for path in sorted((PACKAGE_ROOT / directory).rglob("*")):
            if path.is_file():
                relative = str(path.relative_to(PACKAGE_ROOT))
                files.setdefault(relative, {"path": relative, "sha256": sha256_hex(path.read_bytes())})
    bundle = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "origins": list(ORIGINS),
        "tables": tables,
        "files": sorted(files.values(), key=lambda r: r["path"]),
        "links": links + [{"label": "Frozen prospective replay", "path": f"/replay?run_id={registration.run['id']}"}],
    }
    bundle["content_hash"] = content_hash(bundle)
    destination = DEMO_DIR / "manifest.json"
    destination.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    load_bundle(destination)
    return destination
