"""Offline same-input before/after benchmark; all provider calls are simulated."""

import argparse
import contextlib
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(
    PYTHON_DOTENV_DISABLED="1",
    SENTRY_DSN="",
    ENVIRONMENT="development",
    STATE_DB_BACKEND="sqlite",
    DATABASE_URL="",
    STATE_STORAGE_BACKEND="local",
    TALISMAN_ALLOW_SQLITE_STATE="true",
    MPLCONFIGDIR="tmp/tl204-mpl",
)
import pandas as pd

from api import cache
from api import signal_aggregator as sa
from equities.market_technicals import market_breadth as mb
from portfolio.momentum.fundamental_momentum import edgar_fetcher as edgar
from portfolio.momentum.price_momentum import momentum
from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer
from utils import retry


class Calls:
    def __init__(self):
        self.count = self.active = self.peak = 0
        self.lock = threading.Lock()

    @contextlib.contextmanager
    def call(self, latency):
        with self.lock:
            self.count += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(latency)
            yield
        finally:
            with self.lock:
                self.active -= 1


def sample(name, operation, repeats=5):
    rows = []
    for _ in range(repeats):
        calls = Calls()
        start = time.perf_counter()
        operation(calls)
        rows.append(dict(seconds=round(time.perf_counter() - start, 4), calls=calls.count, peak=calls.peak))
    result = dict(
        median=statistics.median(r["seconds"] for r in rows),
        min=min(r["seconds"] for r in rows),
        max=max(r["seconds"] for r in rows),
        trials=rows,
    )
    print(name, json.dumps(result), flush=True)
    return result


TICKERS = [f"T{i:03}" for i in range(150)]
INDEX = pd.date_range("2026-01-01", periods=4)


def history(calls, ticker):
    with calls.call(0.01):
        return pd.DataFrame(
            {
                "Close": [1.0, 2.0, 3.0, 4.0],
                "High": [2.0, 3.0, 4.0, 5.0],
                "Low": [0.0, 1.0, 2.0, 3.0],
                "Volume": [100] * 4,
            },
            index=INDEX,
        )


def prices(calls):
    def download(tickers, **kwargs):
        with ThreadPoolExecutor(max_workers=8) as pool:
            frames = dict(zip(tickers, pool.map(lambda t: history(calls, t), tickers), strict=True))
        return pd.concat(frames, axis=1).swaplevel(0, 1, axis=1).sort_index(axis=1)

    class Ticker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, **kwargs):
            return history(calls, self.ticker)

    with (
        patch.object(mb, "get_sp500_tickers", return_value=TICKERS),
        patch.object(retry.yf, "download", download),
        patch.object(retry.yf, "Ticker", Ticker),
    ):
        output = sa._download_sp500_prices_uncached()
        assert set(output["Close"].columns) == set(TICKERS)


def sec(calls):
    def request(*args, **kwargs):
        with calls.call(0.15):
            return SimpleNamespace(status_code=200)

    with patch.object(retry._requests, "request", request):
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert all(
                x.status_code == 200 for x in pool.map(edgar._rate_limited_get, ["https://data.sec.gov/test"] * 12)
            )


def source_reads(calls):
    def read(ticker):
        with calls.call(0.02):
            return f"{ticker} content"

    positions = pd.DataFrame({"ticker": TICKERS[:12], "direction": ["long"] * 12})
    with (
        patch.object(analyzer, "_positions_df_for_universe", return_value=positions),
        patch.object(analyzer, "_read_overview_markdown", read),
        patch.object(analyzer, "_read_management_quality_markdown", read),
    ):
        assert len(analyzer.analyzer_source_cache_token()["qualitative_sources"]) == 12


def reference(calls):
    class Ticker:
        def __init__(self, ticker):
            self.ticker = ticker

        @property
        def fast_info(self):
            with calls.call(0.02):
                return SimpleNamespace(currency="USD")

        @property
        def info(self):
            with calls.call(0.02):
                return {"marketCap": 50_000_000_000, "sector": "Technology", "quoteType": "EQUITY"}

    cache.daily_cache.clear()
    with patch.object(retry.yf, "Ticker", Ticker):
        for _ in range(2):
            assert len(analyzer.fetch_currencies(TICKERS[:20])) == 20
            assert len(momentum.fetch_metadata_batch(TICKERS[:20])) == 20


def overlap(calls):
    def metadata(tickers):
        with calls.call(0.06):
            return {t: (50_000_000_000, "Technology", False) for t in tickers}

    def price(tickers, years):
        with calls.call(0.08):
            return ({t: pd.Series([1.0, 2.0], index=INDEX[:2]) for t in tickers}, {})

    def analyze(*args, **kwargs):
        return {"date": INDEX[-1]}

    with (
        patch.object(momentum, "load_universe", return_value=TICKERS[:20]),
        patch.object(momentum, "fetch_metadata_batch", metadata),
        patch.object(momentum, "fetch_prices_batch", price),
        patch.object(momentum, "analyze_ticker", analyze),
    ):
        assert momentum.get_data("test")["count"] == 20


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=Path("outputs/data_job_pacing.json"))
    args = parser.parse_args()
    with (
        patch.object(cache, "_DISK_CACHE_ENABLED", False),
        patch.object(cache, "_gcs_get", return_value=None),
        patch.object(cache, "_gcs_set"),
    ):
        results = {
            name: sample(name, operation)
            for name, operation in [
                ("prices", prices),
                ("sec", sec),
                ("source_reads", source_reads),
                ("reference_twice", reference),
                ("momentum_overlap", overlap),
            ]
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
