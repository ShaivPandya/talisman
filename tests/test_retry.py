from __future__ import annotations

import logging
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pandas as pd
import pytest
import requests
from curl_cffi.requests import Response as CurlResponse
from curl_cffi.requests import exceptions as curl_exceptions
from fredapi import Fred
from yfinance.exceptions import YFPricesMissingError, YFRateLimitError

from utils import retry


@pytest.fixture
def sleep(monkeypatch):
    sleeper = Mock()
    monkeypatch.setattr(retry.time, "sleep", sleeper)
    return sleeper


def _success(provider):
    if provider == "download":
        return pd.DataFrame({"Close": [100.0]})
    if provider == "info":
        return {"currency": "USD"}
    return pd.Series([100.0])


def _call_provider(monkeypatch, provider, operation, *, tickers="AAPL", **kwargs):
    if provider == "download":
        monkeypatch.setattr(retry.yf, "download", operation)
        return retry.yf_download(tickers, **kwargs)
    if provider == "info":

        class Ticker:
            @property
            def info(self):
                return operation()

        monkeypatch.setattr(retry.yf, "Ticker", lambda _ticker: Ticker())
        return retry.yf_ticker_info(tickers, **kwargs)
    return retry.fred_get_series(SimpleNamespace(get_series=operation), "TEST_SERIES", **kwargs)


def _assert_empty(provider, result):
    if provider == "info":
        assert result == {}
    else:
        assert result.empty


def _assert_final_failure(monkeypatch, provider, operation, error, **kwargs):
    if provider == "download":
        with pytest.raises(type(error)) as caught:
            _call_provider(monkeypatch, provider, operation, **kwargs)
        assert caught.value is error
    else:
        _assert_empty(provider, _call_provider(monkeypatch, provider, operation, **kwargs))


def _http_error(stack, status):
    if stack == "urllib":
        return HTTPError("https://provider.test", status, "HTTP failure", {}, BytesIO())
    response = requests.Response() if stack == "requests" else CurlResponse()
    response.status_code = status
    error_type = requests.HTTPError if stack == "requests" else curl_exceptions.HTTPError
    return error_type(f"HTTP Error {status}", response=response)


@pytest.mark.parametrize("provider", ["download", "info", "fred"])
def test_success_returns_provider_result_without_sleep(monkeypatch, sleep, provider):
    result = _success(provider)
    operation = Mock(return_value=result)

    assert _call_provider(monkeypatch, provider, operation) is result
    assert operation.call_count == 1
    sleep.assert_not_called()


def test_download_forwards_arguments_and_disables_progress_by_default(monkeypatch, sleep):
    operation = Mock(return_value=_success("download"))

    _call_provider(monkeypatch, "download", operation, tickers=["AAPL", "SPY"], period="5d", auto_adjust=False)

    operation.assert_called_once_with(["AAPL", "SPY"], period="5d", auto_adjust=False, progress=False)
    _call_provider(monkeypatch, "download", operation, progress=True)
    assert operation.call_args.kwargs == {"progress": True}


def test_fred_forwards_observation_dates(monkeypatch, sleep):
    operation = Mock(return_value=_success("fred"))

    _call_provider(monkeypatch, "fred", operation, observation_start="2026-01-01")

    operation.assert_called_once_with("TEST_SERIES", observation_start="2026-01-01")


@pytest.mark.parametrize("provider", ["download", "info", "fred"])
@pytest.mark.parametrize(
    "error",
    [
        ValueError("invalid input"),
        TypeError("bad argument"),
        RuntimeError("429 in a message"),
        YFPricesMissingError("AAPL", ""),
    ],
)
def test_permanent_errors_stop_after_one_call(monkeypatch, sleep, provider, error):
    operation = Mock(side_effect=error)

    _assert_final_failure(monkeypatch, provider, operation, error)

    assert operation.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("provider", ["download", "info", "fred"])
@pytest.mark.parametrize(
    ("stack", "status"),
    [
        ("requests", 400),
        ("requests", 401),
        ("requests", 403),
        ("requests", 404),
        ("requests", 422),
        ("curl", 404),
        ("urllib", 400),
    ],
)
def test_non_rate_limit_4xx_errors_are_final(monkeypatch, sleep, provider, stack, status):
    error = _http_error(stack, status)
    operation = Mock(side_effect=error)

    _assert_final_failure(monkeypatch, provider, operation, error)

    assert operation.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("provider", ["download", "info", "fred"])
