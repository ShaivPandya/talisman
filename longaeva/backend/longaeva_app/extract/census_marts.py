"""Census MARTS advance-release PDF parser (Census evidence gate; Census vintage parser extends).

Parses archived ``advYYMM.pdf`` files into long-format observation rows with
publication timestamps, SA/NSA flags, and estimate-status tags.
"""

from __future__ import annotations

import csv
import io
import re
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pdfplumber

# Dot leaders and Unicode minus variants used in MARTS PDFs.
_DOT_LEADERS = re.compile(r"[.…·•]+")
_MINUS_CHARS = str.maketrans({"\u2212": "-", "\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-"})

_RELEASE_LINE = re.compile(
    r"FOR RELEASE AT\s+(\d{1,2}:\d{2})\s*(AM|PM)\s+(EDT|EST|CDT|CST|MDT|MST|PDT|PST),\s+"
    r"(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+"
    r"([A-Z]+)\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)
# Pre-2017 layout: "FOR IMMEDIATE RELEASE\nWEDNESDAY, DECEMBER 14, 2016, AT 8:30 A.M. EST"
_RELEASE_LINE_LEGACY = re.compile(
    r"FOR IMMEDIATE RELEASE\s+"
    r"(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+"
    r"([A-Z]+)\s+(\d{1,2}),\s+(\d{4}),\s+AT\s+(\d{1,2}:\d{2})\s*([AP]\.?M\.?)\s+"
    r"(EDT|EST|CDT|CST|MDT|MST|PDT|PST)",
    re.IGNORECASE | re.DOTALL,
)
_RELEASE_NUMBER = re.compile(
    r"Release Number:\s*(CB\d{2}[\-‐‑‒–—]\d+)|(?:^|\s)(CB\d{2}[\-‐‑‒–—]\d+)(?:\s|$)", re.IGNORECASE | re.MULTILINE
)
_TITLE_MONTH = re.compile(
    r"ADVANCE MONTHLY SALES FOR RETAIL AND FOOD SERVICES(?:,\s*|\s+)([A-Z]+)\s+(\d{4})",
    re.IGNORECASE,
)
_HEADLINE_BILLIONS = re.compile(
    r"were\s+\$([0-9]+(?:\.[0-9]+)?)\s+billion",
    re.IGNORECASE,
)
_HEADLINE_MOM = re.compile(
    r"(?:up|down|virtually unchanged)\s+(?:\([^\)]*\)\s+)?"
    r"(?:from the previous month|"
    r"(\d+\.\d+)\s+percent[^\.]{0,80}from the previous month|"
    r"virtually unchanged)",
    re.IGNORECASE,
)

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_ABBREV = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Stable series keys for common aggregate / kind-of-business lines.
_SERIES_ALIASES: dict[str, str] = {
    "retail & food services, total": "retail_food_services_total",
    "retail and food services, total": "retail_food_services_total",
    "total (excl. motor vehicle & parts)": "total_ex_motor",
    "total (excl. gasoline stations)": "total_ex_gas",
    "total (excl. motor vehicle & parts & gasoline stations)": "total_ex_motor_gas",
    "retail": "retail_total",
    "gafo": "gafo",
    "motor vehicle & parts dealers": "naics_441",
    "auto & other motor veh. dealers": "naics_4411_4412",
    "new car dealers": "naics_44111",
    "auto parts, acc. & tire stores": "naics_4413",
    "furniture & home furn. stores": "naics_442",
    "furniture stores": "naics_4421",
    "home furnishings stores": "naics_4422",
    "electronics & appliance stores": "naics_443",
    "building material & garden eq. & supplies dealers": "naics_444",
    "building mat. & sup. dealers": "naics_4441",
    "food & beverage stores": "naics_445",
    "grocery stores": "naics_4451",
    "beer, wine & liquor stores": "naics_4453",
    "health & personal care stores": "naics_446",
    "pharmacies & drug stores": "naics_44611",
    "gasoline stations": "naics_447",
    "clothing & clothing accessories stores": "naics_448",
    "men's clothing stores": "naics_44811",
    "women's clothing stores": "naics_44812",
    "family clothing stores": "naics_44814",
    "shoe stores": "naics_4482",
    "sporting goods, hobby, musical instrument, & book stores": "naics_451",
    "general merchandise stores": "naics_452",
    "department stores": "naics_452_dept",  # code changed 4521 → 4522
    "other general merch. stores": "naics_452_other_legacy",  # 4529 (2024)
    "gen. merchandise stores incl. warehouse clubs & supercenters": "naics_4523",
    "warehouse clubs & supercenters": "naics_452_warehouse",
    "all oth. gen. merch. stores": "naics_452_all_other",
    "miscellaneous store retailers": "naics_453",
    "nonstore retailers": "naics_454",
    "elect. shopping & m/o houses": "naics_4541",
    "food services & drinking places": "naics_722",
}

CSV_COLUMNS = [
    "release_id",
    "release_number",
    "publication_ts",
    "reference_month",
    "table",
    "series_key",
    "naics_code",
    "kind_of_business",
    "measure",
    "basis",
    "period_start",
    "period_end",
    "base_period_start",
    "base_period_end",
    "estimate_status",
    "value",
    "value_flag",
    "unit",
    "geography",
    "page",
]

# Table 1 value-slot descriptors relative to the reference month.
# (measure, basis, month_offset, year_offset, estimate_status, unit)
_TABLE1_SLOTS: tuple[tuple[str, str, int, int, str, str], ...] = (
    ("ytd_level", "nsa", 0, 0, "ytd", "usd_millions"),  # special: YTD through ref
    ("ytd_pct_chg", "nsa", 0, 0, "ytd", "pct"),
    ("level", "nsa", 0, 0, "advance", "usd_millions"),
    ("level", "nsa", -1, 0, "preliminary", "usd_millions"),
    ("level", "nsa", -2, 0, "revised", "usd_millions"),
    ("level", "nsa", 0, -1, "year_ago", "usd_millions"),
    ("level", "nsa", -1, -1, "year_ago", "usd_millions"),
    ("level", "sa", 0, 0, "advance", "usd_millions"),
    ("level", "sa", -1, 0, "preliminary", "usd_millions"),
    ("level", "sa", -2, 0, "revised", "usd_millions"),
    ("level", "sa", 0, -1, "year_ago", "usd_millions"),
    ("level", "sa", -1, -1, "year_ago", "usd_millions"),
)

# Table 2 percent-change slots.
# (measure, month_offset_end, year_offset_end, base_month_offset, base_year_offset, estimate_status)
_TABLE2_SLOTS: tuple[tuple[str, int, int, int, int, str], ...] = (
    ("mom_pct", 0, 0, -1, 0, "advance"),
    ("yoy_pct", 0, 0, 0, -1, "advance"),
    ("mom_pct", -1, 0, -2, 0, "preliminary"),
    ("yoy_pct", -1, 0, -1, -1, "preliminary"),
    ("qoq_pct", 0, 0, -3, 0, "three_month"),  # latest 3m vs prior 3m
    ("yoy_3m_pct", 0, 0, 0, -1, "three_month"),  # latest 3m vs same 3m yo
)


@dataclass(frozen=True)
class ReleaseMeta:
    """Metadata from page 1 of an advance MARTS PDF."""

    release_id: str
    release_number: str
    publication_ts: str  # ISO-8601 Z
    reference_month: str  # YYYY-MM
    headline_billions: float | None
    page_count: int
    pdf_creation_date: str | None
    pdf_mod_date: str | None


@dataclass(frozen=True)
class ObservationRow:
    """One long-format observation from a MARTS table."""

    release_id: str
    release_number: str
    publication_ts: str
    reference_month: str
    table: str
    series_key: str
    naics_code: str
    kind_of_business: str
    measure: str
    basis: str
    period_start: str
    period_end: str
    base_period_start: str
    base_period_end: str
    estimate_status: str
    value: str
    value_flag: str
    unit: str
    geography: str
    page: int


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift a calendar month by ``delta`` months."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Inclusive start/end dates for a calendar month."""
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def ytd_bounds(year: int, month: int) -> tuple[date, date]:
    """Year-to-date through ``month`` of ``year``."""
    return date(year, 1, 1), date(year, month, monthrange(year, month)[1])


def three_month_bounds(year: int, month: int) -> tuple[date, date]:
    """Three-month window ending in ``month`` of ``year``."""
    start_y, start_m = shift_month(year, month, -2)
    _, end = month_bounds(year, month)
    start, _ = month_bounds(start_y, start_m)
    return start, end


def parse_release_line(text: str) -> datetime:
    """Parse the page-1 release line into a timezone-aware UTC datetime."""
    match = _RELEASE_LINE.search(text)
    if match:
        clock, ampm, tz_name, month_name, day_s, year_s = match.groups()
    else:
        legacy = _RELEASE_LINE_LEGACY.search(text)
        if not legacy:
            raise ValueError(f"release line not found in: {text[:200]!r}")
        month_name, day_s, year_s, clock, ampm, tz_name = legacy.groups()
    hour, minute = (int(x) for x in clock.split(":"))
    ampm_u = ampm.upper().replace(".", "")
    if ampm_u == "PM" and hour != 12:
        hour += 12
    if ampm_u == "AM" and hour == 12:
        hour = 0
    month = _MONTH_NAMES.get(month_name.lower())
    if month is None:
        raise ValueError(f"unknown month name in release line: {month_name!r}")
    # Fixed US offsets used by Census on the printed line (no DST table needed).
    offsets = {
        "EDT": -4,
        "EST": -5,
        "CDT": -5,
        "CST": -6,
        "MDT": -6,
        "MST": -7,
        "PDT": -7,
        "PST": -8,
    }
    offset_h = offsets[tz_name.upper()]
    local_naive = datetime(int(year_s), month, int(day_s), hour, minute)
    utc_dt = local_naive - timedelta(hours=offset_h)
    return utc_dt.replace(tzinfo=UTC)


def parse_reference_month(text: str) -> str:
    """Return ``YYYY-MM`` for the reference month in the title line."""
    match = _TITLE_MONTH.search(text)
    if not match:
        raise ValueError("title month not found")
    month = _MONTH_NAMES.get(match.group(1).lower())
    if month is None:
        raise ValueError(f"unknown title month: {match.group(1)!r}")
    return f"{int(match.group(2)):04d}-{month:02d}"


def parse_release_number(text: str) -> str:
    match = _RELEASE_NUMBER.search(text)
    if not match:
        raise ValueError("release number not found")
    raw = match.group(1) or match.group(2)
    return re.sub(r"[\-‐‑‒–—]", "-", raw).upper()


def parse_headline_billions(text: str) -> float | None:
    match = _HEADLINE_BILLIONS.search(text)
    if not match:
        return None
    return float(match.group(1))


def release_id_from_reference(reference_month: str) -> str:
    """Map ``YYYY-MM`` → ``advYYMM``."""
    year_s, month_s = reference_month.split("-")
    return f"adv{year_s[2:]}{month_s}"


def _pdf_date_to_iso(raw: str | None) -> str | None:
    """Convert a PDF ``D:YYYYMMDDHHmmSS…`` date to ISO-8601 Z when possible."""
    if not raw:
        return None
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})([+\-Z].*)?", raw)
    if not m:
        return raw
    year, month, day, hour, minute, second, tz = m.groups()
    base = f"{year}-{month}-{day}T{hour}:{minute}:{second}"
    if not tz or tz == "Z":
        return base + "Z"
    # e.g. -04'00'
    tz_clean = tz.replace("'", "")
    if len(tz_clean) >= 3 and tz_clean[0] in "+-":
        sign = tz_clean[0]
        hh = tz_clean[1:3]
        mm = tz_clean[3:5] if len(tz_clean) >= 5 else "00"
        # Convert to UTC
        local = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
        offset = timedelta(hours=int(hh), minutes=int(mm))
        utc = local - offset if sign == "+" else local + offset
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return base + "Z"


