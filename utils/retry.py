"""
Centralized retry utilities for external API calls.

Provides retry-with-exponential-backoff wrappers for:
- yfinance downloads and ticker lookups
- requests.get / requests.post
- FRED API series fetches

All wrappers log retries at WARNING level. Provider helpers use a short, bounded
backoff and preserve their empty-result or exception contracts on final failure.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, cast
from urllib.error import HTTPError, URLError

import pandas as pd
import requests as _requests  # type: ignore[import-untyped]
import yfinance as yf
from curl_cffi.requests import exceptions as _curl_exceptions
from yfinance.exceptions import YFRateLimitError

from utils.rate_limit import provider_limiter

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0  # seconds; doubles each retry: 2, 4, 8
MAX_BACKOFF = 30.0
PROVIDER_BACKOFF_BASE = 0.25
PROVIDER_BACKOFF_BUDGET = 2.0

# Recognize ordinary Yahoo stock/ETF symbols, including international listings
# and share classes. FX, futures, indices, crypto pairs and options do not qualify.
_EQUITY_SYMBOL = re.compile(r"[A-Z0-9]+(?:\.[A-Z0-9]+)*(?:-[A-Z])?\Z")
_OPTION_SYMBOL = re.compile(r"[A-Z]+\d{6}[CP]\d{8}\Z")


def _sleep_backoff(attempt: int, base: float = DEFAULT_BACKOFF_BASE) -> None:
    delay = min(base * (2**attempt), MAX_BACKOFF)
    time.sleep(delay)


def _is_transient_failure(exc: Exception) -> bool:
    """Classify provider errors, including fredapi's chained HTTPError."""
    current: BaseException | None = exc
    seen: set[int] = set()
    transport_error = False
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = (
            current.code
            if isinstance(current, HTTPError)
            else getattr(getattr(current, "response", None), "status_code", None)
        )
        if isinstance(status, int):
            return status == 429 or 500 <= status < 600
        if isinstance(current, YFRateLimitError):
            return True
        if isinstance(
            current,
            (
                ConnectionError,
                TimeoutError,
                URLError,
                _requests.ConnectionError,
                _requests.Timeout,
                _curl_exceptions.ConnectionError,
                _curl_exceptions.Timeout,
                _curl_exceptions.ProxyError,
            ),
        ):
            transport_error = True
        current = current.__cause__ or current.__context__
    return transport_error


def _can_retry_empty_yf(tickers: str | list[str]) -> bool:
    """Allow one speculative empty retry only for stock/ETF-style symbols."""
    symbols = tickers.replace(",", " ").split() if isinstance(tickers, str) else tickers
    return bool(symbols) and all(
        _EQUITY_SYMBOL.fullmatch(symbol.strip().upper()) and not _OPTION_SYMBOL.fullmatch(symbol.strip().upper())
        for symbol in symbols
    )


def _provider_retry_delay(attempt: int, base: float, spent: float, *, empty: bool = False) -> float | None:
    remaining = PROVIDER_BACKOFF_BUDGET - spent
    if remaining <= 0:
        return None
    delay = min(base * (2.0**attempt), remaining)
    return min(delay, PROVIDER_BACKOFF_BASE) if empty else delay


# ---------------------------------------------------------------------------
# yfinance wrappers
# ---------------------------------------------------------------------------


