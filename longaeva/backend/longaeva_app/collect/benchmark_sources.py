"""Benchmark and price-data probe (LON-6).

CLI:

  probe  — one live fetch per selected vendor source (FRED, Shiller, Ken French);
           process in memory only; write metadata-only probe.json. Also parse
           Visa dividend declarations from retained SEC Ex. 99.1 releases.

No raw vendor payloads are written to disk (DR-01 / DR-07).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import xlrd
import yaml

from longaeva_app.collect.edgar_index import PACKAGE_ROOT, _load_env_user_agent

MANIFEST_PATH = PACKAGE_ROOT / "data" / "manifest" / "benchmarks.yaml"
ORIGINS_CSV_PATH = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"
PROBE_DIR = PACKAGE_ROOT / "data" / "fixtures" / "benchmarks"
PROBE_PATH = PROBE_DIR / "probe.json"
STATES_SOURCES = PACKAGE_ROOT / "data" / "fixtures" / "states" / "sources"

MIN_INTERVAL = 1.0
MAX_RETRIES = 4
JS_CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "Just a moment...",
    "Enable JavaScript and cookies",
    "challenge-platform",
)

DIVIDEND_AMOUNT_RE = re.compile(
    r"quarterly cash dividend(?:[^$]{0,60})?\$\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
PAYABLE_RE = re.compile(r"payable on ([A-Za-z]+ \d{1,2}, \d{4})", re.IGNORECASE)
RECORD_RE = re.compile(
    r"record as of ([A-Za-z]+(?:&\w+;)?\s*\d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"benchmarks manifest must be a mapping: {path}")
    return data


def candidate_coverage_window(origins_path: Path = ORIGINS_CSV_PATH) -> dict[str, str]:
    """First candidate cutoff → last realized target acceptance among candidates."""
    with origins_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    candidates = [r for r in rows if r.get("status") == "candidate"]
    if not candidates:
        raise ValueError("no candidate origins in origins.csv")
    cutoffs = [r["cutoff_utc"] for r in candidates if r.get("cutoff_utc")]
    targets = [r["target_release_accepted_utc"] for r in candidates if r.get("target_release_accepted_utc")]
    if not cutoffs or not targets:
        raise ValueError("candidate origins missing cutoff or target timestamps")
    return {
        "window_start": min(cutoffs)[:10],
        "window_end": max(targets)[:10],
        "n_candidates": str(len(candidates)),
    }


class ProbeClient:
    """Throttled HTTP client (≤ 1 req/s; no 403 / JS-challenge retry)."""

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
            host = urllib.parse.urlparse(url).hostname or ""
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "identity",
                    "Accept": "*/*",
                    **({"Host": host} if host else {}),
                },
            )
            try:
                self._last_request_at = time.monotonic()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read()
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    content_type = headers.get("content-type", "").lower()
                    if "text/html" in content_type or body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                        text_head = body[:4000].decode("utf-8", errors="replace")
                        if any(marker in text_head for marker in JS_CHALLENGE_MARKERS):
                            raise RuntimeError(f"JavaScript challenge for {url}; not retrying (DR-09)")
                    return body, headers
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 403:
                    raise RuntimeError(f"HTTP 403 for {url}; not retrying") from exc
                if exc.code in {429, 500, 502, 503, 504}:
                    time.sleep(2**attempt)
                    continue
                raise
            except urllib.error.URLError as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"fetch failed for {url}: {last_error}")


def parse_fred_csv(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("FRED CSV has no header")
    columns = list(reader.fieldnames)
    dates: list[str] = []
    missing = 0
    for row in reader:
        raw_date = (row.get("observation_date") or row.get("DATE") or "").strip()
        raw_val = (row.get("SP500") or "").strip()
        if not raw_date:
            continue
        dates.append(raw_date)
        if raw_val in {"", "."}:
            missing += 1
    if not dates:
        raise ValueError("FRED CSV has no observation rows")
    return {
        "columns": columns,
        "row_count": len(dates),
        "first_date": dates[0],
        "last_date": dates[-1],
        "missing_value_count": missing,
    }


def parse_shiller_xls(body: bytes) -> dict[str, Any]:
    book = xlrd.open_workbook(file_contents=body)
    sheet = book.sheet_by_name("Data") if "Data" in book.sheet_names() else book.sheet_by_index(0)

    # ie_data.xls layout: row 7 is Date / P / D / E …; data starts at row 8 as YYYY.MM floats.
    # Prefer the short-label header (Date, P, D) over the descriptive row above it
    # (Comp., Dividend, …, Date Fraction), which would point date_col at the wrong column.
    header_row: int | None = None
    date_col: int | None = None
    div_col: int | None = None
    price_col: int | None = None
    for r in range(min(20, sheet.nrows)):
        cells = [str(sheet.cell_value(r, c)).strip() for c in range(min(sheet.ncols, 12))]
        lower = [c.lower() for c in cells]
        if lower[:3] == ["date", "p", "d"]:
            header_row = r
            date_col = 0
            price_col = 1
            div_col = 2
            break
    if header_row is None:
        for r in range(min(20, sheet.nrows)):
            cells = [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
            lower = [c.lower() for c in cells]
            if "date" in lower and "d" in lower:
                header_row = r
                date_col = lower.index("date")
                div_col = lower.index("d")
                price_col = lower.index("p") if "p" in lower else 1
                break
    if header_row is None or date_col is None or div_col is None:
        header_row, date_col, price_col, div_col = 7, 0, 1, 2

    months: list[str] = []
    last_div_month: str | None = None
    missing = 0
    for r in range(header_row + 1, sheet.nrows):
        raw_date = sheet.cell_value(r, date_col)
        if raw_date in {"", None}:
            continue
        month = _shiller_date_to_month(raw_date)
        if month is None:
            continue
        months.append(month)
        try:
            div_val = float(sheet.cell_value(r, div_col))
        except (TypeError, ValueError):
            missing += 1
            continue
        if div_val > 0:
            last_div_month = month
        else:
            missing += 1

    if not months:
        raise ValueError("Shiller workbook has no dated rows")
    columns = [str(sheet.cell_value(header_row, c)).strip() or f"col_{c}" for c in range(sheet.ncols)]
    return {
        "columns": columns[:12],
        "row_count": len(months),
        "first_date": months[0],
        "last_date": months[-1],
        "missing_value_count": missing,
        "last_dividend_month": last_div_month or months[-1],
        "price_col": price_col,
        "dividend_col": div_col,
        "sheet_names": book.sheet_names(),
    }


def _shiller_date_to_month(raw: Any) -> str | None:
    """Parse Shiller Date cells stored as YYYY.MM floats (e.g. 1871.01 → 1871-01)."""
    if isinstance(raw, (int, float)):
        value = float(raw)
        year = int(value)
        # YYYY.MM encoding covers the Shiller history (1871 … present).
        if 1800 <= year <= 2100:
            frac = value - year
            month = int(round(frac * 100))
            if 1 <= month <= 12:
                return f"{year:04d}-{month:02d}"
            return None
        return None
    text = str(raw).strip()
    if not text:
        return None
    m = re.match(r"^(\d{4})\.(\d{1,2})$", text)
    if m:
        month = int(m.group(2))
        if 1 <= month <= 12:
            return f"{int(m.group(1)):04d}-{month:02d}"
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%Y"):
        try:
            dt = datetime.strptime(text[:10], fmt)
            return f"{dt.year:04d}-{dt.month:02d}"
        except ValueError:
            continue
    return None


def parse_ken_french_zip(body: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("Ken French ZIP is empty")
        # Prefer the CSV inside the ZIP.
        csv_name = next((n for n in names if n.lower().endswith(".csv") or "daily" in n.lower()), names[0])
        raw = zf.read(csv_name)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # Skip preamble until the header with Mkt-RF.
    header_idx = None
    for i, line in enumerate(lines):
        if "Mkt-RF" in line or "MktRF" in line.replace("-", ""):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Ken French daily file missing Mkt-RF header")
    header = [c.strip() for c in lines[header_idx].split(",")]
    dates: list[str] = []
    missing = 0
    for line in lines[header_idx + 1 :]:
        if not line.strip():
            # Blank line often separates annual section; stop at first blank after data starts.
            if dates:
                break
            continue
        # Trailer notes start with letters.
        if re.match(r"^[A-Za-z]", line.strip()):
            break
        parts = [p.strip() for p in line.split(",")]
        if not parts or not re.match(r"^\d{8}$", parts[0]):
            if dates:
                break
            continue
        ymd = parts[0]
        dates.append(f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}")
        # Count missing factor cells.
        if any(p in {"", "-99.99", "-999"} for p in parts[1:4]):
            missing += 1
    if not dates:
        raise ValueError("Ken French daily file has no dated rows")
    return {
        "columns": header,
        "row_count": len(dates),
        "first_date": dates[0],
        "last_date": dates[-1],
        "missing_value_count": missing,
        "zip_members": names,
        "csv_member": csv_name,
    }


def coverage_ok(meta: dict[str, Any], window: dict[str, str]) -> bool:
    first = str(meta.get("first_date", ""))[:10]
    last = str(meta.get("last_date", ""))[:10]
    start = window["window_start"]
    end = window["window_end"]
    # Shiller months are YYYY-MM; compare on year-month.
    if len(first) == 7:
        return first <= start[:7] and last >= end[:7]
    return first <= start and last >= end


def html_to_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text


def parse_visa_dividend_text(text: str) -> dict[str, Any] | None:
    """Extract amount / payable / record from a Visa Ex. 99.1 earnings release."""
    amount_m = DIVIDEND_AMOUNT_RE.search(text)
    payable_m = PAYABLE_RE.search(text)
    record_m = RECORD_RE.search(text)
    if not amount_m or not payable_m or not record_m:
        return None
    record_raw = re.sub(r"&\w+;", " ", record_m.group(1))
    record_raw = re.sub(r"\s+", " ", record_raw).strip().rstrip(",")
    payable_raw = payable_m.group(1).strip()
    return {
        "amount_per_share": float(amount_m.group(1)),
        "payable_date": _parse_us_date(payable_raw),
        "record_date": _parse_us_date(record_raw),
        "payable_date_raw": payable_raw,
        "record_date_raw": record_raw,
    }


def _parse_us_date(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw.strip().rstrip(","))
    for fmt in ("%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {raw!r}")


def ex_dividend_date(record_date: str) -> str:
    """Ex-date convention: = record from 2024-05-28; else one business day before."""
    rd = date.fromisoformat(record_date)
    cutoff = date(2024, 5, 28)
    if rd >= cutoff:
        return rd.isoformat()
    # One business day before.
    d = rd
    while True:
        d = date.fromordinal(d.toordinal() - 1)
        if d.weekday() < 5:
            return d.isoformat()


def parse_retained_visa_dividends(sources_dir: Path = STATES_SOURCES) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not sources_dir.is_dir():
        return results
    for path in sorted(sources_dir.glob("*/*earningsrelease.htm.gz")):
        raw = gzip.decompress(path.read_bytes())
        text = html_to_text(raw)
        parsed = parse_visa_dividend_text(text)
        if parsed is None:
            results.append(
                {
                    "path": path.relative_to(PACKAGE_ROOT).as_posix(),
                    "status": "unparsed",
                }
            )
            continue
        results.append(
            {
                "path": path.relative_to(PACKAGE_ROOT).as_posix(),
                "status": "ok",
                "amount_per_share": parsed["amount_per_share"],
                "payable_date": parsed["payable_date"],
                "record_date": parsed["record_date"],
                "ex_dividend_date": ex_dividend_date(parsed["record_date"]),
            }
        )
    return results


def _source_entry(
    source_id: str,
    *,
    status: str,
    url: str,
    content_sha256: str | None = None,
    bytes_len: int | None = None,
    http_last_modified: str | None = None,
    meta: dict[str, Any] | None = None,
    covers_candidate_window: bool | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source_id": source_id,
        "status": status,
        "url": url,
        "retrieval_ts": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if content_sha256 is not None:
        out["content_sha256"] = content_sha256
    if bytes_len is not None:
        out["bytes"] = bytes_len
    if http_last_modified:
        out["http_last_modified"] = http_last_modified
    if meta:
        out.update(meta)
    if covers_candidate_window is not None:
        out["covers_candidate_window"] = covers_candidate_window
    if error:
        out["error"] = error
    return out


def run_probe(*, user_agent: str | None = None) -> dict[str, Any]:
    manifest = load_manifest()
    window = candidate_coverage_window()
    ua = user_agent or _load_env_user_agent()
    client = ProbeClient(ua)
    sources_cfg: dict[str, Any] = manifest["sources"]
    probed: list[dict[str, Any]] = []

    parsers = {
        "fred_sp500": parse_fred_csv,
        "shiller_ie_data": parse_shiller_xls,
        "ken_french_daily": parse_ken_french_zip,
    }

    for source_id, parser in parsers.items():
        cfg = sources_cfg[source_id]
        url = cfg["url"]
        print(f"probe {source_id} …", flush=True)
        try:
            body, headers = client.get(url)
            meta = parser(body)
            covers = coverage_ok(meta, window)
            # Drop internal helper fields from the probe artifact.
            public_meta = {
                k: v
                for k, v in meta.items()
                if k
                not in {
                    "price_col",
                    "dividend_col",
                    "sheet_names",
                    "zip_members",
                    "csv_member",
                }
            }
            entry = _source_entry(
                source_id,
                status="ok" if covers else "coverage_gap",
                url=url,
                content_sha256=sha256_bytes(body),
                bytes_len=len(body),
                http_last_modified=headers.get("last-modified"),
                meta=public_meta,
                covers_candidate_window=covers,
            )
            if source_id == "shiller_ie_data":
                entry["last_dividend_month"] = meta.get("last_dividend_month")
            if source_id == "ken_french_daily":
                entry["last_date"] = meta["last_date"]
            probed.append(entry)
            print(
                f"  ok sha256={entry['content_sha256'][:12]}… "
                f"{entry['first_date']}→{entry['last_date']} "
                f"rows={entry['row_count']} covers={covers}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            probed.append(
                _source_entry(
                    source_id,
                    status="error",
                    url=url,
                    error=str(exc),
                    covers_candidate_window=False,
                )
            )
            print(f"  error: {exc}", flush=True)

    dividends = parse_retained_visa_dividends()
    print(f"visa dividends parsed: {sum(1 for d in dividends if d.get('status') == 'ok')}/{len(dividends)}", flush=True)

    probe = {
        "generated_for": "LON-6",
        "schema_version": 1,
        "probed_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decision": {
            "primary_option": manifest["decision"]["primary_option"],
            "secondary_option": manifest["decision"]["secondary_option"],
            "key_registration": manifest["decision"]["key_registration"],
            "visa_prices": manifest["decision"]["visa_prices"],
        },
        "labels": manifest["labels"],
        "candidate_window": window,
        "sources": probed,
        "visa_dividends": dividends,
        "notes": [
            "Raw vendor payloads processed in memory only; not written to disk.",
            "probe.json holds metadata only (hashes, dates, counts).",
        ],
    }
    return probe


def write_probe(probe: dict[str, Any], path: Path = PROBE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_probe(_args: argparse.Namespace) -> int:
    probe = run_probe()
    write_probe(probe)
    print(f"wrote {PROBE_PATH.relative_to(PACKAGE_ROOT)}", flush=True)
    statuses = {s["source_id"]: s["status"] for s in probe["sources"]}
    if any(st != "ok" for st in statuses.values()):
        print(f"probe statuses: {statuses}", flush=True)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LON-6 benchmark source probe")
    sub = parser.add_subparsers(dest="command", required=True)
    p_probe = sub.add_parser("probe", help="Fetch selected sources; write metadata-only probe.json")
    p_probe.set_defaults(func=cmd_probe)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
