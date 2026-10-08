"""Validated, offline, transactional import of the curated LON-37 demo."""

from __future__ import annotations

import csv
import gzip
import io
import json
import uuid
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from sqlalchemy import Date, DateTime, Table, insert, select, text, tuple_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from longaeva_app.api.schemas import ParameterSetCreate
from longaeva_app.config import PACKAGE_ROOT
from longaeva_app.db import models
from longaeva_app.db.base import Base
from longaeva_app.extract.visa_tables import observation_uuid_for
from longaeva_app.hashing import content_hash, sha256_hex, utc_isoformat
from longaeva_app.runs.inputs import manifest_hash, parse_aware_utc
from longaeva_app.runs.prospective import load_registration
from longaeva_app.storage.local import LocalArtifactStore

VERSION = "lon37-v1"
MANIFEST_PATH = PACKAGE_ROOT / "data/demo/manifest.json"
TABLES: dict[str, type[Base]] = {
    cls.__tablename__: cls
    for cls in (
        models.Source,
        models.DocumentText,
        models.Observation,
        models.ReviewDecision,
        models.MappingRule,
        models.ParameterSet,
        models.ParameterUpdate,
        models.ParameterSetContext,
        models.ParameterUpdateObservation,
        models.Scenario,
        models.Run,
        models.Forecast,
        models.EvaluationResult,
    )
}
SEED_LOCK = 370020261007


class DemoError(ValueError):
    """An invalid bundle or a conflicting local immutable record."""


def json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, (date, uuid.UUID)):
        return str(value)
    return value


def row_payload(row: Base) -> dict[str, Any]:
    return {col.name: json_value(getattr(row, col.name)) for col in row.__table__.columns if col.computed is None}


def _package_file(root: Path, relative: str) -> Path:
    key = PurePosixPath(relative)
    if key.is_absolute() or ".." in key.parts or "\\" in relative or not relative:
        raise DemoError("Demo file must be a relative package path")
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise DemoError(f"Missing or unsafe demo file: {relative}")
    return path


def _decoded_row(table: str, payload: dict[str, Any]) -> dict[str, Any]:
    columns = TABLES[table].__table__.columns
    expected = {col.name for col in columns if col.computed is None}
    if set(payload) != expected:
        raise DemoError(f"Invalid columns in demo table {table}")
    decoded = dict(payload)
    for col in columns:
        value = decoded.get(col.name)
        if value is None:
            if not col.nullable and col.computed is None:
                raise DemoError(f"Missing {table}.{col.name}")
            continue
        if isinstance(col.type, UUID):
            decoded[col.name] = uuid.UUID(value)
        elif isinstance(col.type, DateTime):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise DemoError(f"Naive timestamp in {table}.{col.name}")
            decoded[col.name] = parsed
        elif isinstance(col.type, Date):
            decoded[col.name] = date.fromisoformat(value)
    return decoded


def _identity(table: str, row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[col.name] for col in TABLES[table].__table__.primary_key)


def _artifact_data(entry: dict[str, Any], root: Path) -> bytes:
    raw = _package_file(root, entry["path"]).read_bytes()
    if entry.get("encoding") == "gzip":
        return gzip.decompress(raw)
    if entry.get("encoding") is not None:
        raise DemoError("Unsupported demo artifact encoding")
    return raw


def _fixture_evidence(files: dict[str, bytes]) -> dict[str, str]:
    """Calibration links resolve to the retained Visa parser CSV, not ORM rows."""
    prefix = "data/fixtures/visa_releases/"
    manifest = json.loads(files[prefix + "sources/manifest.json"])
    published = {f"{row['accession']}/{row['document']}": row["acceptance_utc"] for row in manifest["sources"]}
    evidence: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(files[prefix + "observations.csv"].decode("utf-8"))):
        identifier = observation_uuid_for(
            source_id=row["source_id"],
            field=row["field"],
            period_label=row["period_label"],
            geography=row["geography"],
            vintage_role=row["vintage_role"],
            char_start=int(row["char_start"]),
            char_end=int(row["char_end"]),
        )
        evidence[str(identifier)] = published[row["source_id"]]
    return evidence


