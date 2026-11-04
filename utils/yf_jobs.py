"""Bounded concurrent price histories with shared throttling backoff."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd
import yfinance as yf
from yfinance import shared
from yfinance.exceptions import YFRateLimitError

LOGGER = logging.getLogger(__name__)
_cooldown_lock = threading.Lock()
_cooldown_until = 0.0


def _wait_for_cooldown(deadline: float | None = None) -> bool:
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return False
        with _cooldown_lock:
            remaining = _cooldown_until - time.monotonic()
        if remaining <= 0:
            return True
        if deadline is not None:
            remaining = min(remaining, max(0.0, deadline - time.monotonic()))
        time.sleep(remaining)


def _history(ticker: str, kwargs: dict[str, Any], deadline: float | None = None) -> pd.DataFrame:
    global _cooldown_until
    for attempt in range(4):
        if not _wait_for_cooldown(deadline):
            return pd.DataFrame()
        try:
            result = yf.Ticker(ticker).history(**{"actions": False, **kwargs})
            if result is None or result.empty or "Close" not in result:
                return pd.DataFrame()
            result = result.copy()
            # These jobs use daily bars, matching download(ignore_tz=True).
            result.index = pd.to_datetime(result.index).tz_localize(None)
            return result
        except Exception as exc:
            is_throttled = (
                isinstance(exc, YFRateLimitError) or getattr(getattr(exc, "response", None), "status_code", None) == 429
            )
            if is_throttled:
                delay = 0.25 * 2**attempt
                try:
                    retry_after = float(getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After", 0))
                    delay = max(delay, min(retry_after, 30.0))
                except (TypeError, ValueError):
                    pass
                with _cooldown_lock:
                    _cooldown_until = max(_cooldown_until, time.monotonic() + delay)
                if attempt < 3:
                    continue
            LOGGER.warning("Price history failed for %s: %s", ticker, exc)
            return pd.DataFrame()
    return pd.DataFrame()


def download_price_chunks(
    tickers: list[str],
    *,
    chunk_size: int = 50,
    max_chunks: int = 3,
    workers_per_chunk: int = 8,
    progress_callback: Callable[[int, int], None] | None = None,
    time_budget_s: float | None = None,
    **history_kwargs: Any,
) -> tuple[pd.DataFrame, list[str]]:
    """Run up to three chunks at once, retaining successful tickers on failure.

    Individual public Ticker.history calls overlap within one coordinated
    download group and expose Yahoo's rate-limit exceptions. Only explicit
    throttling introduces a shared cooldown; successful chunks never sleep.
    An optional time budget stops retries and new requests, retaining completed
    histories and reporting the remaining symbols as failed. In-flight calls
    still finish within their individual provider timeout.
    """
    if min(chunk_size, max_chunks, workers_per_chunk) < 1:
        raise ValueError("Chunk and worker limits must be positive")
    if time_budget_s is not None and time_budget_s <= 0:
        raise ValueError("Price download time budget must be positive")
    deadline = time.monotonic() + time_budget_s if time_budget_s is not None else None
    symbols = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip()))
    if not symbols:
        return pd.DataFrame(), []
    chunks = [symbols[index : index + chunk_size] for index in range(0, len(symbols), chunk_size)]

    def fetch_chunk(chunk: list[str]) -> list[pd.DataFrame]:
        with ThreadPoolExecutor(max_workers=min(workers_per_chunk, len(chunk))) as workers:
            return list(workers.map(lambda ticker: _history(ticker, history_kwargs, deadline), chunk))

    frames = {}
    failed = []
    # In pinned yfinance 1.3, even public history calls write shared._DFS on
    # errors. Coordinate with download()'s lock so partial failures cannot
    # corrupt an unrelated download. History workers still overlap inside it.
    acquired = (
        shared._LOCK.acquire()
        if deadline is None
        else shared._LOCK.acquire(timeout=max(0, deadline - time.monotonic()))
    )
    if not acquired:
        raise TimeoutError("Price provider is busy with another download. Please retry the screen shortly.")
    try:
        with ThreadPoolExecutor(max_workers=min(max_chunks, len(chunks))) as pool:
            for chunk, results in zip(chunks, pool.map(fetch_chunk, chunks), strict=True):
                for ticker, frame in zip(chunk, results, strict=True):
                    if frame.empty:
                        failed.append(ticker)
                    else:
                        frames[ticker] = frame
                if progress_callback:
                    progress_callback(len(frames) + len(failed), len(symbols))
    finally:
        shared._LOCK.release()
    if not frames:
        return pd.DataFrame(), failed
    combined = pd.concat(frames, axis=1, names=["Ticker", "Price"])
    return combined.swaplevel(0, 1, axis=1).sort_index(axis=1), failed
