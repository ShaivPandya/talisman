"""Industry evidence for the digest, refreshed within its existing dollar budget."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from api.idea_scan.budget import RunBudget

LOGGER = logging.getLogger(__name__)
INDUSTRY_KEY = "industry_monitor:current:v1"


def gather_industry_monitor(
    budget: RunBudget, *, reserve_usd: float, load: Callable[..., dict[str, Any]] | None = None
) -> dict[str, Any]:
    from macro.industry.industry_monitor import get_data, summarize_with_llm

    load = load or get_data
    refreshed = False
    warning = ""

    def summarize(text: str, meta: dict) -> dict | None:
        label = f"Industry Monitor: {meta['ticker']}"
        if not budget.can_start("industry", reserve_usd=reserve_usd):
            budget.skip("industry", label)
            return None
        with budget.track("industry", label):
            return summarize_with_llm(text, meta)

    def read(**kwargs: Any) -> dict[str, Any]:
        payload = load(**kwargs)
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Industry Monitor unavailable")
        return payload

    try:
        data = read(refresh=False)
    except Exception:
        LOGGER.warning("Industry Monitor read failed", exc_info=True)
        data = {}
    companies = [c for s in data.get("by_sector", {}).values() for c in s.get("companies", [])]
    if not companies or any(
        c.get("is_stale") or c.get("missing_data") or not c.get("summary_available") for c in companies
    ):
        try:
            data = read(refresh=True, summarize=summarize)
            refreshed = True
        except Exception:
            LOGGER.warning("Industry Monitor refresh failed; retaining dated evidence", exc_info=True)
            warning = "Refresh failed; any retained evidence is from the previous monitor read."

    sectors = {}
    dates = []
    stale = False
    available = 0
    for name, sector in data.get("by_sector", {}).items():
        rows = []
        for company in sector.get("companies", []):
            usable = not company.get("missing_data") and bool(company.get("summary_available"))
            row = {
                k: company.get(k)
                for k in ("ticker", "call_date", "transcript_date", "age_days", "is_stale", "missing_data")
            }
            row["summary_available"] = usable
            if usable:
                available += 1
                date = company.get("call_date") or company.get("transcript_date")
                if date:
                    dates.append(date)
                for key in ("summary_headline", "demand_trends", "pricing_commentary", "guidance_outlook"):
                    row[key] = str(company.get(key) or "")[:350]
            stale = stale or bool(company.get("is_stale")) or not usable
            rows.append(row)
        # Don't propagate aggregate signals computed from placeholder summaries.
        sectors[name] = rows
    if stale:
        warning = (
            warning
            + " Some transcripts are stale, missing, or lack a usable summary; do not infer a current signal from them."
        ).strip()
    body = {"by_sector": sectors, "warning": warning}
    return {
        "key": INDUSTRY_KEY,
        # last_updated is the time of the read, not the age of its evidence.
        "as_of": max(dates, default=None),
        "stale": stale or not available,
        "available": bool(available),
        "refreshed": refreshed,
        "warning": warning or ("No usable Industry Monitor summaries available." if not available else ""),
        "text": json.dumps(body, default=str, separators=(",", ":")),
    }
