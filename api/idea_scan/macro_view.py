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
MAX_OUTPUT_TOKENS = 8000
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


def _compact(value: Any, depth: int = 0) -> Any:
    """Keep a snapshot's shape and latest values while dropping long series."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {str(k): _compact(v, depth + 1) for k, v in list(value.items())[:40] if k != "raw_modules"}
    if isinstance(value, list):
        tail = value[-3:] if len(value) > 3 else value
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
        if not isinstance(payload, dict):
            continue
        meta = (payload.get("_meta") or {}).get("snapshot") or {}
        body = {k: v for k, v in payload.items() if k != "_meta"}
        text = json.dumps(_compact(body), default=str, separators=(",", ":"))
        if len(text) > SNAPSHOT_CHAR_LIMIT:
            text = text[:SNAPSHOT_CHAR_LIMIT] + "…"
        out.append(
            {"key": key, "as_of": meta.get("as_of") or meta.get("fetched_at"), "stale": meta.get("stale"), "text": text}
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
- summary is two or three sentences on the overall backdrop.
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


def validate_rows(
    raw_rows: Any,
    *,
    snapshot_keys: set[str],
    citation_urls: list[str],
    previous_scores: dict[str, int],
    digest_stories: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    digest_stories = digest_stories or {}
    cited = {_normalize_url(u) for u in citation_urls if u}
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
        evidence: list[dict[str, Any]] = []
        for item in raw.get("evidence") or []:
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
                if not normalized or not any(
                    normalized == c or normalized.startswith(c) or c.startswith(normalized) for c in cited
                ):
                    continue
            else:
                continue
            evidence.append({"type": kind, "ref": ref, "detail": str(item.get("detail") or "")[:300], **extra})
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
    snapshots = gather_snapshots() if snapshots is None else snapshots
    digest_text, stories = _digest_block((news or {}).get("stories") or [])
    cited_digests = {s["ref"].split("/", 1)[0] for s in stories}
    base = {
        "as_of": datetime.now(UTC).isoformat(),
        "rows": [],
        "dropped": [],
        "sources": [],
        "summary": "",
        "snapshots": [{"key": s["key"], "as_of": s.get("as_of"), "stale": s.get("stale")} for s in snapshots],
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
        snapshot_keys={s["key"] for s in snapshots},
        citation_urls=urls,
        previous_scores=previous_scores,
        digest_stories={s["ref"]: s for s in stories},
    )
    return {
        **base,
        "status": "ok",
        "model": record.model,
        "provider": record.provider,
        "summary": str(parsed.get("summary") or "")[:1200],
        "rows": rows,
        "dropped": dropped,
        "sources": [{"title": title, "url": url} for title, url in returned],
    }
