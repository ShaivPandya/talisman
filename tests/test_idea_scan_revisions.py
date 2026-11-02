"""EPS coverage, actual request pacing, recoverable failures and durable cache reuse."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from api.idea_scan import data as d

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "_LOCAL_ROOT", tmp_path / "datasets")
    clock = SimpleNamespace(value=0.0)
    sleeps = []
    calls = []
    responses = {}

    def sleep(seconds):
        sleeps.append(seconds)
        clock.value += seconds

    def ticker(symbol):
        calls.append((symbol, clock.value))
        choices = responses.get(symbol, [])
        value = choices.pop(0) if choices else -0.05
        if isinstance(value, Exception):
            raise value
        trend = (
            pd.DataFrame({"current": [1 + value], "30daysAgo": [1.0]}, index=["0y"])
            if value is not None
            else pd.DataFrame()
        )
        return SimpleNamespace(eps_trend=trend)

    monkeypatch.setattr(d, "time", SimpleNamespace(monotonic=lambda: clock.value))
    monkeypatch.setattr(d, "_sleep", sleep)
    monkeypatch.setattr(d, "REVISION_CALL_INTERVAL_S", 0.5)
    monkeypatch.setattr(d, "RATE_LIMIT_RETRIES", 3)
    monkeypatch.setattr(d, "RATE_LIMIT_BACKOFF_S", 30.0)
    monkeypatch.setattr("yfinance.Ticker", ticker)
    monkeypatch.setattr("equities.short_screen.short_screen._throttled_yf_call", lambda label, call: call())
    return SimpleNamespace(calls=calls, responses=responses, sleeps=sleeps)


def test_full_universe_is_fetched_with_paced_starts_across_workers(provider):
    symbols = [f"T{i:04d}" for i in range(601)]
    progress = []
    result = d.fetch_eps_revisions(
        symbols + [symbols[0]], workers=4, now=NOW, progress=lambda *args: progress.append(args)
    )
    assert set(result) == set(symbols)
    assert Counter(t for t, _ in provider.calls) == Counter(symbols)
    times = sorted(at for _, at in provider.calls)
    assert all(b - a >= 0.5 for a, b in zip(times, times[1:], strict=False))
    assert progress[0] == ("eps_revisions", 0, 601)
    assert progress[-1] == ("eps_revisions", 601, 601)


def test_fresh_successes_are_shared_across_universes_and_expire_without_sliding_ttl(provider):
    provider.responses["AAA"] = [0.0, -0.10]
    assert d.fetch_eps_revisions(["AAA", "BBB"], workers=1, now=NOW)["AAA"] == 0.0
    assert d.fetch_eps_revisions(["AAA", "CCC"], workers=1, now=NOW + timedelta(hours=23))["AAA"] == 0.0
    assert [t for t, _ in provider.calls] == ["AAA", "BBB", "CCC"]
    refreshed = d.fetch_eps_revisions(["AAA", "CCC"], workers=1, now=NOW + timedelta(hours=24))
    assert refreshed["AAA"] == pytest.approx(-0.10)
    assert [t for t, _ in provider.calls] == ["AAA", "BBB", "CCC", "AAA"]


def test_failures_and_empty_results_retry_with_backoff_without_refetching_successes(provider):
    provider.responses.update(
        {
            "RATE": [RuntimeError("Too Many Requests. Rate limited."), -0.1],
            "AUTH": [RuntimeError("HTTP 401: Invalid Crumb"), -0.1],
            "TIMEOUT": [TimeoutError("request timed out"), -0.1],
            "EMPTY": [None, None, -0.1],
        }
    )
    result = d.fetch_eps_revisions(["OK", *provider.responses], workers=1, now=NOW)
    assert set(result) == {"OK", "RATE", "AUTH", "TIMEOUT", "EMPTY"}
    assert Counter(t for t, _ in provider.calls) == {"OK": 1, "RATE": 2, "AUTH": 2, "TIMEOUT": 2, "EMPTY": 3}
    assert [s for s in provider.sleeps if s >= 30] == [30, 60]
    count = len(provider.calls)
    assert d.fetch_eps_revisions(list(result), now=NOW) == result
    assert len(provider.calls) == count


def test_retry_exhaustion_does_not_poison_cache_or_prevent_other_lookups(provider):
    provider.responses["MISSING"] = [None] * 4
    provider.responses["BROKEN"] = [RuntimeError("HTTP 503")] * 4
    first = d.fetch_eps_revisions(["MISSING", "OK", "BROKEN"], workers=1, now=NOW)
    assert set(first) == {"OK"}
    assert Counter(t for t, _ in provider.calls) == {"MISSING": 4, "OK": 1, "BROKEN": 4}
    assert [s for s in provider.sleeps if s >= 30] == [30, 60, 120]
    assert set(d.fetch_eps_revisions(["MISSING", "OK", "BROKEN"], workers=1, now=NOW)) == {"MISSING", "OK", "BROKEN"}
    assert Counter(t for t, _ in provider.calls) == {"MISSING": 5, "OK": 1, "BROKEN": 5}


def test_interrupted_run_resumes_checkpointed_successes(provider):
    symbols = [f"T{i:03d}" for i in range(60)]

    def interrupt(phase, done, total):
        if done == 25:
            raise RuntimeError("worker interrupted")

    with pytest.raises(RuntimeError, match="worker interrupted"):
        d.fetch_eps_revisions(symbols, workers=1, now=NOW, progress=interrupt)
    assert len(provider.calls) == 25
    assert set(d.fetch_eps_revisions(symbols, workers=1, now=NOW)) == set(symbols)
    assert Counter(t for t, _ in provider.calls) == Counter(symbols)


@pytest.mark.parametrize("raw", ["not json", "[]", '{"AAA":null}', '{"AAA":{"value":1,"fetched_at":"bad"}}'])
def test_corrupt_cache_is_refetched(provider, raw):
    d._write_gz(d.REVISION_CACHE_KEY, "revisions.json.gz", raw)
    assert "AAA" in d.fetch_eps_revisions(["AAA"], now=NOW)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True, "-0.1"])
def test_invalid_cached_values_never_satisfy_a_check(provider, value):
    d._write_gz(
        d.REVISION_CACHE_KEY, "revisions.json.gz", json.dumps({"AAA": {"value": value, "fetched_at": NOW.isoformat()}})
    )
    assert d.fetch_eps_revisions(["AAA"], now=NOW)["AAA"] == pytest.approx(-0.05)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("fetched_at", [NOW + timedelta(hours=1), NOW.replace(tzinfo=None)])
def test_invalid_cache_timestamps_are_refetched(provider, fetched_at):
    d._write_gz(
        d.REVISION_CACHE_KEY,
        "revisions.json.gz",
        json.dumps({"AAA": {"value": -0.1, "fetched_at": fetched_at.isoformat()}}),
    )
    assert d.fetch_eps_revisions(["AAA"], now=NOW)["AAA"] == pytest.approx(-0.05)
    assert len(provider.calls) == 1


def test_cache_write_failure_preserves_coverage(provider, monkeypatch):
    def fail(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(d, "_write_gz", fail)
    assert set(d.fetch_eps_revisions(["AAA", "BBB"], now=NOW)) == {"AAA", "BBB"}


@pytest.mark.parametrize("current,prior", [(float("inf"), 1), (1, float("inf")), (float("nan"), 1), (1, 0)])
def test_unusable_estimates_do_not_become_revision_values(current, prior):
    trend = pd.DataFrame({"current": [current], "30daysAgo": [prior]}, index=["0y"])
    assert d.eps_revision_from_trend(trend) is None


def test_empty_universe_needs_no_requests(provider):
    assert d.fetch_eps_revisions([], now=NOW) == {}
    assert provider.calls == provider.sleeps == []
