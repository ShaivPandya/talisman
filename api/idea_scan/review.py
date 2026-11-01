"""Quick LLM review of a screened name, written as an OpportunityCandidate.

One mid-tier call per name with at most a couple of web searches. Headlines
are kept only when the search actually returned their URL. The review text is
scrubbed of buy/sell/short phrasing before it reaches the Scout queue, since
the shared candidate checks only constrain ``next_action``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from api.idea_scan.budget import RunBudget
from api.idea_scan.macro_view import resolve_effort
from api.idea_scan.momentum import evidence_lines

LOGGER = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 3000
REASONING_EFFORT = "low"
FILING_LOOKBACK_DAYS = 90
MAX_HEADLINES = 3
BORROW_MISSING = "Borrow cost and availability (no broker feed connected)"

FORM_8K_ITEMS = {
    "1.01": "material agreement",
    "1.02": "agreement terminated",
    "1.03": "bankruptcy or receivership",
    "2.01": "acquisition or disposal completed",
    "2.02": "results of operations",
    "2.03": "new financial obligation",
    "2.05": "exit or restructuring costs",
    "2.06": "material impairment",
    "3.01": "listing standards notice",
    "3.02": "unregistered equity sale",
    "4.01": "auditor change",
    "4.02": "prior financials no longer reliable",
    "5.02": "officer or director change",
    "5.03": "charter or bylaw amendment",
    "5.07": "shareholder vote",
    "7.01": "Reg FD disclosure",
    "8.01": "other events",
}

PRESET_OPPORTUNITY_TYPES = {
    "long_screen": "undervalued_asset",
    "quality_value": "quality_compounder",
    "value_momentum": "undervalued_asset",
    "composite_top": "quality_compounder",
    "short_screen": "unsustainable_process",
    "breakdown": "unsustainable_process",
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "trigger": {"type": "string"},
        "why_now": {"type": "string"},
        "consensus": {"type": "string"},
        "variant_view": {"type": "string"},
        "headlines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["title", "url", "date"],
                "additionalProperties": False,
            },
        },
        "macro_fit": {"type": "string"},
        "missing_inputs": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string", "enum": ["research", "watch", "avoid"]},
    },
    "required": [
        "trigger",
        "why_now",
        "consensus",
        "variant_view",
        "headlines",
        "macro_fit",
        "missing_inputs",
        "next_action",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You triage screened stocks for an equity research team. You decide whether a name deserves a closer look "
    "and say what to check. You never recommend buying, selling, shorting or sizing a position, and you never "
    "give price targets."
)

# Phrases that read as a trade recommendation. "Short interest", "short screen" and buybacks are fine.
_RECOMMENDATION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(we|i)\s+(would\s+)?(recommend|suggest|advise)\b",
        r"\b(should|must|could)\s+(buy|sell|short|accumulate|trim)\b",
        r"\b(buy|sell|short|accumulate|trim|exit)\s+(the\s+)?(stock|shares|position|name)\b",
        r"\b(buy|sell|short)\s+(it|this|them)\b",
        r"\bis\s+an?\s+(buy|sell|short)\b",
        r"\b(go|going)\s+(long|short)\b",
        r"\b(initiate|open|add\s+to)\s+(a\s+)?(long|short|position)\b",
        r"\b(strong\s+)?(buy|sell|outperform|underperform)\s+rating\b",
        r"\bprice\s+target\b",
    )
]
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def scrub_recommendation_language(text: str) -> tuple[str, bool]:
    """Drop sentences that read as a buy/sell/short recommendation. Returns (text, flagged)."""
    sentences = _SENTENCE_SPLIT.split(str(text or "").strip())
    kept = [s for s in sentences if not any(p.search(s) for p in _RECOMMENDATION_PATTERNS)]
    flagged = len(kept) != len(sentences)
    if flagged and not kept:
        return "(Removed: the text read as a trade recommendation.)", True
    return " ".join(kept), flagged


def recent_filings(ticker: str, *, now: datetime | None = None) -> dict[str, Any]:
    """8-Ks and Form 4 insider transactions from the last 90 days, from SEC EDGAR."""
    from api.public_dataset_adapters import sec_form4
    from portfolio.momentum.fundamental_momentum import edgar_fetcher as edgar

    end = (now or datetime.now(UTC)).date()
    start = end - timedelta(days=FILING_LOOKBACK_DAYS)
    out: dict[str, Any] = {"status": "ok", "eight_k": [], "form4": {"purchases": 0, "sales": 0, "other": 0, "rows": []}}
    try:
        cik = edgar.get_cik_for_ticker(ticker)
        if not cik:
            return {**out, "status": "no_cik"}
        submissions = edgar.fetch_submissions_by_cik(cik)
        recent = (submissions or {}).get("filings", {}).get("recent", {})
        forms = recent.get("form") or []
        for i, form in enumerate(forms):
            day = str((recent.get("filingDate") or [])[i] if i < len(recent.get("filingDate") or []) else "")
            if form not in {"8-K", "8-K/A"} or not (start.isoformat() <= day <= end.isoformat()):
                continue
            items = str((recent.get("items") or [""] * len(forms))[i] or "")
            accession = str(recent["accessionNumber"][i])
            out["eight_k"].append(
                {
                    "date": day,
                    "form": form,
                    "items": [
                        FORM_8K_ITEMS.get(code.strip(), code.strip()) for code in items.split(",") if code.strip()
                    ],
                    "url": edgar.build_filing_url(cik, accession, submissions),
                }
            )
        out["eight_k"] = out["eight_k"][:8]
        try:
            form4 = sec_form4(
                cast(Any, None), {"cik": cik, "start_date": start.isoformat(), "end_date": end.isoformat(), "limit": 40}
            )
            rows = ((form4 or {}).get("snapshot") or {}).get("records") or []
            for row in rows:
                code = str(row.get("transaction_code") or "")
                bucket = "purchases" if code == "P" else "sales" if code == "S" else "other"
                out["form4"][bucket] += 1
            out["form4"]["rows"] = rows[:10]
        except Exception as exc:
            out["form4"]["error"] = type(exc).__name__
    except Exception as exc:
        LOGGER.info("EDGAR filings unavailable for %s: %s", ticker, exc)
        return {**out, "status": "unavailable"}
    return out


def _pct(value: Any, *, scale: float = 100.0, digits: int = 0) -> str:
    try:
        return f"{float(value) * scale:.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _metric_lines(candidate: dict[str, Any]) -> list[str]:
    m = candidate.get("metrics") or {}
    labels = {
        "market_cap": ("Market cap ($M)", 1e-6),
        "price_to_book": ("P/B", 1.0),
        "rev_yoy_avg": ("Revenue YoY, last 3 quarters (%)", 1.0),
        "eps_yoy_avg": ("EPS YoY, last 3 quarters (%)", 1.0),
        "net_issuance": ("Net share issuance, last FY ($M)", 1e-6),
        "return_52w": ("52-week return (%)", 1.0),
        "drawdown_pct": ("Drawdown from 52-week high (%)", 1.0),
        "return_3m": ("3-month return (%)", 1.0),
        "enterpriseToEbitda": ("EV/EBITDA", 1.0),
        "forwardPE": ("Forward P/E", 1.0),
    }
    lines = []
    for key, (label, scale) in labels.items():
        value = m.get(key)
        if value is not None:
            lines.append(f"- {label}: {float(value) * scale:,.1f}")
    return lines


def _filing_lines(filings: dict[str, Any]) -> list[str]:
    if filings.get("status") != "ok":
        return [f"- SEC filings unavailable ({filings.get('status')})."]
    lines = [f"- 8-K {f['date']}: {', '.join(f['items']) or 'no items listed'}" for f in filings.get("eight_k") or []]
    form4 = filings.get("form4") or {}
    if form4.get("error"):
        lines.append("- Form 4 insider filings could not be parsed.")
    else:
        lines.append(
            f"- Form 4 transactions: {form4.get('purchases', 0)} open-market purchases, "
            f"{form4.get('sales', 0)} open-market sales, {form4.get('other', 0)} other (grants, exercises, gifts)."
        )
    return lines or ["- No 8-K or Form 4 filings in the last 90 days."]


def build_prompt(
    candidate: dict[str, Any], *, macro_row: dict[str, Any] | None, filings: dict[str, Any], searches: int
) -> str:
    ranks = candidate.get("factor_ranks") or {}
    presets = ", ".join(p["name"] for p in candidate.get("presets") or [])
    signals = "\n".join(f"- {s['label']}" for s in candidate.get("signals") or []) or "- (none)"
    macro = (
        f"{macro_row['sector']}: score {macro_row['score']:+d} ({macro_row['confidence']} confidence) — {macro_row['reason']}"
        if macro_row
        else "No macro row for this sector this week."
    )
    momentum = (
        "\n".join(evidence_lines(candidate["momentum"], candidate["direction"]))
        if candidate.get("momentum")
        else "Legacy momentum methodology."
    )
    short_block = ""
    if candidate.get("direction") == "short":
        sd = candidate.get("short_data") or {}
        short_block = (
            "\nShort-side data:\n"
            f"- Short interest: {_pct(sd.get('short_percent_of_float'), digits=1)}% of float, "
            f"{sd.get('short_ratio') if sd.get('short_ratio') is not None else 'n/a'} days to cover\n"
            f"- Days to next earnings: {candidate.get('days_to_earnings') if candidate.get('days_to_earnings') is not None else 'unknown'}\n"
            "- Borrow cost and availability: not available\n"
        )
    return f"""Review this screened {candidate["direction"]} idea and say whether it deserves a closer look.

