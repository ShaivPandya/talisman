from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from api import risk_dashboard, snapshot_store
from api.job_registry import get_job_spec
from api.snapshot_keys import SNAPSHOT_PORTFOLIO_RISK_DASHBOARD
from portfolio.risk_dashboard import aggregate_view, beta_eligible, build_rows, load_market_inputs, measured_betas


def holding(ticker="AAPL", **overrides):
    return {
        "ticker": ticker,
        "asset": "equity",
        "instrument_type": "security",
        "direction": "long",
        "quantity": 100,
        "contract_multiplier": 1,
        "currency": "USD",
        "sector": "Technology",
        "role": "position",
        **overrides,
    }


def market_inputs(observations=90):
    index = pd.bdate_range(end="2026-10-14", periods=observations + 1)
    returns = np.sin(np.arange(observations + 1)) * 0.003 + 0.001
    adjusted = pd.DataFrame(
        {
            "SPY": 100 * np.cumprod(1 + returns),
            "IWM": 100 * np.cumprod(1 + returns * 1.5),
            "AAPL": 100 * np.cumprod(1 + returns * 2),
            "META": 100 * np.cumprod(1 + returns * 2),
            "ES=F": 100 * np.cumprod(1 + returns),
        },
        index=index,
    )
    close = pd.DataFrame(
        {
            "AAPL": [100.0],
            "META": [200.0],
            "METU": [50.0],
            "METD": [20.0],
            "IWM": [100.0],
            "ES=F": [5000.0],
            "CL=F": [70.0],
            "EURUSD=X": [1.2],
            "SAP.DE": [100.0],
            "GBPUSD=X": [1.3],
            "ABC.L": [200.0],
            "AAPL261218C00100000": [2.0],
            "USDCHF=X": [0.8],
        },
        index=pd.to_datetime(["2026-10-14"]),
    )
    return {
        "close": close,
        "adjusted": adjusted,
        "metadata": {},
        "currencies": {column: "USD" for column in adjusted},
    }


@pytest.fixture
def isolated_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_store, "_SQLITE_PATH", tmp_path / "snapshots.db")


def test_exposures_and_hedges_reconcile_independently():
    # $10,000 primary long, $5,000 held short hedge: gross $15,000, net $5,000.
    rows = build_rows(
        [holding(), holding("IWM", quantity=50, direction="short", role="hedge")], market_inputs(), 100_000, None
    )
    all_view = aggregate_view(rows, 100_000)
    assert all_view["summary"] == {
        "long_usd": 10_000,
        "short_usd": 5000,
        "gross_usd": 15_000,
        "net_usd": 5000,
        "long_pct": 10,
        "short_pct": 5,
        "gross_pct": 15,
        "net_pct": 5,
    }
    primary = aggregate_view([rows[0]], 100_000)
    assert primary["summary"]["gross_usd"] == primary["summary"]["net_usd"] == 10_000
    # AAPL return sensitivity 2, shrunk 20% toward one -> 1.8; weight 0.1 -> 0.18.
    assert all_view["betas"]["SPY"]["primary"] == pytest.approx(0.18)
    assert all_view["betas"]["SPY"]["hedges"] == pytest.approx(-0.07)
    assert all_view["betas"]["SPY"]["combined"] == pytest.approx(0.11)
    for buckets in all_view["breakdowns"].values():
        assert sum(row["gross_usd"] for row in buckets) == 15_000
        assert sum(row["net_usd"] for row in buckets) == 5000
        assert sum(row["gross_share_pct"] for row in buckets) == pytest.approx(100)


def test_same_underlying_offsets_preserve_gross_and_distinct_legs():
    rows = build_rows(
        [holding(id="long"), holding(id="short", direction="short", role="hedge")], market_inputs(), 100_000, None
    )
    assert len({row["position_id"] for row in rows}) == 2
    view = aggregate_view(rows, 100_000)
    assert view["summary"]["gross_usd"] == 20_000
    assert view["summary"]["net_usd"] == 0
    assert view["breakdowns"]["underlying"][0]["gross_usd"] == 20_000
    assert view["betas"]["SPY"]["combined"] == pytest.approx(0)


def test_future_contract_legs_roll_up_to_the_continuous_underlying():
    rows = build_rows(
        [
            holding("ESZ26", price_symbol="ES=F", instrument_type="future", contract_multiplier=50, quantity=1),
            holding(
                "ESH27",
                price_symbol="ES=F",
                instrument_type="future",
                contract_multiplier=50,
                quantity=1,
                direction="short",
                role="hedge",
            ),
        ],
        market_inputs(),
        100_000,
        None,
    )
    view = aggregate_view(rows, 100_000)
    assert [row["ticker"] for row in rows] == ["ESZ26", "ESH27"]
    assert view["breakdowns"]["underlying"] == [
        {"name": "ES=F", "gross_usd": 500_000, "net_usd": 0, "position_count": 2, "gross_share_pct": 100}
    ]


