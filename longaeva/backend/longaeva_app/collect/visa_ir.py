"""Visa IR guidance probe (LON-7).

CLI:

  probe   — download decks (and extension-era transcripts) into var/cache/visa_ir,
            record hashes / headers / PDF dates / optional archive digests, parse
            outlook coverage, write availability.csv / statements.csv / probe.json
            and four sample guidance observation fixtures.

  verify  — re-hash cached PDFs and re-check sample fixture spans offline.

Originals are never committed (DR-01); fixtures carry metadata and short quotes.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pdfplumber
import yaml

from longaeva_app.collect.edgar_index import PACKAGE_ROOT, _load_env_user_agent
from longaeva_app.extract.visa_guidance import (
    COMPANY_GUIDANCE_LABEL,
    CONSENSUS_UNAVAILABLE_LABEL,
    OBSERVATIONS_DIR,
    VisaGuidanceFixture,
    detect_outlook_slide,
    find_transcript_outlook,
    fiscal_period_bounds,
    load_fixture,
    parse_guidance_phrase,
    parse_outlook_slide_words,
    parse_reconciliation_slide_words,
    required_fixture_paths,
    to_observation_create,
)

MANIFEST_PATH = PACKAGE_ROOT / "data" / "manifest" / "visa_ir.yaml"
ORIGINS_CSV_PATH = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"
FIXTURE_DIR = PACKAGE_ROOT / "data" / "fixtures" / "guidance"
AVAILABILITY_PATH = FIXTURE_DIR / "availability.csv"
STATEMENTS_PATH = FIXTURE_DIR / "statements.csv"
PROBE_PATH = FIXTURE_DIR / "probe.json"
CACHE_DIR = PACKAGE_ROOT / "var" / "cache" / "visa_ir"

MIN_INTERVAL = 10.0
MAX_RETRIES = 4
DECK_EVENT_WINDOW_SECONDS = 3600
JS_CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "Just a moment...",
    "Enable JavaScript and cookies",
    "challenge-platform",
)

AVAILABILITY_FIELDS = [
    "origin_label",
    "fiscal_year",
    "fiscal_quarter",
    "origin_window",
    "status",
    "cutoff_utc",
    "target_fiscal_year",
    "target_fiscal_quarter",
    "deck_outlook_type",
    "deck_url",
    "deck_http_status",
    "deck_last_modified",
    "deck_last_modified_delta_seconds",
    "deck_within_event_window",
    "deck_pdf_creation",
    "deck_pdf_mod",
    "deck_sha256",
    "deck_sha1_base32",
    "deck_page_count",
    "deck_outlook_page",
    "deck_recon_page",
    "archive_digest_match",
    "archive_first_capture",
    "transcript_status",
    "transcript_url",
    "transcript_http_status",
    "transcript_last_modified",
    "transcript_sha256",
    "transcript_has_next_quarter_outlook",
    "guidance_source",
    "comparable_net_revenue",
    "comparable_operating_expenses",
    "notes",
]

STATEMENT_FIELDS = [
    "origin_label",
    "source_kind",
    "metric",
    "period_kind",
    "target_fiscal_year",
    "target_fiscal_quarter",
    "basis",
    "phrase",
    "range_low",
    "range_high",
    "unit",
    "page",
    "quote",
    "comparable",
    "note",
]

SAMPLE_KEYS = {
    (2023, 2),
    (2024, 3),
    (2025, 4),
    (2026, 3),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha1_base32(data: bytes) -> str:
    digest = hashlib.sha1(data).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"visa_ir manifest must be a mapping: {path}")
    return data


def load_origins(path: Path = ORIGINS_CSV_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("status") in {"candidate", "prospective"}]


def origin_label(fy: int, fq: int) -> str:
    return f"FY{fy}Q{fq}"


class ProbeClient:
    """Throttled HTTP client (≥ 10 s spacing; no 403 / JS-challenge retry)."""

    def __init__(self, user_agent: str, min_interval: float = MIN_INTERVAL) -> None:
        self.user_agent = user_agent
        self.min_interval = min_interval
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def get(self, url: str) -> tuple[bytes, dict[str, str], int]:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._throttle()
            host = urllib.parse.urlparse(url).hostname or ""
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "identity",
                    "Accept": "application/pdf,*/*",
                    **({"Host": host} if host else {}),
                },
            )
            try:
                self._last_request_at = time.monotonic()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read()
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    status = int(getattr(resp, "status", 200) or 200)
                    content_type = headers.get("content-type", "").lower()
                    if "text/html" in content_type or body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                        text_head = body[:4000].decode("utf-8", errors="replace")
                        if any(marker in text_head for marker in JS_CHALLENGE_MARKERS):
                            raise RuntimeError(f"JavaScript challenge for {url}; not retrying (DR-09)")
                    return body, headers, status
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 403:
                    raise RuntimeError(f"HTTP 403 for {url}; not retrying") from exc
                if exc.code == 404:
                    return b"", {}, 404
                if exc.code in {429, 500, 502, 503, 504}:
                    time.sleep(2**attempt)
                    continue
                raise
            except urllib.error.URLError as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"fetch failed for {url}: {last_error}")


def parse_http_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_pdf_date(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw)
    match = re.search(r"D:(\d{14})", text)
    if match:
        stamp = match.group(1)
    else:
        match = re.search(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", text)
        if not match:
            return None
        stamp = "".join(match.groups())
    y, mo, d, h, mi, s = stamp[0:4], stamp[4:6], stamp[6:8], stamp[8:10], stamp[10:12], stamp[12:14]
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}"


def pdf_metadata(path: Path) -> dict[str, Any]:
    with pdfplumber.open(path) as pdf:
        meta = pdf.metadata or {}
        page_count = len(pdf.pages)
        outlook_page = None
        outlook_type = "none"
        outlook_title = None
        recon_page = None
        outlook_cells: dict[str, Any] = {}
        recon_cells: dict[str, Any] = {}
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            detected = detect_outlook_slide(text)
            if detected["outlook_type"] != "none" and outlook_page is None:
                outlook_page = idx
                outlook_type = detected["outlook_type"]
                outlook_title = detected["title"]
                if outlook_type == "next_quarter_and_full_year":
                    try:
                        parsed = parse_outlook_slide_words(page.extract_words())
                        outlook_cells = {f"{m}:{c}": phrase for (m, c), phrase in parsed["cells"].items()}
                        outlook_cells["quarter_header"] = parsed["quarter_header"]
                        outlook_cells["full_year_header"] = parsed["full_year_header"]
                    except ValueError as exc:
                        outlook_cells = {"parse_error": str(exc)}
            if "Reconciliation of Fiscal" in text and recon_page is None:
                recon_page = idx
                try:
                    parsed_r = parse_reconciliation_slide_words(page.extract_words())
                    recon_cells = {f"{row}:{metric}": phrase for (row, metric), phrase in parsed_r["cells"].items()}
                except ValueError as exc:
                    recon_cells = {"parse_error": str(exc)}
        return {
            "page_count": page_count,
            "pdf_creation": parse_pdf_date(meta.get("CreationDate")),
            "pdf_mod": parse_pdf_date(meta.get("ModDate")),
            "producer": meta.get("Producer"),
            "outlook_page": outlook_page,
            "outlook_type": outlook_type,
            "outlook_title": outlook_title,
            "outlook_cells": outlook_cells,
            "recon_page": recon_page,
            "recon_cells": recon_cells,
        }


def archive_digest_lookup(url: str, client: ProbeClient) -> dict[str, Any]:
    """Query IA CDX for the earliest 200 capture digest of ``url`` (best-effort)."""
    api = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={urllib.parse.quote(url, safe='')}&output=json&filter=statuscode:200"
        "&fl=timestamp,digest,statuscode&limit=5"
    )
    try:
        body, _, status = client.get(api)
    except Exception as exc:  # noqa: BLE001 — archive outages are non-fatal
        return {"status": "error", "error": str(exc)}
    if status != 200 or not body:
        return {"status": "unavailable", "http_status": status}
    try:
        rows = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"json: {exc}"}
    if not isinstance(rows, list) or len(rows) < 2:
        return {"status": "no_captures"}
    first = rows[1]
    return {
        "status": "ok",
        "first_capture": first[0] if len(first) > 0 else None,
        "digest": first[1] if len(first) > 1 else None,
    }


def cache_path_for(url: str, kind: str, fiscal_year: int, fiscal_quarter: int) -> Path:
    name = Path(urllib.parse.urlparse(url).path).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]
    return CACHE_DIR / f"FY{fiscal_year}Q{fiscal_quarter}_{kind}_{safe}"


def ensure_cached(
    client: ProbeClient,
    url: str,
    path: Path,
    *,
    refresh: bool,
) -> tuple[bytes, dict[str, str], int]:
    meta_path = path.with_suffix(path.suffix + ".headers.json")
    if path.is_file() and not refresh and meta_path.is_file():
        data = path.read_bytes()
        saved = json.loads(meta_path.read_text(encoding="utf-8"))
        headers = {k.lower(): str(v) for k, v in saved.get("headers", {}).items()}
        status = int(saved.get("http_status", 200))
        return data, headers, status
    # Re-fetch when the PDF was seeded without HTTP headers (timing evidence).
    body, headers, status = client.get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    if status == 200 and body:
        path.write_bytes(body)
        meta_path.write_text(
            json.dumps({"http_status": status, "headers": headers}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return body, headers, status


def seed_cache_from_tmp() -> None:
    """Copy previously downloaded research PDFs into the local cache when present."""
    tmp = Path("/tmp/lon7")
    if not tmp.is_dir():
        return
    mapping = {
        "2022_q1.pdf": ("deck", 2022, 1, "Visa-Inc.-First-Quarter-2022-Financial-Results-Presentation.pdf"),
        "2022_q4.pdf": ("deck", 2022, 4, "Visa-Inc.-Fourth-Quarter-2022-Financial-Results-Presentation.pdf"),
        "2023_q2.pdf": ("deck", 2023, 2, "Visa-Inc-Second-Quarter-2023-Financial-Results-Presentation.pdf"),
        "2023_q3.pdf": ("deck", 2023, 3, "Q3-2023-Earnings-Deck.pdf"),
        "2023_q4.pdf": ("deck", 2023, 4, "Q4-23-Earnings-Deck-FINAL.pdf"),
        "2024_q1.pdf": ("deck", 2024, 1, "Visa-Inc-First-Quarter-2024-Financial-Results-Presentation.pdf"),
        "2024_q2.pdf": ("deck", 2024, 2, "Visa-Inc-Second-Quarter-2024-Financial-Results-Presentation.pdf"),
        "2024_q3.pdf": ("deck", 2024, 3, "Visa-Inc-Third-Quarter-2024-Financial-Results-Presentation.pdf"),
        "2024_q4.pdf": ("deck", 2024, 4, "Visa-Inc-Fourth-Quarter-2024-Financial-Results-Presentation.pdf"),
        "2025_q3.pdf": ("deck", 2025, 3, "Visa-Inc-Third-Quarter-2025-Financial-Results-Presentation.pdf"),
        "2025_q4.pdf": ("deck", 2025, 4, "Visa-Inc-Fourth-Quarter-2025-Financial-Results-Presentation.pdf"),
        "2026_q2.pdf": ("deck", 2026, 2, "Visa-Inc-Second-Quarter-2026-Financial-Results-Presentation.pdf"),
        "2026_q3.pdf": ("deck", 2026, 3, "Visa-Inc-Third-Quarter-2026-Financial-Results-Presentation.pdf"),
        "t_2023_q2.pdf": (
            "transcript",
            2023,
            2,
            "CORRECTED-TRANSCRIPT-Visa-Inc-V-US-Q2-2023-Earnings-Call-25-April-2023-500-PM-ET.pdf",
        ),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for src_name, (kind, fy, fq, dest_name) in mapping.items():
        src = tmp / src_name
        if not src.is_file():
            continue
        dest = CACHE_DIR / f"FY{fy}Q{fq}_{kind}_{dest_name}"
        if not dest.is_file():
            dest.write_bytes(src.read_bytes())


def build_availability_row(
    origin: dict[str, str],
    manifest_origin: dict[str, Any],
    deck_meta: dict[str, Any] | None,
    transcript_meta: dict[str, Any] | None,
) -> dict[str, str]:
    fy = int(origin["fiscal_year"])
    fq = int(origin["fiscal_quarter"])
    cutoff = datetime.fromisoformat(origin["cutoff_utc"].replace("Z", "+00:00"))
    notes: list[str] = []

    deck_outlook = "none"
    guidance_source = "none"
    comparable_nr = "false"
    comparable_opex = "false"
    deck_within = ""
    delta = ""

    if deck_meta and deck_meta.get("http_status") == 200:
        deck_outlook = str(deck_meta.get("outlook_type") or "none")
        lm = parse_http_datetime(deck_meta.get("last_modified"))
        if lm is not None:
            delta_s = int((lm - cutoff).total_seconds())
            delta = str(delta_s)
            deck_within = "true" if abs(delta_s) <= DECK_EVENT_WINDOW_SECONDS else "false"
            if deck_within == "false":
                notes.append(f"deck Last-Modified outside +/-1h event window ({delta_s}s)")
        if deck_outlook == "next_quarter_and_full_year" and deck_within != "false":
            guidance_source = "deck"
            comparable_nr = "true"
            comparable_opex = "true"
        elif deck_outlook == "full_year_only":
            notes.append("deck has full-year outlook only")

    transcript_status = "n_a"
    transcript_has = ""
    if manifest_origin.get("transcript", {}).get("url"):
        transcript_status = "missing"
        if transcript_meta and transcript_meta.get("http_status") == 200:
            transcript_status = "ok"
            has = bool(transcript_meta.get("has_next_quarter_outlook"))
            transcript_has = "true" if has else "false"
            if has and guidance_source == "none":
                guidance_source = "transcript"
                comparable_nr = "true"
                comparable_opex = "derived" if transcript_meta.get("opex_relative") else "false"
        elif transcript_meta and transcript_meta.get("http_status") == 404:
            transcript_status = "not_found"
            notes.append("transcript URL returned 404")
    elif manifest_origin.get("transcript", {}).get("discovery") == "ia_cdx_absent":
        transcript_status = "absent"
        notes.append(str(manifest_origin["transcript"].get("note") or "transcript absent from CDN"))
    elif manifest_origin.get("origin_window") in {"primary", "prospective"}:
        transcript_status = "not_required"

    if guidance_source == "none":
        notes.append("no captured next-quarter outlook")

    return {
        "origin_label": origin_label(fy, fq),
        "fiscal_year": str(fy),
        "fiscal_quarter": str(fq),
        "origin_window": origin.get("origin_window") or manifest_origin.get("origin_window") or "",
        "status": origin.get("status") or "",
        "cutoff_utc": origin["cutoff_utc"],
        "target_fiscal_year": origin.get("target_fiscal_year") or "",
        "target_fiscal_quarter": origin.get("target_fiscal_quarter") or "",
        "deck_outlook_type": deck_outlook,
        "deck_url": (manifest_origin.get("deck") or {}).get("url") or "",
        "deck_http_status": str((deck_meta or {}).get("http_status") or ""),
        "deck_last_modified": (deck_meta or {}).get("last_modified") or "",
        "deck_last_modified_delta_seconds": delta,
        "deck_within_event_window": deck_within,
        "deck_pdf_creation": (deck_meta or {}).get("pdf_creation") or "",
        "deck_pdf_mod": (deck_meta or {}).get("pdf_mod") or "",
        "deck_sha256": (deck_meta or {}).get("sha256") or "",
        "deck_sha1_base32": (deck_meta or {}).get("sha1_base32") or "",
        "deck_page_count": str((deck_meta or {}).get("page_count") or ""),
        "deck_outlook_page": str((deck_meta or {}).get("outlook_page") or ""),
        "deck_recon_page": str((deck_meta or {}).get("recon_page") or ""),
        "archive_digest_match": (deck_meta or {}).get("archive_digest_match") or "",
        "archive_first_capture": (deck_meta or {}).get("archive_first_capture") or "",
        "transcript_status": transcript_status,
        "transcript_url": (manifest_origin.get("transcript") or {}).get("url") or "",
        "transcript_http_status": str((transcript_meta or {}).get("http_status") or ""),
        "transcript_last_modified": (transcript_meta or {}).get("last_modified") or "",
        "transcript_sha256": (transcript_meta or {}).get("sha256") or "",
        "transcript_has_next_quarter_outlook": transcript_has,
        "guidance_source": guidance_source,
        "comparable_net_revenue": comparable_nr,
        "comparable_operating_expenses": comparable_opex,
        "notes": "; ".join(notes),
    }


def statements_from_deck(origin: dict[str, str], deck_meta: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    cells = deck_meta.get("outlook_cells") or {}
    recon = deck_meta.get("recon_cells") or {}
    fy = int(origin["target_fiscal_year"]) if origin.get("target_fiscal_year") else 0
    fq = int(origin["target_fiscal_quarter"]) if origin.get("target_fiscal_quarter") else 0
    page = deck_meta.get("outlook_page")
    label = origin_label(int(origin["fiscal_year"]), int(origin["fiscal_quarter"]))

    metric_map = {
        "net_revenue": ("net_revenue", "gaap"),
        "operating_expenses": ("operating_expenses", "ex_special_items"),
        "diluted_eps": ("diluted_eps", "gaap"),
    }
    for metric_key, (activity, default_basis) in metric_map.items():
        phrase = cells.get(f"{metric_key}:q")
        if not phrase:
            continue
        basis = default_basis
        comparable = "true"
        note = "outlook slide adjusted constant-dollar"
        if metric_key == "net_revenue" and recon.get("gaap_nominal:net_revenue"):
            note = "outlook phrase; recon has GAAP nominal row"
            basis = "gaap"
        if metric_key == "operating_expenses" and recon.get("non_gaap_nominal:operating_expenses"):
            note = "outlook phrase; recon has non-GAAP nominal row"
            basis = "ex_special_items"
        if metric_key == "diluted_eps":
            comparable = "context_only"
            note = "EPS guidance is context only for LON-29"
        try:
            low, high = parse_guidance_phrase(phrase)
        except ValueError as exc:
            rows.append(
                {
                    "origin_label": label,
                    "source_kind": "deck",
                    "metric": activity,
                    "period_kind": "next_quarter",
                    "target_fiscal_year": str(fy),
                    "target_fiscal_quarter": str(fq),
                    "basis": basis,
                    "phrase": phrase,
                    "range_low": "",
                    "range_high": "",
                    "unit": "percent",
                    "page": str(page or ""),
                    "quote": phrase,
                    "comparable": "false",
                    "note": f"lexicon miss: {exc}",
                }
            )
            continue
        rows.append(
            {
                "origin_label": label,
                "source_kind": "deck",
                "metric": activity,
                "period_kind": "next_quarter",
                "target_fiscal_year": str(fy),
                "target_fiscal_quarter": str(fq),
                "basis": basis,
                "phrase": phrase,
                "range_low": f"{low:g}",
                "range_high": f"{high:g}",
                "unit": "percent",
                "page": str(page or ""),
                "quote": phrase,
                "comparable": comparable,
                "note": note,
            }
        )
    return rows


def statements_from_transcript(
    origin: dict[str, str],
    transcript_meta: dict[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    fy = int(origin["target_fiscal_year"]) if origin.get("target_fiscal_year") else 0
    fq = int(origin["target_fiscal_quarter"]) if origin.get("target_fiscal_quarter") else 0
    label = origin_label(int(origin["fiscal_year"]), int(origin["fiscal_quarter"]))
    phrase = transcript_meta.get("net_revenue_phrase")
    quote = transcript_meta.get("net_revenue_quote") or phrase or ""
    if phrase:
        try:
            low, high = parse_guidance_phrase(phrase)
            rows.append(
                {
                    "origin_label": label,
                    "source_kind": "transcript",
                    "metric": "net_revenue",
                    "period_kind": "next_quarter",
                    "target_fiscal_year": str(fy),
                    "target_fiscal_quarter": str(fq),
                    "basis": "nominal",
                    "phrase": phrase,
                    "range_low": f"{low:g}",
                    "range_high": f"{high:g}",
                    "unit": "percent",
                    "page": "",
                    "quote": quote[:240],
                    "comparable": "true",
                    "note": "transcript spoken nominal net revenue outlook",
                }
            )
        except ValueError as exc:
            rows.append(
                {
                    "origin_label": label,
                    "source_kind": "transcript",
                    "metric": "net_revenue",
                    "period_kind": "next_quarter",
                    "target_fiscal_year": str(fy),
                    "target_fiscal_quarter": str(fq),
                    "basis": "nominal",
                    "phrase": phrase,
                    "range_low": "",
                    "range_high": "",
                    "unit": "percent",
                    "page": "",
                    "quote": quote[:240],
                    "comparable": "false",
                    "note": f"lexicon miss: {exc}",
                }
            )
    opex = transcript_meta.get("opex_relative")
    if opex:
        rows.append(
            {
                "origin_label": label,
                "source_kind": "transcript",
                "metric": "operating_expenses",
                "period_kind": "next_quarter",
                "target_fiscal_year": str(fy),
                "target_fiscal_quarter": str(fq),
                "basis": "derived",
                "phrase": transcript_meta.get("opex_quote") or "",
                "range_low": "",
                "range_high": "",
                "unit": "percent",
                "page": "",
                "quote": (transcript_meta.get("opex_quote") or "")[:240],
                "comparable": "derived",
                "note": (
                    f"relative: {opex['points_lower_low']}-{opex['points_lower_high']} points "
                    f"lower than {opex.get('reference_quarter') or 'prior'} quarter; "
                    "resolve against reported growth in LON-29"
                ),
            }
        )
    elif transcript_meta.get("opex_absolute_phrase"):
        phrase = str(transcript_meta["opex_absolute_phrase"])
        quote = transcript_meta.get("opex_quote") or phrase
        try:
            low, high = parse_guidance_phrase(phrase)
            rows.append(
                {
                    "origin_label": label,
                    "source_kind": "transcript",
                    "metric": "operating_expenses",
                    "period_kind": "next_quarter",
                    "target_fiscal_year": str(fy),
                    "target_fiscal_quarter": str(fq),
                    "basis": "ex_special_items",
                    "phrase": phrase,
                    "range_low": f"{low:g}",
                    "range_high": f"{high:g}",
                    "unit": "percent",
                    "page": "",
                    "quote": str(quote)[:240],
                    "comparable": "true",
                    "note": "transcript spoken non-GAAP operating expense outlook",
                }
            )
        except ValueError as exc:
            rows.append(
                {
                    "origin_label": label,
                    "source_kind": "transcript",
                    "metric": "operating_expenses",
                    "period_kind": "next_quarter",
                    "target_fiscal_year": str(fy),
                    "target_fiscal_quarter": str(fq),
                    "basis": "ex_special_items",
                    "phrase": phrase,
                    "range_low": "",
                    "range_high": "",
                    "unit": "percent",
                    "page": "",
                    "quote": str(quote)[:240],
                    "comparable": "false",
                    "note": f"lexicon miss: {exc}",
                }
            )
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def build_sample_fixture(
    origin: dict[str, str],
    manifest_origin: dict[str, Any],
    *,
    source_kind: str,
    meta: dict[str, Any],
    statements: list[dict[str, str]],
) -> dict[str, Any]:
    fy = int(origin["fiscal_year"])
    fq = int(origin["fiscal_quarter"])
    tfy = int(origin["target_fiscal_year"])
    tfq = int(origin["target_fiscal_quarter"])
    period_start, period_end = fiscal_period_bounds(tfy, tfq)
    url = (manifest_origin.get(source_kind) or {}).get("url") or ""
    release_date = origin["cutoff_utc"][:10]
    observations: list[dict[str, Any]] = []
    for stmt in statements:
        if stmt["source_kind"] != source_kind:
            continue
        if stmt["metric"] == "diluted_eps":
            continue
        if not stmt.get("range_low"):
            continue
        quote = stmt["quote"] or stmt["phrase"]
        span = {
            "anchor": f"{stmt['metric']}:{stmt['period_kind']}",
            "quote": quote,
            "char_start": 0,
            "char_end": len(quote),
            "page": int(stmt["page"]) if stmt.get("page") else None,
        }
        observations.append(
            {
                "observation_id": (
                    f"visa_{origin_label(fy, fq).lower()}_{stmt['metric']}_{stmt['period_kind']}_{source_kind}"
                ),
                "statement_type": "guidance",
                "activity_type": stmt["metric"],
                "geography": "global",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "value": None,
                "range_low": float(stmt["range_low"]),
                "range_high": float(stmt["range_high"]),
                "unit": "percent",
                "basis": stmt["basis"],
                "source_family": "visa_ir",
                "review_status": "pending",
                "span": span,
                "note": stmt["note"],
                "attributes": {
                    "guidance_label": COMPANY_GUIDANCE_LABEL,
                    "guidance_quarter": f"{tfy}Q{tfq}",
                    "phrase": stmt["phrase"],
                    "comparable": stmt["comparable"],
                    "source_kind": source_kind,
                },
            }
        )
    document_ts = meta.get("last_modified_iso") or meta.get("last_modified")
    return {
        "schema_version": 1,
        "company": "visa",
        "origin_label": origin_label(fy, fq),
        "origin_fiscal_year": fy,
        "origin_fiscal_quarter": fq,
        "target_fiscal_year": tfy,
        "target_fiscal_quarter": tfq,
        "cutoff_utc": origin["cutoff_utc"],
        "release_date": release_date,
        "source": {
            "source_id": f"visa_ir/{origin_label(fy, fq).lower()}/{source_kind}",
            "kind": source_kind,
            "url": url,
            "statement_ts": origin["cutoff_utc"],
            "document_ts": document_ts,
            "content_sha256": meta.get("sha256") or "",
            "note": f"{source_kind} outlook for {origin_label(fy, fq)}",
        },
        "observations": observations,
        "notes": [
            "Guidance is company guidance only; never a model input.",
            CONSENSUS_UNAVAILABLE_LABEL,
        ],
        "labels": {
            "company_guidance": COMPANY_GUIDANCE_LABEL,
            "estimates_unavailable": CONSENSUS_UNAVAILABLE_LABEL,
        },
    }


def _probe_document(
    client: ProbeClient,
    url: str,
    kind: str,
    fy: int,
    fq: int,
    *,
    refresh: bool,
    skip_archive: bool,
) -> dict[str, Any]:
    path = cache_path_for(url, kind, fy, fq)
    body, headers, status = ensure_cached(client, url, path, refresh=refresh)
    meta: dict[str, Any] = {
        "url": url,
        "kind": kind,
        "http_status": status,
        "cache_path": str(path.relative_to(PACKAGE_ROOT)) if path.is_file() else "",
        "last_modified": headers.get("last-modified"),
        "etag": headers.get("etag"),
    }
    lm = parse_http_datetime(headers.get("last-modified"))
    if lm is not None:
        meta["last_modified_iso"] = lm.isoformat().replace("+00:00", "Z")
    if status != 200 or not body:
        return meta
    meta["sha256"] = sha256_bytes(body)
    meta["sha1_base32"] = sha1_base32(body)
    meta["bytes"] = len(body)
    if path.is_file():
        pdf_meta = pdf_metadata(path)
        meta.update(pdf_meta)
        if kind == "transcript":
            with pdfplumber.open(path) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            found = find_transcript_outlook(text)
            meta["has_next_quarter_outlook"] = bool(found.get("net_revenue_phrase"))
            meta["net_revenue_phrase"] = found.get("net_revenue_phrase")
            meta["net_revenue_quote"] = found.get("net_revenue_quote")
            meta["opex_relative"] = found.get("opex_relative")
            meta["opex_absolute_phrase"] = found.get("opex_absolute_phrase")
            meta["opex_quote"] = found.get("opex_quote")
    if kind == "deck" and not skip_archive:
        archive = archive_digest_lookup(url, client)
        meta["archive"] = archive
        digest = archive.get("digest")
        if digest and meta.get("sha1_base32"):
            # IA digests are base32(SHA-1); compare case-insensitively.
            meta["archive_digest_match"] = (
                "true" if str(digest).upper() == str(meta["sha1_base32"]).upper() else "false"
            )
            meta["archive_first_capture"] = archive.get("first_capture") or ""
        else:
            meta["archive_digest_match"] = archive.get("status") or "unavailable"
            meta["archive_first_capture"] = archive.get("first_capture") or ""
    return meta


def run_probe(*, refresh: bool = False, skip_archive: bool = False) -> dict[str, Any]:
    seed_cache_from_tmp()
    manifest = load_manifest()
    origins = load_origins()
    manifest_by_key = {(int(o["fiscal_year"]), int(o["fiscal_quarter"])): o for o in manifest["origins"]}
    user_agent = _load_env_user_agent()
    client = ProbeClient(user_agent)

    availability_rows: list[dict[str, str]] = []
    statement_rows: list[dict[str, str]] = []
    probe_docs: list[dict[str, Any]] = []
    samples_written: list[str] = []

    for origin in origins:
        fy = int(origin["fiscal_year"])
        fq = int(origin["fiscal_quarter"])
        mo = manifest_by_key.get((fy, fq))
        if mo is None:
            raise KeyError(f"manifest missing origin FY{fy}Q{fq}")

        deck_meta: dict[str, Any] | None = None
        transcript_meta: dict[str, Any] | None = None
        deck_url = (mo.get("deck") or {}).get("url")
        if deck_url:
            print(f"probe deck {origin_label(fy, fq)} …", flush=True)
            deck_meta = _probe_document(client, deck_url, "deck", fy, fq, refresh=refresh, skip_archive=skip_archive)
            probe_docs.append({"origin": origin_label(fy, fq), **deck_meta})

        tr_url = (mo.get("transcript") or {}).get("url")
        if tr_url:
            print(f"probe transcript {origin_label(fy, fq)} …", flush=True)
            transcript_meta = _probe_document(client, tr_url, "transcript", fy, fq, refresh=refresh, skip_archive=True)
            probe_docs.append({"origin": origin_label(fy, fq), **transcript_meta})

        avail = build_availability_row(origin, mo, deck_meta, transcript_meta)
        availability_rows.append(avail)

        origin_statements: list[dict[str, str]] = []
        if deck_meta and deck_meta.get("outlook_type") == "next_quarter_and_full_year":
            origin_statements.extend(statements_from_deck(origin, deck_meta))
        if transcript_meta and transcript_meta.get("has_next_quarter_outlook"):
            # Prefer deck statements when both exist; still record transcript for extension.
            if avail["guidance_source"] == "transcript" or (fy, fq) in SAMPLE_KEYS:
                origin_statements.extend(statements_from_transcript(origin, transcript_meta))
        statement_rows.extend(origin_statements)

        if (fy, fq) in SAMPLE_KEYS:
            kind = avail["guidance_source"]
            meta = deck_meta if kind == "deck" else transcript_meta
            if kind in {"deck", "transcript"} and meta is not None:
                fixture = build_sample_fixture(origin, mo, source_kind=kind, meta=meta, statements=origin_statements)
                if fixture["observations"]:
                    model = VisaGuidanceFixture.model_validate(fixture)
                    out = OBSERVATIONS_DIR / f"visa_guidance_{origin['cutoff_utc'][:10]}.json"
                    out.write_text(
                        json.dumps(model.model_dump(mode="json"), indent=2) + "\n",
                        encoding="utf-8",
                    )
                    # Validate against ObservationCreate.
                    for obs in model.observations:
                        to_observation_create(obs, model.source.url)
                    samples_written.append(str(out.relative_to(PACKAGE_ROOT)))

    write_csv(AVAILABILITY_PATH, AVAILABILITY_FIELDS, availability_rows)
    write_csv(STATEMENTS_PATH, STATEMENT_FIELDS, statement_rows)

    covered = sum(1 for r in availability_rows if r["guidance_source"] in {"deck", "transcript"})
    probe = {
        "generated_for": "LON-7",
        "schema_version": 1,
        "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "decision": manifest["decision"],
        "labels": manifest["labels"],
        "timing": manifest["timing"],
        "comparability": manifest["comparability"],
        "access": {
            "ir_quarterly_html": manifest["access"]["ir_quarterly_html"],
            "cdn_host": manifest["access"]["cdn"]["host"],
            "crawl_delay_seconds": manifest["access"]["cdn"]["crawl_delay_seconds"],
            "redistribution": manifest["access"]["redistribution"],
            "cache_dir": manifest["access"]["cache_dir"],
        },
        "coverage": {
            "n_origins": len(availability_rows),
            "n_with_next_quarter_guidance": covered,
            "n_deck_era": sum(1 for r in availability_rows if r["guidance_source"] == "deck"),
            "n_transcript_era": sum(1 for r in availability_rows if r["guidance_source"] == "transcript"),
            "n_gaps": sum(1 for r in availability_rows if r["guidance_source"] == "none"),
        },
        "analyst_estimates_checked": manifest["analyst_estimates_checked"],
        "estimates_unavailable_label": CONSENSUS_UNAVAILABLE_LABEL,
        "documents": [
            {
                "origin": d.get("origin"),
                "kind": d.get("kind"),
                "url": d.get("url"),
                "http_status": d.get("http_status"),
                "sha256": d.get("sha256"),
                "sha1_base32": d.get("sha1_base32"),
                "bytes": d.get("bytes"),
                "last_modified": d.get("last_modified"),
                "pdf_creation": d.get("pdf_creation"),
                "pdf_mod": d.get("pdf_mod"),
                "page_count": d.get("page_count"),
                "outlook_type": d.get("outlook_type"),
                "outlook_page": d.get("outlook_page"),
                "recon_page": d.get("recon_page"),
                "archive_digest_match": d.get("archive_digest_match"),
                "archive_first_capture": d.get("archive_first_capture"),
                "has_next_quarter_outlook": d.get("has_next_quarter_outlook"),
            }
            for d in probe_docs
        ],
        "samples": samples_written,
        "notes": [
            "Original PDFs are cached under var/cache/visa_ir/ and never committed.",
            "investor.visa.com quarterly HTML pages return 403 Cloudflare challenges (DR-09).",
            CONSENSUS_UNAVAILABLE_LABEL,
        ],
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    PROBE_PATH.write_text(json.dumps(probe, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {AVAILABILITY_PATH.relative_to(PACKAGE_ROOT)} "
        f"({covered}/{len(availability_rows)} with next-quarter guidance)",
        flush=True,
    )
    return probe


def run_verify() -> None:
    """Offline re-check of cached hashes and sample fixture contracts."""
    if not AVAILABILITY_PATH.is_file():
        raise FileNotFoundError("availability.csv missing; run probe first")
    with AVAILABILITY_PATH.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    mismatches: list[str] = []
    for row in rows:
        sha = row.get("deck_sha256") or ""
        url = row.get("deck_url") or ""
        if not sha or not url:
            continue
        fy, fq = int(row["fiscal_year"]), int(row["fiscal_quarter"])
        path = cache_path_for(url, "deck", fy, fq)
        if not path.is_file():
            mismatches.append(f"missing cache for {row['origin_label']}")
            continue
        actual = sha256_bytes(path.read_bytes())
        if actual != sha:
            mismatches.append(f"sha256 mismatch {row['origin_label']}: {actual} != {sha}")
    for path in required_fixture_paths():
        if not path.is_file():
            mismatches.append(f"missing sample fixture {path.name}")
            continue
        fixture = load_fixture(path)
        for obs in fixture.observations:
            to_observation_create(obs, fixture.source.url)
    if mismatches:
        raise RuntimeError("verify failed:\n" + "\n".join(mismatches))
    print(f"verify ok: {len(rows)} availability rows; {len(required_fixture_paths())} samples")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visa IR guidance gate (LON-7)")
    sub = parser.add_subparsers(dest="command", required=True)
    probe_p = sub.add_parser("probe", help="Fetch/parse IR decks and transcripts")
    probe_p.add_argument("--refresh", action="store_true", help="Re-download even if cached")
    probe_p.add_argument(
        "--skip-archive",
        action="store_true",
        help="Skip Internet Archive digest lookups",
    )
    sub.add_parser("verify", help="Re-hash cache and validate sample fixtures")
    args = parser.parse_args(argv)
    if args.command == "probe":
        run_probe(refresh=args.refresh, skip_archive=args.skip_archive)
        return 0
    if args.command == "verify":
        run_verify()
        return 0
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
