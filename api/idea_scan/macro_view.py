"""Weekly sector macro view: one high-tier LLM call over the latest macro snapshots.

The model scores each sector from -2 to +2, reading the snapshots alongside
recent stories from the user's uploaded news digests. Rows are checked here,
not trusted: every row must cite a snapshot or digest story we supplied or a
URL the search returned, and a score that moved from last week must say why. Rows that fail
are dropped and listed. ``origin`` lets hand-written ``rule`` rows join later
without changing anything downstream.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from api import snapshot_keys as keys
from api.idea_scan.budget import RunBudget
from api.idea_scan.macro_inputs import INDUSTRY_KEY, gather_industry_monitor

LOGGER = logging.getLogger(__name__)

# yfinance `sector` names, which is what candidates carry.
SECTORS = (
    "Basic Materials",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Energy",
    "Financial Services",
    "Healthcare",
    "Industrials",
    "Real Estate",
    "Technology",
    "Utilities",
)
SECTOR_ALIASES = {
    "materials": "Basic Materials",
    "communication": "Communication Services",
    "communications": "Communication Services",
    "telecommunication services": "Communication Services",
    "consumer discretionary": "Consumer Cyclical",
    "consumer staples": "Consumer Defensive",
    "financials": "Financial Services",
    "financial": "Financial Services",
    "health care": "Healthcare",
    "information technology": "Technology",
    "tech": "Technology",
}

MACRO_SNAPSHOT_KEYS = (
    keys.SNAPSHOT_ECONOMIC_BACKDROP,
    keys.SNAPSHOT_ECONOMIC_GROWTH,
    keys.SNAPSHOT_LABOR_MARKET,
    keys.SNAPSHOT_HOUSING,
    keys.SNAPSHOT_LIQUIDITY,
    keys.SNAPSHOT_SENTIMENT,
    keys.SNAPSHOT_POSITIONING_SUMMARY,
    keys.SNAPSHOT_SECTOR_METRICS,
    keys.SNAPSHOT_VIX_TERM_STRUCTURE,
    keys.SNAPSHOT_MARKET_BREADTH,
)
SNAPSHOT_CHAR_LIMIT = 2500
DIGEST_MAX_DIGESTS = 7
DIGEST_MAX_STORIES = 40
DIGEST_CHAR_LIMIT = 12000
DIGEST_TEXT_CHARS = 240
MAX_OUTPUT_TOKENS = 10000
REASONING_EFFORT = "medium"

MACRO_VIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sector": {"type": "string"},
                    "score": {"type": "integer"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reason": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["snapshot", "digest", "search"]},
                                "ref": {"type": "string"},
                                "detail": {"type": "string"},
                            },
                            "required": ["type", "ref", "detail"],
                            "additionalProperties": False,
                        },
                    },
                    "change_explanation": {"type": "string"},
                },
                "required": ["sector", "score", "confidence", "reason", "evidence", "change_explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "rows"],
    "additionalProperties": False,
}

EVIDENCE_SCHEMA = MACRO_VIEW_SCHEMA["properties"]["rows"]["items"]["properties"]["evidence"]
APPROACHES = {
    "industry_monitor": "Industry Monitor",
    "market_prices": "Economic growth dashboard",
    "economic_indicators": "Economic indicators",
    "news": "News and other market drivers",
}
APPROACH_SCHEMA = {
    "type": "object",
    "properties": {
        "signal": {"type": "string"},
        "interpretation": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "caveats": {"type": "string"},
        "evidence": EVIDENCE_SCHEMA,
    },
    "required": ["signal", "interpretation", "confidence", "caveats", "evidence"],
    "additionalProperties": False,
}
MACRO_VIEW_SCHEMA["properties"].update(
    {
        "approaches": {
            "type": "object",
            "properties": {key: APPROACH_SCHEMA for key in APPROACHES},
            "required": list(APPROACHES),
            "additionalProperties": False,
        },
        "synthesis": {
            "type": "object",
            "properties": {
                "outlook": {"type": "string"},
                "horizon": {"type": "string"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                "agreements": {"type": "string"},
                "conflicts": {"type": "string"},
                "watchpoints": {"type": "array", "items": {"type": "string"}},
                "evidence": EVIDENCE_SCHEMA,
            },
            "required": ["outlook", "horizon", "confidence", "agreements", "conflicts", "watchpoints", "evidence"],
            "additionalProperties": False,
        },
    }
)
MACRO_VIEW_SCHEMA["required"] += ["approaches", "synthesis"]

SYSTEM_PROMPT = (
    "You are a macro strategist preparing a weekly sector backdrop for an equity research team. "
    "The output only decides which screened names get a closer look; it is not a trade recommendation. "
    "Be specific, cite evidence for every claim, and say plainly when the data is mixed."
)


def normalize_sector(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    for sector in SECTORS:
        if text.lower() == sector.lower():
            return sector
    return SECTOR_ALIASES.get(text.lower())


def _compact(value: Any, depth: int = 0, *, field: str = "") -> Any:
    """Keep a snapshot's shape and latest values while dropping long series."""
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        return {str(k): _compact(v, depth + 1, field=str(k)) for k, v in list(value.items())[:40] if k != "raw_modules"}
    if isinstance(value, list):
        tail = value[:40] if field == "readings" else value[-3:]
        return [_compact(v, depth + 1) for v in tail]
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…"
    return value


