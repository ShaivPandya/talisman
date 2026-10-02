"""EDGAR document resolution and fetch helpers (LON-13 / DR-02)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from longaeva_app.collect.edgar_index import (
    accession_to_index_url,
    extract_accepted_from_index_html,
    format_utc,
    parse_acceptance_datetime,
)
from longaeva_app.collect.http import FetchError, FetchResult, PoliteClient, SourceUnavailable

_TYPE_EX_99_1 = re.compile(r"EX-99\.1", re.IGNORECASE)
_TYPE_EX_99_2 = re.compile(r"EX-99\.2", re.IGNORECASE)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


@dataclass(frozen=True)
class EdgarDocument:
    """Resolved EDGAR document bytes plus publication metadata."""

    url: str
    content: bytes
    publication_ts: datetime
    publication_ts_source: str
    http_status: int
    etag: str | None
    headers: dict[str, str]
    document: str
    exhibit: str | None
    index_accepted_raw: str | None


def accession_nodash(accession: str) -> str:
    return accession.replace("-", "")


def document_url(cik: int | str, accession: str, document: str) -> str:
    cik_int = int(str(cik).lstrip("0") or "0")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash(accession)}/{document}"


def index_json_url(cik: int | str, accession: str) -> str:
    cik_int = int(str(cik).lstrip("0") or "0")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash(accession)}/index.json"


def resolve_document_name(
    client: PoliteClient,
    *,
    cik: int | str,
    accession: str,
    document: str | None = None,
    exhibit: str | None = None,
) -> str:
    """Return the filing document filename.

    Prefer an explicit ``document``. Otherwise locate ``exhibit`` (e.g. EX-99.1)
    via the ``-index.htm`` Type column, falling back to ``index.json``.
    """
    if document:
        return document
    if not exhibit:
        raise FetchError(
            accession_to_index_url(int(str(cik).lstrip("0") or "0"), accession),
            "document or exhibit is required to resolve an EDGAR filing",
        )
    cik_int = int(str(cik).lstrip("0") or "0")
    index_url = accession_to_index_url(cik_int, accession)
    try:
        index_html = client.get(index_url)
        name = _document_from_index_html(index_html.content.decode("utf-8", errors="replace"), exhibit)
        if name:
            return name
    except SourceUnavailable:
        raise
    except FetchError:
        pass

    json_url = index_json_url(cik_int, accession)
    payload = client.get(json_url)
    name = _document_from_index_json(payload.content, exhibit)
    if name:
        return name
    raise FetchError(index_url, f"could not resolve exhibit {exhibit} in filing {accession}")


def fetch_edgar_document(
    client: PoliteClient,
    *,
    cik: int | str,
    accession: str,
    document: str | None = None,
    exhibit: str | None = None,
    expected_publication_ts: datetime | None = None,
) -> EdgarDocument:
    """Resolve, fetch, and timestamp an EDGAR primary document or exhibit."""
    cik_int = int(str(cik).lstrip("0") or "0")
    resolved = resolve_document_name(
        client,
        cik=cik_int,
        accession=accession,
        document=document,
        exhibit=exhibit,
    )
    url = document_url(cik_int, accession, resolved)

    # Prefer the filing index "Accepted" field for publication_ts (DR-04).
    index_url = accession_to_index_url(cik_int, accession)
    index_accepted_raw: str | None = None
    publication_ts: datetime | None = None
    try:
        index_result = client.get(index_url)
        index_accepted_raw = extract_accepted_from_index_html(index_result.content.decode("utf-8", errors="replace"))
        if index_accepted_raw:
            publication_ts = parse_acceptance_datetime(index_accepted_raw)
    except SourceUnavailable:
        raise
    except FetchError:
        publication_ts = None

    result = client.get(url)
    if publication_ts is None:
        raise FetchError(index_url, f"missing Accepted timestamp for {accession}")

    if expected_publication_ts is not None and format_utc(publication_ts) != format_utc(expected_publication_ts):
        raise FetchError(
            url,
            "publication_ts mismatch: "
            f"index={format_utc(publication_ts)} expected={format_utc(expected_publication_ts)}",
        )

    return EdgarDocument(
        url=url,
        content=result.content,
        publication_ts=publication_ts,
        publication_ts_source="edgar_acceptance",
        http_status=result.status_code,
        etag=result.etag,
        headers=dict(result.headers),
        document=resolved,
        exhibit=exhibit,
        index_accepted_raw=index_accepted_raw,
    )


def _document_from_index_html(html: str, exhibit: str) -> str | None:
    """Parse the EDGAR filing index table for a Type matching ``exhibit``."""
    target = exhibit.strip().upper()
    # Rows look like: <tr>...<a href=".../file.htm">file.htm</a>...<td>EX-99.1</td>...
    row_re = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    for row_html in row_re.findall(html):
        if not _row_matches_exhibit(row_html, target):
            continue
        hrefs = _HREF_RE.findall(row_html)
        for href in hrefs:
            name = str(href.rsplit("/", 1)[-1].split("?", 1)[0])
            if name and not name.lower().endswith(("-index.htm", "-index.html", ".json")):
                return name
    return None


def _row_matches_exhibit(row_html: str, target: str) -> bool:
    text = re.sub(r"<[^>]+>", " ", row_html)
    text_u = re.sub(r"\s+", " ", text).upper()
    if target in text_u:
        return True
    if target == "EX-99.1" and _TYPE_EX_99_1.search(row_html):
        return True
    if target == "EX-99.2" and _TYPE_EX_99_2.search(row_html):
        return True
    return False


def _document_from_index_json(payload: bytes, exhibit: str) -> str | None:
    try:
        data: dict[str, Any] = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    target = exhibit.strip().upper()
    items = data.get("directory", {}).get("item", [])
    if isinstance(items, dict):
        items = [items]
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or item.get("Type") or "").upper()
        name = str(item.get("name") or item.get("Name") or "")
        if not name:
            continue
        if item_type == target or target in item_type:
            return name
        # Some index.json feeds omit Type; fall back to filename heuristics for exhibits.
        if target.startswith("EX-") and target.replace("-", "").lower() in name.lower().replace("-", "").replace(
            ".", ""
        ):
            return name
    return None


def fetch_url(client: PoliteClient, url: str) -> FetchResult:
    """Thin wrapper kept for callers that already have a fully-qualified URL."""
    return client.get(url)


def absolutize(base: str, href: str) -> str:
    return urljoin(base, href)
