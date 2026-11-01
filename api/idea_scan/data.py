"""Fetch prices and fundamentals once per idea scan run, shared by every preset.

Prices come from one chunked download. Fundamentals (a trimmed ``.info`` plus
annual, quarterly, balance-sheet and cash-flow statements) are fetched per
ticker through the same Yahoo throttle the screens use, and checkpointed to
state storage in chunks so a retried or repeated run in the same week resumes
instead of starting over.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from api import state_storage
from paths import PROJECT_ROOT

LOGGER = logging.getLogger(__name__)

# The S&P index ETFs are each universe's relative-momentum benchmark; SPY also anchors beta and the ranker.
UNIVERSE_BENCHMARKS = {"sp500": "SPY", "sp400": "MDY", "sp600": "IJR", "russell2000": "IWM"}
MARKET_BENCHMARK = "SPY"
PRICE_PERIOD = "3y"
CHECKPOINT_CHUNK = 250
# Price history goes in pages of 50 symbols. From a home connection Yahoo serves a page a second,
# but from Cloud Run that pace was blocked after ~1,300 symbols and stayed blocked for an hour
# (2026-10-29), so the default is a page every 8 seconds, about the rate fundamentals get through.
PRICE_BATCH = max(1, int(os.getenv("IDEA_SCAN_PRICE_BATCH") or 50))
PRICE_BATCH_INTERVAL_S = float(os.getenv("IDEA_SCAN_PRICE_BATCH_INTERVAL_SECONDS") or 8.0)
PRICE_BATCH_WORKERS = 4
# A page where most symbols fail is taken as throttling: the next page waits, twice as long each time.
PRICE_COOLDOWN_S = 60.0
PRICE_COOLDOWN_MAX_S = 300.0
# Prices stop starting pages after this, so a blocked run still leaves time for fundamentals.
PRICE_DEADLINE_S = float(os.getenv("IDEA_SCAN_PRICE_DEADLINE_SECONDS") or 30 * 60)
DATASET_MAX_AGE_S = 4 * 24 * 60 * 60
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_S = 30.0
# Leaves room in the 150-minute job for screening, the LLM steps and publishing.
FETCH_DEADLINE_S = float(os.getenv("IDEA_SCAN_FETCH_DEADLINE_SECONDS") or 100 * 60)
NOT_FETCHED = "not fetched: time limit"

# Only the .info fields the presets, ranker and cards read; the full dict is ~150 keys.
INFO_FIELDS = (
    "longName",
    "shortName",
    "sector",
    "industry",
    "quoteType",
    "currency",
    "marketCap",
    "priceToBook",
    "sharesOutstanding",
    "floatShares",
    "enterpriseToEbitda",
    "forwardPE",
    "trailingPE",
    "sharesShort",
    "shortPercentOfFloat",
    "shortRatio",
    "dateShortInterest",
    "earningsTimestamp",
    "earningsTimestampStart",
    "earningsTimestampEnd",
    "averageVolume",
    "numberOfAnalystOpinions",
)

STATEMENTS = ("financials", "quarterly_financials", "balance_sheet", "cashflow")

_LOCAL_ROOT = PROJECT_ROOT / "data_cache" / "idea_scan" / "datasets"
_GCS_ROOT = "idea_scan/datasets"

ProgressCallback = Callable[[str, int, int], None]

_sleep = time.sleep


@dataclass
class TickerFundamentals:
    info: dict[str, Any] = field(default_factory=dict)
    financials: pd.DataFrame | None = None
    quarterly_financials: pd.DataFrame | None = None
    balance_sheet: pd.DataFrame | None = None
    cashflow: pd.DataFrame | None = None
    error: str | None = None


@dataclass
class ScanDataset:
    key: str
    membership: dict[str, list[str]]
    prices: pd.DataFrame
    fundamentals: dict[str, TickerFundamentals]
    failed: dict[str, str]
    fetched_at: str
    reused_chunks: int = 0

    @property
    def tickers(self) -> list[str]:
        return list(self.membership)

    def primary_benchmark(self, ticker: str) -> str:
        for universe in ("sp500", "sp400", "sp600", "russell2000"):
            if universe in self.membership.get(ticker, []):
                return UNIVERSE_BENCHMARKS[universe]
        return MARKET_BENCHMARK


def resolve_membership(universes: Sequence[str], *, tickers: Sequence[str] | None = None) -> dict[str, list[str]]:
    """Map each ticker to the universes it belongs to, deduplicated across universes."""
    from equities.common import get_universe_tickers

    membership: dict[str, list[str]] = {}
    for universe in universes:
        for ticker in get_universe_tickers(universe):
            membership.setdefault(ticker, []).append(universe)
    if tickers:
        wanted = {t.strip().upper() for t in tickers if t.strip()}
        membership = {t: u for t, u in membership.items() if t in wanted}
        for ticker in sorted(wanted - set(membership)):
            membership[ticker] = []
    return membership


def dataset_key(membership: dict[str, list[str]], *, now: datetime | None = None) -> str:
    """One dataset per ISO week and ticker set."""
    when = now or datetime.now(UTC)
    year, week, _ = when.isocalendar()
    digest = hashlib.sha256(json.dumps(sorted(membership), separators=(",", ":")).encode()).hexdigest()[:12]
    return f"{year}-W{week:02d}-{digest}"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _frame_to_json(frame: pd.DataFrame | None) -> str | None:
    if frame is None or frame.empty:
        return None
    return str(frame.to_json(orient="split", date_format="iso"))


def _frame_from_json(value: str | None) -> pd.DataFrame | None:
    if not value:
        return None
    frame = pd.read_json(io.StringIO(value), orient="split")
    try:
        frame.columns = pd.to_datetime(frame.columns)
    except (TypeError, ValueError):
        pass
    return frame


def _fundamentals_to_record(ticker: str, item: TickerFundamentals) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "info": item.info,
        "error": item.error,
        **{name: _frame_to_json(getattr(item, name)) for name in STATEMENTS},
    }


def _fundamentals_from_record(record: dict[str, Any]) -> TickerFundamentals:
    return TickerFundamentals(
        info=dict(record.get("info") or {}),
        error=record.get("error"),
        **{name: _frame_from_json(record.get(name)) for name in STATEMENTS},
    )


def _paths(key: str, name: str) -> tuple[Any, str]:
    return _LOCAL_ROOT / key / name, f"{_GCS_ROOT}/{key}/{name}"


def _write_gz(key: str, name: str, text: str) -> None:
    local, remote = _paths(key, name)
    state_storage.write_bytes(local, remote, gzip.compress(text.encode("utf-8")), content_type="application/gzip")


def _read_bytes(key: str, name: str) -> bytes | None:
    local, remote = _paths(key, name)
    try:
        if not state_storage.exists_text(local, remote):
            return None
        return state_storage.read_bytes(local, remote)
    except Exception:
        LOGGER.warning("Idea scan checkpoint %s/%s unreadable; refetching", key, name, exc_info=True)
        return None


def _read_gz(key: str, name: str) -> str | None:
    raw = _read_bytes(key, name)
    if raw is None:
        return None
    try:
        return gzip.decompress(raw).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        LOGGER.warning("Idea scan checkpoint %s/%s corrupt; refetching", key, name)
        return None


def _write_prices(key: str, prices: pd.DataFrame) -> None:
    buffer = io.BytesIO()
    frame = prices.copy()
    frame.columns = [str(c) for c in frame.columns]
    frame.to_parquet(buffer)
    local, remote = _paths(key, "prices.parquet")
    state_storage.write_bytes(local, remote, buffer.getvalue(), content_type="application/vnd.apache.parquet")


def _read_prices(key: str) -> pd.DataFrame | None:
    raw = _read_bytes(key, "prices.parquet")
    if raw is None:
        return None
    try:
        prices = pd.read_parquet(io.BytesIO(raw))
    except Exception:
        LOGGER.warning("Idea scan price checkpoint corrupt; refetching", exc_info=True)
        return None
    prices.index = pd.to_datetime(prices.index)
    return prices if not prices.empty else None


def _manifest(key: str) -> dict[str, Any]:
    text = _read_gz(key, "manifest.json.gz")
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _fresh(manifest: dict[str, Any]) -> bool:
    try:
        started = datetime.fromisoformat(str(manifest.get("started_at")))
    except ValueError:
        return False
    return (datetime.now(UTC) - started).total_seconds() <= DATASET_MAX_AGE_S


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _trim_info(info: dict[str, Any]) -> dict[str, Any]:
    return {k: info.get(k) for k in INFO_FIELDS if info.get(k) is not None}


def fetch_ticker_fundamentals(ticker: str) -> TickerFundamentals:
    """Fetch .info and the four statements for one ticker through the shared Yahoo throttle."""
    import yfinance as yf

    from equities.short_screen.short_screen import YahooRateLimitError, _throttled_yf_call

    t = yf.Ticker(ticker)
    out = TickerFundamentals()
    try:
        out.info = _trim_info(_throttled_yf_call(f"{ticker}.info", lambda: dict(t.info or {})))
    except YahooRateLimitError as exc:
        return TickerFundamentals(error=str(exc))
    except Exception as exc:
        LOGGER.debug("info fetch failed for %s", ticker, exc_info=True)
        out.error = f"info: {exc}"
    for name in STATEMENTS:
        try:
            frame = _throttled_yf_call(f"{ticker}.{name}", lambda name=name: getattr(t, name))
            setattr(out, name, frame if isinstance(frame, pd.DataFrame) and not frame.empty else None)
        except YahooRateLimitError as exc:
            return TickerFundamentals(error=str(exc))
        except Exception:
            LOGGER.debug("%s fetch failed for %s", name, ticker, exc_info=True)
    if not out.info and all(getattr(out, name) is None for name in STATEMENTS):
        out.error = out.error or "no data returned"
    return out


def _is_retryable(error: str | None) -> bool:
    """Rate limits and Yahoo's expired-crumb 401s clear up on a later attempt; other errors don't."""
    text = str(error or "").lower()
    return any(marker in text for marker in ("too many requests", "rate limit", "invalid crumb", "unauthorized"))


def _price_symbols(tickers: Sequence[str]) -> list[str]:
    """Benchmarks first: every momentum score and beta is measured against them."""
    return list(dict.fromkeys([*UNIVERSE_BENCHMARKS.values(), *tickers]))


def _download_closes(symbols: list[str], *, deadline: float | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Adjusted closes in pages of ``PRICE_BATCH`` symbols, one page every ``PRICE_BATCH_INTERVAL_S``.

    After a page where most symbols fail (Yahoo throttling), the next page waits out a cooldown
    that doubles each time instead of hitting a blocked endpoint. No page starts after
    ``deadline``; its symbols come back as failed. Only each page's Close column is kept, so
    memory stays flat across ~3,000 symbols.
    """
    from utils.yf_jobs import download_price_chunks

    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    cooldown = PRICE_COOLDOWN_S
    for start in range(0, len(symbols), PRICE_BATCH):
        if deadline is not None and time.monotonic() >= deadline:
            LOGGER.warning("Idea scan price time limit reached; %d symbols not fetched", len(symbols) - start)
            failed.extend(symbols[start:])
            break
        batch = symbols[start : start + PRICE_BATCH]
        batch_started = time.monotonic()
        raw, batch_failed = download_price_chunks(
            batch,
            chunk_size=PRICE_BATCH,
            max_chunks=1,
            workers_per_chunk=PRICE_BATCH_WORKERS,
            period=PRICE_PERIOD,
            interval="1d",
            auto_adjust=True,
        )
        failed.extend(batch_failed)
        if not raw.empty:
            frames.append(raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]])
        if start + PRICE_BATCH >= len(symbols):
            break
        if len(batch_failed) * 2 > len(batch):
            LOGGER.warning(
                "Idea scan price page throttled (%d of %d failed); pausing %.0fs",
                len(batch_failed),
                len(batch),
                cooldown,
            )
            _sleep(cooldown)
            cooldown = min(cooldown * 2, PRICE_COOLDOWN_MAX_S)
        else:
            cooldown = PRICE_COOLDOWN_S
            _sleep(max(0.0, PRICE_BATCH_INTERVAL_S - (time.monotonic() - batch_started)))
    if not frames:
        return pd.DataFrame(), failed
    close = pd.concat(frames, axis=1).sort_index()
    close = close.loc[:, ~close.columns.duplicated()]
    if getattr(close.index, "tz", None) is not None:
        close.index = close.index.tz_localize(None)
    return close, failed


