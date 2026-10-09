"""Visa IR guidance helpers for the guidance availability review availability gate.

Provides:

* phrase-to-range lexicon (analyst assumption) for verbal growth outlooks
* word-layout parser for earnings-deck outlook / reconciliation slides
* transcript next-quarter outlook sentence finder
* Pydantic fixture models validated against ``ObservationCreate``
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from longaeva_app.api.schemas import ObservationCreate, StatementType
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import VISA_FISCAL_CALENDAR

PACKAGE_ROOT = Path(__file__).resolve().parents[3]  # longaeva/
OBSERVATIONS_DIR = PACKAGE_ROOT / "data" / "fixtures" / "observations"
GUIDANCE_DIR = PACKAGE_ROOT / "data" / "fixtures" / "guidance"

EXTRACTOR_ID = "manual_gate"
EXTRACTOR_VERSION = "lon-7-v1"

SOURCE_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

BasisToken = Literal[
    "nominal",
    "constant_dollar",
    "gaap",
    "ex_special_items",
    "derived",
    "count",
]
GuidanceSourceKind = Literal["deck", "transcript", "none"]
OutlookType = Literal[
    "next_quarter_and_full_year",
    "full_year_only",
    "none",
    "transcript_spoken",
]

# Base verbal growth phrases → percent YoY intervals (analyst assumption).
BASE_PHRASES: dict[str, tuple[float, float]] = {
    "approximately flat": (-1.0, 1.0),
    "flat": (-1.0, 1.0),
    "low single digit": (1.0, 3.0),
    "mid single digit": (4.0, 6.0),
    "high single digit": (7.0, 9.0),
    "low double digit": (10.0, 12.0),
    "double digit": (10.0, 19.0),
    "low teens": (12.0, 14.0),
    "mid teens": (14.0, 16.0),
    "high teens": (17.0, 19.0),
    "low 20s": (20.0, 23.0),
    "mid 20s": (24.0, 26.0),
    "high 20s": (27.0, 29.0),
}

_SCALE_WORDS = ("single digit", "double digit", "teens", "20s")
_MODIFIER_ONLY = re.compile(
    r"^(?:upper\s+)?(?:low|mid|high|upper\s+mid)$",
    re.IGNORECASE,
)
_HIGH_END = re.compile(
    r"^(?:high(?:-|\s)?end\s+of|upper)\s+(.+)$",
    re.IGNORECASE,
)
_LOW_END = re.compile(
    r"^(?:low(?:-|\s)?end\s+of)\s+(.+)$",
    re.IGNORECASE,
)
_TO_SPLIT = re.compile(r"\s+to\s+", re.IGNORECASE)
_NUMERIC_CELL = re.compile(
    r"^\(?~?\s*(-?\d+(?:\.\d+)?)\s*%?\)?$",
)
_LABEL_RE = re.compile(
    r"^(Net Revenues? Growth|Operating Expense Growth|"
    r"Diluted Class A Common Stock Earnings Per Share Growth)\s*(.*)$"
)
_OUTLOOK_TITLE = re.compile(
    r"Financial Outlook for Fiscal (\w+) Quarter(?: and Fiscal Full-Year (\d{4}))?",
    re.IGNORECASE,
)
_FULL_YEAR_ONLY = re.compile(
    r"Financial Outlook for Fiscal Full-Year (\d{4})",
    re.IGNORECASE,
)
_QUARTER_WORD = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
}
# Ordered from most specific (named next quarter) to broader spoken forms.
_TRANSCRIPT_NR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:third|second|fourth|first)\s+quarter\s+net\s+revenue\s+growth\s+is\s+expected\s+to\s+be"
        r"(?:\s+in\s+the)?\s+(?P<phrase>[^.;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:reported\s+)?nominal\s+dollar\s+Q(?P<qn>[1-4])\s+net\s+revenue\s+growth\s+would\s+be"
        r"(?:\s+in\s+the)?\s+(?P<phrase>[^.;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:we\s+expect\s+)?reported\s+nominal\s+dollar\s+net\s+revenue\s+growth\s+"
        r"(?:in\s+the\s+)?(?P<phrase>(?:high|low|mid)[^.;]{0,40}(?:digit|teen)\w*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:third|second|fourth|first)\s+quarter\s+net\s+revenues?\s+could\s+grow\s+at\s+(?:the\s+)?"
        r"(?P<phrase>.+?)(?:\s+in\s+constant\s+dollars|\s+range)?(?=[.,;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"we\s+expect\s+net\s+revenues?\s+to\s+grow\s+at\s+(?:the\s+)?(?P<phrase>.+?)"
        r"(?:\s+in\s+the\s+(?:third|second|fourth|first)\s+quarter)",
        re.IGNORECASE,
    ),
    re.compile(
        r"net\s+revenue\s+growth\s+is\s+expected\s+to\s+be(?:\s+in\s+the)?\s+(?P<phrase>[^.;]+)",
        re.IGNORECASE,
    ),
)
_TRANSCRIPT_OPEX_REL = re.compile(
    r"(?:Q(?P<q>\d)\s+|In\s+the\s+(?P<qname>\w+)\s+quarter,\s+)?"
    r"non-GAAP operating expense growth(?:\s+in\s+nominal\s+dollars)?\s+is\s+expected\s+to\s+be\s+"
    r"(?P<a>\d+)\s+to\s+(?P<b>\d+)\s+points?\s+lower"
    r"(?:\s+than\s+(?:the\s+)?(?P<ref>\w+)\s+quarter)?",
    re.IGNORECASE,
)
_TRANSCRIPT_OPEX_ABS = re.compile(
    r"(?:Nominal\s+dollar\s+)?non-GAAP\s+operating\s+expense\s+growth\s+is\s+expected\s+to\s+be"
    r"(?:\s+in\s+the)?\s+(?P<phrase>[^.;]+)",
    re.IGNORECASE,
)


def source_uuid_for_url(url: str) -> UUID:
    """Deterministic UUIDv5 for a fixture source URL."""
    return uuid.uuid5(SOURCE_UUID_NAMESPACE, url)


def normalize_phrase(raw: str) -> str:
    """Lowercase, unify hyphens/spaces, drop trailing 'growth'."""
    text = raw.strip().lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+growth$", "", text)
    text = re.sub(r"\s+range$", "", text)
    # Drop leading articles / hedges that do not change the interval.
    text = re.sub(r"^(?:the\s+|an?\s+)", "", text)
    text = re.sub(r"^approximately\s+(?=flat\b)", "approximately ", text)
    # Accept plural "digits" / "teens" forms used in transcripts.
    text = re.sub(r"\bdigits\b", "digit", text)
    # "20%" / "20 %" → bare number for numeric cells / ranges.
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1", text)
    return text


def _lookup_base(norm: str) -> tuple[float, float] | None:
    if norm in BASE_PHRASES:
        return BASE_PHRASES[norm]
    # Accept "low-teens" style already normalized to "low teens".
    return None


def _half_interval(low: float, high: float, which: Literal["low", "high"]) -> tuple[float, float]:
    mid = (low + high) / 2.0
    if which == "low":
        return (low, mid)
    return (mid, high)


def _parse_atomic(norm: str) -> tuple[float, float]:
    """Parse a single (non-range) verbal phrase into a percent interval."""
    if norm in {"n/a", "na", "none", "-"}:
        raise ValueError(f"non-numeric cell: {norm!r}")
    num = _NUMERIC_CELL.match(norm.replace(" ", ""))
    if num:
        value = float(num.group(1))
        return (value, value)

    high = _HIGH_END.match(norm)
    if high:
        base = _parse_atomic(normalize_phrase(high.group(1)))
        return _half_interval(base[0], base[1], "high")
    low = _LOW_END.match(norm)
    if low:
        base = _parse_atomic(normalize_phrase(low.group(1)))
        return _half_interval(base[0], base[1], "low")

    found = _lookup_base(norm)
    if found is not None:
        return found

    # "upper mid single digit" → upper half of mid single digit
    if norm.startswith("upper "):
        inner = normalize_phrase(norm[len("upper ") :])
        upper_base = _lookup_base(inner)
        if upper_base is not None:
            return _half_interval(upper_base[0], upper_base[1], "high")

    raise ValueError(f"unknown guidance phrase: {norm!r}")


def _complete_modifier(left: str, right: str) -> str:
    """Attach the scale word from ``right`` when ``left`` is only a modifier."""
    if _MODIFIER_ONLY.match(left):
        for scale in _SCALE_WORDS:
            if right.endswith(scale) or scale in right:
                return normalize_phrase(f"{left} {scale}")
    return left


def parse_guidance_phrase(raw: str) -> tuple[float, float]:
    """Map a verbal growth phrase to ``(range_low, range_high)`` percent.

    Raises ``ValueError`` for unknown phrases so the gate tests force lexicon
    updates rather than silent mis-parses.
    """
    norm = normalize_phrase(raw)
    if not norm:
        raise ValueError("empty guidance phrase")

    if _TO_SPLIT.search(norm):
        parts = _TO_SPLIT.split(norm, maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"malformed range phrase: {raw!r}")
        left_raw, right_raw = parts[0].strip(), parts[1].strip()
        left = _complete_modifier(left_raw, right_raw)
        right = right_raw
        left_iv = _parse_atomic(normalize_phrase(left))
        right_iv = _parse_atomic(normalize_phrase(right))
        return (left_iv[0], right_iv[1])

    return _parse_atomic(norm)


def fiscal_period_bounds(fiscal_year: int, fiscal_quarter: int) -> tuple[date, date]:
    period = FiscalPeriod(fiscal_year, fiscal_quarter)
    return VISA_FISCAL_CALENDAR.period_start(period), VISA_FISCAL_CALENDAR.period_end(period)


# --- Deck layout parsing -----------------------------------------------------


def group_phrases(words: list[dict[str, Any]], gap: float = 6.0) -> list[dict[str, Any]]:
    """Group pdfplumber words into horizontal phrases by inter-word gap."""
    lines: dict[int, list[dict[str, Any]]] = {}
    for word in words:
        lines.setdefault(round(float(word["top"])), []).append(word)
    phrases: list[dict[str, Any]] = []
    for top in sorted(lines):
        ordered = sorted(lines[top], key=lambda w: float(w["x0"]))
        current = [ordered[0]]
        for word in ordered[1:]:
            if float(word["x0"]) - float(current[-1]["x1"]) > gap:
                phrases.append(_phrase_from_words(current))
                current = [word]
            else:
                current.append(word)
        phrases.append(_phrase_from_words(current))
    return phrases


def _phrase_from_words(words: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "text": " ".join(str(w["text"]) for w in words),
        "x0": float(words[0]["x0"]),
        "x1": float(words[-1]["x1"]),
        "yc": (float(words[0]["top"]) + float(words[0]["bottom"])) / 2.0,
        "top": float(words[0]["top"]),
        "words": words,
    }


def detect_outlook_slide(page_text: str) -> dict[str, Any]:
    """Classify a page of extracted PDF text as an outlook slide."""
    next_q = _OUTLOOK_TITLE.search(page_text)
    if next_q:
        qword = next_q.group(1).lower()
        return {
            "outlook_type": "next_quarter_and_full_year",
            "guided_quarter_word": qword,
            "guided_quarter": _QUARTER_WORD.get(qword),
            "full_year": next_q.group(2),
            "title": next_q.group(0),
        }
    fy_only = _FULL_YEAR_ONLY.search(page_text)
    if fy_only:
        return {
            "outlook_type": "full_year_only",
            "guided_quarter_word": None,
            "guided_quarter": None,
            "full_year": fy_only.group(1),
            "title": fy_only.group(0),
        }
    return {
        "outlook_type": "none",
        "guided_quarter_word": None,
        "guided_quarter": None,
        "full_year": None,
        "title": None,
    }


def parse_outlook_slide_words(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse next-quarter / full-year verbal outlook cells from page words.

    Returns keys: ``quarter_header``, ``full_year_header``, ``cells`` mapping
    ``(metric, column)`` → phrase string, where metric ∈
    ``net_revenue`` / ``operating_expenses`` / ``diluted_eps`` and column ∈
    ``q`` / ``fy``.
    """
    qh: tuple[dict[str, Any], dict[str, Any]] | None = None
    fy: tuple[dict[str, Any], dict[str, Any]] | None = None
    for i in range(len(words) - 1):
        a, b = words[i], words[i + 1]
        if qh is None and re.fullmatch(r"Q[1-4]", str(a["text"])) and re.fullmatch(r"\d{4}", str(b["text"])):
            qh = (a, b)
        if fy is None and str(a["text"]) == "Full-Year" and re.fullmatch(r"\d{4}", str(b["text"])):
            fy = (a, b)
    if qh is None or fy is None:
        raise ValueError("outlook slide missing Qn / Full-Year headers")

    qc = (float(qh[0]["x0"]) + float(qh[1]["x1"])) / 2.0
    fc = (float(fy[0]["x0"]) + float(fy[1]["x1"])) / 2.0
    sub = [w for w in words if str(w["text"]).startswith("YoY")]
    top0 = max(
        float(qh[1]["bottom"]),
        float(fy[1]["bottom"]),
        float(sub[0]["bottom"]) if sub else 0.0,
    )
    foot = [
        float(words[i]["top"])
        for i in range(len(words) - 1)
        if str(words[i]["text"]) == "(1)" and str(words[i + 1]["text"]).startswith("Refer")
    ]
    page_bottom = max(float(w["bottom"]) for w in words) + 20.0
    foot_top = foot[0] if foot else page_bottom

    body = [w for w in words if top0 + 1.0 < float(w["top"]) < foot_top - 1.0]
    if not body:
        raise ValueError("outlook slide has empty body region")
    phrases = group_phrases(body, gap=6.0)
    min_x = min(float(p["x0"]) for p in phrases)

    anchors: dict[str, float] = {}
    rest: list[dict[str, Any]] = []
    for phrase in phrases:
        match = _LABEL_RE.match(phrase["text"])
        if match and float(phrase["x0"]) < min_x + 5.0:
            key = {"N": "net_revenue", "O": "operating_expenses", "D": "diluted_eps"}[match.group(1)[0]]
            anchors[key] = float(phrase["yc"])
            residual = match.group(2).strip()
            if residual:
                n_lab = len(match.group(1).split())
                line_words = [
                    w
                    for w in body
                    if round(float(w["top"])) == round(float(phrase["top"]))
                    and float(phrase["x0"]) - 0.1 <= float(w["x0"]) <= float(phrase["x1"]) + 0.1
                ]
                line_words = sorted(line_words, key=lambda w: float(w["x0"]))[n_lab:]
                if line_words:
                    rest.append(_phrase_from_words(line_words))
        elif not phrase["text"].startswith("YoY increase"):
            rest.append(phrase)

    if len(anchors) < 3:
        raise ValueError(f"outlook slide missing metric labels: {sorted(anchors)}")

    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for phrase in rest:
        pc = (float(phrase["x0"]) + float(phrase["x1"])) / 2.0
        col = "q" if abs(pc - qc) < abs(pc - fc) else "fy"
        metric = min(anchors, key=lambda k: abs(anchors[k] - float(phrase["yc"])))
        cells.setdefault((metric, col), []).append(phrase)

    return {
        "quarter_header": f"{qh[0]['text']} {qh[1]['text']}",
        "full_year_header": f"Full-Year {fy[1]['text']}",
        "cells": {
            key: " ".join(p["text"] for p in sorted(vals, key=lambda p: float(p["top"]))) for key, vals in cells.items()
        },
    }


