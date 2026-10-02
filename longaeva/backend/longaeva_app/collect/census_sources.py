"""Download and calendar Census MARTS advance releases (LON-5).

CLI:

  fetch     — download retained PDFs + revised XLSX snapshot; write manifest.json
  calendar  — scan adv1611…adv2606 page-1 release lines into release_calendar.csv
  build     — regenerate adv2406.csv / adv2506.csv from retained PDFs
"""

from __future__ import annotations

import argparse
import csv
import email.utils
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from longaeva_app.collect.edgar_index import PACKAGE_ROOT, _load_env_user_agent
from longaeva_app.extract.census_marts import (
    parse_marts_pdf,
    parse_release_meta,
    write_observations_csv,
)

CENSUS_DIR = PACKAGE_ROOT / "data" / "fixtures" / "census"
SOURCES_DIR = CENSUS_DIR / "sources"
MANIFEST_PATH = SOURCES_DIR / "manifest.json"
CALENDAR_PATH = CENSUS_DIR / "release_calendar.csv"
ADVANCE_BASE = "https://www2.census.gov/retail/releases/historical/marts"
XLSX_URL = "https://www.census.gov/retail/mrts/www/mrtssales92-present.xlsx"

RETAINED_PDFS = ("adv2406", "adv2506")
CALENDAR_START = (2016, 11)  # adv1611
CALENDAR_END = (2026, 6)  # adv2606
MIN_INTERVAL = 1.0  # ≤ 1 req/s
MAX_RETRIES = 4
REPLACE_GAP_DAYS = 2.0

CALENDAR_COLUMNS = [
    "release_id",
    "reference_month",
    "release_number",
    "publication_ts",
    "url",
    "content_sha256",
    "http_last_modified",
    "last_modified_gap_days",
    "integrity_flag",
    "bytes",
    "error",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def advance_url(release_id: str) -> str:
    return f"{ADVANCE_BASE}/{release_id}.pdf"


def month_iter(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    y, m = start
    ey, em = end
    out: list[tuple[int, int]] = []
    while (y, m) <= (ey, em):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def release_id_for(year: int, month: int) -> str:
    return f"adv{year % 100:02d}{month:02d}"


class CensusClient:
    """Throttled HTTP client for Census downloads (≤ 1 req/s; no 403 retry)."""

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)

    def get(self, url: str) -> tuple[bytes, dict[str, str]]:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._throttle()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "identity",
                    "Host": urllib.parse.urlparse(url).hostname or "www2.census.gov",
                },
            )
            try:
                self._last_request_at = time.monotonic()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read()
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    return body, headers
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 403:
                    raise RuntimeError(f"Census returned 403 for {url}; not retrying") from exc
                if exc.code in {429, 500, 502, 503, 504}:
                    time.sleep(2**attempt)
                    continue
                raise
            except urllib.error.URLError as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"Census fetch failed for {url}: {last_error}")


def parse_http_last_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def gap_days(publication_ts: str, last_modified: datetime | None) -> str:
    if last_modified is None:
        return ""
    pub = datetime.strptime(publication_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return f"{(last_modified - pub).total_seconds() / 86400:.2f}"


def integrity_for(publication_ts: str, last_modified: datetime | None, *, parse_ok: bool) -> str:
    if not parse_ok:
        return "unparsed"
    if last_modified is None:
        return "ok"
    pub = datetime.strptime(publication_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    gap = (last_modified - pub).total_seconds() / 86400
    if gap > REPLACE_GAP_DAYS:
        return "possibly_replaced"
    return "ok"


def cmd_fetch(_args: argparse.Namespace) -> int:
    user_agent = _load_env_user_agent()
    client = CensusClient(user_agent)
    retrieval_ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, Any]] = []

    for release_id in RETAINED_PDFS:
        url = advance_url(release_id)
        print(f"fetch {release_id} …", flush=True)
        raw, headers = client.get(url)
        out_path = SOURCES_DIR / f"{release_id}.pdf"
        out_path.write_bytes(raw)
        meta = parse_release_meta(raw, release_id=release_id)
        lm = headers.get("last-modified", "")
        sources.append(
            {
                "kind": "advance_pdf",
                "release_id": release_id,
                "url": url,
                "path": out_path.relative_to(PACKAGE_ROOT).as_posix(),
                "content_sha256": sha256_bytes(raw),
                "bytes": len(raw),
                "http_last_modified": lm,
                "retrieval_ts": retrieval_ts,
                "publication_ts": meta.publication_ts,
                "release_number": meta.release_number,
                "reference_month": meta.reference_month,
                "headline_billions": meta.headline_billions,
                "pdf_creation_date": meta.pdf_creation_date,
                "pdf_mod_date": meta.pdf_mod_date,
                "page_count": meta.page_count,
            }
        )
        print(f"  wrote {out_path.relative_to(PACKAGE_ROOT)} ({len(raw)} bytes)")

    print("fetch revised XLSX …", flush=True)
    xlsx_raw, xlsx_headers = client.get(XLSX_URL)
    date_stamp = retrieval_ts[:10].replace("-", "")
    xlsx_name = f"mrtssales92-present_{date_stamp}.xlsx"
    xlsx_path = SOURCES_DIR / xlsx_name
    xlsx_path.write_bytes(xlsx_raw)
    sources.append(
        {
            "kind": "revised_xlsx",
            "release_id": None,
            "url": XLSX_URL,
            "path": xlsx_path.relative_to(PACKAGE_ROOT).as_posix(),
            "content_sha256": sha256_bytes(xlsx_raw),
            "bytes": len(xlsx_raw),
            "http_last_modified": xlsx_headers.get("last-modified", ""),
            "retrieval_ts": retrieval_ts,
            "note": (
                "Revised monthly retail sales workbook; not a vintage source (DR-04). "
                "Header cites Annual Integrated Economic Survey."
            ),
        }
    )
    print(f"  wrote {xlsx_path.relative_to(PACKAGE_ROOT)} ({len(xlsx_raw)} bytes)")

    manifest = {
        "schema_version": 1,
        "generated_for": "LON-5",
        "retrieved_at": retrieval_ts,
        "sources": sources,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(PACKAGE_ROOT)} ({len(sources)} sources)")
    return 0


