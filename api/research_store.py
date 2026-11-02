"""Workspace research stored as authoritative DocumentArtifact versions and private blobs."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from api import state_storage as storage
from api.exceptions import NotFoundError, ValidationError
from api.postgres import connect
from ontology.object_service import OntologyObjectService, object_uid_for
from ontology.temporal_repository import TemporalOntologyRepository
from paths import PROJECT_ROOT

CATEGORIES = {
    "equity_strategy": "Equity Strategy",
    "credit_strategy": "Credit Strategy",
    "economic": "Economic",
    "industry_thematic": "Industry & Thematic",
}
ACTIVE = {"queued", "reading", "condensing", "checking"}
PREFIX = "live/research"


class SupersededResearch(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


def validate_id(report_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", report_id):
        raise NotFoundError("Research report", report_id)
    return report_id


def uid(report_id: str) -> str:
    key = f"research-{validate_id(report_id)}"
    return object_uid_for("DocumentArtifact", key, {"document_type": "research_report", "document_id": key})


def blob_key(report_id: str, filename: str) -> str:
    validate_id(report_id)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename):
        raise ValidationError("Invalid research artifact name.")
    return f"{PREFIX}/{report_id}/{filename}"


def read_blob(report_id: str, filename: str) -> bytes:
    key = blob_key(report_id, filename)
    return storage.read_bytes(PROJECT_ROOT / key, key)


def write_blob(report_id: str, filename: str, content: bytes, mime: str) -> None:
    key = blob_key(report_id, filename)
    storage.write_bytes(PROJECT_ROOT / key, key, content, content_type=mime)


class _TransactionConnection:
    """Keep repository commits inside the caller's advisory-lock transaction."""

    def __init__(self, connection: Any):
        self.connection = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)

    def commit(self) -> None:
        pass


@contextmanager
def locked(report_id: str) -> Iterator[OntologyObjectService]:
    validate_id(report_id)
    with connect() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"research:{report_id}",))

        @contextmanager
        def bound():
            yield _TransactionConnection(conn)

        yield OntologyObjectService(TemporalOntologyRepository(bound))


def _state(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    props = row.get("properties_json") or row.get("properties") or {}
    if props.get("document_type") != "research_report":
        return None
    return {**props["metadata"], "object_uid": row["object_uid"], "object_version_id": str(row["version_id"])}


def _write(service: OntologyObjectService, state: dict[str, Any], actor: Any) -> dict[str, Any]:
    state = {k: v for k, v in state.items() if k not in {"object_uid", "object_version_id"}}
    state["updated_at"] = now()
    report_id = state["id"]
    event_id = f"research:{report_id}:{uuid4().hex}"
    # The audit event and document version share the same transaction and connection.
    service.write_object(
        "ProvenanceEvent",
        event_id,
        {
            "event_id": event_id,
            "event_type": "source_adapter_run",
            "event_name": "research_report_update",
            "status": "succeeded",
            "started_at": state["updated_at"],
            "completed_at": state["updated_at"],
            "summary": {"report_id": report_id, "status": state["status"]},
            "lineage_root_id": f"research:{report_id}",
            "retention_class": "user_state",
            "redaction_policy": "safe_summary",
        },
        state["updated_at"],
        actor=actor,
        provenance=event_id,
    )
    row = service.write_object(
        "DocumentArtifact",
        f"research-{report_id}",
        {
            "document_type": "research_report",
            "document_id": f"research-{report_id}",
            "title": state.get("title"),
            "mime_type": "application/pdf",
            "content_hash": report_id,
            "byte_size": state["size"],
            "artifact_uri": blob_key(report_id, "original.pdf"),
            "status": "deleted" if state["status"] == "deleted" else "active",
            "source_type": "research_upload",
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
            "metadata": state,
        },
        state["created_at"],
        actor=actor,
        provenance=event_id,
    )
    return _state(row) or state


def get(report_id: str, *, include_deleted: bool = False) -> dict[str, Any]:
    state = _state(OntologyObjectService().get_object(uid(report_id)))
    if not state or (state["status"] == "deleted" and not include_deleted):
        raise NotFoundError("Research report", report_id)
    return state


def mutate(
    report_id: str, change: Callable[[dict[str, Any]], None], *, actor: Any = None, token: str | None = None
) -> dict[str, Any]:
    with locked(report_id) as service:
        state = _state(service.get_object(uid(report_id)))
        if not state or state["status"] == "deleted":
            raise NotFoundError("Research report", report_id)
        if token is not None and state.get("token") != token:
            raise SupersededResearch("This processing attempt has been replaced.")
        change(state)
        return _write(service, state, actor)


def create(data: bytes, filename: str, category: str | None, pages: int, actor: Any) -> tuple[dict[str, Any], bool]:
    report_id = hashlib.sha256(data).hexdigest()
    with locked(report_id) as service:
        existing = _state(service.get_object(uid(report_id)))
        if existing and existing["status"] != "deleted":
            return existing, False
        write_blob(report_id, "original.pdf", data, "application/pdf")
        stamp = now()
        state = {
            "id": report_id,
            "filename": filename,
            "size": len(data),
            "page_count": pages,
            "title": None,
            "subtitle": None,
            "institution": None,
            "publication_date": None,
            "authors": [],
            "category": category,
            "category_source": "manual" if category else "automatic",
            "category_uncertain": False,
            "status": "queued",
            "token": uuid4().hex,
            "job_id": None,
            "created_at": stamp,
            "updated_at": stamp,
            "revisions": [],
            "current_revision": None,
            "issues": [],
            "error": None,
            "index_status": "pending",
        }
        return _write(service, state, actor), True


def all_reports() -> list[dict[str, Any]]:
    service = OntologyObjectService()
    reports: list[dict[str, Any]] = []
    offset = 0
    while True:
        rows = service.query_objects(
            "DocumentArtifact", {"document_type": "research_report", "status": "active"}, limit=200, offset=offset
        )
        reports.extend(state for row in rows if (state := _state(row)))
        if len(rows) < 200:
            return reports
        offset += len(rows)


def save_artifact(report_id: str, token: str, filename: str, content: bytes, mime: str) -> None:
    # Serialize blob publication with deletion and retry, so stale workers cannot restore files.
    with locked(report_id) as service:
        state = _state(service.get_object(uid(report_id)))
        if not state or state["status"] == "deleted" or state.get("token") != token:
            raise SupersededResearch("This processing attempt is no longer active.")
        write_blob(report_id, filename, content, mime)
