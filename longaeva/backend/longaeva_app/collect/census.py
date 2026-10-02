"""Census MARTS advance-PDF fetch helpers (LON-13 / DR-04)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from longaeva_app.collect.edgar_index import format_utc, parse_acceptance_datetime
from longaeva_app.collect.http import FetchError, PoliteClient
from longaeva_app.extract.census_marts import ReleaseMeta, parse_release_meta


@dataclass(frozen=True)
class CensusDocument:
    """Fetched MARTS advance PDF with printed publication timestamp."""

    url: str
    content: bytes
    publication_ts: datetime
    publication_ts_source: str
    http_status: int
    etag: str | None
    headers: dict[str, str]
    release_meta: ReleaseMeta
    integrity_flag: str | None


def fetch_census_pdf(
    client: PoliteClient,
    url: str,
    *,
    expected_publication_ts: datetime | None = None,
    release_id: str | None = None,
    integrity_flag: str | None = None,
) -> CensusDocument:
    """Fetch a MARTS advance PDF and read publication_ts from the printed release line."""
    result = client.get(url)
    meta = parse_release_meta(result.content, release_id=release_id)
    publication_ts = parse_acceptance_datetime(meta.publication_ts)
    if expected_publication_ts is not None and format_utc(publication_ts) != format_utc(expected_publication_ts):
        raise FetchError(
            url,
            f"publication_ts mismatch: pdf={format_utc(publication_ts)} expected={format_utc(expected_publication_ts)}",
        )
    return CensusDocument(
        url=url,
        content=result.content,
        publication_ts=publication_ts,
        publication_ts_source="census_release_line",
        http_status=result.status_code,
        etag=result.etag,
        headers=dict(result.headers),
        release_meta=meta,
        integrity_flag=integrity_flag,
    )