def open_pdf(source: Path | bytes) -> Any:
    if isinstance(source, Path):
        return pdfplumber.open(source)
    return pdfplumber.open(io.BytesIO(source))


def extract_page_texts(source: Path | bytes) -> tuple[list[str], dict[str, Any]]:
    """Return per-page text and PDF metadata."""
    with open_pdf(source) as pdf:
        texts = [(page.extract_text() or "") for page in pdf.pages]
        meta = dict(pdf.metadata or {})
        return texts, meta


def parse_release_meta(source: Path | bytes, *, release_id: str | None = None) -> ReleaseMeta:
    """Parse page-1 metadata from a MARTS advance PDF."""
    texts, meta = extract_page_texts(source)
    if not texts:
        raise ValueError("PDF has no pages")
    page1 = texts[0]
    publication = parse_release_line(page1)
    reference_month = parse_reference_month(page1)
    rid = release_id or release_id_from_reference(reference_month)
    return ReleaseMeta(
        release_id=rid,
        release_number=parse_release_number(page1),
        publication_ts=publication.strftime("%Y-%m-%dT%H:%M:%SZ"),
        reference_month=reference_month,
        headline_billions=parse_headline_billions(page1),
        page_count=len(texts),
        pdf_creation_date=_pdf_date_to_iso(meta.get("CreationDate")),
        pdf_mod_date=_pdf_date_to_iso(meta.get("ModDate")),
    )


