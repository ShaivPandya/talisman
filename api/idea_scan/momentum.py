"""Directional, fixed-credit momentum used only by Idea Digests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

import numpy as np
import pandas as pd

from utils.market_freshness import expected_market_date

MOMENTUM_VERSION: Literal[2] = 2
LOOKBACK_SESSIONS = 63
MomentumRequirement = Literal["either", "both", "absolute", "relative"]
STATE_COLUMNS = ("momentum_absolute_state", "momentum_relative_state")


@lru_cache(maxsize=16)
def _sessions(end: str) -> pd.DatetimeIndex:
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XNYS")
    return calendar.sessions_in_range(pd.Timestamp(end) - pd.Timedelta(days=150), end)[-(LOOKBACK_SESSIONS + 1) :]


def _return(close: pd.Series | None, sessions: pd.DatetimeIndex) -> tuple[float | None, str | None]:
    if close is None or close.empty:
        return None, "No price history"
    values = pd.to_numeric(close, errors="coerce").copy()
    # Daily bars label exchange dates, even when the provider includes a timezone.
    values.index = pd.to_datetime(values.index).tz_localize(None).normalize()
    values = values[~values.index.duplicated(keep="last")].reindex(sessions)
    valid = values.notna() & np.isfinite(values) & (values > 0)
    if not valid.iloc[-1]:
        return None, f"No valid close for {sessions[-1].date()} (stale or missing)"
    if len(sessions) != LOOKBACK_SESSIONS + 1 or not valid.all():
        return None, "Insufficient valid history for 63 trading sessions"
    result = float((values.iloc[-1] / values.iloc[0] - 1) * 100)
    return (result, None) if np.isfinite(result) else (None, "Invalid return")


def state(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "unavailable"
    if abs(value) < 1e-10:
        return "flat"
    return "positive" if value > 0 else "negative"


def calculate_momentum(
    close: pd.Series, benchmark_close: pd.Series | None, benchmark: str, *, now: datetime | None = None
) -> dict[str, Any]:
    sessions = _sessions(expected_market_date(now).isoformat())
    absolute, absolute_reason = _return(close, sessions)
    benchmark_return, benchmark_reason = _return(benchmark_close, sessions)
    excess = absolute - benchmark_return if absolute is not None and benchmark_return is not None else None
    return {
        "momentum_version": MOMENTUM_VERSION,
        "momentum_lookback_sessions": LOOKBACK_SESSIONS,
        "momentum_start_date": sessions[0].date().isoformat(),
        "momentum_end_date": sessions[-1].date().isoformat(),
        "momentum_benchmark": benchmark,
        "return_3m": absolute,
        "momentum_benchmark_return": benchmark_return,
        "momentum_excess_return": excess,
        "momentum_absolute_state": state(absolute),
        "momentum_relative_state": state(excess),
        "momentum_absolute_reason": absolute_reason,
        "momentum_relative_reason": absolute_reason or benchmark_reason,
    }


def momentum_credit(frame: pd.DataFrame, direction: str) -> tuple[pd.Series, pd.Series]:
    """Return credit and observed coverage; a missing half is never reallocated."""
    target = "positive" if direction == "long" else "negative"
    credit = pd.Series(0.0, index=frame.index)
    coverage = credit.copy()
    for column in STATE_COLUMNS:
        values = frame.get(column, pd.Series("unavailable", index=frame.index))
        credit += values.eq(target).astype(float) * 0.5
        coverage += values.isin(["positive", "negative", "flat"]).astype(float) * 0.5
    return credit, coverage


def momentum_evidence(row: Mapping[str, Any] | pd.Series, direction: str) -> dict[str, Any]:
    target = "positive" if direction == "long" else "negative"

    def signal(kind: str, value_key: str) -> dict[str, Any]:
        status = row.get(f"momentum_{kind}_state", "unavailable")
        available = status in {"positive", "negative", "flat"}
        value = row.get(value_key)
        return {
            "state": status if available else "unavailable",
            "passes": status == target if available else None,
            "value": float(value) if value is not None and pd.notna(value) else None,
            "reason": row.get(f"momentum_{kind}_reason") if not available else None,
        }

    absolute = signal("absolute", "return_3m")
    relative = signal("relative", "momentum_excess_return")
    benchmark_return = row.get("momentum_benchmark_return")
    return {
        "version": MOMENTUM_VERSION,
        "lookback_sessions": LOOKBACK_SESSIONS,
        "start_date": row.get("momentum_start_date"),
        "end_date": row.get("momentum_end_date"),
        "benchmark": row.get("momentum_benchmark"),
        "benchmark_return": float(benchmark_return)
        if benchmark_return is not None and pd.notna(benchmark_return)
        else None,
        "absolute": absolute,
        "relative": relative,
        "credit": sum(s["passes"] is True for s in (absolute, relative)) * 0.5,
        "coverage": sum(s["passes"] is not None for s in (absolute, relative)) * 0.5,
    }


def evidence_lines(evidence: dict[str, Any], direction: str) -> list[str]:
    labels = (
        f"{'Up' if direction == 'long' else 'Down'} over 3 months",
        f"{'Outperforming' if direction == 'long' else 'Underperforming'} {evidence.get('benchmark') or 'benchmark'} over 3 months",
    )
    lines = []
    for kind, label, unit in zip(("absolute", "relative"), labels, ("%", " percentage points"), strict=True):
        signal = evidence[kind]
        result = "Unavailable" if signal["passes"] is None else ("Yes" if signal["passes"] else "No")
        detail = f"{signal['value']:+.2f}{unit}" if signal["value"] is not None else signal.get("reason")
        lines.append(f"{label}: {result}" + (f" ({detail})" if detail else ""))
    return lines


def momentum_check(row: pd.Series, direction: str, requirement: MomentumRequirement) -> tuple[str, bool, bool]:
    evidence = momentum_evidence(row, direction)
    signals = [
        evidence[k] for k in ("absolute", "relative") if requirement not in {"absolute", "relative"} or k == requirement
    ]
    # With OR, one known pass is sufficient even if the other signal is unavailable.
    passes = [s["passes"] for s in signals]
    ok = any(p is True for p in passes) if requirement == "either" else all(p is True for p in passes)
    known = ok or all(p is not None for p in passes)
    label = f"Momentum ({requirement}): " + "; ".join(evidence_lines(evidence, direction))
    return label, ok, known


def compatible_frame(frame: pd.DataFrame) -> bool:
    if frame.attrs.get("momentum_version") != MOMENTUM_VERSION:
        return False
    if frame.empty:
        return True
    return (
        all(c in frame.columns for c in STATE_COLUMNS)
        and "momentum_version" in frame.columns
        and frame["momentum_version"].eq(MOMENTUM_VERSION).all()
    )