@pytest.mark.parametrize(
    "error",
    [
        requests.ConnectionError("connection reset"),
        requests.Timeout("timed out"),
        curl_exceptions.ConnectionError("connection reset"),
        curl_exceptions.Timeout("timed out"),
        URLError("connection refused"),
        TimeoutError("timed out"),
        YFRateLimitError(),
        _http_error("requests", 429),
        _http_error("curl", 503),
        _http_error("urllib", 500),
        _http_error("requests", 501),
        _http_error("curl", 599),
    ],
)
def test_transient_failures_can_recover(monkeypatch, sleep, provider, error):
    result = _success(provider)
    operation = Mock(side_effect=[error, result])

    assert _call_provider(monkeypatch, provider, operation) is result

    assert operation.call_count == 2
    sleep.assert_called_once_with(0.25)


@pytest.mark.parametrize("provider", ["download", "info", "fred"])
def test_default_transient_retry_backoff_totals_under_two_seconds(monkeypatch, sleep, provider):
    error = requests.Timeout("still unavailable")
    operation = Mock(side_effect=error)

    _assert_final_failure(monkeypatch, provider, operation, error)

    assert operation.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [0.25, 0.5, 1.0]


@pytest.mark.parametrize("provider", ["download", "info", "fred"])
@pytest.mark.parametrize("backoff_base", [0.25, 10.0])
def test_sleep_budget_holds_with_extra_retries_and_custom_backoff(monkeypatch, sleep, provider, backoff_base):
    error = requests.Timeout("still unavailable")
    operation = Mock(side_effect=error)

    _assert_final_failure(monkeypatch, provider, operation, error, max_retries=100, backoff_base=backoff_base)

    assert operation.call_count <= 5
    assert sum(call.args[0] for call in sleep.call_args_list) == pytest.approx(2.0)


@pytest.mark.parametrize("provider", ["download", "info", "fred"])
def test_max_retries_zero_disables_transient_retries(monkeypatch, sleep, provider):
    error = requests.Timeout("unavailable")
    operation = Mock(side_effect=error)

    _assert_final_failure(monkeypatch, provider, operation, error, max_retries=0)

    assert operation.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("empty", [None, pd.Series(dtype=float)])
def test_empty_fred_series_is_final(monkeypatch, sleep, empty):
    operation = Mock(return_value=empty)

    result = _call_provider(monkeypatch, "fred", operation)

    assert result.empty
    assert operation.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("provider", ["download", "info"])
@pytest.mark.parametrize(
    "ticker", ["EURUSD=X", "USDJPY=X", "GC=F", "ES=F", "^GSPC", "BTC-USD", "AAPL261218C00200000", ""]
)
def test_empty_non_equity_results_are_final(monkeypatch, sleep, caplog, provider, ticker):
    operation = Mock(return_value=pd.DataFrame() if provider == "download" else {})

    with caplog.at_level(logging.WARNING, logger="utils.retry"):
        result = _call_provider(monkeypatch, provider, operation, tickers=ticker)

    _assert_empty(provider, result)
    assert operation.call_count == 1
    sleep.assert_not_called()
    assert "retrying" not in caplog.text


@pytest.mark.parametrize("tickers", [[], ["AAPL", "EURUSD=X"], ["SPY", "GC=F"], "AAPL, GC=F"])
def test_empty_mixed_download_batches_are_final(monkeypatch, sleep, tickers):
    operation = Mock(return_value=pd.DataFrame())

    result = _call_provider(monkeypatch, "download", operation, tickers=tickers)

    assert result.empty
    assert operation.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("provider", ["download", "info"])
@pytest.mark.parametrize("ticker", ["AAPL", "SPY", "BRK-B", "0700.HK", " vod.l "])
def test_empty_equity_results_get_only_one_short_retry(monkeypatch, sleep, provider, ticker):
    operation = Mock(return_value=pd.DataFrame() if provider == "download" else {})

    result = _call_provider(monkeypatch, provider, operation, tickers=ticker, max_retries=100, backoff_base=10.0)

    _assert_empty(provider, result)
    assert operation.call_count == 2
    sleep.assert_called_once_with(0.25)


@pytest.mark.parametrize("provider", ["download", "info"])
def test_empty_equity_retry_can_recover(monkeypatch, sleep, provider):
    result = _success(provider)
    operation = Mock(side_effect=[None, result])

    assert _call_provider(monkeypatch, provider, operation) is result
    assert operation.call_count == 2
    sleep.assert_called_once_with(0.25)