{candidate["ticker"]} — {candidate.get("company")} ({candidate.get("sector")}; {candidate.get("industry") or "industry n/a"})
Presets hit: {presets}
Signals that fired:
{signals}

Factor percentiles (100 = best in the scanned universe):
- Composite {_pct(ranks.get("composite_pct"))}, quality {_pct(ranks.get("quality_pct"))},
  EPS momentum {_pct(ranks.get("eps_momentum_pct"))}, revenue momentum {_pct(ranks.get("revenue_momentum_pct"))}

Price momentum (each passing signal earns fixed half credit; larger returns add no credit):
{momentum}

Key metrics:
{chr(10).join(_metric_lines(candidate)) or "- (none available)"}

Sector macro view: {macro}
{short_block}
Recent SEC filings (last 90 days):
{chr(10).join(_filing_lines(filings))}

Use up to {searches} web searches for news about {candidate["ticker"]} from the last 30 days.

Fill every field:
- trigger: one line on what put the name on the list.
- why_now: one or two sentences on what changed recently.
- consensus: what the market appears to assume.
- variant_view: where the data above disagrees with that.
- headlines: two or three recent headlines you found, each with title, url and date. Only include pages your searches returned.
- macro_fit: one line on whether the sector backdrop helps or hurts this {candidate["direction"]} idea.
- missing_inputs: up to four things a researcher still needs to check.
- next_action: research, watch or avoid.
Do not recommend buying, selling or shorting, and do not give a price target.
"""


def _normalize_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def sourced_headlines(raw: Any, citations: list[tuple[str, str]]) -> list[dict[str, str]]:
    cited = {_normalize_url(url): (title, url) for title, url in citations or [] if url}
    out: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_url(str(item.get("url") or ""))
        if not normalized or normalized not in cited:
            continue
        title, url = cited[normalized]
        out.append(
            {
                "title": str(item.get("title") or title or url)[:200],
                "url": url,
                "date": str(item.get("date") or "")[:20],
            }
        )
        if len(out) >= MAX_HEADLINES:
            break
    return out


def review_candidate(
    candidate: dict[str, Any],
    *,
    macro_row: dict[str, Any] | None,
    budget: RunBudget,
    searches: int,
    filings: dict[str, Any] | None = None,
    call: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run one review. Returns the review dict with ``status`` ok or failed."""
    from llm_utils import MODEL_MID, call_llm_json

    call = call or call_llm_json
    filings = recent_filings(candidate["ticker"]) if filings is None else filings
    provider, effort = resolve_effort(MODEL_MID, REASONING_EFFORT)
    prompt = build_prompt(candidate, macro_row=macro_row, filings=filings, searches=searches)
    label = f"{candidate['ticker']} ({candidate['direction']})"
    try:
        with budget.track("review", label) as record:
            parsed, citations, _response, diagnostics = call(
                prompt=prompt,
                model=MODEL_MID,
                provider=provider,
                system=SYSTEM_PROMPT,
                max_tokens=MAX_OUTPUT_TOKENS,
                enable_web_search=searches > 0,
                max_web_search_uses=max(1, searches),
                reasoning_effort=effort,
                json_schema=REVIEW_SCHEMA,
                json_schema_name="idea_scan_review",
            )
    except Exception as exc:
        LOGGER.warning("Idea scan review failed for %s", label, exc_info=True)
        return {"status": "failed", "error": f"Review call failed: {type(exc).__name__}", "filings": filings}
    if not isinstance(parsed, dict):
        reason = (diagnostics or {}).get("failure_reason") or "no JSON returned"
        return {"status": "failed", "error": f"Review unusable: {reason}", "filings": filings}

    flagged = False
    texts: dict[str, str] = {}
    for key in ("trigger", "why_now", "consensus", "variant_view", "macro_fit"):
        texts[key], hit = scrub_recommendation_language(str(parsed.get(key) or "")[:600])
        flagged = flagged or hit
    missing: list[str] = []
    for item in parsed.get("missing_inputs") or []:
        text, hit = scrub_recommendation_language(str(item)[:200])
        flagged = flagged or hit
        if text and not text.startswith("(Removed"):
            missing.append(text)
    headlines = sourced_headlines(parsed.get("headlines"), [*(citations or []), *record.sources])
    if len(headlines) < 2:
        missing.append("Recent news (fewer than two sourced headlines found)")
    if candidate.get("direction") == "short":
        if not any("borrow" in item.lower() for item in missing):
            missing.append(BORROW_MISSING)
        if (candidate.get("short_data") or {}).get("short_percent_of_float") is None:
            missing.append("Short interest (not reported by the data source)")
    next_action = str(parsed.get("next_action") or "research").lower()
    return {
        "status": "ok",
        "model": record.model,
        "cost_usd": round(record.cost_usd, 6),
        "web_searches": record.usage.web_searches,
        **texts,
        "headlines": headlines,
        "missing_inputs": list(dict.fromkeys(missing))[:6],
        "next_action": next_action if next_action in {"research", "watch", "avoid"} else "research",
        "language_flagged": flagged,
        "filings": filings,
    }