def parse_reconciliation_slide_words(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse the GAAP / non-GAAP / FX / adjusted-constant reconciliation table.

    Returns row phrases keyed by ``(row_label, metric)`` where metric is
    ``net_revenue``, ``operating_expenses``, or ``diluted_eps``. Row labels are
    normalized lowercase tokens such as ``gaap_nominal``, ``non_gaap_nominal``,
    ``fx_impact``, ``acquisition_impact``, ``adjusted_constant_dollar``.
    """
    text = " ".join(str(w["text"]) for w in words)
    if "Reconciliation of Fiscal" not in text and "reconciliation of" not in text.lower():
        raise ValueError("not a reconciliation slide")

    # Heuristic: locate column headers Net Revenue / Operating Expense / EPS.
    headers: dict[str, float] = {}
    for i, word in enumerate(words):
        tok = str(word["text"]).lower()
        if tok == "net" and i + 1 < len(words) and "revenue" in str(words[i + 1]["text"]).lower():
            headers["net_revenue"] = (float(word["x0"]) + float(words[i + 1]["x1"])) / 2.0
        if tok == "operating" and i + 1 < len(words) and "expense" in str(words[i + 1]["text"]).lower():
            headers["operating_expenses"] = (float(word["x0"]) + float(words[i + 1]["x1"])) / 2.0
        if "earnings" in tok or tok in {"eps", "share"}:
            # Prefer "Diluted" / "EPS" style headers near the right.
            if (
                "diluted" in tok
                or tok == "eps"
                or (tok == "share" and i > 0 and "per" in str(words[i - 1]["text"]).lower())
            ):
                headers.setdefault("diluted_eps", float(word["x0"]))

    row_patterns: list[tuple[str, re.Pattern[str]]] = [
        ("gaap_nominal", re.compile(r"^gaap\b.*nominal", re.I)),
        ("non_gaap_adjustments", re.compile(r"^non[- ]gaap adjust", re.I)),
        ("non_gaap_nominal", re.compile(r"^non[- ]gaap\b.*nominal", re.I)),
        ("fx_impact", re.compile(r"foreign currency|fx impact", re.I)),
        ("acquisition_impact", re.compile(r"acquisition impact", re.I)),
        ("adjusted_constant_dollar", re.compile(r"adjusted constant", re.I)),
    ]

    phrases = group_phrases(words, gap=8.0)
    # Build row anchors from left-side labels.
    anchors: dict[str, float] = {}
    for phrase in phrases:
        for key, pattern in row_patterns:
            if key in anchors:
                continue
            if pattern.search(phrase["text"]) and float(phrase["x0"]) < 120:
                anchors[key] = float(phrase["yc"])
                break

    cells: dict[tuple[str, str], str] = {}
    if headers and anchors:
        for phrase in phrases:
            if float(phrase["x0"]) < 120:
                continue
            metric = min(headers, key=lambda k: abs(headers[k] - (float(phrase["x0"]) + float(phrase["x1"])) / 2.0))
            row = min(anchors, key=lambda k: abs(anchors[k] - float(phrase["yc"])))
            # Skip if too far from both.
            if abs(anchors[row] - float(phrase["yc"])) > 14:
                continue
            prev = cells.get((row, metric), "")
            cells[(row, metric)] = (prev + " " + phrase["text"]).strip()

    return {"headers": headers, "rows": anchors, "cells": cells}


# --- Transcript helpers ------------------------------------------------------


def _clean_transcript_phrase(phrase: str) -> str | None:
    """Strip hedges; reject relative / non-band phrases."""
    phrase = phrase.strip().strip(" ,;")
    phrase = re.split(
        r",\s*(?:inclusive|excluding|which|and we|including|with client)",
        phrase,
        maxsplit=1,
    )[0].strip()
    phrase = re.sub(r"\s+in\s+constant\s+dollars$", "", phrase, flags=re.I).strip()
    phrase = re.sub(r"\s+range$", "", phrase, flags=re.I).strip()
    # Reject relative comparisons that are not growth bands.
    if re.search(r"\blower than\b|\bhigher than\b|\bmoderate\b", phrase, re.I):
        return None
    if not re.search(
        r"flat|single|double|teen|20|digit|mid|low|high",
        phrase,
        re.I,
    ):
        return None
    return phrase


def find_transcript_outlook(text: str) -> dict[str, Any]:
    """Locate spoken next-quarter net-revenue (and optional opex) outlook sentences."""
    compact = re.sub(r"\s+", " ", text)
    result: dict[str, Any] = {
        "net_revenue_phrase": None,
        "net_revenue_quote": None,
        "net_revenue_span": None,
        "opex_relative": None,
        "opex_absolute_phrase": None,
        "opex_quote": None,
        "opex_span": None,
    }

    for pattern in _TRANSCRIPT_NR_PATTERNS:
        match = pattern.search(compact)
        if match is None:
            continue
        phrase = _clean_transcript_phrase(match.group("phrase"))
        if phrase is None:
            continue
        result["net_revenue_phrase"] = phrase
        result["net_revenue_quote"] = match.group(0).strip()
        result["net_revenue_span"] = (match.start(), match.end())
        break

    opex_rel = _TRANSCRIPT_OPEX_REL.search(compact)
    if opex_rel is not None:
        a, b = int(opex_rel.group("a")), int(opex_rel.group("b"))
        result["opex_relative"] = {
            "points_lower_low": min(a, b),
            "points_lower_high": max(a, b),
            "reference_quarter": opex_rel.group("ref"),
            "guided_quarter": opex_rel.group("q"),
        }
        result["opex_quote"] = opex_rel.group(0).strip()
        result["opex_span"] = (opex_rel.start(), opex_rel.end())
    else:
        opex_abs = _TRANSCRIPT_OPEX_ABS.search(compact)
        if opex_abs is not None:
            phrase = _clean_transcript_phrase(opex_abs.group("phrase"))
            if phrase is not None:
                result["opex_absolute_phrase"] = phrase
                result["opex_quote"] = opex_abs.group(0).strip()
                result["opex_span"] = (opex_abs.start(), opex_abs.end())
    return result


def resolve_relative_opex(
    points_lower_low: int,
    points_lower_high: int,
    reference_growth_low: float,
    reference_growth_high: float,
) -> tuple[float, float]:
    """Resolve 'N to M points lower than Qref' against a reference growth band."""
    return (
        reference_growth_low - points_lower_high,
        reference_growth_high - points_lower_low,
    )


# --- Fixture models ----------------------------------------------------------


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor: str
    quote: str
    char_start: int
    char_end: int
    page: int | None = None

    @model_validator(mode="after")
    def _order(self) -> Span:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        if self.char_end - self.char_start != len(self.quote):
            raise ValueError(f"char span length {self.char_end - self.char_start} != quote length {len(self.quote)}")
        return self


class GuidanceSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    kind: GuidanceSourceKind
    url: str
    statement_ts: str
    document_ts: str | None = None
    content_sha256: str
    note: str = ""


class VisaGuidanceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    statement_type: StatementType = "guidance"
    activity_type: str | None = None
    geography: str = "global"
    period_start: date
    period_end: date
    value: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    unit: str = "percent"
    basis: BasisToken
    source_family: str = "visa_ir"
    review_status: Literal["pending"] = "pending"
    span: Span
    note: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def _unit_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("unit must be non-empty")
        return v


class VisaGuidanceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    company: str = "visa"
    origin_label: str
    origin_fiscal_year: int
    origin_fiscal_quarter: int
    target_fiscal_year: int
    target_fiscal_quarter: int
    cutoff_utc: str
    release_date: str
    source: GuidanceSourceRef
    observations: list[VisaGuidanceObservation]
    notes: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _at_least_one(self) -> VisaGuidanceFixture:
        if not self.observations:
            raise ValueError("fixture must contain at least one observation")
        return self


def to_observation_create(entry: VisaGuidanceObservation, source_url: str) -> ObservationCreate:
    """Validate a fixture observation against the API contract."""
    return ObservationCreate(
        company="visa",
        source_id=source_uuid_for_url(source_url),
        document_text_id=None,
        span_page=entry.span.page,
        span_char_start=entry.span.char_start,
        span_char_end=entry.span.char_end,
        statement_type=entry.statement_type,
        activity_type=entry.activity_type,
        geography=entry.geography,
        period_start=entry.period_start,
        period_end=entry.period_end,
        value=entry.value,
        range_low=entry.range_low,
        range_high=entry.range_high,
        unit=entry.unit,
        basis=entry.basis,
        source_family=entry.source_family,
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        review_status=entry.review_status,
        attributes={
            **entry.attributes,
            "observation_id": entry.observation_id,
            "anchor": entry.span.anchor,
            "quote": entry.span.quote,
            "note": entry.note,
        },
    )


def load_fixture(path: Path) -> VisaGuidanceFixture:
    return VisaGuidanceFixture.model_validate_json(path.read_text(encoding="utf-8"))


def required_fixture_paths() -> list[Path]:
    return [
        OBSERVATIONS_DIR / "visa_guidance_2023-04-25.json",
        OBSERVATIONS_DIR / "visa_guidance_2024-07-23.json",
        OBSERVATIONS_DIR / "visa_guidance_2025-10-28.json",
        OBSERVATIONS_DIR / "visa_guidance_2026-07-28.json",
    ]


CONSENSUS_UNAVAILABLE_LABEL = "consensus unavailable (no licensed free historical source)"
COMPANY_GUIDANCE_LABEL = "company guidance"