def gather_snapshots(read: Callable[[str], Any] | None = None) -> list[dict[str, Any]]:
    """Latest macro snapshots as compact JSON text, keyed so rows can cite them."""
    if read is None:
        from api.snapshot_store import get_snapshot_response

        def read(key: str) -> Any:
            return get_snapshot_response(key, include_raw_modules=False)

    out: list[dict[str, Any]] = []
    for key in MACRO_SNAPSHOT_KEYS:
        try:
            payload = read(key)
        except Exception:
            LOGGER.warning("Macro snapshot %s unreadable", key, exc_info=True)
            continue
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        meta = (payload.get("_meta") or {}).get("snapshot") or {}
        body = {k: v for k, v in payload.items() if k != "_meta"}
        # Keep every dashboard asset class and indicator reading. A single prefix
        # cap used to lose currencies and all but the last three indicators.
        if key == keys.SNAPSHOT_ECONOMIC_GROWTH:
            groups = (
                "equities",
                "equity_relative_returns",
                "currencies",
                "commodities",
                "benchmarks",
                "crb_available",
                "crb_latest_date",
                "timestamp",
            )
            body = {k: body[k] for k in groups if k in body}
        text = json.dumps(_compact(body), default=str, separators=(",", ":"))
        if (
            key not in {keys.SNAPSHOT_ECONOMIC_GROWTH, keys.SNAPSHOT_ECONOMIC_BACKDROP}
            and len(text) > SNAPSHOT_CHAR_LIMIT
        ):
            text = text[:SNAPSHOT_CHAR_LIMIT] + "…"
        out.append(
            {
                "key": key,
                "as_of": meta.get("as_of") or meta.get("fetched_at"),
                "stale": True if meta.get("refresh_status") not in (None, "ok") else meta.get("stale"),
                "text": text,
            }
        )
    return out


