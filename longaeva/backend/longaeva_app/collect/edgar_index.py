"""Visa eligible-origin inventory from EDGAR acceptance timestamps (LON-1).

Standard-library only. Two CLI modes:

  fetch  — live EDGAR requests (requires SEC_USER_AGENT); writes filing_index.json
  build  — offline; reads filing_index.json and writes origins.csv + origins-inventory.md
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VISA_CIK = "0001403161"
BOOKING_CIK = "0001075531"
VISA_CIK_INT = 1403161
BOOKING_CIK_INT = 1075531

EASTERN = ZoneInfo("America/New_York")
SEC_MIN_INTERVAL = 0.5  # ≤ 2 req/s
SEC_MAX_RETRIES = 4

PACKAGE_ROOT = Path(__file__).resolve().parents[3]  # longaeva/
SNAPSHOT_PATH = PACKAGE_ROOT / "data" / "fixtures" / "edgar" / "filing_index.json"
ORIGINS_CSV_PATH = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"
INVENTORY_MD_PATH = PACKAGE_ROOT / "docs" / "origins-inventory.md"

# Visa fiscal year ends September 30.
# Q1: Oct–Dec (period end Dec 31), Q2: Jan–Mar (Mar 31), Q3: Apr–Jun (Jun 30), Q4: Jul–Sep (Sep 30)
FISCAL_QUARTER_ENDS: dict[int, tuple[int, int]] = {
    1: (12, 31),
    2: (3, 31),
    3: (6, 30),
    4: (9, 30),
}

CSV_COLUMNS = [
    "fiscal_year",
    "fiscal_quarter",
    "period_end",
    "release_accession",
    "cutoff_utc",
    "cutoff_et",
    "target_fiscal_year",
    "target_fiscal_quarter",
    "target_release_accession",
    "target_release_accepted_utc",
    "is_calibration",
    "origin_window",
    "pandemic_flag",
    "prior_10q_form",
    "prior_10q_accession",
    "prior_10q_accepted_utc",
    "prior_10q_eligible",
    "same_q_10q_form",
    "same_q_10q_accession",
    "same_q_10q_accepted_utc",
    "same_q_10q_hours_after_cutoff",
    "same_q_10q_eligible",
    "booking_accession",
    "booking_accepted_utc",
    "booking_age_days",
    "booking_age_weeks",
    "booking_eligible",
    "booking_same_day",
    "booking_margin_seconds",
    "booking_guidance_covers_target",
    "booking_fallback_accession",
    "census_release",
    "census_reference_month",
    "census_publication_utc",
    "census_age_days",
    "census_status",
    "status",
    "exclusion_reasons",
]


@dataclass(frozen=True)
class Filing:
    cik: int
    accession: str
    form: str
    filed_date: str  # YYYY-MM-DD
    accepted_utc: str  # ISO-8601 with Z
    period_of_report: str  # YYYY-MM-DD or ""
    items: str  # semicolon-separated Item codes
    primary_document: str
    is_amendment: bool


@dataclass(frozen=True)
class FiscalQuarter:
    year: int
    quarter: int  # 1..4

    @property
    def period_end(self) -> date:
        month, day = FISCAL_QUARTER_ENDS[self.quarter]
        # Q1 period end is Dec 31 of the prior calendar year
        cal_year = self.year - 1 if self.quarter == 1 else self.year
        return date(cal_year, month, day)

    def next(self) -> FiscalQuarter:
        if self.quarter == 4:
            return FiscalQuarter(self.year + 1, 1)
        return FiscalQuarter(self.year, self.quarter + 1)

    def label(self) -> str:
        return f"FY{self.year}Q{self.quarter}"


def is_eligible(accepted_utc: datetime, cutoff_utc: datetime) -> bool:
    """A document is eligible iff its acceptance timestamp ≤ cutoff."""
    if accepted_utc.tzinfo is None:
        raise ValueError("accepted_utc must be timezone-aware")
    if cutoff_utc.tzinfo is None:
        raise ValueError("cutoff_utc must be timezone-aware")
    return accepted_utc <= cutoff_utc


def parse_acceptance_datetime(raw: str) -> datetime:
    """Parse EDGAR acceptanceDateTime to timezone-aware UTC.

    EDGAR submissions JSON stores acceptanceDateTime as
    ``YYYY-MM-DD HH:MM:SS`` in US/Eastern (no timezone suffix).
    Confirm via spot-check against filing index pages.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("empty acceptanceDateTime")
    # With explicit Z or offset
    if raw.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", raw):
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(UTC)
    # Eastern wall-clock without suffix
    if "T" in raw:
        naive = datetime.fromisoformat(raw)
    else:
        naive = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=EASTERN).astimezone(UTC)


def format_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_et(dt: datetime) -> str:
    return dt.astimezone(EASTERN).strftime("%Y-%m-%d %H:%M:%S %Z")