def scout_candidate_id(week: str, ticker: str, direction: str) -> str:
    return f"idea_scan_{week.lower().replace('-', '')}_{direction}_{ticker.lower()}"


def build_scout_record(
    candidate: dict[str, Any], review: dict[str, Any], *, run_id: str, week: str, screen_kinds: Mapping[str, str]
) -> dict[str, Any] | None:
    """OpportunityCandidate persistence record, or None when the shared checks block it."""
    from decision_quality.candidate_gates import apply_opportunity_candidate_gates
    from decision_quality.opportunity_candidate import parse_opportunity_candidate

    first_preset = (candidate.get("presets") or [{}])[0]
    metrics = candidate.get("metrics") or {}
    price_bits = [
        f"52-week return {metrics['return_52w']:.1f}%" if metrics.get("return_52w") is not None else None,
        f"3-month return {metrics['return_3m']:.1f}%" if metrics.get("return_3m") is not None else None,
    ]
    crowding = ""
    if candidate.get("direction") == "short":
        sd = candidate.get("short_data") or {}
        if sd.get("short_percent_of_float") is not None:
            crowding = f"Short interest {float(sd['short_percent_of_float']) * 100:.1f}% of float"
            if sd.get("short_ratio") is not None:
                crowding += f", {sd['short_ratio']} days to cover"
    refs = [{"label": h["title"], "url": h["url"]} for h in review.get("headlines") or []]
    refs += [
        {"label": f"SEC {f['form']} {f['date']}", "url": f["url"]}
        for f in (review.get("filings") or {}).get("eight_k") or []
    ][:3]
    refs.append({"label": f"Weekly idea scan {week}", "source_path": f"idea_scan_run:{run_id}"})
    parsed, _errors = parse_opportunity_candidate(
        {
            "ticker": candidate["ticker"],
            "source": "workflow",
            "trigger": review.get("trigger") or f"Weekly idea scan: {first_preset.get('name')}",
            "opportunity_type": PRESET_OPPORTUNITY_TYPES.get(
                screen_kinds.get(str(first_preset.get("id")), ""), "unclear"
            ),
            "consensus": review.get("consensus") or "",
            "variant_view": review.get("variant_view") or "",
            "why_now": review.get("why_now") or "",
            "price_confirmation": "; ".join(b for b in price_bits if b) or "Not checked.",
            "crowding": crowding,
            "payoff_asymmetry": "",
            "missing_inputs": review.get("missing_inputs") or [],
            "source_refs": refs,
            "next_action": review.get("next_action") or "research",
            "summary": f"{candidate['direction'].title()} screen: {', '.join(p['name'] for p in candidate.get('presets') or [])}. "
            f"Macro fit: {review.get('macro_fit') or 'n/a'}",
        }
    )
    if parsed is None:
        return None
    gate = apply_opportunity_candidate_gates(parsed)
    if gate.status in {"blocked", "invalid"}:
        return None
    candidate_id = scout_candidate_id(week, candidate["ticker"], candidate["direction"])
    return {
        "candidate_id": candidate_id,
        "idempotency_key": candidate_id,
        "source_kind": "workflow",
        "source_type": "workflow",
        "source_id": f"idea_scan:{run_id}",
        "status": "open",
        "decision_state": "generated",
        "rank_signals": {
            "agreement_score": candidate.get("agreement_score"),
            "final_score": candidate.get("final_score"),
            "presets": [p["id"] for p in candidate.get("presets") or []],
            "direction": candidate.get("direction"),
        },
        "opportunity_candidate": parsed.model_dump(mode="json"),
        "opportunity_candidate_gate": gate.model_dump(mode="json"),
        **parsed.model_dump(mode="json"),
    }