def yf_download(
    tickers: str | list[str],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = PROVIDER_BACKOFF_BASE,
    **kwargs: Any,
) -> pd.DataFrame:
    """Wrap ``yf.download()`` with bounded retries for transient failures.

    All keyword arguments are forwarded to ``yf.download()``.
    Empty stock/ETF downloads get at most one short retry; other empties are
    final. yfinance can hide per-ticker failures as empty data, so those follow
    the same empty-result policy. Final exceptions are raised to the caller.
    """
    if "progress" not in kwargs:
        kwargs["progress"] = False

    ticker_label = tickers if isinstance(tickers, str) else f"{len(tickers)} tickers"
    retry_empty = _can_retry_empty_yf(tickers)
    spent = 0.0

    for attempt in range(max_retries + 1):
        try:
            df = yf.download(tickers, **kwargs)
            if df is not None and not df.empty:
                return df
            delay = (
                _provider_retry_delay(attempt, backoff_base, spent, empty=True)
                if retry_empty and attempt < max_retries
                else None
            )
            if delay is not None:
                logger.warning(
                    "yf.download(%s) returned empty (attempt %d/%d), retrying",
                    ticker_label,
                    attempt + 1,
                    max_retries + 1,
                )
                retry_empty = False
                time.sleep(delay)
                spent += delay
            else:
                logger.warning("yf.download(%s) returned empty after %d attempts", ticker_label, attempt + 1)
                return pd.DataFrame()
        except Exception as exc:
            delay = (
                _provider_retry_delay(attempt, backoff_base, spent)
                if _is_transient_failure(exc) and attempt < max_retries
                else None
            )
            if delay is not None:
                logger.warning(
                    "yf.download(%s) failed (attempt %d/%d): %s — retrying",
                    ticker_label,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                time.sleep(delay)
                spent += delay
            else:
                logger.error("yf.download(%s) failed after %d attempts: %s", ticker_label, attempt + 1, exc)
                raise

    return pd.DataFrame()  # unreachable, but satisfies type checker


def yf_ticker_info(
    ticker: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = PROVIDER_BACKOFF_BASE,
) -> dict[str, Any]:
    """Fetch ticker info with bounded transient retries; return {} on failure.

    Empty stock/ETF metadata gets at most one short retry. Other empties are final.
    """
    retry_empty = _can_retry_empty_yf(ticker)
    spent = 0.0
    for attempt in range(max_retries + 1):
        try:
            info = yf.Ticker(ticker).info
            if info:
                return cast(dict[str, Any], info)
            delay = (
                _provider_retry_delay(attempt, backoff_base, spent, empty=True)
                if retry_empty and attempt < max_retries
                else None
            )
            if delay is not None:
                logger.warning(
                    "yf.Ticker(%s).info returned empty (attempt %d/%d), retrying",
                    ticker,
                    attempt + 1,
                    max_retries + 1,
                )
                retry_empty = False
                time.sleep(delay)
                spent += delay
            else:
                return {}
        except Exception as exc:
            delay = (
                _provider_retry_delay(attempt, backoff_base, spent)
                if _is_transient_failure(exc) and attempt < max_retries
                else None
            )
            if delay is not None:
                logger.warning(
                    "yf.Ticker(%s).info failed (attempt %d/%d): %s — retrying",
                    ticker,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                time.sleep(delay)
                spent += delay
            else:
                logger.error("yf.Ticker(%s).info failed after %d attempts: %s", ticker, attempt + 1, exc)
                return {}
    return {}


# ---------------------------------------------------------------------------
# requests wrappers
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def requests_get(
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    **kwargs: Any,
) -> _requests.Response:
    """``requests.get()`` with retry on network errors and 429/5xx status codes."""
    return _requests_with_retry("GET", url, max_retries=max_retries, backoff_base=backoff_base, **kwargs)


def requests_post(
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    **kwargs: Any,
) -> _requests.Response:
    """``requests.post()`` with retry on network errors and 429/5xx status codes."""
    return _requests_with_retry("POST", url, max_retries=max_retries, backoff_base=backoff_base, **kwargs)


def _requests_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    **kwargs: Any,
) -> _requests.Response:
    if "timeout" not in kwargs:
        kwargs["timeout"] = 30

    for attempt in range(max_retries + 1):
        try:
            resp = _requests.request(method, url, **kwargs)

            if resp.status_code < 400:
                return resp

            if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < max_retries:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = min(float(retry_after), MAX_BACKOFF)
                    except ValueError:
                        delay = min(backoff_base * (2**attempt), MAX_BACKOFF)
                else:
                    delay = min(backoff_base * (2**attempt), MAX_BACKOFF)
                logger.warning(
                    "%s %s returned %d (attempt %d/%d), retrying in %.1fs",
                    method,
                    url,
                    resp.status_code,
                    attempt + 1,
                    max_retries + 1,
                    delay,
                )
                time.sleep(delay)
                continue

            return resp  # non-retryable status or final attempt

        except (_requests.ConnectionError, _requests.Timeout) as exc:
            if attempt < max_retries:
                logger.warning(
                    "%s %s failed (attempt %d/%d): %s — retrying",
                    method,
                    url,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                _sleep_backoff(attempt, backoff_base)
            else:
                raise

    raise RuntimeError(f"Unreachable: {method} {url}")  # satisfies type checker


# ---------------------------------------------------------------------------
# FRED API wrapper
# ---------------------------------------------------------------------------


def fred_get_series(
    fred_client: Any,
    series_id: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = PROVIDER_BACKOFF_BASE,
    **kwargs: Any,
) -> pd.Series:
    """Retry transient FRED failures with bounded backoff; empty results are final.

    Every attempt takes a token from the shared FRED rate limiter first.
    Returns an empty Series on final failure, including invalid series IDs.
    """
    spent = 0.0
    for attempt in range(max_retries + 1):
        try:
            provider_limiter("fred").acquire()
            result = fred_client.get_series(series_id, **kwargs)
            if result is not None and not result.empty:
                return result
            return pd.Series(dtype=float)
        except Exception as exc:
            delay = (
                _provider_retry_delay(attempt, backoff_base, spent)
                if _is_transient_failure(exc) and attempt < max_retries
                else None
            )
            if delay is not None:
                logger.warning(
                    "fred.get_series(%s) failed (attempt %d/%d): %s — retrying",
                    series_id,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                time.sleep(delay)
                spent += delay
            else:
                logger.error("fred.get_series(%s) failed after %d attempts: %s", series_id, attempt + 1, exc)
                return pd.Series(dtype=float)

    return pd.Series(dtype=float)