def fiscal_quarter_from_period_end(period: date) -> FiscalQuarter:
    """Map a period-of-report date to a Visa fiscal quarter."""
    if period.month == 12 and period.day == 31:
        return FiscalQuarter(period.year + 1, 1)
    if period.month == 3 and period.day == 31:
        return FiscalQuarter(period.year, 2)
    if period.month == 6 and period.day == 30:
        return FiscalQuarter(period.year, 3)
    if period.month == 9 and period.day == 30:
        return FiscalQuarter(period.year, 4)
    raise ValueError(f"unrecognized Visa period end: {period.isoformat()}")


def fiscal_quarter_from_release_date(release_date: date) -> FiscalQuarter:
    """Map a release calendar date to the latest fiscal quarter-end before it.

    Earnings for quarter ending D are typically released ~3–4 weeks after D.
    So the reported quarter is the most recent quarter-end strictly before
    the release date (or on the release date, which does not occur).
    """
    candidates = [
        date(release_date.year, 12, 31),
        date(release_date.year, 9, 30),
        date(release_date.year, 6, 30),
        date(release_date.year, 3, 31),
        date(release_date.year - 1, 12, 31),
        date(release_date.year - 1, 9, 30),
    ]
    prior = [c for c in candidates if c < release_date]
    if not prior:
        raise ValueError(f"no prior quarter-end for release date {release_date}")
    return fiscal_quarter_from_period_end(max(prior))


def _load_env_user_agent() -> str:
    env_path = PACKAGE_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SEC_USER_AGENT=") and not line.startswith("#"):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if not value:
        raise RuntimeError(
            "SEC_USER_AGENT is required for live EDGAR fetches. Set it in longaeva/.env or the environment."
        )
    return value


class EdgarClient:
    """Throttled SEC EDGAR HTTP client (≤ 2 req/s, backoff on 429/5xx)."""

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < SEC_MIN_INTERVAL:
            time.sleep(SEC_MIN_INTERVAL - elapsed)

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(SEC_MAX_RETRIES):
            self._throttle()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "identity",
                    "Host": urllib.parse.urlparse(url).hostname or "data.sec.gov",
                },
            )
            try:
                self._last_request_at = time.monotonic()
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body: str = resp.read().decode("utf-8", errors="replace")
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

    def get_json(self, url: str) -> dict[str, Any]:
        data = json.loads(self.get_text(url))
        if not isinstance(data, dict):
            raise TypeError(f"Expected JSON object from {url}, got {type(data).__name__}")
        return data


def _zip_filings(cik: int, recent: dict[str, Any]) -> list[Filing]:
    """Convert a submissions 'recent' or file-page parallel arrays into Filings."""
    n = len(recent.get("accessionNumber", []))
    out: list[Filing] = []
    for i in range(n):
        accession = recent["accessionNumber"][i]
        form = recent["form"][i]
        filed = recent["filingDate"][i]
        accepted_raw = recent["acceptanceDateTime"][i]
        period = recent.get("reportDate", [""] * n)[i] or ""
        items = recent.get("items", [""] * n)[i] or ""
        primary = recent.get("primaryDocument", [""] * n)[i] or ""
        is_amendment = form.endswith("/A")
        try:
            accepted_utc = format_utc(parse_acceptance_datetime(accepted_raw))
        except ValueError:
            continue
        out.append(
            Filing(
                cik=cik,
                accession=accession,
                form=form,
                filed_date=filed,
                accepted_utc=accepted_utc,
                period_of_report=period,
                items=items,
                primary_document=primary,
                is_amendment=is_amendment,
            )
        )
    return out


def parse_submissions(primary: dict[str, Any], extra_pages: list[dict[str, Any]], cik: int) -> list[Filing]:
    """Merge recent + paged submissions; dedupe by accession (keep first = most recent)."""
    filings = _zip_filings(cik, primary.get("filings", {}).get("recent", {}))
    for page in extra_pages:
        # Paged files are themselves the parallel-array object (not wrapped in filings.recent)
        if "accessionNumber" in page:
            filings.extend(_zip_filings(cik, page))
        elif "filings" in page:
            filings.extend(_zip_filings(cik, page["filings"].get("recent", {})))
    seen: set[str] = set()
    deduped: list[Filing] = []
    for f in filings:
        if f.accession in seen:
            continue
        seen.add(f.accession)
        deduped.append(f)
    deduped.sort(key=lambda f: f.accepted_utc)
    return deduped


def fetch_company_filings(client: EdgarClient, cik_padded: str) -> tuple[list[Filing], list[str]]:
    """Fetch submissions JSON + older pages. Returns (filings, source_urls)."""
    cik_int = int(cik_padded)
    primary_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    primary = client.get_json(primary_url)
    urls = [primary_url]
    extra_pages: list[dict[str, Any]] = []
    for file_meta in primary.get("filings", {}).get("files", []):
        name = file_meta.get("name", "")
        # Older pages are named either ``submissions-001.json`` (Visa/Booking)
        # or ``CIK0000104169-submissions-001.json`` (Walmart/JPMorgan, …).
        if not re.search(r"(?:^|-)submissions-\d{3}\.json$", name):
            continue
        page_url = f"https://data.sec.gov/submissions/{name}"
        extra_pages.append(client.get_json(page_url))
        urls.append(page_url)
    return parse_submissions(primary, extra_pages, cik_int), urls


