"""Visa IR CDN PDF fetch helpers (LON-13 / ER-07 / DR-04)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from longaeva_app.collect.edgar_index import EASTERN
from longaeva_app.collect.http import FetchError, PoliteClient
from longaeva_app.collect.visa_ir import DECK_EVENT_WINDOW_SECONDS, parse_http_datetime


@dataclass(frozen=True)
class IrDocument:
    """Fetched IR PDF with Last-Modified publication timestamp."""

    url: str
    content: bytes
    publication_ts: datetime
    publication_ts_source: str
    http_status: int
    etag: str | None
    headers: dict[str, str]
    timing_ok: bool
    timing_notes: list[str]
    attributes: dict[str, Any]


def fetch_ir_pdf(
    client: PoliteClient,
    url: str,
    *,
    doc_kind: str,
    cutoff_utc: datetime | None = None,
    call_date: date | None = None,
) -> IrDocument:
    """Fetch an IR deck/transcript PDF.

    ``publication_ts`` is the HTTP ``Last-Modified`` header. Missing
    Last-Modified refuses ingestion (DR-04). Timing checks against the
    ``visa_ir.yaml`` event-window rules flag mismatches but still ingest.
    """
    result = client.get(url)
    last_modified = parse_http_datetime(result.last_modified)
    if last_modified is None:
        raise FetchError(url, "missing Last-Modified header; refusing IR ingest (DR-04)")

    notes: list[str] = []
    timing_ok = True
    if doc_kind == "deck" and cutoff_utc is not None:
        delta = abs((last_modified - cutoff_utc).total_seconds())
        if delta > DECK_EVENT_WINDOW_SECONDS:
            timing_ok = False
            notes.append(
                f"deck Last-Modified delta {delta:.0f}s exceeds {DECK_EVENT_WINDOW_SECONDS}s event window vs cutoff"
            )
    if doc_kind == "transcript" and call_date is not None:
        lm_date = last_modified.astimezone(EASTERN).date()
        if lm_date != call_date:
            # Primary rule is call_date == cutoff Eastern date; when call_date
            # is provided on the manifest entry, require Last-Modified's
            # Eastern date to match the declared call date.
            timing_ok = False
            notes.append(
                f"transcript Last-Modified Eastern date {lm_date.isoformat()} != call_date {call_date.isoformat()}"
            )
    if doc_kind == "transcript" and cutoff_utc is not None and call_date is None:
        cutoff_date = cutoff_utc.astimezone(EASTERN).date()
        lm_date = last_modified.astimezone(EASTERN).date()
        if lm_date != cutoff_date:
            timing_ok = False
            notes.append(
                f"transcript Last-Modified Eastern date {lm_date.isoformat()} "
                f"!= cutoff Eastern date {cutoff_date.isoformat()}"
            )

    attributes: dict[str, Any] = {
        "model_input": False,
        "ir_doc_kind": doc_kind,
        "timing_ok": timing_ok,
    }
    if notes:
        attributes["timing_notes"] = notes
    if cutoff_utc is not None:
        attributes["cutoff_utc"] = cutoff_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if call_date is not None:
        attributes["call_date"] = call_date.isoformat()

    return IrDocument(
        url=result.final_url or url,
        content=result.content,
        publication_ts=last_modified,
        publication_ts_source="http_last_modified",
        http_status=result.status_code,
        etag=result.etag,
        headers=dict(result.headers),
        timing_ok=timing_ok,
        timing_notes=notes,
        attributes=attributes,
    )