def test_firebase_risk_deep_link_rewrites_and_disables_html_caching():
    hosting = json.loads(Path("firebase.json").read_text())["hosting"]
    rewrites = [rule for rule in hosting["rewrites"] if rule.get("destination") == "/index.html"]
    assert any(re.fullmatch(rule["regex"], "/risk") for rule in rewrites)
    headers = [rule for rule in hosting["headers"] if rule.get("regex") and re.fullmatch(rule["regex"], "/risk")]
    assert any(
        header["key"] == "Cache-Control" and "no-store" in header["value"]
        for rule in headers
        for header in rule["headers"]
    )
    assert not any(re.fullmatch(rule["regex"], "/api/risk/dashboard/latest") for rule in rewrites)


def test_futures_fx_and_minor_currency_notional():
    rows = build_rows(
        [
            holding("ES=F", quantity=2, instrument_type="future", contract_multiplier=50),
            holding("CL=F", quantity=1, instrument_type="future", asset="commodity", contract_multiplier=1000),
            holding("SAP.DE", quantity=10, currency="EUR"),
            holding("ABC.L", quantity=100, currency="GBp"),
            holding("USDCHF=X", quantity=1000, instrument_type="spot_fx", asset="fx", currency="CHF"),
        ],
        market_inputs(),
        100_000,
        None,
    )
    assert [row["signed_notional"] for row in rows] == pytest.approx([500_000, 70_000, 1200, 260, 1000])
    assert rows[0]["beta_spy"] == pytest.approx(1)
    assert rows[1]["beta_spy"] is None
    assert not rows[-1]["beta_eligible"]
    assert rows[-1]["fx_rate_to_usd"] == pytest.approx(1.25)


def test_economic_leverage_applied_once_with_underlying_beta():
    rows = build_rows(
        [
            holding("METU", quantity=100),
            holding("METD", quantity=100),
            holding("METD", id="short-inverse", quantity=100, direction="short"),
        ],
        market_inputs(),
        100_000,
        None,
    )
    assert [row["signed_notional"] for row in rows] == [10_000, -2000, 2000]
    assert all(row["underlying_ticker"] == "META" for row in rows)
    assert rows[0]["beta_spy"] == pytest.approx(1.8)
    assert rows[0]["beta_contribution_spy"] == pytest.approx(0.18)
    view = aggregate_view(rows, 100_000)
    assert view["breakdowns"]["underlying"][0]["gross_usd"] == 14_000


def test_options_are_premiums_only_and_never_use_underlying_price():
    option = holding(
        instrument_type="option",
        option_contract_symbol="AAPL261218C00100000",
        underlying_ticker="AAPL",
        quantity=1,
        contract_multiplier=100,
        option_type="call",
        option_expiration="2026-12-18",
        option_strike=100,
    )
    rows = build_rows(
        [holding(), option, {**option, "id": "missing-contract", "option_contract_symbol": None}],
        market_inputs(),
        100_000,
        None,
    )
    assert rows[1]["premium_usd"] == 200
    assert rows[1]["gross_notional"] is None
    assert rows[1]["beta_spy"] is None
    assert rows[2]["premium_usd"] is None
    assert "missing_price" in rows[2]["issues"]
    view = aggregate_view(rows, 100_000)
    assert view["summary"]["gross_usd"] == 10_000
    assert view["coverage"]["option_count"] == 2
    assert view["coverage"]["priced_option_count"] == 1


@pytest.mark.parametrize("observations,available", [(59, False), (60, True)])
def test_beta_minimum_paired_observations(observations, available):
    estimate = measured_betas(market_inputs(observations), [holding()])["AAPL"]["SPY"]
    assert estimate["observations"] == observations
    assert (estimate["beta"] is not None) is available
    if available:
        assert estimate["beta"] == pytest.approx(1.8)


def test_missing_or_constant_benchmark_never_gets_assumed_beta():
    inputs = market_inputs()
    inputs["adjusted"]["SPY"] = 100.0
    inputs["adjusted"] = inputs["adjusted"].drop(columns="IWM")
    estimates = measured_betas(inputs, [holding()])["AAPL"]
    assert estimates["SPY"]["beta"] is None
    assert estimates["IWM"]["beta"] is None
    assert not beta_eligible(holding("CL=F", asset="equity", instrument_type="future"))