def gather_digest_stories(days: int, load: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Recent stories from the user's news digests, each with a ref rows can cite.

    Only digests generated within ``days`` count; an older digest is never used
    as a stand-in, since stale news would read as this week's backdrop.
    """
    if load is None:
        from portfolio.news_digests import get_report_context

        load = get_report_context
    context = load(
        days=days,
        max_digests=DIGEST_MAX_DIGESTS,
        max_stories=DIGEST_MAX_STORIES,
        notes_per_story=1,
        max_text_chars=DIGEST_TEXT_CHARS,
    )
    out: dict[str, Any] = {"window_days": days, "digests": [], "stories": []}
    if context.get("fallback_used"):
        return out
    for digest in context.get("digests") or []:
        digest_id = str(digest.get("id") or "")
        used = False
        for section in digest.get("sections") or []:
            for story in section.get("stories") or []:
                if not digest_id or not story.get("id") or not story.get("headline"):
                    continue
                out["stories"].append(
                    {
                        "ref": f"{digest_id}/{story['id']}",
                        "date": digest.get("generated_date"),
                        "section": section.get("name"),
                        "headline": story["headline"],
                        # One line on why it matters: the digest's implication, else its first note.
                        "takeaway": story.get("implication") or (story.get("notes") or [""])[0],
                        "top_rank": story.get("top_rank"),
                        "multi_signal": bool(story.get("multi_signal")),
                        "confidence": story.get("confidence"),
                    }
                )
                used = True
        if used:
            out["digests"].append(
                {"id": digest_id, "title": digest.get("title"), "generated_date": digest.get("generated_date")}
            )
    # Strongest stories first, so the size cap drops the weakest: Top N, then multi-signal, then confidence.
    out["stories"].sort(
        key=lambda s: (
            s["top_rank"] is None,
            s["top_rank"] or 0,
            not s["multi_signal"],
            -(s["confidence"] or 0.0),
        )
    )
    return out


def _digest_block(stories: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Prompt text for the digest stories and the stories that fit under the size cap."""
    lines: list[str] = []
    kept: list[dict[str, Any]] = []
    used = 0
    for story in stories:
        text = f"[digest:{story['ref']}] {story.get('date')} · {story.get('section')}: {story['headline']}"
        if story.get("takeaway"):
            text += f"\n  {story['takeaway']}"
        if used + len(text) > DIGEST_CHAR_LIMIT:
            continue
        lines.append(text)
        kept.append(story)
        used += len(text) + 1
    return "\n".join(lines), kept


def build_prompt(
    snapshots: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    *,
    searches: int,
    digest_text: str = "",
) -> str:
    previous = (
        "\n".join(
            f"- {r.get('sector')}: score {r.get('score')}, confidence {r.get('confidence')} — {r.get('reason')}"
            for r in previous_rows
        )
        or "- None (first week)."
    )
    snapshot_text = (
        "\n\n".join(
            f"[snapshot:{s['key']}] as_of={s.get('as_of')}{' (stale)' if s.get('stale') else ''}\n{s['text']}"
            for s in snapshots
        )
        or "(no snapshots available)"
    )
    return f"""Score each sector's macro backdrop for US equities over the next few weeks.

Sectors (use these exact names): {", ".join(SECTORS)}.
The sector_metrics snapshot uses sector ETFs (XLK = Technology, XLF = Financial Services, XLV = Healthcare,
XLY = Consumer Cyclical, XLP = Consumer Defensive, XLC = Communication Services, XLB = Basic Materials,
XLE = Energy, XLI = Industrials, XLRE = Real Estate, XLU = Utilities).

Rules:
- score is an integer from -2 (strong headwind) to +2 (strong tailwind); 0 means neutral or mixed.
- confidence is low, medium or high.
- reason is one line, under 200 characters.
- evidence needs at least one item per row. Use {{"type": "snapshot", "ref": "<snapshot key>", "detail": "<the data point>"}}
  for a value from the snapshots below, {{"type": "digest", "ref": "<id inside digest:[...]>", "detail": "<the point it makes>"}}
  for a story from the news digests below, or {{"type": "search", "ref": "<url>", "detail": "<what it says>"}} for a page you found.
  A row without evidence will be discarded.
- change_explanation: if the score differs from last week's, explain what changed. Otherwise use an empty string.
- The news digests are the research team's own curated reading. Weigh them alongside the data: they often
  carry credit, policy and industry developments the snapshots can't show yet. A story is evidence about a
  sector only when it bears on that sector directly.
- You may run up to {searches} web searches for recent developments the snapshots and digests don't cover.
- Build approaches with all four sections below, keeping observed facts (signal) separate from
  interpretation. Each section needs its own supplied evidence, confidence and caveats. If its
  source is absent, stale or incomplete, say so; never invent a signal to fill a section.
  1. industry_monitor: What do earnings-call demand, pricing and guidance across Housing, Trucking,
     Banks, Retail and Capital Goods say about the economy? Use industry_monitor:current:v1.
     Respect individual transcript dates, summary_available and refresh warnings; a refresh does
     not make an old transcript current. Do not extrapolate one company to the whole economy.
  2. market_prices: What does price action in the economic_growth dashboard's equity indices,
     benchmark-relative returns, currencies and commodities imply? Compare time windows, breadth
     and cross-asset agreement. Explain currency quote direction. Separate growth/inflation/rates
     expectations from risk appetite; a price move alone does not establish its cause.
  3. economic_indicators: Cross-check market-implied expectations against economic_backdrop, labor,
     housing and liquidity observations. Preserve observation dates, release lags and units;
     distinguish actual data from publisher nowcasts/forecasts. Note confirmation and disagreement.
  4. news: Use dated digest stories and verified search results to explain alternative causes of
     price moves: supply disruptions, geopolitics, policy, positioning, flows, index concentration,
     earnings or one-off events. Distinguish an evidenced driver from an unconfirmed hypothesis.
     Investors are not always forecasting the macro when markets move.
- synthesis combines the four approaches into a conditional broader economic outlook, with a
  stated horizon, confidence, agreements, conflicts and specific watchpoints that would confirm,
  invalidate or change the view. Explain unresolved contradictions instead of averaging them away.
  Account for common underlying evidence rather than counting correlated signals as independent.
  Include evidence from the approaches used. Lower conviction when key sources are missing/stale.
- summary is two or three sentences summarizing that consolidated outlook.
- Do not recommend buying, selling or shorting anything.

Last week's view:
{previous}

Latest snapshots:
{snapshot_text}

Recent news digest stories:
{digest_text or "(none this week)"}
"""


def _normalize_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def validate_evidence(
    raw_evidence: Any,
    *,
    snapshot_keys: set[str],
    citation_urls: list[str],
    digest_stories: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    digest_stories = digest_stories or {}
    cited = {_normalize_url(u) for u in citation_urls if u}
    evidence: list[dict[str, Any]] = []
    for item in raw_evidence if isinstance(raw_evidence, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        ref = str(item.get("ref") or "").strip()
        extra: dict[str, Any] = {}
        if kind == "snapshot":
            ref = ref.removeprefix("snapshot:")
            if ref not in snapshot_keys:
                continue
        elif kind == "digest":
            ref = ref.removeprefix("digest:")
            story = digest_stories.get(ref)
            if story is None:
                continue
            extra = {"headline": story["headline"], "date": story.get("date")}
        elif kind == "search":
            normalized = _normalize_url(ref)
            if not normalized or normalized not in cited or urlsplit(ref).scheme not in {"http", "https"}:
                continue
        else:
            continue
        evidence.append({"type": kind, "ref": ref, "detail": str(item.get("detail") or "")[:300], **extra})
    return evidence


def validate_rows(
    raw_rows: Any,
    *,
    snapshot_keys: set[str],
    citation_urls: list[str],
    previous_scores: dict[str, int],
    digest_stories: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    digest_stories = digest_stories or {}
    rows: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(raw, dict):
            continue
        sector = normalize_sector(raw.get("sector"))
        label = str(raw.get("sector") or "?")
        if sector is None:
            dropped.append({"sector": label, "reason": "unknown sector"})
            continue
        if sector in seen:
            dropped.append({"sector": sector, "reason": "duplicate row"})
            continue
        try:
            score = int(raw["score"])
        except (KeyError, TypeError, ValueError):
            dropped.append({"sector": sector, "reason": "score is not an integer"})
            continue
        if not -2 <= score <= 2:
            dropped.append({"sector": sector, "reason": "score outside -2..+2"})
            continue
        evidence = validate_evidence(
            raw.get("evidence"),
            snapshot_keys=snapshot_keys,
            citation_urls=citation_urls,
            digest_stories=digest_stories,
        )
        if not evidence:
            dropped.append({"sector": sector, "reason": "no verifiable evidence"})
            continue
        previous = previous_scores.get(sector)
        explanation = str(raw.get("change_explanation") or "").strip()
        if previous is not None and previous != score and not explanation:
            dropped.append({"sector": sector, "reason": "score changed without an explanation"})
            continue
        confidence = str(raw.get("confidence") or "low").lower()
        seen.add(sector)
        rows.append(
            {
                "sector": sector,
                "score": score,
                "previous_score": previous,
                "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
                "reason": str(raw.get("reason") or "")[:240],
                "evidence": evidence,
                "change_explanation": explanation[:400] if previous is not None and previous != score else "",
                "origin": "llm",
            }
        )
    rows.sort(key=lambda r: SECTORS.index(r["sector"]))
    return rows, dropped


def validate_breakdown(
    parsed: dict[str, Any],
    *,
    snapshots: list[dict[str, Any]],
    urls: list[str],
    stories: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    available = {s["key"] for s in snapshots if s.get("available") is not False}
    by_key = {s["key"]: s for s in snapshots}
    families = {
        "industry_monitor": {INDUSTRY_KEY},
        "market_prices": {
            keys.SNAPSHOT_ECONOMIC_GROWTH,
            keys.SNAPSHOT_SECTOR_METRICS,
            keys.SNAPSHOT_MARKET_BREADTH,
            keys.SNAPSHOT_VIX_TERM_STRUCTURE,
        },
        "economic_indicators": {
            keys.SNAPSHOT_ECONOMIC_BACKDROP,
            keys.SNAPSHOT_LABOR_MARKET,
            keys.SNAPSHOT_HOUSING,
            keys.SNAPSHOT_LIQUIDITY,
        },
        "news": set(),
    }
    raw_approaches = parsed.get("approaches")
    raw_approaches = raw_approaches if isinstance(raw_approaches, dict) else {}
    sections = []
    for key, title in APPROACHES.items():
        raw = raw_approaches.get(key)
        raw = raw if isinstance(raw, dict) else {}
        evidence = validate_evidence(
            raw.get("evidence"),
            snapshot_keys=available & families[key],
            citation_urls=urls if key == "news" else [],
            digest_stories={s["ref"]: s for s in stories} if key == "news" else {},
        )
        # The price-action approach must actually read the growth dashboard.
        if key == "market_prices" and not any(e["ref"] == keys.SNAPSHOT_ECONOMIC_GROWTH for e in evidence):
            evidence = []
        source_rows = [by_key[e["ref"]] for e in evidence if e["type"] == "snapshot"]
        warnings = [
            s.get("warning") or f"{s['key']}: stale source data."
            for s in source_rows
            if s.get("warning") or s.get("stale")
        ]
        if key == "industry_monitor" and not evidence and INDUSTRY_KEY in by_key:
            warnings.append(by_key[INDUSTRY_KEY].get("warning") or "Industry Monitor evidence unavailable.")
        confidence = raw.get("confidence")
        sections.append(
            {
                "key": key,
                "title": title,
                "status": "ok" if evidence else "unavailable",
                "signal": str(raw.get("signal") or "")[:1200]
                if evidence
                else "No verifiable evidence available for this approach.",
                "interpretation": str(raw.get("interpretation") or "")[:1600] if evidence else "",
                "confidence": confidence if confidence in {"medium", "high"} and evidence and not warnings else "low",
                "caveats": " ".join([str(raw.get("caveats") or "")[:1000] if evidence else "", *warnings]).strip(),
                "evidence": evidence,
                "sources": [
                    {k: source.get(k) for k in ("key", "as_of", "stale", "refreshed", "warning")}
                    for source in source_rows
                ],
            }
        )
    raw = parsed.get("synthesis")
    synthesis: dict[str, Any] | None = None
    if isinstance(raw, dict):
        evidence = validate_evidence(
            raw.get("evidence"),
            snapshot_keys=available,
            citation_urls=urls,
            digest_stories={s["ref"]: s for s in stories},
        )
        if evidence and str(raw.get("outlook") or "").strip():
            confidence = raw.get("confidence")
            incomplete = any(s["status"] != "ok" or s["confidence"] == "low" for s in sections)
            synthesis = {k: str(raw.get(k) or "")[:1800] for k in ("outlook", "horizon", "agreements", "conflicts")}
            synthesis.update(
                {
                    "confidence": confidence if confidence in {"medium", "high"} and not incomplete else "low",
                    "watchpoints": [str(w)[:600] for w in raw.get("watchpoints", [])[:8]]
                    if isinstance(raw.get("watchpoints"), list)
                    else [],
                    "evidence": evidence,
                }
            )
    return sections, synthesis


def resolve_effort(tier: str, preferred: str) -> tuple[str | None, str | None]:
    """The provider for ``tier`` and ``preferred`` effort if that provider/model accepts it."""
    from llm_utils import model_for_tier, reasoning_effort_options, selected_provider_for_tier

    try:
        provider = selected_provider_for_tier(tier)
        model = model_for_tier(tier, provider)
        return provider, preferred if preferred in reasoning_effort_options(provider, model) else None
    except Exception:
        return None, None


def run_macro_view(
    *,
    budget: RunBudget,
    previous_view: dict[str, Any] | None,
    searches: int,
    reserve_usd: float,
    snapshots: list[dict[str, Any]] | None = None,
    news: dict[str, Any] | None = None,
    call: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    from llm_utils import MODEL_HIGH, call_llm_json

    call = call or call_llm_json
    previous_rows = [r for r in (previous_view or {}).get("rows") or [] if isinstance(r, dict)]
    previous_scores = {
        str(r["sector"]): int(r["score"]) for r in previous_rows if r.get("sector") and r.get("score") is not None
    }
    if snapshots is None:
        snapshots = gather_snapshots()
        if budget.can_start("macro", reserve_usd=reserve_usd):
            snapshots = [
                *snapshots,
                gather_industry_monitor(budget, reserve_usd=reserve_usd + budget.estimate("macro")),
            ]
    digest_text, stories = _digest_block((news or {}).get("stories") or [])
    cited_digests = {s["ref"].split("/", 1)[0] for s in stories}
    base = {
        "as_of": datetime.now(UTC).isoformat(),
        "rows": [],
        "dropped": [],
        "sources": [],
        "summary": "",
        "approaches": [],
        "synthesis": None,
        "snapshots": [
            {k: s.get(k) for k in ("key", "as_of", "stale", "available", "refreshed", "warning")} for s in snapshots
        ],
        "previous_scores": previous_scores,
        # None when digests were turned off or could not be read; otherwise what the prompt carried.
        "news": None
        if news is None
        else {
            "window_days": news.get("window_days"),
            "digests": [d for d in news.get("digests") or [] if d.get("id") in cited_digests],
            "stories": len(stories),
        },
        "error": None,
    }
    if not budget.can_start("macro", reserve_usd=reserve_usd):
        budget.skip("macro", "Sector macro view")
        return {**base, "status": "skipped", "error": "Not run: the run budget could not cover it."}

    provider, effort = resolve_effort(MODEL_HIGH, REASONING_EFFORT)
    prompt = build_prompt(snapshots, previous_rows, searches=searches, digest_text=digest_text)
    try:
        with budget.track("macro", "Sector macro view") as record:
            parsed, citations, _response, diagnostics = call(
                prompt=prompt,
                model=MODEL_HIGH,
                provider=provider,
                system=SYSTEM_PROMPT,
                max_tokens=MAX_OUTPUT_TOKENS,
                enable_web_search=searches > 0,
                max_web_search_uses=max(1, searches),
                reasoning_effort=effort,
                json_schema=MACRO_VIEW_SCHEMA,
                json_schema_name="sector_macro_view",
            )
    except Exception as exc:
        LOGGER.warning("Macro view call failed", exc_info=True)
        return {**base, "status": "failed", "error": f"Macro view call failed: {type(exc).__name__}"}

    if not isinstance(parsed, dict):
        reason = (diagnostics or {}).get("failure_reason") or "no JSON returned"
        return {**base, "status": "failed", "model": record.model, "error": f"Macro view unusable: {reason}"}

    returned = list({url: (title, url) for title, url in [*(citations or []), *record.sources]}.values())
    urls = [url for _title, url in returned]
    rows, dropped = validate_rows(
        parsed.get("rows"),
        snapshot_keys={s["key"] for s in snapshots if s.get("available") is not False},
        citation_urls=urls,
        previous_scores=previous_scores,
        digest_stories={s["ref"]: s for s in stories},
    )
    approaches, synthesis = validate_breakdown(parsed, snapshots=snapshots, urls=urls, stories=stories)
    return {
        **base,
        "status": "ok",
        "approaches": approaches,
        "synthesis": synthesis,
        "model": record.model,
        "provider": record.provider,
        "summary": str(parsed.get("summary") or "")[:1200],
        "rows": rows,
        "dropped": dropped,
        "sources": [{"title": title, "url": url} for title, url in returned],
    }