def normalize_label(raw: str) -> str:
    """Strip leaders/whitespace and lowercase for series-key lookup."""
    text = raw.translate(_MINUS_CHARS)
    text = _DOT_LEADERS.sub(" ", text)
    # Collapse punctuation noise from PDF leaders / ellipses mid-label.
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w\s,()/.-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"(\D)\d+$", r"\1", text).strip()
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text


def naics_era_from_rows(rows: list[ObservationRow]) -> str:
    """Department-store NAICS printed in this release (4521 before the 2025 break, else 4522)."""
    codes: set[str] = set()
    for row in rows:
        if row.naics_code not in {"4521", "4522"}:
            continue
        kind = row.kind_of_business.lower()
        if row.series_key == "naics_452_dept" or kind.startswith("department store"):
            codes.add(row.naics_code)
    if codes == {"4521"}:
        return "4521"
    if codes == {"4522"}:
        return "4522"
    if not codes:
        return "unspecified"
    return "mixed"


def _strip_label_debris(label: str) -> str:
    """Remove year-to-date digits that dot leaders left stuck to a row label."""
    text = re.sub(r"\s+", " ", label).strip(" .,&*")
    return re.sub(r"(?:\s*[\d,.*]+)+\s*$", "", text).strip(" .,&*")


def series_key_for(naics_code: str, kind_of_business: str) -> str:
    """Map NAICS + label to a stable series key."""

    def canon(text: str) -> str:
        out = normalize_label(_strip_label_debris(text)).replace("excl.", "excl")
        return re.sub(r"\s+", " ", out).strip()

    label = canon(kind_of_business)
    for alias, key in _SERIES_ALIASES.items():
        if label == canon(alias):
            return key
    if label.startswith("department stores"):
        return "naics_452_dept"
    if naics_code:
        code = re.sub(r"[^0-9,]", "", naics_code.replace(" ", ""))
        return f"naics_{code}" if code else f"label_{re.sub(r'[^a-z0-9]+', '_', label).strip('_')}"
    return f"label_{re.sub(r'[^a-z0-9]+', '_', label).strip('_')}"