def test_missing_inputs_unclassified_and_measured_zero_are_distinct():
    rows = build_rows(
        [
            holding(quantity=None, cost_basis=100, conviction=5),
            holding("UNKNOWN", currency=None),
            holding("SAP.DE", currency="EUR", sector=None, asset=None),
            holding("AAPL", id="zero", quantity=0),
        ],
        market_inputs(),
        100_000,
        None,
    )
    assert rows[0]["signed_notional"] is None
    assert rows[1]["signed_notional"] is None
    assert "missing_currency" in rows[1]["issues"]
    assert rows[2]["signed_notional"] == 12_000
    view = aggregate_view(rows, 100_000)
    assert view["coverage"]["valued_linear_count"] == 2
    assert any(bucket["name"] == "Unclassified" for bucket in view["breakdowns"]["asset"])
    assert aggregate_view([rows[0]], 100_000)["summary"]["gross_usd"] is None
    assert aggregate_view([rows[3]], 100_000)["summary"]["gross_usd"] == 0
    assert aggregate_view([], 100_000)["coverage"]["position_count"] == 0


def test_daily_loader_removes_unfinished_bar_and_keeps_raw_marks(monkeypatch):
    index = pd.to_datetime(["2026-10-13", "2026-10-14"])
    columns = pd.MultiIndex.from_product([["Close", "Adj Close"], ["AAPL", "SPY", "IWM"]])
    raw = pd.DataFrame([[100, 500, 200, 95, 495, 195], [150, 600, 300, 150, 600, 300]], index=index, columns=columns)
    monkeypatch.setattr("portfolio.risk_dashboard.yf_download", lambda *args, **kwargs: raw)
    monkeypatch.setattr(
        "portfolio.risk_dashboard.yf_ticker_info", lambda *args, **kwargs: {"currency": "USD", "sector": "Technology"}
    )
    inputs = load_market_inputs([holding()], now=datetime(2026, 10, 14, 14, tzinfo=UTC))
    assert inputs["close"]["AAPL"].tolist() == [100]
    assert inputs["adjusted"]["AAPL"].tolist() == [95]


def install_compute_mocks(monkeypatch):
    from api.routers import risk as risk_router

    monkeypatch.setattr(risk_dashboard, "load_market_inputs", lambda *args, **kwargs: market_inputs())
    monkeypatch.setattr(
        "api.position_risk.refresh_portfolio_risk",
        lambda: {
            "position_count": 1,
            "average_risk_score": 0.3,
            "max_risk_score": 0.3,
            "risk_buckets": {"low": 1, "medium": 0, "high": 0},
            "quality": "ok",
            "position_snapshots": [],
        },
    )
    payload = {"holdings": [holding()], "book_size": 100_000.0, "book_is_default": False}
    monkeypatch.setattr(risk_dashboard, "dashboard_request", lambda: copy.deepcopy(payload))
    monkeypatch.setattr(risk_router, "dashboard_request", lambda: copy.deepcopy(payload))
    return payload


def test_persist_read_staleness_and_retained_snapshot(isolated_snapshots, monkeypatch):
    payload = install_compute_mocks(monkeypatch)
    result = risk_dashboard.compute_dashboard(payload)
    assert risk_dashboard.PortfolioRiskDashboard.model_validate(result).positions[0].gross_notional == 10_000
    assert risk_dashboard.latest_dashboard()["freshness"]["holdings_changed"] is False
    payload["holdings"][0]["quantity"] = 200
    payload["book_size"] = 200_000
    latest = risk_dashboard.latest_dashboard()
    assert latest["freshness"]["holdings_changed"] is True
    assert latest["freshness"]["book_changed"] is True
    snapshot_store.write_snapshot_failure(SNAPSHOT_PORTFOLIO_RISK_DASHBOARD, "prices offline")
    latest = risk_dashboard.latest_dashboard()
    assert latest["positions"][0]["gross_notional"] == 10_000
    assert latest["freshness"]["refresh_error"] == "prices offline"


def test_failed_refresh_preserves_saved_values(isolated_snapshots, monkeypatch):
    payload = install_compute_mocks(monkeypatch)
    risk_dashboard.compute_dashboard(payload)
    monkeypatch.setattr(
        risk_dashboard,
        "load_market_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("prices offline")),
    )
    with pytest.raises(ValueError, match="prices offline"):
        risk_dashboard.compute_dashboard(payload)
    assert risk_dashboard.latest_dashboard()["views"]["all_holdings"]["summary"]["gross_usd"] == 10_000


