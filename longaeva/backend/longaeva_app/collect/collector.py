"""Manifest-driven source collector (LON-13).

Fetches curated documents politely, stores content-addressed originals, records
publication vs retrieval timestamps, extracts page-preserving passages, and
reports unavailable sources without bypassing access controls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.collect.census import fetch_census_pdf
from longaeva_app.collect.edgar import fetch_edgar_document
from longaeva_app.collect.edgar_index import format_utc
from longaeva_app.collect.http import FetchError, PoliteClient, SourceUnavailable
from longaeva_app.collect.ir import fetch_ir_pdf
from longaeva_app.collect.manifest import DocumentEntry, load_manifests
from longaeva_app.collect.text import Passage, extract_passages
from longaeva_app.config import Settings, get_settings
from longaeva_app.db.models import DocumentText, Source, SourceRetrieval
from longaeva_app.db.session import get_session_factory
from longaeva_app.hashing import sha256_hex
from longaeva_app.storage.local import LocalArtifactStore

EntryStatus = Literal["collected", "cached", "refreshed", "superseded", "unavailable", "failed", "dry_run"]


@dataclass
class EntryResult:
    key: str
    status: EntryStatus
    source_id: str | None = None
    content_hash: str | None = None
    publication_ts: str | None = None
    retrieval_ts: str | None = None
    passage_count: int = 0
    duplicate_passages: int = 0
    http_status: int | None = None
    message: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class CollectionReport:
    started_at: str
    finished_at: str | None = None
    refresh: bool = False
    dry_run: bool = False
    entries: list[EntryResult] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return sum(1 for e in self.entries if e.status == "failed")

    @property
    def unavailable_count(self) -> int:
        return sum(1 for e in self.entries if e.status == "unavailable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "refresh": self.refresh,
            "dry_run": self.dry_run,
            "counts": {
                "total": len(self.entries),
                "collected": sum(1 for e in self.entries if e.status == "collected"),
                "cached": sum(1 for e in self.entries if e.status == "cached"),
                "refreshed": sum(1 for e in self.entries if e.status == "refreshed"),
                "superseded": sum(1 for e in self.entries if e.status == "superseded"),
                "unavailable": self.unavailable_count,
                "failed": self.failed_count,
                "dry_run": sum(1 for e in self.entries if e.status == "dry_run"),
            },
            "entries": [
                {
                    "key": e.key,
                    "status": e.status,
                    "source_id": e.source_id,
                    "content_hash": e.content_hash,
                    "publication_ts": e.publication_ts,
                    "retrieval_ts": e.retrieval_ts,
                    "passage_count": e.passage_count,
                    "duplicate_passages": e.duplicate_passages,
                    "http_status": e.http_status,
                    "message": e.message,
                    "warnings": e.warnings,
                }
                for e in self.entries
            ],
        }


def collect(
    *,
    session: Session | None = None,
    store: LocalArtifactStore | None = None,
    client: PoliteClient | None = None,
    settings: Settings | None = None,
    manifests: list[str] | None = None,
    only_keys: list[str] | None = None,
    refresh: bool = False,
    dry_run: bool = False,
    entries: list[DocumentEntry] | None = None,
) -> CollectionReport:
    """Collect curated documents into the artifact store and database."""
    cfg = settings or get_settings()
    started = datetime.now(UTC)
    report = CollectionReport(started_at=format_utc(started), refresh=refresh, dry_run=dry_run)

    own_session = session is None
    own_client = client is None
    db = session or get_session_factory()()
    artifact_store = store or LocalArtifactStore(Path(cfg.artifact_dir))
    http = client
    if http is None and not dry_run:
        http = PoliteClient(user_agent=cfg.sec_user_agent)

    try:
        docs = entries if entries is not None else load_manifests(names=manifests)
        if only_keys:
            wanted = set(only_keys)
            docs = [d for d in docs if d.key in wanted]
            missing = wanted - {d.key for d in docs}
            for key in sorted(missing):
                report.entries.append(EntryResult(key=key, status="failed", message="unknown manifest key"))

        for entry in docs:
            report.entries.append(
                _collect_one(
                    entry,
                    session=db,
                    store=artifact_store,
                    client=http,
                    refresh=refresh,
                    dry_run=dry_run,
                )
            )
            if own_session and not dry_run:
                db.commit()
    finally:
        report.finished_at = format_utc(datetime.now(UTC))
        if own_client and http is not None:
            http.close()
        if own_session:
            if dry_run:
                db.rollback()
            db.close()

    if not dry_run:
        _write_report(artifact_store, report)
    return report


def canonical_passage(session: Session, text_hash: str) -> DocumentText | None:
    """Return the earliest-published passage with the given normalized text hash (DR-08)."""
    stmt = (
        select(DocumentText)
        .join(Source, DocumentText.source_id == Source.id)
        .where(DocumentText.text_hash == text_hash)
        .order_by(Source.publication_ts.asc(), DocumentText.id.asc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _collect_one(
    entry: DocumentEntry,
    *,
    session: Session,
    store: LocalArtifactStore,
    client: PoliteClient | None,
    refresh: bool,
    dry_run: bool,
) -> EntryResult:
    if entry.availability != "available":
        return EntryResult(
            key=entry.key,
            status="unavailable",
            message=entry.unavailable_reason or "unavailable_for_automation",
            http_status=(entry.attributes or {}).get("http_status"),
        )

    existing = _find_source_by_key(session, entry.key)
    if existing is not None and not refresh and store.exists(existing.original_path):
        return EntryResult(
            key=entry.key,
            status="cached",
            source_id=str(existing.id),
            content_hash=existing.content_hash,
            publication_ts=format_utc(existing.publication_ts),
            retrieval_ts=format_utc(existing.retrieval_ts),
            passage_count=len(existing.passages) if existing.passages is not None else 0,
            message="already collected; pass --refresh to re-fetch",
        )

    if dry_run:
        return EntryResult(key=entry.key, status="dry_run", message="would fetch")

    if client is None:
        return EntryResult(key=entry.key, status="failed", message="HTTP client not configured")

    try:
        fetched = _fetch_entry(entry, client)
    except SourceUnavailable as exc:
        return EntryResult(
            key=entry.key,
            status="unavailable",
            message=exc.reason,
            http_status=exc.http_status,
        )
    except FetchError as exc:
        return EntryResult(
            key=entry.key,
            status="failed",
            message=str(exc),
            http_status=exc.http_status,
        )
    except Exception as exc:  # noqa: BLE001 — per-entry isolation
        return EntryResult(key=entry.key, status="failed", message=f"{type(exc).__name__}: {exc}")

    from datetime import timedelta

    retrieval_ts = datetime.now(UTC)
    if fetched["publication_ts"] >= retrieval_ts:
        # Ensure CHECK publication_ts < retrieval_ts (clock skew / fixture clocks).
        retrieval_ts = fetched["publication_ts"] + timedelta(seconds=1)

    content: bytes = fetched["content"]
    digest = sha256_hex(content)
    warnings: list[str] = list(fetched.get("warnings") or [])
    attributes: dict[str, Any] = {
        "manifest_key": entry.key,
        "publication_ts_source": fetched.get("publication_ts_source") or entry.publication_ts_source,
        **(entry.attributes or {}),
        **(fetched.get("attributes") or {}),
    }
    if entry.expected_sha256 and entry.expected_sha256 != digest:
        attributes["hash_mismatch"] = True
        attributes["expected_sha256"] = entry.expected_sha256
        warnings.append(f"content hash mismatch: got {digest[:12]}… expected {entry.expected_sha256[:12]}…")
    if entry.integrity_flag:
        attributes["integrity_flag"] = entry.integrity_flag

    by_hash = session.execute(select(Source).where(Source.content_hash == digest)).scalar_one_or_none()
    if by_hash is not None:
        session.add(
            SourceRetrieval(
                source_id=by_hash.id,
                retrieved_at=retrieval_ts,
                url=fetched["url"],
                http_status=fetched.get("http_status"),
                etag=fetched.get("etag"),
                notes=f"recollect key={entry.key}",
            )
        )
        # Ensure the manifest key is recorded on the existing source.
        attrs = dict(by_hash.attributes or {})
        attrs.setdefault("manifest_key", entry.key)
        by_hash.attributes = attrs
        session.flush()
        status: EntryStatus = "refreshed" if refresh else "cached"
        return EntryResult(
            key=entry.key,
            status=status,
            source_id=str(by_hash.id),
            content_hash=digest,
            publication_ts=format_utc(by_hash.publication_ts),
            retrieval_ts=format_utc(retrieval_ts),
            passage_count=len(by_hash.passages) if by_hash.passages is not None else 0,
            http_status=fetched.get("http_status"),
            warnings=warnings,
            message="content hash already present; recorded retrieval only",
        )

    original_path, _ = store.put_original(content)
    supersedes_id = _resolve_supersedes(session, entry, existing)
    period_start, period_end = _period_bounds(entry)

    source = Source(
        provider=entry.provider,
        company=entry.company,
        doc_type=entry.doc_type,
        url=fetched["url"],
        publication_ts=fetched["publication_ts"],
        retrieval_ts=retrieval_ts,
        period_start=period_start,
        period_end=period_end,
        content_hash=digest,
        original_path=original_path,
        license_note=entry.license_note,
        supersedes_id=supersedes_id,
        attributes=attributes,
    )
    session.add(source)
    session.flush()

    session.add(
        SourceRetrieval(
            source_id=source.id,
            retrieved_at=retrieval_ts,
            url=fetched["url"],
            http_status=fetched.get("http_status"),
            etag=fetched.get("etag"),
            notes=f"collect key={entry.key}",
        )
    )

    passages = extract_passages(
        content,
        content_type=fetched.get("content_type"),
        filename=fetched.get("filename") or entry.document,
    )
    dup_count = _insert_passages(session, source.id, passages)

    status = "superseded" if supersedes_id is not None else "collected"
    return EntryResult(
        key=entry.key,
        status=status,
        source_id=str(source.id),
        content_hash=digest,
        publication_ts=format_utc(source.publication_ts),
        retrieval_ts=format_utc(source.retrieval_ts),
        passage_count=len(passages),
        duplicate_passages=dup_count,
        http_status=fetched.get("http_status"),
        warnings=warnings,
    )


def _fetch_entry(entry: DocumentEntry, client: PoliteClient) -> dict[str, Any]:
    provider = entry.provider
    if provider == "census" or entry.doc_type == "marts_advance":
        doc = fetch_census_pdf(
            client,
            entry.url or "",
            expected_publication_ts=entry.publication_ts,
            release_id=(entry.period.release_id if entry.period else None),
            integrity_flag=entry.integrity_flag,
        )
        attrs: dict[str, Any] = {
            "release_id": doc.release_meta.release_id,
            "release_number": doc.release_meta.release_number,
            "reference_month": doc.release_meta.reference_month,
            "page_count": doc.release_meta.page_count,
        }
        if doc.integrity_flag:
            attrs["integrity_flag"] = doc.integrity_flag
        return {
            "url": doc.url,
            "content": doc.content,
            "publication_ts": doc.publication_ts,
            "publication_ts_source": doc.publication_ts_source,
            "http_status": doc.http_status,
            "etag": doc.etag,
            "content_type": "application/pdf",
            "filename": f"{doc.release_meta.release_id}.pdf",
            "attributes": attrs,
        }

    if provider == "visa_ir" or entry.doc_type in {"ir_deck", "ir_transcript"}:
        kind = "transcript" if "transcript" in entry.doc_type else "deck"
        doc_ir = fetch_ir_pdf(
            client,
            entry.url or "",
            doc_kind=kind,
            cutoff_utc=entry.cutoff_utc,
            call_date=entry.call_date,
        )
        return {
            "url": doc_ir.url,
            "content": doc_ir.content,
            "publication_ts": doc_ir.publication_ts,
            "publication_ts_source": doc_ir.publication_ts_source,
            "http_status": doc_ir.http_status,
            "etag": doc_ir.etag,
            "content_type": "application/pdf",
            "filename": (entry.url or "").rsplit("/", 1)[-1],
            "attributes": doc_ir.attributes,
            "warnings": list(doc_ir.timing_notes),
        }

    # Default: SEC EDGAR
    if not entry.cik or not entry.accession:
        if entry.url:
            result = client.get(entry.url)
            if entry.publication_ts is None:
                raise FetchError(entry.url, "publication_ts required for direct URL EDGAR fetch")
            return {
                "url": entry.url,
                "content": result.content,
                "publication_ts": entry.publication_ts,
                "publication_ts_source": entry.publication_ts_source or "manifest",
                "http_status": result.status_code,
                "etag": result.etag,
                "content_type": result.content_type,
                "filename": entry.document or entry.url.rsplit("/", 1)[-1],
            }
        raise FetchError(entry.key, "missing cik/accession for EDGAR entry")

    edgar = fetch_edgar_document(
        client,
        cik=entry.cik,
        accession=entry.accession,
        document=entry.document,
        exhibit=entry.exhibit,
        expected_publication_ts=entry.publication_ts,
    )
    return {
        "url": edgar.url,
        "content": edgar.content,
        "publication_ts": edgar.publication_ts,
        "publication_ts_source": edgar.publication_ts_source,
        "http_status": edgar.http_status,
        "etag": edgar.etag,
        "content_type": "text/html",
        "filename": edgar.document,
        "attributes": {"document": edgar.document, "exhibit": edgar.exhibit},
    }


def _find_source_by_key(session: Session, key: str) -> Source | None:
    # JSONB containment: attributes @> {"manifest_key": key}
    stmt = select(Source).where(Source.attributes.contains({"manifest_key": key})).order_by(Source.retrieval_ts.desc())
    return session.execute(stmt).scalars().first()


def _resolve_supersedes(session: Session, entry: DocumentEntry, existing: Source | None) -> UUID | None:
    if entry.supersedes:
        prior = _find_source_by_key(session, entry.supersedes)
        if prior is not None:
            return prior.id
    if existing is not None:
        return existing.id
    return None


def _period_bounds(entry: DocumentEntry) -> tuple[Any, Any]:
    if entry.period is None:
        return None, None
    return entry.period.period_start, entry.period.period_end


def _insert_passages(session: Session, source_id: UUID, passages: list[Passage]) -> int:
    """Insert passages; return count of DR-08 duplicates already present for another source."""
    dup = 0
    for passage in passages:
        # text_hash is generated by Postgres; we approximate the same normalize for lookup.
        norm = _normalize_for_hash(passage.text)
        existing_hash_rows = session.execute(
            select(DocumentText.id)
            .join(Source, DocumentText.source_id == Source.id)
            .where(DocumentText.text_hash == _md5_hex(norm))
            .where(DocumentText.source_id != source_id)
            .limit(1)
        ).first()
        if existing_hash_rows is not None:
            dup += 1
        session.add(
            DocumentText(
                source_id=source_id,
                page=passage.page,
                char_start=passage.char_start,
                char_end=passage.char_end,
                text=passage.text,
            )
        )
    session.flush()
    return dup


def _normalize_for_hash(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text).strip().lower()


def _md5_hex(text: str) -> str:
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _write_report(store: LocalArtifactStore, report: CollectionReport) -> str:
    stamp = report.started_at.replace(":", "").replace("-", "")
    key = f"reports/collect/{stamp}.json"
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    try:
        return store.write_once(key, payload.encode("utf-8"))
    except Exception:  # noqa: BLE001 — report write must not fail the collect
        # Collision on same-second runs: suffix with entry count.
        key = f"reports/collect/{stamp}-{len(report.entries)}.json"
        return store.write_once(key, payload.encode("utf-8"))


def summarize_report(report: CollectionReport) -> str:
    counts = report.to_dict()["counts"]
    lines = [
        f"collect finished at {report.finished_at}",
        (
            f"  total={counts['total']} collected={counts['collected']} cached={counts['cached']} "
            f"refreshed={counts['refreshed']} superseded={counts['superseded']} "
            f"unavailable={counts['unavailable']} failed={counts['failed']}"
        ),
    ]
    for entry in report.entries:
        extra = f" — {entry.message}" if entry.message else ""
        lines.append(f"  [{entry.status}] {entry.key}{extra}")
        for warning in entry.warnings:
            lines.append(f"    warning: {warning}")
    return "\n".join(lines)