def is_earnings_8k(filing: Filing) -> bool:
    """Item 2.02 8-K that is not an amendment."""
    if filing.form not in {"8-K", "8-K/A"}:
        return False
    items = {part.strip() for part in filing.items.replace(",", ";").split(";") if part.strip()}
    return "2.02" in items


def filter_forms(filings: list[Filing], forms: set[str]) -> list[Filing]:
    return [f for f in filings if f.form in forms]


def accession_to_index_url(cik: int, accession: str) -> str:
    no_dash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{no_dash}/{accession}-index.htm"


_ACCEPTED_RE = re.compile(
    r"Accepted[:\s]*</(?:td|div|span|b)>\s*<(?:td|div|span)[^>]*>\s*"
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)
_ACCEPTED_PLAIN_RE = re.compile(
    r"Accepted[:\s]+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)


def extract_accepted_from_index_html(html: str) -> str | None:
    """Pull the 'Accepted' Eastern wall-clock string from an EDGAR index page."""
    for pattern in (_ACCEPTED_RE, _ACCEPTED_PLAIN_RE):
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def spot_check_filings(
    client: EdgarClient,
    filings: list[Filing],
    picks: list[Filing],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for filing in picks:
        url = accession_to_index_url(filing.cik, filing.accession)
        html = client.get_text(url)
        page_accepted = extract_accepted_from_index_html(html)
        parsed_from_page = format_utc(parse_acceptance_datetime(page_accepted)) if page_accepted else None
        results.append(
            {
                "accession": filing.accession,
                "form": filing.form,
                "filed_date": filing.filed_date,
                "submissions_accepted_utc": filing.accepted_utc,
                "index_page_url": url,
                "index_page_accepted_et": page_accepted,
                "index_page_accepted_utc": parsed_from_page,
                "match": parsed_from_page == filing.accepted_utc if parsed_from_page else False,
            }
        )
    return results


def select_spot_check_picks(visa_earnings: list[Filing]) -> list[Filing]:
    """Pick five earnings 8-Ks from different years spanning FY2017–FY2026."""
    by_year: dict[int, Filing] = {}
    for f in visa_earnings:
        year = int(f.filed_date[:4])
        by_year.setdefault(year, f)
    preferred_years = [2017, 2019, 2021, 2024, 2026]
    picks: list[Filing] = []
    for y in preferred_years:
        if y in by_year:
            picks.append(by_year[y])
    # Fill from remaining years if needed
    if len(picks) < 5:
        for y in sorted(by_year):
            if by_year[y] not in picks:
                picks.append(by_year[y])
            if len(picks) >= 5:
                break
    return picks[:5]


def trim_filings_for_snapshot(filings: list[Filing], forms: set[str], since: date) -> list[dict[str, Any]]:
    out = []
    for f in filings:
        if f.form not in forms:
            continue
        if date.fromisoformat(f.filed_date) < since:
            continue
        out.append(asdict(f))
    return out


def fetch_snapshot(client: EdgarClient) -> dict[str, Any]:
    visa_all, visa_urls = fetch_company_filings(client, VISA_CIK)
    booking_all, booking_urls = fetch_company_filings(client, BOOKING_CIK)

    visa_forms = {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A"}
    booking_forms = {"8-K", "8-K/A"}
    since = date(2016, 1, 1)  # cover FY2017 Q1 (released early 2017) with margin

    visa_trimmed = trim_filings_for_snapshot(visa_all, visa_forms, since)
    booking_trimmed = trim_filings_for_snapshot(booking_all, booking_forms, since)

    # Rebuild Filing objects for earnings filter / spot checks
    visa_filings = [Filing(**row) for row in visa_trimmed]
    visa_earnings = [f for f in visa_filings if is_earnings_8k(f) and not f.is_amendment]
    picks = select_spot_check_picks(visa_earnings)
    spot_checks = spot_check_filings(client, visa_filings, picks)

    return {
        "retrieved_at_utc": format_utc(datetime.now(UTC)),
        "user_agent_declared": True,
        "sources": {
            "visa": visa_urls,
            "booking": booking_urls,
        },
        "visa_filings": visa_trimmed,
        "booking_filings": booking_trimmed,
        "spot_checks": spot_checks,
    }


def filing_from_dict(row: dict[str, Any]) -> Filing:
    return Filing(**row)


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def classify_origin_window(fq: FiscalQuarter) -> str:
    """primary | extension | prospective | calibration_only | none."""
    # Prospective is handled separately (no target release)
    if fq.year >= 2024 or (fq.year == 2022 or fq.year == 2023):
        if fq.year >= 2024 and not (fq.year == 2026 and fq.quarter == 3):
            # FY2024Q1–FY2026Q2 primary; FY2026Q3 is prospective origin
            if fq.year < 2026 or (fq.year == 2026 and fq.quarter <= 2):
                return "primary"
            if fq.year == 2026 and fq.quarter == 3:
                return "prospective"
        if fq.year in {2022, 2023}:
            return "extension"
        if fq.year == 2026 and fq.quarter == 3:
            return "prospective"
    return "none"


def build_origins(
    snapshot: dict[str, Any],
    *,
    booking_calendar: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    visa = [filing_from_dict(r) for r in snapshot["visa_filings"]]
    booking = [filing_from_dict(r) for r in snapshot["booking_filings"]]

    visa_earnings = sorted(
        [f for f in visa if is_earnings_8k(f) and f.form == "8-K"],
        key=lambda f: f.accepted_utc,
    )
    visa_10qs = sorted(
        [f for f in visa if f.form in {"10-Q", "10-K"}],
        key=lambda f: f.accepted_utc,
    )
    booking_earnings = sorted(
        [f for f in booking if is_earnings_8k(f) and f.form == "8-K"],
        key=lambda f: f.accepted_utc,
    )
    booking_accessions_ordered = [f.accession for f in booking_earnings]

    # Lazy import: calendar is optional so toy snapshots still build.
    if booking_calendar is None:
        try:
            from longaeva_app.collect.booking_sources import load_calendar

            booking_calendar = load_calendar()
        except (FileNotFoundError, OSError):
            booking_calendar = []
    booking_cal_by_acc = {row["accession"]: row for row in booking_calendar if row.get("accession")}

    from longaeva_app.extract.booking_release import guidance_covers_target

    # Map earnings to fiscal quarters; detect duplicates
    quarter_to_release: dict[tuple[int, int], Filing] = {}
    duplicate_notes: dict[tuple[int, int], list[str]] = {}
    mapped: list[tuple[FiscalQuarter, Filing, list[str]]] = []

    for release in visa_earnings:
        release_date = date.fromisoformat(release.filed_date)
        reasons: list[str] = []
        fq = fiscal_quarter_from_release_date(release_date)

        # Cross-check against period_of_report only when it looks like a quarter-end.
        # For earnings 8-Ks, reportDate is often the event/release date, not the fiscal period.
        if release.period_of_report:
            try:
                por = date.fromisoformat(release.period_of_report)
            except ValueError:
                reasons.append(f"unparseable period_of_report: {release.period_of_report}")
            else:
                is_quarter_end = (por.month, por.day) in {(3, 31), (6, 30), (9, 30), (12, 31)}
                if is_quarter_end:
                    try:
                        fq_por = fiscal_quarter_from_period_end(por)
                        if fq_por != fq:
                            reasons.append(
                                f"period_of_report {release.period_of_report} maps to "
                                f"{fq_por.label()} but release date maps to {fq.label()}"
                            )
                            fq = fq_por  # prefer period_of_report when it is a quarter-end
                    except ValueError as exc:
                        reasons.append(f"unrecognized period_of_report: {exc}")
                # else: event-date reportDate on 8-K — ignore for quarter mapping

        key = (fq.year, fq.quarter)
        if key in quarter_to_release:
            duplicate_notes.setdefault(key, []).append(release.accession)
            continue
        quarter_to_release[key] = release
        mapped.append((fq, release, reasons))

    # Restrict to FY2017Q1 .. FY2026Q3
    mapped = [(fq, rel, rs) for fq, rel, rs in mapped if FiscalQuarter(2017, 1).year <= fq.year <= 2026]
    mapped = [
        (fq, rel, rs)
        for fq, rel, rs in mapped
        if (fq.year > 2017 or fq.quarter >= 1) and (fq.year < 2026 or fq.quarter <= 3)
    ]
    mapped.sort(key=lambda t: (t[0].year, t[0].quarter))

    rows: list[dict[str, Any]] = []
    for fq, release, base_reasons in mapped:
        cutoff = _parse_utc(release.accepted_utc)
        target = fq.next()
        reasons = list(base_reasons)

        # Target release
        target_key = (target.year, target.quarter)
        target_release = quarter_to_release.get(target_key)
        target_acc = target_release.accession if target_release else ""
        target_accepted = target_release.accepted_utc if target_release else ""

        # Origin window / status
        if fq.year == 2026 and fq.quarter == 3:
            origin_window = "prospective"
            status = "prospective"
        elif FiscalQuarter(2024, 1).year <= fq.year and (fq.year < 2026 or (fq.year == 2026 and fq.quarter <= 2)):
            origin_window = "primary"
            status = "candidate" if target_release else "excluded"
            if not target_release:
                reasons.append("no realized target-quarter release")
        elif fq.year in {2022, 2023}:
            origin_window = "extension"
            status = "candidate" if target_release else "excluded"
            if not target_release:
                reasons.append("no realized target-quarter release")
        elif 2017 <= fq.year <= 2023:
            origin_window = "none"
            status = "calibration_only"
        else:
            origin_window = "none"
            status = "excluded"
            reasons.append("outside FY2017–FY2026 inventory window")

        is_calibration = 2017 <= fq.year <= 2023
        pandemic_flag = fq.year in {2020, 2021}

        # Same-quarter 10-Q / 10-K (period matches fq.period_end)
        period_end_str = fq.period_end.isoformat()
        same_q = next(
            (f for f in visa_10qs if f.period_of_report == period_end_str and not f.is_amendment),
            None,
        )
        # Prefer non-amendment; fall back to any
        if same_q is None:
            same_q = next((f for f in visa_10qs if f.period_of_report == period_end_str), None)

        same_q_form = same_q.form if same_q else ""
        same_q_acc = same_q.accession if same_q else ""
        same_q_accepted = same_q.accepted_utc if same_q else ""
        same_q_hours = ""
        same_q_eligible = False
        if same_q:
            same_accepted_dt = _parse_utc(same_q.accepted_utc)
            same_q_eligible = is_eligible(same_accepted_dt, cutoff)
            delta = same_accepted_dt - cutoff
            same_q_hours = f"{delta.total_seconds() / 3600:.2f}"

        # Prior quarter 10-Q / 10-K
        prior_fq = FiscalQuarter(fq.year - 1, 4) if fq.quarter == 1 else FiscalQuarter(fq.year, fq.quarter - 1)
        prior_period = prior_fq.period_end.isoformat()
        prior_10q = next(
            (f for f in visa_10qs if f.period_of_report == prior_period and not f.is_amendment),
            None,
        )
        if prior_10q is None:
            prior_10q = next((f for f in visa_10qs if f.period_of_report == prior_period), None)

        prior_form = prior_10q.form if prior_10q else ""
        prior_acc = prior_10q.accession if prior_10q else ""
        prior_accepted = prior_10q.accepted_utc if prior_10q else ""
        prior_eligible = False
        if prior_10q:
            prior_eligible = is_eligible(_parse_utc(prior_10q.accepted_utc), cutoff)
        else:
            reasons.append(f"missing prior-quarter 10-Q/10-K for period {prior_period}")
            if status == "candidate":
                status = "excluded"

        # Booking: latest earnings 8-K with acceptance ≤ cutoff
        booking_hit = None
        for b in reversed(booking_earnings):
            if is_eligible(_parse_utc(b.accepted_utc), cutoff):
                booking_hit = b
                break
        booking_acc = booking_hit.accession if booking_hit else ""
        booking_accepted = booking_hit.accepted_utc if booking_hit else ""
        booking_age = ""
        booking_age_weeks = ""
        booking_eligible = booking_hit is not None
        booking_same_day = ""
        booking_margin_seconds = ""
        booking_guidance_covers_target = ""
        booking_fallback_accession = ""
        if booking_hit:
            booking_dt = _parse_utc(booking_hit.accepted_utc)
            age = cutoff - booking_dt
            age_seconds = age.total_seconds()
            booking_age = f"{age_seconds / 86400:.1f}"
            booking_age_weeks = f"{age_seconds / 86400 / 7:.4f}"
            cutoff_et_date = cutoff.astimezone(EASTERN).date()
            booking_et_date = booking_dt.astimezone(EASTERN).date()
            same_day = cutoff_et_date == booking_et_date
            booking_same_day = str(same_day).lower()
            if same_day:
                booking_margin_seconds = str(int(age_seconds))
                try:
                    idx = booking_accessions_ordered.index(booking_hit.accession)
                except ValueError:
                    idx = -1
                if idx > 0:
                    booking_fallback_accession = booking_accessions_ordered[idx - 1]
            cal_row = booking_cal_by_acc.get(booking_hit.accession)
            if cal_row is None:
                booking_guidance_covers_target = "unknown"
            else:
                booking_guidance_covers_target = guidance_covers_target(
                    cal_row.get("guidance_quarter", ""),
                    target.year,
                    target.quarter,
                )
        else:
            reasons.append("no Booking earnings 8-K accepted ≤ cutoff")

        # Census: newest MARTS advance release with publication_ts ≤ cutoff (LON-5).
        # Lazy import avoids a circular dependency with census_sources.
        from longaeva_app.collect.census_sources import latest_release_at_or_before

        census_hit = latest_release_at_or_before(release.accepted_utc)
        if census_hit is not None:
            census_release = census_hit["release_id"]
            census_ref = census_hit["reference_month"]
            census_pub = census_hit["publication_ts"]
            census_age = f"{(cutoff - _parse_utc(census_pub)).total_seconds() / 86400:.1f}"
            census_status = "eligible"
        else:
            census_release = ""
            census_ref = ""
            census_pub = ""
            census_age = ""
            census_status = "unavailable"
            reasons.append("no Census MARTS advance release published ≤ cutoff")

        # Duplicate notes
        dup_key = (fq.year, fq.quarter)
        if dup_key in duplicate_notes:
            reasons.append("duplicate Item 2.02 8-K(s) for quarter ignored: " + ",".join(duplicate_notes[dup_key]))

        if status == "excluded" and not reasons:
            reasons.append("excluded without detailed reason")

        rows.append(
            {
                "fiscal_year": fq.year,
                "fiscal_quarter": fq.quarter,
                "period_end": period_end_str,
                "release_accession": release.accession,
                "cutoff_utc": release.accepted_utc,
                "cutoff_et": format_et(cutoff),
                "target_fiscal_year": target.year,
                "target_fiscal_quarter": target.quarter,
                "target_release_accession": target_acc,
                "target_release_accepted_utc": target_accepted,
                "is_calibration": str(is_calibration).lower(),
                "origin_window": origin_window,
                "pandemic_flag": str(pandemic_flag).lower(),
                "prior_10q_form": prior_form,
                "prior_10q_accession": prior_acc,
                "prior_10q_accepted_utc": prior_accepted,
                "prior_10q_eligible": str(prior_eligible).lower(),
                "same_q_10q_form": same_q_form,
                "same_q_10q_accession": same_q_acc,
                "same_q_10q_accepted_utc": same_q_accepted,
                "same_q_10q_hours_after_cutoff": same_q_hours,
                "same_q_10q_eligible": str(same_q_eligible).lower(),
                "booking_accession": booking_acc,
                "booking_accepted_utc": booking_accepted,
                "booking_age_days": booking_age,
                "booking_age_weeks": booking_age_weeks,
                "booking_eligible": str(booking_eligible).lower(),
                "booking_same_day": booking_same_day,
                "booking_margin_seconds": booking_margin_seconds,
                "booking_guidance_covers_target": booking_guidance_covers_target,
                "booking_fallback_accession": booking_fallback_accession,
                "census_release": census_release,
                "census_reference_month": census_ref,
                "census_publication_utc": census_pub,
                "census_age_days": census_age,
                "census_status": census_status,
                "status": status,
                "exclusion_reasons": "; ".join(reasons),
            }
        )
    return rows


def write_origins_csv(rows: list[dict[str, Any]], path: Path = ORIGINS_CSV_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})


def _amendment_summary(snapshot: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    visa = [filing_from_dict(r) for r in snapshot["visa_filings"]]
    earnings_amends = [f for f in visa if is_earnings_8k(f) and f.is_amendment]
    if earnings_amends:
        lines.append(
            f"- Item 2.02 8-K/A filings in window: {len(earnings_amends)} "
            f"({', '.join(f.accession for f in earnings_amends)})"
        )
    else:
        lines.append("- No Item 2.02 8-K/A amendments in the inventory window.")
    # Non-earnings Item 2.02? Unusual; check 8-K with 2.02 that we skipped for other reasons
    return lines


def render_inventory_md(snapshot: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    retrieved = snapshot.get("retrieved_at_utc", "")
    spot = snapshot.get("spot_checks", [])

    calibration = [r for r in rows if r["is_calibration"] == "true"]
    calibration_with_ts = [r for r in calibration if r["cutoff_utc"]]
    candidates = [r for r in rows if r["status"] == "candidate"]
    # FY2022–FY2026 window rows (18 expected candidates + 1 prospective = 19)
    window_rows = [
        r
        for r in rows
        if (int(r["fiscal_year"]) > 2022 or (int(r["fiscal_year"]) == 2022))
        and (int(r["fiscal_year"]) < 2026 or (int(r["fiscal_year"]) == 2026 and int(r["fiscal_quarter"]) <= 3))
    ]
    prospective = [r for r in rows if r["status"] == "prospective"]
    excluded = [r for r in rows if r["status"] == "excluded"]

    lines: list[str] = []
    lines.append("# Visa eligible-origin and vintage inventory")
    lines.append("")
    lines.append(
        f"Generated for LON-1 · snapshot retrieved `{retrieved}` · cutoff convention: EDGAR acceptance timestamp of Visa's quarter-q earnings 8-K (data plan §2.3)."
    )
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        "- Sources: SEC EDGAR `submissions` JSON for Visa (CIK 1403161) and Booking Holdings (CIK 1075531), including older `submissions-00N.json` pages when present."
    )
    lines.append(
        "- A contact User-Agent was declared for all live requests (value not recorded here). Rate ≤ 2 requests/s."
    )
    lines.append(
        "- Documents are eligible for an origin only when `acceptance_ts ≤ cutoff_ts` (timezone-aware UTC comparison)."
    )
    lines.append(
        "- Fiscal quarters: Visa FY ends 30 September. Release dates map to the latest quarter-end before the release; cross-checked against `period_of_report` when present."
    )
    lines.append(
        "- Census MARTS timing uses the LON-5 release calendar (`data/fixtures/census/release_calendar.csv`): newest advance PDF with printed `publication_ts` ≤ cutoff."
    )
    lines.append("")
    lines.append("## Counts (exact; not rounded up)")
    lines.append("")
    lines.append(f"- Inventory rows (FY2017Q1–FY2026Q3): **{len(rows)}**")
    lines.append(f"- Calibration quarters (FY2017–FY2023) with timestamps: **{len(calibration_with_ts)}**")
    lines.append(f"- FY2022–FY2026 window rows (incl. prospective): **{len(window_rows)}**")
    lines.append(f"- Candidate origins (timestamp checks pass; realized target quarter): **{len(candidates)}**")
    lines.append(f"- Prospective origins: **{len(prospective)}**")
    if prospective:
        p = prospective[0]
        lines.append(
            f"  - `{p['cutoff_utc'][:10]}` release → target FY{p['target_fiscal_year']}Q{p['target_fiscal_quarter']} "
            f"(accession `{p['release_accession']}`)"
        )
    lines.append(f"- Excluded rows: **{len(excluded)}**")
    census_eligible = sum(1 for r in rows if r.get("census_status") == "eligible")
    lines.append(f"- Census-eligible origins (advance release ≤ cutoff): **{census_eligible}**")
    lines.append("")
    lines.append(
        "These counts reflect EDGAR timestamp, prior-10-Q availability and Census release timing. "
        "Definition stability (LON-2) and starting-state reconstruction (LON-3) are settled separately and did not lower the count."
    )
    lines.append("")
    lines.append("## Exclusion reasons")
    lines.append("")
    if not excluded:
        lines.append("- None at the timestamp/prior-10-Q layer.")
    else:
        for r in excluded:
            lines.append(
                f"- FY{r['fiscal_year']}Q{r['fiscal_quarter']} (`{r['release_accession']}`): {r['exclusion_reasons'] or '(no reason recorded)'}"
            )
    lines.append("")
    lines.append("## Same-quarter 10-Q / 10-K lag vs cutoff")
    lines.append("")
    lines.append("| Origin | Same-quarter form | Hours after cutoff | Eligible at cutoff |")
    lines.append("| --- | --- | --- | --- |")
    for r in rows:
        if r["origin_window"] not in {"primary", "extension", "prospective"} and r["status"] != "calibration_only":
            continue
        if not r["same_q_10q_accession"]:
            continue
        # Show origin-window and a sample of calibration
        if r["status"] in {"candidate", "prospective"} or (
            r["is_calibration"] == "true" and int(r["fiscal_year"]) >= 2022
        ):
            lines.append(
                f"| FY{r['fiscal_year']}Q{r['fiscal_quarter']} | {r['same_q_10q_form']} | "
                f"{r['same_q_10q_hours_after_cutoff']} | {r['same_q_10q_eligible']} |"
            )
    lines.append("")
    lines.append(
        "Under the §2.3 cutoff convention the same-quarter 10-Q is typically accepted hours after the earnings 8-K and is therefore **not** eligible as an input for that origin. LON-3 should use the prior-quarter 10-Q for nominal payments-volume levels."
    )
    lines.append("")
    lines.append("## Booking release age at Visa cutoffs")
    lines.append("")
    lines.append(
        "| Origin | Booking accession | Age (days) | Age (weeks) | Same-day | "
        "Margin (s) | Guidance covers target | Fallback | Eligible |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in candidates + prospective:
        lines.append(
            f"| FY{r['fiscal_year']}Q{r['fiscal_quarter']} | `{r['booking_accession']}` | "
            f"{r['booking_age_days']} | {r.get('booking_age_weeks', '')} | "
            f"{r.get('booking_same_day', '')} | {r.get('booking_margin_seconds', '')} | "
            f"{r.get('booking_guidance_covers_target', '')} | "
            f"`{r.get('booking_fallback_accession', '')}` | {r['booking_eligible']} |"
        )
    lines.append("")
    lines.append(
        "Age is from Booking's EDGAR acceptance to the Visa cutoff. "
        "`same_day` is true when both accepted timestamps fall on the same US/Eastern calendar date. "
        "Since April 2025 four candidate origins are same-day (Booking accepted 71–233 seconds earlier); "
        "the evaluation should also report a variant that falls back to `booking_fallback_accession`. "
        "`guidance_covers_target` is true only when the Ex. 99.1 outlook table's next quarter equals "
        "Visa's target quarter mapped to a calendar quarter (see `docs/gates/booking.md`). "
        "Ex. 99.1 guidance tables begin with the 2025-07-29 release."
    )
    lines.append("")
    lines.append("## Census release age at Visa cutoffs")
    lines.append("")
    lines.append("| Origin | Census release | Reference month | Age (days) | Status |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in candidates + prospective:
        lines.append(
            f"| FY{r['fiscal_year']}Q{r['fiscal_quarter']} | `{r.get('census_release', '')}` | "
            f"{r.get('census_reference_month', '')} | {r.get('census_age_days', '')} | "
            f"{r.get('census_status', '')} |"
        )
    lines.append("")
    lines.append(
        "Ages are days from the printed MARTS release timestamp to the Visa earnings 8-K cutoff. "
        "The 2025 federal shutdown delayed `adv2509` to 2025-11-25, so the 2025-10-28 Visa origin uses `adv2508`. "
        "The 2018–2019 shutdown delayed `adv1812`/`adv1901`; see `docs/gates/census.md`."
    )
    lines.append("")
    lines.append("## Amendment scan")
    lines.append("")
    lines.extend(_amendment_summary(snapshot))
    # Non-earnings 8-K with other items — note Item 2.02 count vs earnings kept
    visa = [filing_from_dict(r) for r in snapshot["visa_filings"]]
    item_202 = [f for f in visa if is_earnings_8k(f)]
    earnings_kept = [f for f in item_202 if f.form == "8-K"]
    lines.append(f"- Item 2.02 8-K filings kept as earnings releases in snapshot: {len(earnings_kept)}")
    lines.append("")
    lines.append("## Spot-check: submissions acceptance vs filing index page")
    lines.append("")
    lines.append(
        "Five earnings 8-K timestamps were compared to the `Accepted` field on the EDGAR filing index page (Eastern wall-clock). Agreement confirms that submissions `acceptanceDateTime` is Eastern time."
    )
    lines.append("")
    lines.append("| Accession | Filed | Submissions UTC | Index page (ET) | Index → UTC | Match |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for s in spot:
        lines.append(
            f"| `{s['accession']}` | {s['filed_date']} | `{s['submissions_accepted_utc']}` | "
            f"`{s.get('index_page_accepted_et') or ''}` | `{s.get('index_page_accepted_utc') or ''}` | "
            f"{'yes' if s.get('match') else 'NO'} |"
        )
    lines.append("")
    lines.append("## Pending checks (can only lower the count)")
    lines.append("")
    lines.append("- LON-2: Visa driver and accounting definition stability across the window. **Done — 0 exclusions.**")
    lines.append(
        "- LON-3: reconstructable starting state from release + prior 10-Q under the cutoff convention. "
        "**Done — complete with eligible-family inputs; 0 exclusions. See `docs/gates/starting-states.md`.**"
    )
    lines.append(
        "- LON-5: Census MARTS vintage timing relative to each Visa cutoff. "
        "**Done — every inventory origin has a Census advance release ≤ cutoff; "
        "0 exclusions from timing. See `docs/gates/census.md`.**"
    )
    lines.append(
        "- LON-4: Booking Holdings family gate (measured + qualitative/guidance passages, "
        "staleness in weeks, same-day margin). "
        "**Done — required family with lagged measured rules and guidance only where it "
        "covers the Visa target quarter; same-day fallback variant required. "
        "See `docs/gates/booking.md`.**"
    )
    lines.append(
        "- LON-7: Visa IR guidance availability (earnings deck / transcript outlook) and "
        "analyst-estimate confirmation. **Done — guidance is a comparison baseline only "
        "(never a model input), so gaps do not change origin eligibility. 16/19 origins "
        "have next-quarter company guidance; consensus unavailable (no licensed free "
        "historical source). See `docs/gates/guidance.md`.**"
    )
    lines.append(
        "- LON-8: Second-wave disclosure families (one airline, one retailer, one pure "
        "payment processor). **Done — context-first families; selection and timing live "
        "in `docs/gates/second-wave.md` and do not change origin eligibility.**"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_inventory_md(snapshot: dict[str, Any], rows: list[dict[str, Any]], path: Path = INVENTORY_MD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_inventory_md(snapshot, rows), encoding="utf-8")


def cmd_fetch(args: argparse.Namespace) -> int:
    user_agent = _load_env_user_agent()
    client = EdgarClient(user_agent)
    snapshot = fetch_snapshot(client)
    mismatches = [s for s in snapshot["spot_checks"] if not s.get("match")]
    if mismatches:
        print("WARNING: spot-check mismatches:", file=sys.stderr)
        for m in mismatches:
            print(f"  {m}", file=sys.stderr)
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {SNAPSHOT_PATH}")
    print(f"Visa filings: {len(snapshot['visa_filings'])}")
    print(f"Booking filings: {len(snapshot['booking_filings'])}")
    print(f"Spot checks: {len(snapshot['spot_checks'])} (mismatches={len(mismatches)})")
    return 0 if not mismatches else 1


def cmd_build(args: argparse.Namespace) -> int:
    snapshot = load_snapshot(Path(args.snapshot) if args.snapshot else SNAPSHOT_PATH)
    rows = build_origins(snapshot)
    out_csv = Path(args.origins_csv) if args.origins_csv else ORIGINS_CSV_PATH
    out_md = Path(args.inventory_md) if args.inventory_md else INVENTORY_MD_PATH
    write_origins_csv(rows, out_csv)
    write_inventory_md(snapshot, rows, out_md)
    candidates = sum(1 for r in rows if r["status"] == "candidate")
    calibration = sum(1 for r in rows if r["is_calibration"] == "true" and r["cutoff_utc"])
    prospective = sum(1 for r in rows if r["status"] == "prospective")
    window = [
        r
        for r in rows
        if int(r["fiscal_year"]) >= 2022 and (int(r["fiscal_year"]) < 2026 or int(r["fiscal_quarter"]) <= 3)
    ]
    print(f"Wrote {out_csv} ({len(rows)} rows)")
    print(f"Wrote {out_md}")
    print(
        f"candidates={candidates} calibration_with_ts={calibration} prospective={prospective} window_rows={len(window)}"
    )
    ok = len(window) >= 18 and calibration >= 28 and prospective >= 1
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch EDGAR submissions and write filing_index.json")
    fetch_p.set_defaults(func=cmd_fetch)

    build_p = sub.add_parser("build", help="Build origins.csv and inventory note from snapshot")
    build_p.add_argument("--snapshot", default=None)
    build_p.add_argument("--origins-csv", default=None)
    build_p.add_argument("--inventory-md", default=None)
    build_p.set_defaults(func=cmd_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