def parse_cell(raw: str) -> tuple[str, str]:
    """Return ``(value, value_flag)`` where value is empty when flagged."""
    token = raw.translate(_MINUS_CHARS).strip()
    token = token.replace(",", "")
    if token in {"(*)", "(NA)", "(S)", "*", "NA", "S"}:
        flag = {
            "(*)": "unavailable",
            "(NA)": "na",
            "(S)": "suppressed",
            "*": "unavailable",
            "NA": "na",
            "S": "suppressed",
        }[token]
        return "", flag
    if token == "":
        return "", "empty"
    # Allow leading ellipsis garbage from PDF extraction (e.g. "…3,824,542").
    token = token.lstrip(".…")
    if re.fullmatch(r"-?\d+(?:\.\d+)?", token):
        return token, ""
    raise ValueError(f"unparseable cell: {raw!r}")


_VALUE_TOKEN = re.compile(r"\(\*\)|\(NA\)|\(S\)|-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?")
# Monthly levels and unavailable flags. Percents (no thousands comma) are not included.
_CLEAN_CELL = re.compile(
    r"\(\*\)|\(NA\)|\(S\)|(?<![\w.*])\*(?![\w.*])|(?<![\w.])NA(?![\w.])|(?<![\w.])S(?![\w.])|\d{1,3}(?:,\d{3})+"
)
_PERCENT_CELL = re.compile(r"-?\d+\.\d+")
_MONTH_TOKEN_STRICT = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\d*\b", re.I)
_MONTH_TOKEN_LENIENT = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|Sept|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\d*\b",
    re.I,
)