def fetch_prices(tickers: list[str], *, deadline: float | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Adjusted daily closes for benchmarks plus tickers, one column per symbol.

    Failed symbols (mostly Yahoo rate limits on a cold run) are retried after a backoff, until a
    round recovers nothing: what's left then is delisted or still blocked, and a rerun the same
    week tries it again.
    """
    prices, failed = _download_closes(_price_symbols(tickers), deadline=deadline)
    for attempt in range(RATE_LIMIT_RETRIES):
        backoff = RATE_LIMIT_BACKOFF_S * (attempt + 1)
        if not failed or (deadline is not None and time.monotonic() + backoff >= deadline):
            break
        LOGGER.info("Retrying %d price downloads after a backoff", len(failed))
        _sleep(backoff)
        retried, still_failed = _download_closes(failed, deadline=deadline)
        if not retried.empty:
            prices = retried if prices.empty else pd.concat([prices, retried], axis=1).sort_index()
        recovered = len(failed) - len(still_failed)
        failed = still_failed
        if not recovered:
            break
    return prices, failed


def _fetch_round(
    tickers: list[str], *, workers: int, on_done: Callable[[], None] | None = None
) -> dict[str, TickerFundamentals]:
    out: dict[str, TickerFundamentals] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_ticker_fundamentals, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                out[ticker] = future.result()
            except Exception as exc:
                out[ticker] = TickerFundamentals(error=str(exc))
            if on_done:
                on_done()
    return out


def _fetch_fundamentals_chunked(
    key: str,
    tickers: list[str],
    *,
    resume: bool,
    progress: ProgressCallback | None,
    workers: int,
    deadline: float,
) -> tuple[dict[str, TickerFundamentals], int]:
    chunks = [tickers[i : i + CHECKPOINT_CHUNK] for i in range(0, len(tickers), CHECKPOINT_CHUNK)]
    results: dict[str, TickerFundamentals] = {}
    reused = 0
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if progress and (done % 25 == 0 or done == len(tickers)):
            progress("fundamentals", done, len(tickers))

    for index, chunk in enumerate(chunks):
        name = f"fundamentals-{index:04d}.jsonl.gz"
        cached = _read_gz(key, name) if resume else None
        chunk_results: dict[str, TickerFundamentals] = {}
        todo = chunk
        if cached:
            records = [json.loads(line) for line in cached.splitlines() if line.strip()]
            if [r.get("ticker") for r in records] == chunk:
                chunk_results = {r["ticker"]: _fundamentals_from_record(r) for r in records}
                # Rate-limited or unfetched names are retried on resume; everything else is kept.
                todo = [t for t, r in chunk_results.items() if _is_retryable(r.error) or r.error == NOT_FETCHED]
                done += len(chunk) - len(todo)
                if not todo:
                    results.update(chunk_results)
                    reused += 1
                    if progress:
                        progress("fundamentals", done, len(tickers))
                    continue

        if time.monotonic() >= deadline:
            for ticker in todo:
                chunk_results[ticker] = TickerFundamentals(error=NOT_FETCHED)
                tick()
        else:
            chunk_results.update(_fetch_round(todo, workers=workers, on_done=tick))
            for attempt in range(RATE_LIMIT_RETRIES):
                limited = [t for t in todo if _is_retryable(chunk_results[t].error)]
                backoff = RATE_LIMIT_BACKOFF_S * (attempt + 1)
                if not limited or time.monotonic() + backoff >= deadline:
                    break
                LOGGER.info("Retrying %d rate-limited tickers after %.0fs", len(limited), backoff)
                _sleep(backoff)
                chunk_results.update(_fetch_round(limited, workers=workers))
        results.update(chunk_results)
        lines = [json.dumps(_fundamentals_to_record(t, chunk_results[t]), default=str) for t in chunk]
        try:
            _write_gz(key, name, "\n".join(lines))
        except Exception:
            LOGGER.warning("Idea scan checkpoint write failed for %s/%s", key, name, exc_info=True)
    return results, reused


def fetch_dataset(
    membership: dict[str, list[str]],
    *,
    progress: ProgressCallback | None = None,
    workers: int | None = None,
    now: datetime | None = None,
    deadline_s: float | None = None,
) -> ScanDataset:
    """Fetch (or resume) this week's shared data set for the given tickers.

    Fetching stops starting new tickers after ``deadline_s`` (default
    ``FETCH_DEADLINE_S``) so a throttled run still finishes with what it has;
    the rest are marked "not fetched" and picked up by a rerun the same week.
    """
    from equities.short_screen.short_screen import PHASE1_WORKERS

    key = dataset_key(membership, now=now)
    manifest = _manifest(key)
    resume = _fresh(manifest)
    if not resume:
        manifest = {"started_at": datetime.now(UTC).isoformat(), "tickers": len(membership)}
        _write_gz(key, "manifest.json.gz", json.dumps(manifest))

    tickers = list(membership)
    started = time.monotonic()
    deadline = started + (FETCH_DEADLINE_S if deadline_s is None else deadline_s)
    price_deadline = min(deadline, started + PRICE_DEADLINE_S)
    prices = _read_prices(key) if resume else None
    price_failed: list[str] = []
    if prices is not None:
        missing = [s for s in _price_symbols(tickers) if s not in prices.columns]
        if missing:
            # One pass only: what's still missing after the first run's backoffs is mostly delisted.
            retried, price_failed = _download_closes(missing, deadline=price_deadline)
            new_cols = [c for c in retried.columns if c not in prices.columns]
            if new_cols:
                prices = pd.concat([prices, retried[new_cols]], axis=1).sort_index()
                _write_prices(key, prices)
    else:
        if progress:
            progress("prices", 0, len(tickers))
        prices, price_failed = fetch_prices(tickers, deadline=price_deadline)
        if not prices.empty:
            try:
                _write_prices(key, prices)
            except Exception:
                LOGGER.warning("Idea scan price checkpoint write failed", exc_info=True)
        if progress:
            progress("prices", len(tickers), len(tickers))

    fundamentals, reused = _fetch_fundamentals_chunked(
        key,
        tickers,
        resume=resume,
        progress=progress,
        workers=max(1, workers or PHASE1_WORKERS),
        deadline=deadline,
    )
    failed = {t: "no price history" for t in price_failed if t in membership}
    for ticker, item in fundamentals.items():
        if item.error and not item.info:
            failed[ticker] = item.error
    LOGGER.info(
        "Idea scan data set %s: %d tickers, %d failed, %d checkpoint chunks reused, %.0fs",
        key,
        len(tickers),
        len(failed),
        reused,
        time.monotonic() - started,
    )
    return ScanDataset(
        key=key,
        membership=membership,
        prices=prices,
        fundamentals=fundamentals,
        failed=failed,
        fetched_at=str(manifest.get("started_at")),
        reused_chunks=reused,
    )


def fetch_eps_revisions(tickers: list[str], *, workers: int | None = None) -> dict[str, float]:
    """30-day change in consensus EPS for the current and next fiscal year, as a fraction.

    Read from yfinance ``eps_trend``; only fetched for the names a preset needs.
    """
    import yfinance as yf

    from equities.short_screen.short_screen import PHASE1_WORKERS, _throttled_yf_call

    def one(ticker: str) -> float | None:
        try:
            trend = _throttled_yf_call(f"{ticker}.eps_trend", lambda: yf.Ticker(ticker).eps_trend)
        except Exception:
            return None
        return eps_revision_from_trend(trend)

    out: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers or PHASE1_WORKERS)) as pool:
        futures = {pool.submit(one, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            value = future.result()
            if value is not None:
                out[futures[future]] = value
    return out


def eps_revision_from_trend(trend: pd.DataFrame | None) -> float | None:
    if trend is None or not isinstance(trend, pd.DataFrame) or trend.empty:
        return None
    changes: list[float] = []
    for period in ("0y", "+1y"):
        if period not in trend.index or "current" not in trend.columns or "30daysAgo" not in trend.columns:
            continue
        try:
            current = float(trend.loc[period, "current"])
            prior = float(trend.loc[period, "30daysAgo"])
        except (TypeError, ValueError):
            continue
        if prior and pd.notna(prior) and pd.notna(current):
            changes.append((current - prior) / abs(prior))
    return float(sum(changes) / len(changes)) if changes else None
