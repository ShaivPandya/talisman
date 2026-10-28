from __future__ import annotations

import os
import time

import pytest

from equities.common import universe_loader as ul


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ul, "_INDEX_CACHE_DIR", tmp_path / "universes")


def _tickers(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i:03d}" for i in range(n)]


@pytest.mark.parametrize(("key", "alias"), [("sp400", "S&P 400"), ("sp600", "s&p600"), ("sp500", "sp-500")])
def test_sp_indexes_resolve_from_wikipedia(monkeypatch, key, alias):
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return _tickers("T", 410)

    monkeypatch.setattr(ul, "_fetch_wikipedia_constituents", fake_fetch)
    assert len(ul.get_universe_tickers(alias)) == 410
    assert urls == [ul._SP_INDEXES[key][0]]
    # Second call is served from the 24h cache.
    assert len(ul.get_universe_tickers(key)) == 410
    assert len(urls) == 1


def test_sp_index_falls_back_to_spdr_holdings(monkeypatch):
    def broken(_url):
        raise OSError("wikipedia down")

    calls = []
    monkeypatch.setattr(ul, "_fetch_wikipedia_constituents", broken)
    monkeypatch.setattr(ul, "fetch_etf_holdings_ssga", lambda etf: calls.append(etf) or _tickers("H", 605))
    assert len(ul.get_universe_tickers("sp600")) == 605
    assert calls == ["SPSM"]


def test_sp_index_uses_stale_cache_when_every_source_fails(monkeypatch):
    cache = ul._INDEX_CACHE_DIR / "sp400.txt"
    cache.parent.mkdir(parents=True)
    cache.write_text("\n".join(_tickers("OLD", 400)) + "\n")
    old = time.time() - 3 * 24 * 3600
    os.utime(cache, (old, old))
    monkeypatch.setattr(ul, "_fetch_wikipedia_constituents", lambda _url: [])
    monkeypatch.setattr(ul, "fetch_etf_holdings_ssga", lambda _etf: [])
    assert len(ul.get_universe_tickers("sp400")) == 400


def test_short_constituent_list_is_not_cached(monkeypatch):
    monkeypatch.setattr(ul, "_fetch_wikipedia_constituents", lambda _url: ["AAA", "BBB"])
    monkeypatch.setattr(ul, "fetch_etf_holdings_ssga", lambda _etf: [])
    assert ul.get_universe_tickers("sp400") == ["AAA", "BBB"]
    assert not (ul._INDEX_CACHE_DIR / "sp400.txt").exists()


def test_headerless_universe_csv_keeps_first_ticker(tmp_path):
    path = tmp_path / "mini.csv"
    path.write_text("BE,BLOOM ENERGY\nCRDO,CREDO TECHNOLOGY\nBRK.B,BERKSHIRE\n")
    assert ul.load_universe(str(path)) == ["BE", "CRDO", "BRK-B"]


def test_universe_csv_with_header_still_reads_ticker_column(tmp_path):
    path = tmp_path / "with_header.csv"
    path.write_text("Name,Ticker\nApple,AAPL\nMicrosoft,MSFT\n")
    assert ul.load_universe(str(path)) == ["AAPL", "MSFT"]


def test_russell2000_file_includes_its_first_row():
    tickers = ul.get_universe_tickers("russell2000")
    assert tickers[0] == "BE"
    assert len(tickers) > 1900


@pytest.mark.parametrize(
    "module",
    ["quality", "short_screen", "long_screen", "price_momentum", "fundamental_momentum"],
)
def test_screen_routers_map_sp600(module):
    import importlib

    router = importlib.import_module(f"api.routers.{module}")
    assert router._UNIVERSE_MAP["S&P 600"] == "sp600"
    assert router._UNIVERSE_MAP["S&P 400"] == "sp400"