def split_label_and_values(line: str) -> tuple[str, list[str]]:
    """Split a data line into a label prefix and trailing value tokens."""
    cleaned = line.translate(_MINUS_CHARS)
    tokens = list(_VALUE_TOKEN.finditer(cleaned))
    if not tokens:
        return cleaned.strip(), []
    run: list[re.Match[str]] = []
    end = len(cleaned)
    for match in reversed(tokens):
        between = cleaned[match.end() : end]
        if between.strip() == "" or between == "":
            run.append(match)
            end = match.start()
        else:
            break
    run.reverse()
    if not run:
        return cleaned.strip(), []
    # Footnote digits glued to labels (e.g. GAFO4) can be tokenized as a leading value.
    if (
        len(run) in {7, 13}
        and re.fullmatch(r"[1-9]", run[0].group(0))
        and run[0].start() > 0
        and cleaned[run[0].start() - 1].isalnum()
    ):
        run = run[1:]
    if not run:
        return cleaned.strip(), []
    label = cleaned[: run[0].start()]
    label = _DOT_LEADERS.sub(" ", label)
    label = re.sub(r"\s+", " ", label).strip(" .")
    # Drop trailing footnote digit left on the label after absorption.
    label = re.sub(r"(\D)\d+$", r"\1", label).strip()
    values = [m.group(0) for m in run]
    return label, values


def _prepare_table_line(line: str) -> str:
    """Normalize flags that older PDFs print as ``*``, ``NA`` or ``( * )``.

    Clean lines from the gate fixtures have no bare flags, so this is a no-op
    for them and the rebuilt table text stays the same.
    """
    text = line.translate(_MINUS_CHARS)
    text = re.sub(r"\(\s*\*\s*\)", "(*)", text)
    text = re.sub(r"\(\s*N\s*A\s*\)", "(NA)", text)
    text = re.sub(r"\(\s*S\s*\)", "(S)", text)
    text = re.sub(r"\(\s*\.\s*\*\s*\.\s*\)", "(*)", text)
    text = re.sub(r"(?<!\S)\*\.(?!\S)", "(*)", text)
    text = re.sub(r"(?<!\S)\*(?!\S)", "(*)", text)
    text = re.sub(r"(?<!\S)NA(?![\w)])", "(NA)", text)
    text = re.sub(r"(?<!\S)S(?!\S)", "(S)", text)
    return text