def load_bundle(path: Path = MANIFEST_PATH, *, root: Path = PACKAGE_ROOT) -> dict[str, Any]:
    """Validate checksums, columns, references and pinned inputs before any writes."""
    bundle: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("version") != VERSION or set(bundle.get("tables", {})) != set(TABLES):
        raise DemoError("Unsupported or incomplete demo manifest")
    if content_hash({k: v for k, v in bundle.items() if k != "content_hash"}) != bundle.get("content_hash"):
        raise DemoError("Demo manifest checksum mismatch")
    files: dict[str, bytes] = {}
    originals: dict[str, bytes] = {}
    keys: set[str] = set()
    for entry in bundle["files"]:
        relative = entry["path"]
        if relative in files:
            raise DemoError("Duplicate demo file")
        raw = _package_file(root, relative).read_bytes()
        if sha256_hex(raw) != entry["sha256"]:
            raise DemoError(f"Demo file checksum mismatch: {relative}")
        files[relative] = raw
        key = entry.get("artifact_key")
        if key:
            LocalArtifactStore._normalize_key(key)
            if key in keys:
                raise DemoError("Duplicate demo artifact key")
            keys.add(key)
            decoded_bytes = _artifact_data(entry, root)
            if sha256_hex(decoded_bytes) != entry.get("artifact_sha256", entry["sha256"]):
                raise DemoError("Demo artifact checksum mismatch")
            originals[key] = decoded_bytes
    ids: dict[str, set[tuple[Any, ...]]] = {}
    for table, rows in bundle["tables"].items():
        identities = [_identity(table, row) for row in rows]
        if len(identities) != len(set(identities)):
            raise DemoError(f"Duplicate record in {table}")
        ids[table] = set(identities)
        for row in rows:
            _decoded_row(table, row)
    for table, rows in bundle["tables"].items():
        for row in rows:
            for col in TABLES[table].__table__.columns:
                for fk in col.foreign_keys:
                    value = row[col.name]
                    if value is not None and (value,) not in ids.get(fk.column.table.name, set()):
                        raise DemoError(f"Unresolved demo reference: {table}.{col.name}")
    parameters = {row["id"]: row for row in bundle["tables"]["parameter_set"]}
    scenarios = {row["id"]: row for row in bundle["tables"]["scenario"]}
    sources = {row["id"]: row for row in bundle["tables"]["source"]}
    sources_by_hash = {row["content_hash"]: row for row in sources.values()}
    observations = {row["id"]: row for row in bundle["tables"]["observation"]}
    passages = {row["id"]: row for row in bundle["tables"]["document_text"]}
    fixture_evidence = _fixture_evidence(files)
    for observation in observations.values():
        passage = passages.get(observation["document_text_id"])
        start, end = observation["span_char_start"], observation["span_char_end"]
        if (
            passage is None
            or passage["source_id"] != observation["source_id"]
            or passage["page"] != observation["span_page"]
            or start is None
            or end is None
            or not passage["char_start"] <= start < end <= passage["char_end"]
            or end - passage["char_start"] > len(passage["text"])
        ):
            raise DemoError("Invalid demo observation evidence span")
    for row in parameters.values():
        for link in row["evidence_links"].values():
            for observation_id in link["observation_ids"]:
                observation = observations.get(observation_id)
                published = (
                    sources[observation["source_id"]]["publication_ts"]
                    if observation is not None
                    else fixture_evidence.get(observation_id)
                )
                if published is None:
                    raise DemoError("Unresolved demo parameter evidence reference")
                if parse_aware_utc(published) > parse_aware_utc(row["cutoff_ts"]):
                    raise DemoError("Demo parameter evidence was published after its cutoff")
        create = ParameterSetCreate.model_validate({k: v for k, v in row.items() if k not in {"id", "created_at"}})
        if create.computed_content_hash() != row["content_hash"]:
            raise DemoError("Demo parameter hash mismatch")
    for source in sources.values():
        original_bytes = originals.get(source["original_path"])
        if original_bytes is None:
            raise DemoError("Demo source original is not inventoried")
        if sha256_hex(original_bytes) != source["content_hash"]:
            raise DemoError("Demo source original checksum mismatch")
    for row in bundle["tables"]["run"]:
        parameter = parameters[scenarios[row["scenario_id"]]["parameter_set_id"]]
        for entry in row["source_manifest"]:
            source = (
                sources.get(entry["source_id"]) if "source_id" in entry else sources_by_hash.get(entry["content_hash"])
            )
            if source is None or source["content_hash"] != entry["content_hash"]:
                raise DemoError("Unresolved demo run source reference")
            if parse_aware_utc(source["publication_ts"]) != parse_aware_utc(entry["publication_ts"]):
                raise DemoError("Demo run source publication timestamp mismatch")
        if (
            row["status"] != "succeeded"
            or row["outputs_path"] not in keys
            or row["job_id"] is not None
            or row["parameter_set_hash"] != parameter["content_hash"]
            or manifest_hash(row["source_manifest"]) != row["source_manifest_hash"]
            or content_hash(row["starting_state"]) != row["starting_state_hash"]
            or content_hash(row["interventions"]) != row["interventions_hash"]
        ):
            raise DemoError("Invalid pinned demo run")
        if any(
            parse_aware_utc(entry["publication_ts"]) > parse_aware_utc(row["cutoff_ts"])
            for entry in row["source_manifest"]
        ):
            raise DemoError("Demo run contains a post-cutoff source")
    registration = load_registration(root / "data/demo/forecasts/prospective_fy2026q4.json")
    run = next((row for row in bundle["tables"]["run"] if row["id"] == registration.run["id"]), None)
    if run is None or any(run[k] != v for k, v in registration.run.items()):
        raise DemoError("Demo run differs from frozen prospective registration")
    forecasts = {row["id"]: row for row in bundle["tables"]["forecast"]}
    for archived in registration.forecasts:
        row = forecasts.get(archived["id"])
        if row is None or any(row[k] != v for k, v in archived.items() if k != "period_label"):
            raise DemoError("Demo forecast differs from frozen prospective registration")
    return bundle