def test_empty_portfolio_does_not_download_prices(isolated_snapshots, monkeypatch):
    payload = install_compute_mocks(monkeypatch)
    payload["holdings"] = []
    monkeypatch.setattr(
        risk_dashboard, "load_market_inputs", lambda *args, **kwargs: pytest.fail("empty portfolios need no downloads")
    )
    assert risk_dashboard.compute_dashboard(payload)["views"]["all_holdings"]["summary"]["gross_usd"] == 0


@pytest.mark.parametrize(
    ("changes", "issue"),
    [
        ({"quantity": None}, "missing_quantity"),
        ({"ticker": "NOQUOTE"}, "missing_price"),
        ({"currency": "JPY"}, "missing_fx_rate"),
    ],
)
def test_unavailable_portfolio_persists_visible_coverage(isolated_snapshots, monkeypatch, changes, issue):
    payload = install_compute_mocks(monkeypatch)
    payload["holdings"] = [holding(**changes)]
    risk_dashboard.compute_dashboard(payload)
    saved = risk_dashboard.latest_dashboard()
    assert saved["quality"] == "degraded"
    assert len(saved["positions"]) == 1
    assert issue in saved["positions"][0]["issues"]
    assert saved["positions"][0]["signed_notional"] is None
    view = saved["views"]["all_holdings"]
    assert view["coverage"]["linear_count"] == 1
    assert view["coverage"]["valued_linear_count"] == 0
    assert view["summary"]["gross_usd"] is None
    assert view["summary"]["net_pct"] is None


def test_fingerprint_stable_for_bookkeeping_but_tracks_legs_and_edits():
    rows = [holding(id="one"), holding(id="two", direction="short")]
    original = risk_dashboard.holdings_fingerprint(rows)
    assert risk_dashboard.holdings_fingerprint(list(reversed(rows))) == original
    rows[0]["loaded_at"] = "new bookkeeping"
    assert risk_dashboard.holdings_fingerprint(rows) == original
    rows[0]["quantity"] = 101
    assert risk_dashboard.holdings_fingerprint(rows) != original
    spec = get_job_spec("portfolio_risk_dashboard")
    assert spec.completed_ttl_s == 300
    assert spec.timeout_s == 600


def test_dashboard_api_requires_authentication(client):
    assert client.get("/api/risk/dashboard/latest").status_code == 401
    assert client.post("/api/risk/dashboard/refresh").status_code == 401
    assert client.get("/api/risk/dashboard/async/example").status_code == 401


def test_api_read_never_computes_and_csrf_required(auth_client, isolated_snapshots, monkeypatch):
    payload = install_compute_mocks(monkeypatch)
    assert auth_client.get("/api/risk/dashboard/latest").status_code == 404
    risk_dashboard.compute_dashboard(payload)
    monkeypatch.setattr(
        risk_dashboard, "load_market_inputs", lambda *args, **kwargs: pytest.fail("reads must not download")
    )
    assert auth_client.get("/api/risk/dashboard/latest").status_code == 200
    auth_client._csrf_token = None
    assert auth_client.post("/api/risk/dashboard/refresh").status_code == 403


def test_async_refresh_deduplicates_and_polls(auth_client, isolated_snapshots, monkeypatch, tmp_path):
    from api import async_job_runner, job_events, job_queue

    payload = install_compute_mocks(monkeypatch)
    monkeypatch.setattr(job_queue, "_memory_jobs", {})
    monkeypatch.setattr(job_events, "_memory_events", {})
    monkeypatch.setattr(async_job_runner, "_enqueue_local_job", lambda job_id: None)
    first = auth_client.post("/api/risk/dashboard/refresh")
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    second = auth_client.post("/api/risk/dashboard/refresh")
    assert second.json()["job_id"] == job_id
    assert auth_client.get(f"/api/risk/dashboard/async/{job_id}").json()["status"] == "queued"
    async_job_runner.perform_job(job_id)
    done = auth_client.get(f"/api/risk/dashboard/async/{job_id}")
    assert done.json()["status"] == "done"
    assert done.json()["result"]["views"]["all_holdings"]["summary"]["gross_usd"] == 10_000
    cached = auth_client.post("/api/risk/dashboard/refresh")
    assert cached.status_code == 200
    assert cached.json()["job_id"] == job_id
    payload["holdings"][0]["quantity"] = 101
    assert auth_client.post("/api/risk/dashboard/refresh").json()["job_id"] != job_id
    other, _ = job_queue.create_or_reuse_job("hedging", payload={}, cache_key="other")
    assert auth_client.get(f"/api/risk/dashboard/async/{other['job_id']}").status_code == 404
