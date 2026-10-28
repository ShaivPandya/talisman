"""Per-run LLM spend tracking with a hard dollar limit for the idea scan.

Every provider response inside ``RunBudget.track`` is costed, including
pause-turn continuations and JSON repair calls (via
``llm_utils.observe_llm_responses``). Before a step starts, the caller asks
``can_start`` with an estimate; a step that would take spend past the limit is
skipped and reported instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

# USD per million tokens: input, output, cache read, cache write. Anthropic list prices as of 2026-10.
MODEL_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 1.0, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
    "gpt-6.1-sol": (2.50, 10.0, 0.25, 2.50),
}
# Unknown models are costed at the most expensive listed rate so the limit stays safe.
FALLBACK_PRICE = (10.0, 50.0, 1.0, 12.5)
WEB_SEARCH_USD = 0.01


def model_price(model: str) -> tuple[float, float, float, float]:
    name = str(model or "").lower()
    if name in MODEL_PRICES:
        return MODEL_PRICES[name]
    # Dated or prefixed ids ("anthropic.claude-opus-5-5", "claude-haiku-4-5-2025...") match the longest known prefix.
    matches = [key for key in MODEL_PRICES if key in name]
    return MODEL_PRICES[max(matches, key=len)] if matches else FALLBACK_PRICE


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.web_searches += other.web_searches


def usage_from_response(provider: str, response: Any) -> Usage:
    """Token and search counts from an Anthropic, OpenAI or Gemini response object."""
    if provider == "gemini":
        meta = _get(response, "usage_metadata")
        searches = 0
        for candidate in _get(response, "candidates", None) or []:
            grounding = _get(candidate, "grounding_metadata")
            searches += len(_get(grounding, "web_search_queries", None) or [])
        return Usage(
            input_tokens=_int(_get(meta, "prompt_token_count")),
            output_tokens=_int(_get(meta, "candidates_token_count")) + _int(_get(meta, "thoughts_token_count")),
            cache_read_tokens=_int(_get(meta, "cached_content_token_count")),
            web_searches=searches,
        )

    usage = _get(response, "usage")
    if provider in {"openai", "talisman"}:
        details = _get(usage, "input_tokens_details")
        cached = _int(_get(details, "cached_tokens"))
        searches = sum(1 for item in (_get(response, "output", None) or []) if _get(item, "type") == "web_search_call")
        return Usage(
            input_tokens=max(0, _int(_get(usage, "input_tokens")) - cached),
            output_tokens=_int(_get(usage, "output_tokens")),
            cache_read_tokens=cached,
            web_searches=searches,
        )

    server_tools = _get(usage, "server_tool_use")
    return Usage(
        input_tokens=_int(_get(usage, "input_tokens")),
        output_tokens=_int(_get(usage, "output_tokens")),
        cache_read_tokens=_int(_get(usage, "cache_read_input_tokens")),
        cache_write_tokens=_int(_get(usage, "cache_creation_input_tokens")),
        web_searches=_int(_get(server_tools, "web_search_requests")),
    )


def search_sources(response: Any) -> list[tuple[str, str]]:
    """(title, url) for every page a web search returned, plus any inline citations.

    Anthropic returns search hits as ``web_search_tool_result`` blocks; a JSON answer
    usually carries no inline citations, so the hits are what evidence is checked against.
    """
    from llm_utils import extract_citations

    found: list[tuple[str, str]] = list(extract_citations(response))
    for block in _get(response, "content", None) or []:
        if _get(block, "type") != "web_search_tool_result":
            continue
        results = _get(block, "content")
        for item in results if isinstance(results, list) else []:
            url = _get(item, "url")
            if isinstance(url, str) and url:
                found.append((str(_get(item, "title") or url), url))
    return found


def cost_usd(model: str, usage: Usage) -> float:
    price_in, price_out, price_read, price_write = model_price(model)
    return (
        usage.input_tokens * price_in
        + usage.output_tokens * price_out
        + usage.cache_read_tokens * price_read
        + usage.cache_write_tokens * price_write
    ) / 1_000_000 + usage.web_searches * WEB_SEARCH_USD


@dataclass
class StepRecord:
    step: str
    label: str
    model: str = ""
    provider: str = ""
    calls: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    sources: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "label": self.label,
            "model": self.model,
            "provider": self.provider,
            "calls": self.calls,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cache_read_tokens": self.usage.cache_read_tokens,
            "cache_write_tokens": self.usage.cache_write_tokens,
            "web_searches": self.usage.web_searches,
            "cost_usd": round(self.cost_usd, 6),
        }


class RunBudget:
    """Dollar limit for one scan run; tracks actual spend as responses arrive."""

    # Starting estimates per step until the run has observed real costs (issue TL-233's estimate, padded).
    PRIOR_ESTIMATES_USD = {"macro": 0.60, "review": 0.15, "digest": 0.10}
    # The next call of a step is assumed to cost this much more than the most expensive one so far.
    ESTIMATE_MARGIN = 1.25

    def __init__(self, limit_usd: float) -> None:
        self.limit_usd = float(limit_usd)
        self.records: list[StepRecord] = []
        self.skipped: list[dict[str, Any]] = []

    @property
    def spent_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def estimate(self, step: str) -> float:
        seen = [r.cost_usd for r in self.records if r.step == step and r.calls]
        prior = self.PRIOR_ESTIMATES_USD.get(step, 0.25)
        if not seen:
            return prior
        return max(seen) * self.ESTIMATE_MARGIN

    def can_start(self, step: str, *, reserve_usd: float = 0.0) -> bool:
        """True when this step's estimate fits under the limit, keeping ``reserve_usd`` for later steps."""
        return self.spent_usd + self.estimate(step) + reserve_usd <= self.limit_usd

    def skip(self, step: str, label: str, reason: str = "budget") -> None:
        self.skipped.append({"step": step, "label": label, "reason": reason})

    @contextmanager
    def track(self, step: str, label: str) -> Iterator[StepRecord]:
        from llm_utils import observe_llm_responses

        record = StepRecord(step=step, label=label)
        self.records.append(record)

        def observe(provider: str, model: str, response: Any) -> None:
            usage = usage_from_response(provider, response)
            record.calls += 1
            record.model = model
            record.provider = provider
            record.usage.add(usage)
            record.cost_usd += cost_usd(model, usage)
            seen = {url for _title, url in record.sources}
            for title, url in search_sources(response):
                if url not in seen:
                    seen.add(url)
                    record.sources.append((title, url))

        with observe_llm_responses(observe):
            yield record

    def summary(self) -> dict[str, Any]:
        searches = sum(r.usage.web_searches for r in self.records)
        return {
            "limit_usd": self.limit_usd,
            "spent_usd": round(self.spent_usd, 6),
            "remaining_usd": round(self.remaining_usd, 6),
            "web_searches": searches,
            "by_step": {
                step: round(sum(r.cost_usd for r in self.records if r.step == step), 6)
                for step in dict.fromkeys(r.step for r in self.records)
            },
            "entries": [r.to_dict() for r in self.records],
            "skipped": list(self.skipped),
        }