def _normalize_leader_line(line: str) -> str:
    """Drop dot leaders and close up flags that pdf text extraction splits."""
    text = _prepare_table_line(line)
    text = _DOT_LEADERS.sub(" ", text)
    text = re.sub(r"\(\s*\*\s*\)", "(*)", text)
    text = re.sub(r"\(\s*N\s*A\s*\)", "(NA)", text)
    text = re.sub(r"\(\s*S\s*\)", "(S)", text)
    text = re.sub(r"\(\s*\.\s*\*\s*\.\s*\)", "(*)", text)
    text = re.sub(r"(?<=\d)\.,(?=\d)", ",", text)
    text = re.sub(r"(?<=\d)\s*,\s*(?=\d{3}\b)", ",", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_recovered_label(label: str) -> str:
    label = _DOT_LEADERS.sub(" ", label)
    label = re.sub(r"\s+", " ", label).strip(" .,&*")
    # Footnote digits and year-to-date fragments the leaders left on the label.
    label = re.sub(r"(?:\s*[\d,.*]+)+\s*$", "", label).strip(" .,&*")
    return label


def split_label_and_values_lenient(line: str) -> tuple[str, list[str]]:
    """Recover 12 Table 1 cells when dot leaders have split the year-to-date figure.

    The last 10 comma-grouped levels (or flags) are the monthly columns. The
    year-to-date level is the comma-grouped number before them, or the digits
    left in the leader soup. The percent change is the decimal, or a flag,
    between that level and the monthly columns.
    """
    text = _normalize_leader_line(line)
    matches = list(_CLEAN_CELL.finditer(text))
    if len(matches) < 10:
        return text, []
    monthly = matches[-10:]
    prefix = text[: monthly[0].start()]
    prefix_cells = list(_CLEAN_CELL.finditer(prefix))
    if len(prefix_cells) >= 2:
        ytd = prefix_cells[-2].group(0)
        pct = prefix_cells[-1].group(0)
        label = prefix[: prefix_cells[-2].start()]
    elif len(prefix_cells) == 1:
        ytd = prefix_cells[0].group(0)
        between = prefix[prefix_cells[0].end() :]
        pct_match = list(_PERCENT_CELL.finditer(between))
        flag_match = list(_CLEAN_CELL.finditer(between))
        if pct_match:
            pct = pct_match[-1].group(0)
        elif flag_match:
            pct = flag_match[-1].group(0)
        else:
            return text, []
        label = prefix[: prefix_cells[0].start()]
    else:
        pct_match = list(_PERCENT_CELL.finditer(prefix))
        if not pct_match:
            return text, []
        pct = pct_match[-1].group(0)
        ytd_src = prefix[: pct_match[-1].start()]
        digits = re.sub(r"\D", "", ytd_src)
        if not digits:
            return text, []
        ytd = digits
        label = re.sub(r"[\d,.\s]+$", "", ytd_src)
    values = [ytd, pct, *[match.group(0) for match in monthly]]
    if len(values) != 12:
        return text, []
    return _clean_recovered_label(label), values


def split_percent_values_lenient(line: str) -> tuple[str, list[str]]:
    """Recover the six Table 2 percent cells from a leader-joined line."""
    text = _normalize_leader_line(line)
    matches = list(re.finditer(r"\(\*\)|\(NA\)|\(S\)|(?<![\w.*])\*(?![\w.*])|-?\d+\.\d+", text))
    if len(matches) < 6:
        return text, []
    chosen = matches[-6:]
    return _clean_recovered_label(text[: chosen[0].start()]), [match.group(0) for match in chosen]


_NAICS_PREFIX = re.compile(r"^([0-9]{2,6}(?:,\s*[0-9]{2,6})*)\s+(.*)$")


def parse_naics_and_label(label: str) -> tuple[str, str]:
    """Split optional NAICS code(s) from the kind-of-business label."""
    text = re.sub(r"\s+", " ", label).strip()
    match = _NAICS_PREFIX.match(text)
    if match:
        return match.group(1).replace(" ", ""), match.group(2).strip()
    return "", text


def _month_token_to_num(token: str) -> int:
    key = re.sub(r"[^A-Za-z]", "", token).lower()[:3]
    if key not in _MONTH_ABBREV:
        raise ValueError(f"unknown month token: {token!r}")
    return _MONTH_ABBREV[key]


def validate_table1_header(header_text: str, reference_month: str) -> None:
    """Raise if Table 1 month tokens disagree with the reference month."""
    ref_y, ref_m = (int(x) for x in reference_month.split("-"))
    # Five month columns (ref, ref-1, ref-2, yo-ref, yo-ref-1), repeated for NSA and SA.
    expected_nums: list[int] = []
    for month_off, year_off in ((0, 0), (-1, 0), (-2, 0), (0, -1), (-1, -1)):
        y, m = shift_month(ref_y, ref_m, month_off)
        y += year_off
        expected_nums.append(m)
    expected_nums = expected_nums + expected_nums

    def months(pattern: re.Pattern[str], text: str) -> list[int] | None:
        tokens = pattern.findall(text)
        if len(tokens) < 10:
            return None
        return [_month_token_to_num(token) for token in tokens[:10]]

    got = months(_MONTH_TOKEN_STRICT, header_text)
    if got != expected_nums:
        # Older releases print "Sept" and the strict pattern misses it.
        header_only = header_text
        lines = header_text.splitlines()
        for index, line in enumerate(lines):
            if "(a)" in line and "(p)" in line:
                header_only = "\n".join(lines[: index + 1])
                break
        got = months(_MONTH_TOKEN_LENIENT, header_only)
    if got is None:
        raise ValueError(f"Table 1 header has fewer than 10 month tokens in: {header_text[:240]!r}")
    if got != expected_nums:
        raise ValueError(
            f"Table 1 header months {got} disagree with reference {reference_month} expected {expected_nums}"
        )


def _join_continued_labels(lines: list[str]) -> list[str]:
    """Join label-only wrap lines with the following data line.

    Lines the strict splitter already accepts (6 or 12 cells) are rebuilt, which
    is what the committed gate CSVs were generated from. Other lines keep their
    original text so a later lenient pass can recover digits the leaders split.
    """
    out: list[str] = []
    buf_label = ""
    buf_raw = ""
    for line in lines:
        stripped = _prepare_table_line(line.strip())
        if not stripped:
            continue
        label, values = split_label_and_values(stripped)
        if not values:
            buf_label = f"{buf_label} {label}".strip() if buf_label else label
            buf_raw = f"{buf_raw} {stripped}".strip() if buf_raw else stripped
            continue
        if len(values) in {6, 12}:
            full_label = f"{buf_label} {label}".strip() if buf_label else label
            out.append(f"{full_label} {' '.join(values)}")
        else:
            out.append(f"{buf_raw} {stripped}".strip() if buf_raw else stripped)
        buf_label = ""
        buf_raw = ""
    return out


def _table1_period(
    reference_month: str,
    measure: str,
    month_offset: int,
    year_offset: int,
) -> tuple[str, str, str, str]:
    ref_y, ref_m = (int(x) for x in reference_month.split("-"))
    if measure.startswith("ytd"):
        start, end = ytd_bounds(ref_y, ref_m)
        if measure == "ytd_pct_chg":
            base_start, base_end = ytd_bounds(ref_y - 1, ref_m)
            return start.isoformat(), end.isoformat(), base_start.isoformat(), base_end.isoformat()
        return start.isoformat(), end.isoformat(), "", ""
    y, m = shift_month(ref_y, ref_m, month_offset)
    y += year_offset
    start, end = month_bounds(y, m)
    return start.isoformat(), end.isoformat(), "", ""


def parse_table1_rows(
    page_text: str,
    meta: ReleaseMeta,
    *,
    page_number: int,
) -> list[ObservationRow]:
    """Parse Table 1 kind-of-business rows from a page's text."""
    validate_table1_header(page_text, meta.reference_month)
    # Isolate data lines between the status header and the footnotes.
    lines = page_text.splitlines()
    start_idx = 0
    for i, line in enumerate(lines):
        if "(a)" in line and "(p)" in line and "(r)" in line:
            start_idx = i + 1
            break
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if lines[i].startswith("(*)") or lines[i].startswith("(1)") or lines[i].startswith("Source:"):
            end_idx = i
            break
    data_lines = _join_continued_labels(lines[start_idx:end_idx])
    rows: list[ObservationRow] = []
    for line in data_lines:
        label, raw_values = split_label_and_values(line)
        if len(raw_values) != 12:
            label, raw_values = split_label_and_values_lenient(line)
        if len(raw_values) != 12:
            if len(raw_values) == 0:
                continue
            raise ValueError(f"expected 12 Table 1 values, got {len(raw_values)} for {label!r}: {raw_values}")
        naics, kind = parse_naics_and_label(label)
        kind = _strip_label_debris(kind)
        key = series_key_for(naics, kind)
        for raw, slot in zip(raw_values, _TABLE1_SLOTS, strict=True):
            measure, basis, month_off, year_off, status, unit = slot
            value, flag = parse_cell(raw)
            period_start, period_end, base_start, base_end = _table1_period(
                meta.reference_month, measure, month_off, year_off
            )
            rows.append(
                ObservationRow(
                    release_id=meta.release_id,
                    release_number=meta.release_number,
                    publication_ts=meta.publication_ts,
                    reference_month=meta.reference_month,
                    table="1",
                    series_key=key,
                    naics_code=naics,
                    kind_of_business=kind,
                    measure=measure,
                    basis=basis,
                    period_start=period_start,
                    period_end=period_end,
                    base_period_start=base_start,
                    base_period_end=base_end,
                    estimate_status=status,
                    value=value,
                    value_flag=flag,
                    unit=unit,
                    geography="US",
                    page=page_number,
                )
            )
    return rows


def parse_table2_rows(
    page_text: str,
    meta: ReleaseMeta,
    *,
    page_number: int,
) -> list[ObservationRow]:
    """Parse Table 2 percent-change rows from a page's text."""
    lines = page_text.splitlines()
    # Data starts at the first aggregate / NAICS row after the header block.
    data_start = 0
    for i, line in enumerate(lines):
        label, values = split_label_and_values(line)
        joined_probe = label
        if i > 0 and not values:
            continue
        # After joining with a prior wrap line, labels look like "Retail & food services, total"
        if values and (
            "food services" in line.lower()
            or line.lower().lstrip().startswith("total ")
            or line.lower().lstrip().startswith("retail")
            or re.match(r"^\d", line.lstrip())
        ):
            # Prefer the wrap start one line earlier when this line is a continuation.
            if i > 0 and not split_label_and_values(lines[i - 1])[1]:
                data_start = i - 1
            else:
                data_start = i
            break
        _ = joined_probe
    end_idx = len(lines)
    for i in range(data_start, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith("(p) Preliminary") or stripped.startswith("(1)") or stripped.startswith("Source:"):
            end_idx = i
            break
    data_lines = _join_continued_labels(lines[data_start:end_idx])
    ref_y, ref_m = (int(x) for x in meta.reference_month.split("-"))
    rows: list[ObservationRow] = []
    for line in data_lines:
        label, raw_values = split_label_and_values(line)
        if len(raw_values) != 6:
            label, raw_values = split_percent_values_lenient(line)
        if len(raw_values) != 6:
            if len(raw_values) == 0:
                continue
            raise ValueError(f"expected 6 Table 2 values, got {len(raw_values)} for {label!r}: {raw_values}")
        naics, kind = parse_naics_and_label(label)
        kind = _strip_label_debris(kind)
        key = series_key_for(naics, kind)
        for raw, slot in zip(raw_values, _TABLE2_SLOTS, strict=True):
            measure, m_off, y_off, bm_off, by_off, status = slot
            value, flag = parse_cell(raw)
            if measure in {"qoq_pct", "yoy_3m_pct"}:
                end_y, end_m = shift_month(ref_y, ref_m, m_off)
                end_y += y_off
                period_start_d, period_end_d = three_month_bounds(end_y, end_m)
                if measure == "qoq_pct":
                    base_end_y, base_end_m = shift_month(end_y, end_m, -3)
                    base_start_d, base_end_d = three_month_bounds(base_end_y, base_end_m)
                else:
                    base_start_d, base_end_d = three_month_bounds(end_y - 1, end_m)
            else:
                y, m = shift_month(ref_y, ref_m, m_off)
                y += y_off
                period_start_d, period_end_d = month_bounds(y, m)
                by, bm = shift_month(ref_y, ref_m, bm_off)
                by += by_off
                base_start_d, base_end_d = month_bounds(by, bm)
            rows.append(
                ObservationRow(
                    release_id=meta.release_id,
                    release_number=meta.release_number,
                    publication_ts=meta.publication_ts,
                    reference_month=meta.reference_month,
                    table="2",
                    series_key=key,
                    naics_code=naics,
                    kind_of_business=kind,
                    measure=measure,
                    basis="sa",
                    period_start=period_start_d.isoformat(),
                    period_end=period_end_d.isoformat(),
                    base_period_start=base_start_d.isoformat(),
                    base_period_end=base_end_d.isoformat(),
                    estimate_status=status,
                    value=value,
                    value_flag=flag,
                    unit="pct",
                    geography="US",
                    page=page_number,
                )
            )
    return rows


def find_table_page(texts: list[str], table_prefix: str) -> int:
    """1-based page number whose text starts with ``Table N.``.

    Some releases put a running header above the table title. Those match on a
    line, and only when no page starts with the title.
    """
    for i, text in enumerate(texts):
        if text.lstrip().startswith(table_prefix):
            return i + 1
    for i, text in enumerate(texts):
        for line in text.splitlines():
            if line.lstrip().startswith(table_prefix):
                return i + 1
    raise ValueError(f"{table_prefix} page not found")


def parse_marts_pdf(source: Path | bytes, *, release_id: str | None = None) -> tuple[ReleaseMeta, list[ObservationRow]]:
    """Parse Tables 1 and 2 from a MARTS advance PDF."""
    texts, meta_dict = extract_page_texts(source)
    meta = parse_release_meta(source, release_id=release_id)
    # Re-open avoided: parse_release_meta already opened; re-extract is fine for gate size.
    t1_page = find_table_page(texts, "Table 1.")
    t2_page = find_table_page(texts, "Table 2.")
    rows = parse_table1_rows(texts[t1_page - 1], meta, page_number=t1_page)
    rows.extend(parse_table2_rows(texts[t2_page - 1], meta, page_number=t2_page))
    return meta, rows


def write_observations_csv(rows: list[ObservationRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def read_observations_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def sa_advance_total(rows: list[ObservationRow] | list[dict[str, str]]) -> float:
    """Seasonally adjusted advance total for the reference month ($ millions)."""

    def get(row: ObservationRow | dict[str, str], key: str) -> str:
        if isinstance(row, ObservationRow):
            return str(getattr(row, key))
        return str(row[key])

    for row in rows:
        if (
            get(row, "table") == "1"
            and get(row, "series_key") == "retail_food_services_total"
            and get(row, "measure") == "level"
            and get(row, "basis") == "sa"
            and get(row, "estimate_status") == "advance"
            and get(row, "value")
        ):
            return float(get(row, "value"))
    raise KeyError("SA advance total not found")
