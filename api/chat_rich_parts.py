"""Rich parts of an assistant message: inline charts, proposal cards and follow-up suggestions.

Charts are built from a tool's whole result, before the agent's output budget cuts it down, and saved
with the message as a compact snapshot. A proposal part names the approval a ``propose_*`` tool created;
the card reads the approval itself, so its state stays current. Suggestions are written after the answer
by the turn's follow-up job.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

MAX_CHART_ROWS = 240
MAX_CHARTS_PER_MESSAGE = 6
MAX_SUGGESTIONS = 3
MAX_SUGGESTION_CHARS = 140
MIN_ANSWER_CHARS_FOR_SUGGESTIONS = 80

CHART_TOOLS = frozenset(
    {"run_chart", "run_ratio_chart", "get_yield_curve", "get_commodities_curve", "get_price_volume_signals"}
)

# Newest results are kept; a chart that was never picked up (a workflow run, say) ages out here.
_MAX_PENDING_CHARTS = 64
_pending_charts: OrderedDict[str, dict[str, Any]] = OrderedDict()
_pending_lock = threading.Lock()


def stash_chart(event_id: str, part: dict[str, Any]) -> None:
    """Hold a chart until the chat stream picks it up by the tool call's provenance event id."""
    with _pending_lock:
        _pending_charts[event_id] = part
        _pending_charts.move_to_end(event_id)
        while len(_pending_charts) > _MAX_PENDING_CHARTS:
            _pending_charts.popitem(last=False)


def stashed_chart(event_id: str) -> dict[str, Any] | None:
    with _pending_lock:
        part = _pending_charts.get(event_id)
    return dict(part) if part is not None else None


def _number(value: Any, digits: int = 4) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return round(float(value), digits)