def _existing_rows(session: Session, table: str, rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], Base]:
    cls = TABLES[table]
    primary = list(cls.__table__.primary_key)
    keys = [_identity(table, _decoded_row(table, row)) for row in rows]
    if not keys:
        return {}
    condition: ColumnElement[bool] = (
        primary[0].in_([key[0] for key in keys]) if len(primary) == 1 else tuple_(*primary).in_(keys)
    )
    if table == "document_text":
        condition = condition | models.DocumentText.source_id.in_([uuid.UUID(row["source_id"]) for row in rows])
    found = session.scalars(select(cls).where(condition))
    return {_identity(table, row_payload(row)): row for row in found}


def _remap(row: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    def visit(value: Any) -> Any:
        if isinstance(value, str):
            return aliases.get(value, value)
        if isinstance(value, dict):
            return {k: visit(v) for k, v in value.items()}
        if isinstance(value, list):
            return [visit(v) for v in value]
        return value

    return dict(visit(row))


def _frozen_parameter_ids(bundle: dict[str, Any]) -> set[str]:
    parameters = {row["id"]: row for row in bundle["tables"]["parameter_set"]}
    scenarios = {row["id"]: row for row in bundle["tables"]["scenario"]}
    run_id = next(row["run_id"] for row in bundle["tables"]["forecast"] if row["kind"] == "prospective")
    run = next(row for row in bundle["tables"]["run"] if row["id"] == run_id)
    current: str | None = scenarios[run["scenario_id"]]["parameter_set_id"]
    frozen: set[str] = set()
    while current is not None:
        if current in frozen:
            raise DemoError("Cyclic frozen parameter lineage")
        frozen.add(current)
        current = parameters[current]["parent_id"]
    return frozen


def seed_demo(
    factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    path: Path = MANIFEST_PATH,
    root: Path = PACKAGE_ROOT,
) -> dict[str, Any]:
    bundle = load_bundle(path, root=root)
    counts: dict[str, dict[str, int]] = {}
    aliases: dict[str, str] = {}
    frozen_parameters = _frozen_parameter_ids(bundle)
    frozen_observations = {
        observation_id
        for row in bundle["tables"]["parameter_set"]
        if row["id"] in frozen_parameters
        for link in row["evidence_links"].values()
        for observation_id in link["observation_ids"]
    } | {
        row["observation_id"]
        for row in bundle["tables"]["parameter_set_context"]
        if row["parameter_set_id"] in frozen_parameters
    }
    with factory.begin() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK})
        # Preflight existing artifacts before database writes. Leftover matching files
        # from a rolled-back transaction are safe to reuse on the next attempt.
        for entry in bundle["files"]:
            key = entry.get("artifact_key")
            expected = entry.get("artifact_sha256", entry["sha256"])
            if key and store.exists(key) and sha256_hex(store.read_bytes(key)) != expected:
                raise DemoError(f"Conflicting demo artifact: {key}")
        for table in TABLES:
            counts[table] = {"imported": 0, "reused": 0}
            existing_rows = _existing_rows(session, table, [_remap(row, aliases) for row in bundle["tables"][table]])
            passages = (
                {
                    (row.source_id, row.page, row.char_start): row  # type: ignore[attr-defined]
                    for row in existing_rows.values()
                }
                if table == "document_text"
                else {}
            )
            pending: list[dict[str, Any]] = []
            for payload in bundle["tables"][table]:
                row = _remap(payload, aliases)
                if table == "parameter_set":
                    create = ParameterSetCreate.model_validate(
                        {k: v for k, v in row.items() if k not in {"id", "created_at"}}
                    )
                    digest = create.computed_content_hash()
                    if digest != payload["content_hash"]:
                        if payload["id"] in frozen_parameters:
                            raise DemoError("Frozen registration requires its original parameter identifiers")
                        aliases[payload["content_hash"]] = digest
                        row["content_hash"] = digest
                decoded = _decoded_row(table, row)
                existing = existing_rows.get(_identity(table, row))
                natural = {
                    "source": ("content_hash",),
                    "mapping_rule": ("rule_key", "version"),
                    "document_text": ("source_id", "page", "char_start"),
                    "parameter_set": ("content_hash",),
                    "parameter_set_context": ("parameter_set_id", "observation_id"),
                    "parameter_update_observation": ("parameter_update_id", "observation_id"),
                    "review_decision": ("observation_id", "version"),
                }.get(table)
                if existing is None and natural:
                    if table == "document_text":
                        existing = passages.get(tuple(decoded[k] for k in natural))
                    else:
                        existing = session.scalar(select(TABLES[table]).filter_by(**{k: decoded[k] for k in natural}))
                if existing is None and table == "observation" and payload["id"] not in frozen_observations:
                    existing = session.scalar(
                        select(models.Observation).where(
                            models.Observation.source_id == decoded["source_id"],
                            models.Observation.attributes["fixture_observation_id"].astext
                            == row["attributes"].get("fixture_observation_id"),
                        )
                    )
                if existing is not None:
                    actual = row_payload(existing)
                    ignored = {"created_at"}
                    if table in {"run", "forecast"}:
                        ignored = set()
                    if table == "source":
                        ignored |= {"id", "retrieval_ts", "original_path", "license_note", "attributes"}
                    elif table in {"mapping_rule", "document_text", "parameter_set", "parameter_set_context"}:
                        ignored |= {"id"}
                    elif table == "observation":
                        ignored |= {"review_status", "id"}
                        # Enrich older gate rows with missing evidence metadata;
                        # all measurement fields still must match below.
                        if actual["document_text_id"] is None and (
                            (
                                actual["span_char_start"] == row["span_char_start"]
                                and actual["span_char_end"] == row["span_char_end"]
                            )
                            or all(actual[k] is None for k in ("span_page", "span_char_start", "span_char_end"))
                        ):
                            existing.document_text_id = decoded["document_text_id"]  # type: ignore[attr-defined]
                            existing.span_page = decoded["span_page"]  # type: ignore[attr-defined]
                            existing.span_char_start = decoded["span_char_start"]  # type: ignore[attr-defined]
                            existing.span_char_end = decoded["span_char_end"]  # type: ignore[attr-defined]
                            ignored |= {"document_text_id", "span_page", "span_char_start", "span_char_end"}
                    elif table == "review_decision" and payload["observation_id"] in aliases:
                        # A previously reviewed natural-key match owns its own
                        # history. Do not replace it with the curator's version.
                        counts[table]["reused"] += 1
                        continue
                    if any(actual[k] != v for k, v in row.items() if k not in ignored):
                        raise DemoError(f"Conflicting immutable demo record in {table}: {_identity(table, row)}")
                    if "id" in payload and str(existing.id) != payload["id"]:  # type: ignore[attr-defined]
                        if table == "parameter_set" and payload["id"] in frozen_parameters:
                            raise DemoError("Frozen registration requires its original parameter identifiers")
                        aliases[payload["id"]] = str(existing.id)  # type: ignore[attr-defined]
                    counts[table]["reused"] += 1
                    continue
                pending.append(decoded)
                counts[table]["imported"] += 1
            if pending:
                session.execute(insert(cast(Table, TABLES[table].__table__)), pending)
            session.flush()
        for entry in bundle["files"]:
            key = entry.get("artifact_key")
            if key and not store.exists(key):
                store.write_bytes(key, _artifact_data(entry, root))
    return {"version": bundle["version"], "counts": counts, "links": bundle["links"]}