@pytest.mark.parametrize("provider", ["download", "info"])
def test_empty_retry_is_not_reset_by_a_transient_failure(monkeypatch, sleep, provider):
    operation = Mock(side_effect=[None, requests.Timeout("unavailable"), None, _success(provider)])

    _assert_empty(provider, _call_provider(monkeypatch, provider, operation))

    assert operation.call_count == 3
    assert sum(call.args[0] for call in sleep.call_args_list) == 0.75


@pytest.mark.parametrize("provider", ["download", "info"])
def test_empty_retry_shares_the_transient_sleep_budget(monkeypatch, sleep, provider):
    operation = Mock(side_effect=[requests.Timeout("unavailable"), None, _success(provider)])

    _assert_empty(provider, _call_provider(monkeypatch, provider, operation, backoff_base=10.0))

    assert operation.call_count == 2
    sleep.assert_called_once_with(2.0)


@pytest.mark.parametrize("provider", ["download", "info"])
def test_max_retries_zero_disables_empty_equity_retry(monkeypatch, sleep, provider):
    operation = Mock(return_value=None)

    _assert_empty(provider, _call_provider(monkeypatch, provider, operation, max_retries=0))

    assert operation.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("tickers", [["AAPL", "SPY"], "AAPL, SPY", "AAPL SPY"])
def test_empty_equity_download_batches_can_recover(monkeypatch, sleep, tickers):
    result = _success("download")
    operation = Mock(side_effect=[pd.DataFrame(), result])

    assert _call_provider(monkeypatch, "download", operation, tickers=tickers) is result
    assert operation.call_count == 2
    sleep.assert_called_once_with(0.25)


@pytest.mark.parametrize("status", [400, 429, 503])
def test_real_fred_client_preserves_http_status_through_value_error(monkeypatch, sleep, status):
    import fredapi.fred

    def http_failure(_url):
        body = f'<error code="{status}" message="Provider HTTP failure"/>'.encode()
        raise HTTPError("https://provider.test", status, "HTTP failure", {}, BytesIO(body))

    urlopen = Mock(side_effect=http_failure)
    monkeypatch.setattr(fredapi.fred, "urlopen", urlopen)

    result = retry.fred_get_series(Fred(api_key="x" * 32), "INVALID_SERIES")

    assert result.empty
    assert urlopen.call_count == (1 if status == 400 else 4)
    assert sleep.call_count == (0 if status == 400 else 3)


def test_momentum_metadata_for_fx_and_futures_has_no_empty_retries(monkeypatch, sleep, caplog):
    from portfolio.momentum.price_momentum import momentum

    ticker = Mock(return_value=SimpleNamespace(info={}))
    monkeypatch.setattr(retry.yf, "Ticker", ticker)

    with caplog.at_level(logging.WARNING, logger="utils.retry"):
        result = momentum.fetch_metadata_batch(["EURUSD=X", "GC=F"], max_workers=2)

    assert result == {"EURUSD=X": (None, None, False), "GC=F": (None, None, False)}
    assert ticker.call_count == 2
    sleep.assert_not_called()
    assert "retrying" not in caplog.text


def test_analyzer_currency_fallback_for_fx_and_futures_has_no_empty_retries(monkeypatch, sleep, caplog):
    from portfolio.portfolio_optimizer import portfolio_analyzer

    info = Mock(return_value={})

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def fast_info(self):
            raise KeyError("currency")

        @property
        def info(self):
            return info(self.symbol)

    monkeypatch.setattr(retry.yf, "Ticker", Ticker)

    with caplog.at_level(logging.WARNING, logger="utils.retry"):
        result = portfolio_analyzer.fetch_currencies(["EURUSD=X", "GC=F"])

    assert result == {"EURUSD=X": portfolio_analyzer.BASE_CCY, "GC=F": portfolio_analyzer.BASE_CCY}
    assert info.call_count == 2
    sleep.assert_not_called()
    assert "retrying" not in caplog.text


def test_generic_http_wrapper_keeps_existing_backoff_policy(monkeypatch, sleep):
    response = requests.Response()
    response.status_code = 200
    operation = Mock(side_effect=[requests.Timeout("unavailable"), response])
    monkeypatch.setattr(retry._requests, "request", operation)

    assert retry.requests_get("https://provider.test") is response

    sleep.assert_called_once_with(2.0)