def _day(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else (text or None)


def _sample(rows: list[dict[str, Any]], limit: int = MAX_CHART_ROWS) -> list[dict[str, Any]]:
    """At most ``limit`` rows, evenly spaced and always keeping the first and the last."""
    if len(rows) <= limit:
        return rows
    step = (len(rows) - 1) / (limit - 1)
    return [rows[round(index * step)] for index in range(limit)]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _chart(tool: str, kind: str, x_key: str, **fields: Any) -> dict[str, Any] | None:
    rows = fields.pop("rows")
    series = fields.pop("series")
    if len(rows) < (2 if kind == "line" else 1) or not series:
        return None
    sampled = _sample(rows)
    part: dict[str, Any] = {"tool": tool, "kind": kind, "x_key": x_key, "series": series, "rows": sampled, **fields}
    if len(sampled) < len(rows):
        part["sampled_from"] = len(rows)
    return part


def _price_chart(tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    ticker = str(result.get("ticker") or args.get("ticker") or "").upper()
    records = _records(result.get("price_data"))
    wanted = ("Close", "100D SMA", "200D SMA")
    rows: list[dict[str, Any]] = []
    for record in records:
        day = _day(record.get("Date") or record.get("date") or record.get("index"))
        close = _number(record.get("Close"))
        if not day or close is None:
            continue
        row: dict[str, Any] = {"date": day}
        for key in wanted:
            row[key] = _number(record.get(key), 4)
        rows.append(row)
    series = [{"key": key, "name": key} for key in wanted if any(row[key] is not None for row in rows)]
    name = str(result.get("name") or "").strip()
    lookback = str(args.get("lookback") or "2Y").upper()
    return _chart(
        tool,
        "line",
        "date",
        title=f"{name} ({ticker})" if name and name.upper() != ticker else ticker,
        subtitle=f"{lookback} daily close with moving averages",
        as_of=rows[-1]["date"] if rows else None,
        y_format="price",
        series=series,
        rows=rows,
    )


def _ratio_chart(tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    rows = []
    for record in _records(result.get("ratio_data")):
        day = _day(record.get("Date") or record.get("date") or record.get("index"))
        ratio = _number(record.get("Ratio"), 6)
        if day and ratio is not None:
            rows.append({"date": day, "Ratio": ratio})
    stats = _mapping(result.get("stats"))
    change = _number(stats.get("change_pct"))
    average = _number(stats.get("historical_avg"), 4)
    facts = [
        f"{change * 100:+.1f}% over the window" if change is not None else None,
        f"average {average}" if average is not None else None,
    ]
    label = str(result.get("ratio_label") or f"{args.get('symbol_a', '')}/{args.get('symbol_b', '')}").upper()
    return _chart(
        tool,
        "line",
        "date",
        title=f"{label} ratio",
        subtitle=" · ".join(fact for fact in facts if fact) or None,
        as_of=rows[-1]["date"] if rows else None,
        y_format="ratio",
        series=[{"key": "Ratio", "name": label}],
        rows=rows,
    )


def _yield_curve_chart(tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    countries = [c for c in _records(result.get("countries")) if _records(c.get("points"))]
    order = [str(t.get("tenor")) for t in _records(result.get("tenor_order")) if t.get("tenor")]
    if not countries:
        return None
    lookback = result.get("lookback_days") or args.get("lookback_days")
    if len(countries) == 1:
        country = countries[0]
        by_tenor = {str(p.get("tenor")): p for p in _records(country.get("points"))}
        columns = [
            ("current", "Current"),
            ("historical", f"{lookback}d ago" if lookback else "Earlier"),
            ("historical_1y", "1Y ago"),
        ]
        rows = [
            {"label": tenor, **{key: _number(by_tenor[tenor].get(key)) for key, _ in columns}}
            for tenor in (order or list(by_tenor))
            if tenor in by_tenor
        ]
        series = [{"key": key, "name": name} for key, name in columns if any(row[key] is not None for row in rows)]
        title = f"{country.get('name') or country.get('code')} yield curve"
        as_of = country.get("as_of_date")
    else:
        keys = [str(c.get("code") or c.get("name")) for c in countries]
        tenors = order or [str(p.get("tenor")) for p in _records(countries[0].get("points"))]
        points = {
            key: {str(p.get("tenor")): p for p in _records(country.get("points"))}
            for key, country in zip(keys, countries, strict=True)
        }
        rows = [
            {"label": tenor, **{key: _number(points[key].get(tenor, {}).get("current")) for key in keys}}
            for tenor in tenors
        ]
        series = [{"key": key, "name": key} for key in keys if any(row[key] is not None for row in rows)]
        title = "Government yield curves"
        as_of = max((str(c.get("as_of_date")) for c in countries if c.get("as_of_date")), default=None)
    return _chart(
        tool,
        "curve",
        "label",
        title=title,
        subtitle="Yield by tenor" if len(countries) == 1 else "Current yield by tenor",
        as_of=_day(as_of),
        y_format="yield",
        series=series,
        rows=rows,
    )


def _commodity_curve_chart(tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    lookback = result.get("lookback_days") or args.get("lookback_days")
    rows = [
        {
            "label": str(point.get("label") or ""),
            "current": _number(point.get("current")),
            "historical": _number(point.get("historical")),
        }
        for point in _records(result.get("points"))
        if point.get("label")
    ]
    columns = [("current", "Current"), ("historical", f"{lookback}d ago" if lookback else "Earlier")]
    analysis = _mapping(result.get("analysis"))
    unit = str(result.get("unit") or "").strip()
    return _chart(
        tool,
        "curve",
        "label",
        title=f"{result.get('commodity_name') or result.get('commodity_code') or 'Commodity'} forward curve",
        subtitle=" · ".join(part for part in (analysis.get("shape"), unit) if part) or None,
        as_of=_day(
            next((p.get("current_date") for p in _records(result.get("points")) if p.get("current_date")), None)
        ),
        y_format="price",
        unit=unit or None,
        series=[{"key": key, "name": name} for key, name in columns if any(row[key] is not None for row in rows)],
        rows=rows,
    )


_SIGNAL_NAMES = {
    "DownsideRecordVol": "record volume on a down day",
    "NewHigh_LowVol": "new high on low volume",
    "HiVol_Churn": "high-volume churn",
}


def _signals_chart(tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    latest = _records(result.get("latest_df"))
    rows = [
        {"label": str(row.get("Market") or ""), "RetPct": _number(row.get("RetPct"), 2)}
        for row in latest
        if row.get("Market") and _number(row.get("RetPct")) is not None
    ]
    flagged = [
        f"{str(row.get('Market'))}: {_SIGNAL_NAMES[key]}"
        for row in latest
        for key in _SIGNAL_NAMES
        if row.get(key) is True
    ]
    return _chart(
        tool,
        "bars",
        "label",
        title="Latest session return by market",
        subtitle="Signals: " + "; ".join(flagged) if flagged else "No price/volume signals on the latest session",
        as_of=_day(next((row.get("Date") for row in latest if row.get("Date")), None)),
        y_format="percent",
        series=[{"key": "RetPct", "name": "Return %"}],
        rows=rows,
    )


_CHART_BUILDERS = {
    "run_chart": _price_chart,
    "run_ratio_chart": _ratio_chart,
    "get_yield_curve": _yield_curve_chart,
    "get_commodities_curve": _commodity_curve_chart,
    "get_price_volume_signals": _signals_chart,
}


def build_chart_part(tool: str, arguments: dict[str, Any], result: Any) -> dict[str, Any] | None:
    """A chart snapshot of a tool's whole result, or None when it has nothing to plot."""
    builder = _CHART_BUILDERS.get(tool)
    if builder is None or not isinstance(result, dict) or result.get("error"):
        return None
    try:
        return builder(tool, arguments if isinstance(arguments, dict) else {}, result)
    except Exception:
        logger.exception("chart_part_failed tool=%s", tool)
        return None


def build_proposal_part(tool: str, result_text: Any) -> dict[str, Any] | None:
    """The card for a ``propose_*`` tool call that created a pending approval."""
    try:
        result = json.loads(result_text) if isinstance(result_text, str) else result_text
    except ValueError:
        return None
    if not isinstance(result, dict) or result.get("status") != "pending_approval_created":
        return None
    approval_id = str(result.get("approval_id") or "").strip()
    if not approval_id:
        return None
    return {
        "tool": tool,
        "approval_id": approval_id,
        "entity_type": result.get("entity_type"),
        "ticker": result.get("ticker"),
    }


SUGGESTIONS_PROMPT = """You write the follow-up questions shown under an answer in a markets research chat.
Given the user's question and the assistant's answer, write {count} short questions the user is likely to ask
next. Phrase each as the user would type it, make each one specific to this answer (name the ticker, metric or
risk it discusses), and do not repeat the question that was just asked. Reply with JSON only:
{{"suggestions": ["...", "..."]}}

User question:
{question}

Assistant answer:
{answer}
"""


def parse_suggestions(text: str, question: str = "") -> list[str]:
    """The questions in a model reply, trimmed, de-duplicated and capped. Anything unparseable gives none."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0)).get("suggestions")
    except (ValueError, AttributeError):
        return []
    asked = question.strip().lower()
    found: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        text_item = " ".join(str(item).split())
        if not text_item or len(text_item) > MAX_SUGGESTION_CHARS or text_item.lower() == asked:
            continue
        if text_item.lower() not in {s.lower() for s in found}:
            found.append(text_item)
    return found[:MAX_SUGGESTIONS]


def suggestions_enabled() -> bool:
    """Whether answered turns get suggested follow-up questions (one low-tier model call each); on unless switched off."""
    return (os.getenv("AGENT_FOLLOWUP_SUGGESTIONS") or "true").strip().lower() not in {"0", "false", "no", "off"}


def generate_suggestions(question: str, answer: str) -> list[str]:
    """Ask the low-tier model for follow-up questions; an empty list when there is nothing to suggest."""
    if len(answer.strip()) < MIN_ANSWER_CHARS_FOR_SUGGESTIONS:
        return []
    from llm_utils import MODEL_LOW, call_llm_text, has_llm_api_key

    if not has_llm_api_key():
        return []
    text, _citations, _response = call_llm_text(
        prompt=SUGGESTIONS_PROMPT.format(
            count=MAX_SUGGESTIONS, question=question.strip()[:1500], answer=answer.strip()[:6000]
        ),
        model=MODEL_LOW,
        api_key=None,
        max_tokens=300,
    )
    return parse_suggestions(text, question)
