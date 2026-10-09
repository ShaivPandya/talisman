"""Download and calendar Booking Holdings Ex. 99.1 releases.

CLI:

  fetch     — download three retained Ex. 99.1 originals + write manifest.json
  calendar  — scan 20 Item 2.02 8-Ks into release_calendar.csv (Ex. 99.1 in memory)
  locate    — fill char spans in an observation fixture from anchor+quote
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from longaeva_app.collect.edgar_index import (
    PACKAGE_ROOT,
    SEC_MAX_RETRIES,
    SNAPSHOT_PATH,
    EdgarClient,
    _load_env_user_agent,
    accession_to_index_url,
    extract_accepted_from_index_html,
    format_utc,
    load_snapshot,
    parse_acceptance_datetime,
)
from longaeva_app.collect.state_sources import locate_span
from longaeva_app.extract.booking_release import (
    BOOKING_CIK,
    archive_url,
    detect_guidance,
    reported_quarter_from_period_end,
)

BOOKING_DIR = PACKAGE_ROOT / "data" / "fixtures" / "booking"
SOURCES_DIR = BOOKING_DIR / "sources"
MANIFEST_PATH = SOURCES_DIR / "manifest.json"
CALENDAR_PATH = BOOKING_DIR / "release_calendar.csv"
OBSERVATIONS_DIR = PACKAGE_ROOT / "data" / "fixtures" / "observations"

CALENDAR_COLUMNS = [
    "accession",
    "document",
    "filed_date",
    "acceptance_utc",
    "index_page_accepted_utc",
    "reported_quarter",
    "guidance_table",
    "guidance_quarter",
    "guidance_full_year",
    "content_sha256",
    "bytes",
    "error",
]

# 20 releases: 17 newest-eligible at some Visa origin + 2 same-day fallbacks
# (2025-02-20, 2026-02-18) + the 2026-08-04 post-cutoff negative test.
CALENDAR_ACCESSIONS: tuple[str, ...] = (
    "0001075531-21-000051",
    "0001075531-22-000006",
    "0001075531-22-000020",
    "0001075531-22-000031",
    "0001075531-22-000042",
    "0001075531-23-000012",
    "0001075531-23-000029",
    "0001075531-23-000045",
    "0001075531-23-000060",
    "0001075531-24-000011",
    "0001075531-24-000026",
    "0001075531-24-000039",
    "0001075531-24-000047",
    "0001075531-25-000009",
    "0001075531-25-000021",
    "0001075531-25-000035",
    "0001075531-25-000050",
    "0001075531-26-000008",
    "0001075531-26-000024",
    "0001075531-26-000036",
)


@dataclass(frozen=True)
class RetainedSpec:
    accession: str
    document: str
    role: str  # input | post_cutoff_check
    origins: tuple[str, ...]
    note: str


RETAINED_SPECS: tuple[RetainedSpec, ...] = (
    RetainedSpec(
        accession="0001075531-24-000026",
        document="ex99133124.htm",
        role="input",
        origins=("2024-07-23",),
        note="Origin A gate release (Booking Q1 2024); 11.7 weeks old at Visa 2024-07-23",
    ),
    RetainedSpec(
        accession="0001075531-25-000050",
        document="q3-25bkngearningsrelease.htm",
        role="input",
        origins=("2025-10-28",),
        note="Origin B gate release (Booking Q3 2025); same-day, 224 s before Visa cutoff",
    ),
    RetainedSpec(
        accession="0001075531-26-000036",
        document="q2-26bkngearningsrelease.htm",
        role="post_cutoff_check",
        origins=("2026-07-28",),
        note="Post-cutoff negative test at prospective origin; accepted 2026-08-04",
    ),
)

_EXHIBIT_HREF_RE = re.compile(
    r'href=["\']([^"\']+\.htm)["\'][^>]*>\s*EX-99\.1',
    re.IGNORECASE,
)
_EXHIBIT_ROW_RE = re.compile(
    r"EX-99\.1.*?<a[^>]+href=[\"']([^\"']+\.htm)[\"']",
    re.IGNORECASE | re.DOTALL,
)
_INDEX_JSON_SKIP = frozenset(
    {
        "index.htm",
        "index.html",
        "index-headers.html",
        "filing-index.htm",
        "filing-index.html",
    }
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_gz_path(accession: str, document: str) -> str:
    return f"{accession}/{document}.gz"


def absolute_gz_path(accession: str, document: str) -> Path:
    return SOURCES_DIR / accession / f"{document}.gz"


def write_deterministic_gzip(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0, compresslevel=9) as gz:
        gz.write(data)


def read_gzip_bytes(path: Path) -> bytes:
    with gzip.open(path, "rb") as gz:
        return gz.read()


def get_bytes(client: EdgarClient, url: str) -> bytes:
    """Binary fetch with the same throttle/backoff policy as ``EdgarClient.get_text``."""
    last_error: Exception | None = None
    for attempt in range(SEC_MAX_RETRIES):
        client._throttle()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": client.user_agent,
                "Accept-Encoding": "identity",
                "Host": urllib.parse.urlparse(url).hostname or "www.sec.gov",
            },
        )
        try:
            client._last_request_at = time.monotonic()
            with urllib.request.urlopen(req, timeout=120) as resp:
                body: bytes = resp.read()
                return body
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 403:
                raise RuntimeError(f"EDGAR returned 403 for {url}; not retrying") from exc
            if exc.code in {429, 500, 502, 503, 504}:
                time.sleep(2**attempt)
                continue
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"EDGAR fetch failed for {url}: {last_error}")


def acceptance_utc_for(snapshot: dict[str, Any], accession: str) -> str:
    for row in snapshot["booking_filings"]:
        if row["accession"] == accession:
            return str(row["accepted_utc"])
    raise KeyError(f"Accession {accession} not in LON-1 Booking snapshot")


def filing_row_for(snapshot: dict[str, Any], accession: str) -> dict[str, Any]:
    for row in snapshot["booking_filings"]:
        if row["accession"] == accession:
            if not isinstance(row, dict):
                raise TypeError(f"Expected dict for filing {accession}")
            return cast(dict[str, Any], row)
    raise KeyError(f"Accession {accession} not in LON-1 Booking snapshot")


def find_exhibit_99_1(index_html: str, index_json: dict[str, Any] | None = None) -> str:
    """Return the Ex. 99.1 document filename from an EDGAR filing index page."""
    for pattern in (_EXHIBIT_HREF_RE, _EXHIBIT_ROW_RE):
        match = pattern.search(index_html)
        if match:
            name = match.group(1).rsplit("/", 1)[-1]
            if name.lower().endswith(".htm"):
                return name

    # Fallback: prefer exhibit-like names from the directory listing.
    if index_json is not None:
        items = index_json.get("directory", {}).get("item", [])
        names = [
            str(item["name"])
            for item in items
            if isinstance(item, dict)
            and str(item.get("name", "")).lower().endswith(".htm")
            and str(item.get("name", "")).lower() not in _INDEX_JSON_SKIP
            and not str(item.get("name", "")).startswith("R")
            and "-index" not in str(item.get("name", "")).lower()
        ]
        preferred = [
            n
            for n in names
            if n.lower().startswith("ex99")
            or "earnings" in n.lower()
            or "press" in n.lower()
            or n.lower().startswith("q")
        ]
        # Prefer exhibit / earnings docs over the 8-K wrapper (bkng-YYYYMMDD.htm).
        for name in preferred:
            if not name.lower().startswith("bkng-"):
                return name
        for name in names:
            if not name.lower().startswith("bkng-"):
                return name
    raise ValueError("EX-99.1 document not found in filing index")


def source_text(accession: str, document: str) -> str:
    path = absolute_gz_path(accession, document)
    if not path.exists():
        raise FileNotFoundError(f"Missing source original: {path}")
    return read_gzip_bytes(path).decode("utf-8", errors="replace")


def build_manifest_entry(
    spec: RetainedSpec,
    raw: bytes,
    acceptance_utc: str,
    index_accepted_utc: str,
    retrieval_ts: str,
) -> dict[str, Any]:
    return {
        "accession": spec.accession,
        "document": spec.document,
        "form": "8-K Ex. 99.1",
        "role": spec.role,
        "origins": list(spec.origins),
        "url": archive_url(spec.accession, spec.document),
        "path": relative_gz_path(spec.accession, spec.document),
        "content_sha256": sha256_bytes(raw),
        "raw_bytes": len(raw),
        "acceptance_utc": acceptance_utc,
        "index_page_accepted_utc": index_accepted_utc,
        "retrieval_ts": retrieval_ts,
        "note": spec.note,
    }


def cmd_fetch(_args: argparse.Namespace) -> int:
    snapshot = load_snapshot(SNAPSHOT_PATH)
    client = EdgarClient(_load_env_user_agent())
    retrieval_ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries: list[dict[str, Any]] = []
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)

    for spec in RETAINED_SPECS:
        url = archive_url(spec.accession, spec.document)
        print(f"fetch {spec.accession}/{spec.document} …", flush=True)
        raw = get_bytes(client, url)
        out = absolute_gz_path(spec.accession, spec.document)
        write_deterministic_gzip(out, raw)

        index_url = accession_to_index_url(BOOKING_CIK, spec.accession)
        index_html = client.get_text(index_url)
        page_accepted = extract_accepted_from_index_html(index_html)
        if not page_accepted:
            raise RuntimeError(f"Accepted timestamp missing on {index_url}")
        index_utc = format_utc(parse_acceptance_datetime(page_accepted))
        acceptance = acceptance_utc_for(snapshot, spec.accession)
        if index_utc != acceptance:
            raise RuntimeError(f"Index page UTC {index_utc} != snapshot {acceptance} for {spec.accession}")

        entries.append(build_manifest_entry(spec, raw, acceptance, index_utc, retrieval_ts))
        print(
            f"  wrote {out.relative_to(PACKAGE_ROOT)} ({len(raw)} bytes, sha256={entries[-1]['content_sha256'][:12]}…)"
        )

    manifest = {
        "schema_version": 1,
        "generated_for": "LON-4",
        "retrieved_at": retrieval_ts,
        "snapshot_path": str(SNAPSHOT_PATH.relative_to(PACKAGE_ROOT)),
        "sources": entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(PACKAGE_ROOT)} ({len(entries)} sources)")
    return 0


def cmd_calendar(_args: argparse.Namespace) -> int:
    snapshot = load_snapshot(SNAPSHOT_PATH)
    client = EdgarClient(_load_env_user_agent())
    rows: list[dict[str, str]] = []
    print(f"scanning {len(CALENDAR_ACCESSIONS)} Booking Ex. 99.1 documents")

    for accession in CALENDAR_ACCESSIONS:
        filing = filing_row_for(snapshot, accession)
        row: dict[str, str] = {k: "" for k in CALENDAR_COLUMNS}
        row["accession"] = accession
        row["filed_date"] = str(filing["filed_date"])
        row["acceptance_utc"] = str(filing["accepted_utc"])
        try:
            index_url = accession_to_index_url(BOOKING_CIK, accession)
            index_html = client.get_text(index_url)
            page_accepted = extract_accepted_from_index_html(index_html)
            if not page_accepted:
                raise RuntimeError("Accepted timestamp missing on index page")
            index_utc = format_utc(parse_acceptance_datetime(page_accepted))
            row["index_page_accepted_utc"] = index_utc
            if index_utc != row["acceptance_utc"]:
                raise RuntimeError(f"index UTC {index_utc} != snapshot {row['acceptance_utc']}")

            nodash = accession.replace("-", "")
            index_json_url = f"https://www.sec.gov/Archives/edgar/data/{BOOKING_CIK}/{nodash}/index.json"
            index_json = json.loads(client.get_text(index_json_url))
            document = find_exhibit_99_1(index_html, index_json)
            row["document"] = document

            raw = get_bytes(client, archive_url(accession, document))
            row["content_sha256"] = sha256_bytes(raw)
            row["bytes"] = str(len(raw))
            text = raw.decode("utf-8", errors="replace")
            guidance = detect_guidance(text)
            row.update(guidance)
            row["reported_quarter"] = reported_quarter_from_period_end(
                str(filing.get("period_of_report") or ""),
                str(filing["filed_date"]),
            )
            print(
                f"  {accession}: {document} reported={row['reported_quarter']} "
                f"guidance={row['guidance_table']} {row['guidance_quarter']}"
            )
        except Exception as exc:  # noqa: BLE001 — calendar must record failures
            row["error"] = str(exc)[:400]
            print(f"  {accession}: ERROR {exc}")
        rows.append(row)

    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CALENDAR_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CALENDAR_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    errors = sum(1 for r in rows if r["error"])
    guided = sum(1 for r in rows if r["guidance_table"] == "true")
    print(f"wrote {CALENDAR_PATH.relative_to(PACKAGE_ROOT)}")
    print(f"rows={len(rows)} with_guidance={guided} errors={errors}")
    return 0 if errors == 0 else 1


def cmd_locate(args: argparse.Namespace) -> int:
    fixture_path = Path(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    source = fixture.get("source") or {}
    accession = source.get("accession")
    document = source.get("document")
    if not accession or not document:
        raise SystemExit("fixture.source must include accession and document")
    text = source_text(accession, document)
    updated = 0
    for entry in fixture.get("observations", []):
        span = entry.get("span")
        if not span:
            continue
        start, end = locate_span(text, span["anchor"], span["quote"])
        span["char_start"] = start
        span["char_end"] = end
        updated += 1
        print(f"{entry.get('observation_id', '?')}: [{start}:{end}]")
    fixture_path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated {updated} spans in {fixture_path}")
    return 0


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return data


def load_calendar(path: Path = CALENDAR_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def calendar_by_accession(calendar: list[dict[str, str]] | None = None) -> dict[str, dict[str, str]]:
    rows = calendar if calendar is not None else load_calendar()
    return {row["accession"]: row for row in rows if row.get("accession")}


def previous_booking_accession(
    accession: str,
    ordered_accessions: list[str],
) -> str:
    """Return the chronologically previous accession, or empty string."""
    try:
        idx = ordered_accessions.index(accession)
    except ValueError:
        return ""
    if idx <= 0:
        return ""
    return ordered_accessions[idx - 1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Download retained Ex. 99.1 originals")
    fetch_p.set_defaults(func=cmd_fetch)

    cal_p = sub.add_parser("calendar", help="Build release_calendar.csv from EDGAR")
    cal_p.set_defaults(func=cmd_calendar)

    locate_p = sub.add_parser("locate", help="Fill char spans in an observation fixture")
    locate_p.add_argument("fixture", help="Path to booking_YYYY-MM-DD.json")
    locate_p.set_defaults(func=cmd_locate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