def cmd_calendar(_args: argparse.Namespace) -> int:
    user_agent = _load_env_user_agent()
    client = CensusClient(user_agent)
    rows: list[dict[str, str]] = []
    months = month_iter(CALENDAR_START, CALENDAR_END)
    print(f"scanning {len(months)} advance PDFs ({release_id_for(*CALENDAR_START)}…{release_id_for(*CALENDAR_END)})")

    for year, month in months:
        release_id = release_id_for(year, month)
        url = advance_url(release_id)
        row: dict[str, str] = {k: "" for k in CALENDAR_COLUMNS}
        row["release_id"] = release_id
        row["url"] = url
        try:
            raw, headers = client.get(url)
        except Exception as exc:  # noqa: BLE001 — calendar must record failures
            row["integrity_flag"] = "fetch_failed"
            row["error"] = str(exc)[:300]
            rows.append(row)
            print(f"  {release_id}: FETCH FAILED {exc}")
            continue
        row["content_sha256"] = sha256_bytes(raw)
        row["bytes"] = str(len(raw))
        lm_raw = headers.get("last-modified", "")
        row["http_last_modified"] = lm_raw
        lm_dt = parse_http_last_modified(lm_raw)
        try:
            meta = parse_release_meta(raw, release_id=release_id)
            row["reference_month"] = meta.reference_month
            row["release_number"] = meta.release_number
            row["publication_ts"] = meta.publication_ts
            row["last_modified_gap_days"] = gap_days(meta.publication_ts, lm_dt)
            row["integrity_flag"] = integrity_for(meta.publication_ts, lm_dt, parse_ok=True)
            print(f"  {release_id}: {meta.publication_ts} [{row['integrity_flag']}]")
        except Exception as exc:  # noqa: BLE001
            row["integrity_flag"] = "unparsed"
            row["error"] = str(exc)[:300]
            row["last_modified_gap_days"] = ""
            print(f"  {release_id}: UNPARSED {exc}")
        rows.append(row)

    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CALENDAR_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CALENDAR_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    ok = sum(1 for r in rows if r["integrity_flag"] in {"ok", "possibly_replaced"})
    unparsed = sum(1 for r in rows if r["integrity_flag"] == "unparsed")
    failed = sum(1 for r in rows if r["integrity_flag"] == "fetch_failed")
    replaced = sum(1 for r in rows if r["integrity_flag"] == "possibly_replaced")
    print(f"wrote {CALENDAR_PATH.relative_to(PACKAGE_ROOT)}")
    print(f"ok={ok} possibly_replaced={replaced} unparsed={unparsed} fetch_failed={failed}")
    return 0 if failed == 0 and unparsed == 0 else 1


def cmd_build(_args: argparse.Namespace) -> int:
    for release_id in RETAINED_PDFS:
        pdf_path = SOURCES_DIR / f"{release_id}.pdf"
        if not pdf_path.is_file():
            raise SystemExit(f"missing retained PDF: {pdf_path} (run fetch first)")
        print(f"build {release_id} …", flush=True)
        _meta, rows = parse_marts_pdf(pdf_path, release_id=release_id)
        out = CENSUS_DIR / f"{release_id}.csv"
        write_observations_csv(rows, out)
        print(f"  wrote {out.relative_to(PACKAGE_ROOT)} ({len(rows)} rows)")
    return 0


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return data


def load_calendar(path: Path = CALENDAR_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def latest_release_at_or_before(cutoff_utc: str, calendar: list[dict[str, str]] | None = None) -> dict[str, str] | None:
    """Newest calendar row with publication_ts ≤ cutoff and a parsed release time."""
    rows = calendar if calendar is not None else load_calendar()
    cutoff = datetime.strptime(cutoff_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    best: dict[str, str] | None = None
    best_ts: datetime | None = None
    for row in rows:
        pub_s = row.get("publication_ts") or ""
        if not pub_s:
            continue
        if row.get("integrity_flag") == "fetch_failed":
            continue
        pub = datetime.strptime(pub_s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if pub <= cutoff and (best_ts is None or pub > best_ts):
            best = row
            best_ts = pub
    return best


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Download retained PDFs and XLSX snapshot")
    fetch_p.set_defaults(func=cmd_fetch)

    cal_p = sub.add_parser("calendar", help="Build release_calendar.csv from archive PDFs")
    cal_p.set_defaults(func=cmd_calendar)

    build_p = sub.add_parser("build", help="Regenerate vintage CSVs from retained PDFs")
    build_p.set_defaults(func=cmd_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
