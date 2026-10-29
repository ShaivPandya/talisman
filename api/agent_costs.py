"""Saved, standard-rate USD estimates for the model calls behind a chat reply.

Rates verified 2026-10-29. These exclude tool/provider fees and background jobs;
unknown models or missing usage never silently become a zero-dollar estimate.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class TokenRates:
    input: float
    output: float
    cache_read: float
    cache_write: float
    cache_write_long: float


# USD per million tokens. Only exact IDs and their dated snapshots are matched.
# https://developers.openai.com/api/docs/models/gpt-6-luna
# https://developers.openai.com/api/docs/models/gpt-6.1-sol
# https://developers.openai.com/api/docs/models/gpt-5.4-mini
# https://platform.claude.com/docs/en/about-claude/pricing
# https://ai.google.dev/gemini-api/docs/pricing
# https://ai.google.dev/gemini-api/docs/latest-model
TOKEN_RATES = {
    ("openai", "gpt-5.4-mini"): TokenRates(0.75, 4.50, 0.075, 0.75, 0.75),
    ("openai", "gpt-6-luna"): TokenRates(0.10, 0.50, 0.01, 0.125, 0.25),
    ("openai", "gpt-6.1-sol"): TokenRates(2.0, 10.0, 0.10, 2.50, 5.0),
    ("anthropic", "claude-haiku-4-5"): TokenRates(1.0, 5.0, 0.10, 1.25, 2.0),
    ("anthropic", "claude-sonnet-5-5"): TokenRates(2.0, 10.0, 0.10, 2.50, 4.0),
    ("anthropic", "claude-opus-5-5"): TokenRates(4.0, 20.0, 0.20, 5.0, 8.0),
    ("gemini", "gemini-3.1-flash-lite"): TokenRates(0.25, 1.50, 0.025, 0.25, 0.25),
    ("gemini", "gemini-4-argon"): TokenRates(2.0, 10.0, 0.10, 2.0, 2.0),
}


def _tokens(call: Mapping[str, Any], key: str) -> int | None:
    value = call.get(key)
    return value if type(value) is int and value >= 0 else None


def _call_cost(call: Mapping[str, Any], now: datetime) -> Decimal | None:
    incoming, outgoing = _tokens(call, "input_tokens"), _tokens(call, "output_tokens")
    if incoming is None or outgoing is None:
        return None
    provider = str(call.get("provider") or "")
    model = re.sub(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$", "", str(call.get("model") or ""))
    rates = TOKEN_RATES.get((provider, model))
    if rates is None:
        return None
    if model == "gemini-4-argon" and now.date().isoformat() >= "2026-12-01":
        rates = TokenRates(4.0, 20.0, 0.20, 4.0, 4.0)
    read = _tokens(call, "cache_read_input_tokens") or 0
    write = _tokens(call, "cache_creation_input_tokens") or 0
    long_write = _tokens(call, "cache_creation_long_input_tokens") or 0
    if read + write > incoming or long_write > write:
        return None
    # OpenAI's long-context rates apply to the entire request, independently per call.
    long_context = provider == "openai" and model in {"gpt-6-luna", "gpt-6.1-sol"} and incoming > 272_000
    input_multiplier, output_multiplier = (2, Decimal("1.5")) if long_context else (1, Decimal(1))
    input_cost = (
        Decimal(incoming - read - write) * Decimal(str(rates.input))
        + Decimal(read) * Decimal(str(rates.cache_read))
        + Decimal(write - long_write) * Decimal(str(rates.cache_write))
        + Decimal(long_write) * Decimal(str(rates.cache_write_long))
    ) * input_multiplier
    return (input_cost + Decimal(outgoing) * Decimal(str(rates.output)) * output_multiplier) / 1_000_000


def agent_turn_cost(model_calls: Sequence[Mapping[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """Price each round with its own model and cache usage, including reported retry usage."""
    now = now or datetime.now(UTC)
    calls = [call for call in model_calls if call.get("status") != "denied"]
    costs = [_call_cost(call, now) for call in calls]
    priced = [cost for cost in costs if cost is not None]
    complete = len(priced) == len(calls)
    return {
        "estimated_usd": float(sum(priced, Decimal(0))) if priced or not calls else None,
        "currency": "USD",
        "complete": complete,
        "model_calls": len(calls),
        "priced_model_calls": len(priced),
        "input_tokens": sum(_tokens(call, "input_tokens") or 0 for call in calls),
        "output_tokens": sum(_tokens(call, "output_tokens") or 0 for call in calls),
        "cache_read_input_tokens": sum(_tokens(call, "cache_read_input_tokens") or 0 for call in calls),
        "pricing_version": "2026-10-29",
    }
