"""Independent financial identities, SEC normalization and API ownership contracts."""

import copy
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from api import graph_fundamentals as gf


def companyfacts():
    """Three years of known flows, YTD cash flows and period-end balances."""
    values = {
        "revenue": 100,
        "eps": 1,
        "net_income": 10,
        "gross_profit": 60,
        "operating_income": 20,
        "assets": 200,
        "cash": 30,
        "equity": 100,
        "shares": 10,
        "cfo": 15,
        "capex": 5,
        "sbc": 1,
        "dividends": 2,
        "buybacks": 3,
        "cost": 40,
        "sga": 7,
        "rd": 3,
        "da": 4,
        "interest": 2,
        "tax": 4,
        "pretax": 16,
        "diluted_shares": 10,
        "debt_total": 50,
    }
    gaap = {}
    for field in [*gf.FIELDS, *gf.INTERNAL]:
        if field.id not in values or not field.concepts:
            continue
        rows = []
        for year in (2023, 2024, 2025):
            for q, month, day in ((1, 3, 31), (2, 6, 30), (3, 9, 30), (4, 12, 31)):
                end = f"{year}-{month:02}-{day}"
                row = {
                    "end": end,
                    "val": values[field.id],
                    "fy": year,
                    "fp": f"Q{q}",
                    "form": "10-Q" if q < 4 else "10-K",
                    "filed": f"{year + (q == 4)}-{'02-15' if q == 4 else f'{month + 1:02}-20'}",
                    "accn": f"{year}-q{q}",
                }
                if field.kind != "stock":
                    row["start"] = f"{year}-{month - 2:02}-01"
                    # Cash flow statements often have only year-to-date values.
                    if field.id in {"cfo", "capex", "dividends", "buybacks", "sbc"}:
                        row["start"] = f"{year}-01-01"
                        row["val"] *= q
                rows.append(row)
            if field.kind != "stock":
                rows.append(
                    {
                        "start": f"{year}-01-01",
                        "end": f"{year}-12-31",
                        "val": values[field.id] * (1 if field.kind == "average" else 4),
                        "fy": year,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": f"{year + 1}-02-15",
                        "accn": f"{year}-annual",
                    }
                )
        unit = "shares" if field.unit == "count" else "USD/shares" if field.kind == "eps" else "USD"
        gaap[field.concepts[0]] = {"units": {unit: rows}}
    return {"entityName": "Fixture Incorporated", "facts": {"us-gaap": gaap}}


def company(ticker="AAA"):
    facts = companyfacts()
    return {
        "ticker": ticker,
        "name": "Fixture",
        "cik": "0000000001",
        "currency": "USD",
        "quote_currency": "USD",
        "quarters": gf._extract(facts, "USD", "quarters"),
        "annual": gf._extract(facts, "USD", "annual"),
        "prices": [
            {"date": f"{y}-{m:02}-{d}", "value": 100}
            for y in (2023, 2024, 2025)
            for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
        ],
        "source": "SEC EDGAR",
        "as_of": "2026-01-01T00:00:00Z",
        "estimates": {},
    }


def value(grid, field, end="2025-12-31"):
    return next(p["value"] for p in grid[field]["points"] if p["date"] == end)


@pytest.mark.parametrize("period", ["quarters", "ltm", "annual"])
def test_all_40_catalog_fields_and_flow_stock_identities(period):
    grid = gf.compute_company(company(), period)
    assert len(gf.catalog()) == 40
    assert all(value(grid, field.id) is not None for field in gf.FIELDS)
    multiplier = 1 if period == "quarters" else 4
    assert value(grid, "revenue") == 100 * multiplier
    assert value(grid, "capex") == 5 * multiplier  # YTD cash flows become discrete quarters.
    assert value(grid, "fcf") == 10 * multiplier
    assert value(grid, "eps") == multiplier
    assert value(grid, "assets") == 200  # A stock is never summed for LTM.
    assert value(grid, "gross_margin") == 60
    assert value(grid, "operating_margin") == 20
    assert value(grid, "debt") == 50
    assert value(grid, "net_debt") == 20
    assert value(grid, "roic") == pytest.approx(12.5 * multiplier)
    assert value(grid, "roe") == 10 * multiplier
    assert value(grid, "market_cap") == 1000
    assert value(grid, "enterprise_value") == 1020
    assert value(grid, "pe") == 25
    assert value(grid, "fcf_yield") == 4
    assert value(grid, "dividend_yield") == 0.8
    assert grid["pe"]["computed"] is True
    assert grid["revenue"]["points"][-1]["filing_url"].startswith("https://www.sec.gov/")


def test_historical_pe_uses_three_historical_prices_and_reported_shares():
    bundle = company()
    ends = ["2025-06-30", "2025-09-30", "2025-12-31"]
    for price, end in zip((100, 102, 104), ends, strict=True):
        next(p for p in bundle["prices"] if p["date"] == end)["value"] = price
    grid = gf.compute_company(bundle, "quarters")
    for expected, end in zip((25, 25.5, 26), ends, strict=True):
        assert value(grid, "pe", end) == expected
    bundle["quarters"]["shares"][ends[-1]]["val"] = 20
    assert value(gf.compute_company(bundle, "quarters"), "pe") == 52


def test_weekend_price_uses_previous_close_and_rejects_future_stale_and_fx():
    bundle = company()
    bundle["prices"] = [{"date": "2025-12-30", "value": 99}, {"date": "2026-01-01", "value": 500}]
    assert value(gf.compute_company(bundle, "quarters"), "market_cap") == 990
    bundle["prices"] = [{"date": "2025-12-01", "value": 99}]
    assert value(gf.compute_company(bundle, "quarters"), "market_cap") is None
    bundle = company()
    bundle["quote_currency"] = "EUR"
    assert value(gf.compute_company(bundle, "quarters"), "pe") is None


def test_gaps_zero_denominators_and_negative_earnings_remain_null():
    bundle = company()
    bundle["quarters"]["revenue"]["2025-12-31"]["val"] = 0
    bundle["quarters"]["interest"]["2025-12-31"]["val"] = 0
    bundle["quarters"]["net_income"]["2025-12-31"]["val"] = -100
    bundle["quarters"]["cfo"].pop("2025-06-30")
    bundle["annual"]["cfo"].pop("2025-12-31")
    grid = gf.compute_company(bundle, "quarters")
    assert value(grid, "operating_margin") is None
    assert value(grid, "interest_coverage") is None
    assert value(grid, "pe") is None
    assert value(grid, "fcf_yield") is None
    assert grid["pe"]["points"][-1]["reason"]
    json.dumps(grid, allow_nan=False)


def test_latest_comparative_does_not_displace_own_filing_and_explicit_amendment_wins():
    facts = companyfacts()
    rows = facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    own = next(r for r in rows if r["end"] == "2024-03-31")
    rows.append({**own, "fy": 2025, "filed": "2025-04-20", "val": 999, "accn": "comparative"})
    assert gf._extract(facts, "USD", "quarters")["revenue"]["2024-03-31"]["val"] == 100
    rows.append({**own, "form": "10-Q/A", "filed": "2024-05-01", "val": 110, "accn": "amendment"})
    assert gf._extract(facts, "USD", "quarters")["revenue"]["2024-03-31"]["val"] == 110


def test_split_prices_reconstructed_and_one_companyfacts_call(monkeypatch):
    import pandas as pd
    import yfinance as yf

    calls = []
    monkeypatch.setattr(gf, "get_cik_for_ticker", lambda t: "1")
    monkeypatch.setattr(gf, "fetch_companyfacts_by_cik", lambda cik, **kw: calls.append((cik, kw)) or companyfacts())

    class Ticker:
        def history(self, **kwargs):
            assert kwargs["auto_adjust"] is False
            return pd.DataFrame(
                {"Close": [25, 30, 31], "Stock Splits": [0, 4, 0]},
                index=pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-03"]),
            )

        def get_history_metadata(self):
            return {"currency": "USD"}

        def get_earnings_estimate(self, **kwargs):
            return pd.DataFrame()

        def get_revenue_estimate(self):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", lambda _: Ticker())
    loaded = gf.load_company("AAA")
    assert loaded["prices"][0]["value"] == 100
    assert loaded["prices"][1]["value"] == 30
    assert len(calls) == 1 and calls[0][1]["force_refresh"] is True
    assert value(gf.compute_company(loaded, "quarters"), "pe") == 25


def test_yfinance_fallback_labels_currency_and_normalizes_cash_outflows(monkeypatch):
    import pandas as pd
    import yfinance as yf

    monkeypatch.setattr(gf, "get_cik_for_ticker", lambda _: None)

    class Ticker:
        def get_info(self):
            return {"financialCurrency": "EUR", "currency": "EUR"}

        def get_income_stmt(self, **kwargs):
            return pd.DataFrame({pd.Timestamp("2025-12-31"): {"Total Revenue": 100, "Diluted EPS": 2}})

        def get_balance_sheet(self, **kwargs):
            return pd.DataFrame()

        def get_cashflow(self, **kwargs):
            return pd.DataFrame({pd.Timestamp("2025-12-31"): {"Operating Cash Flow": 15, "Capital Expenditure": -5}})

        def history(self, **kwargs):
            return pd.DataFrame()

        def get_history_metadata(self):
            return {}

        def get_earnings_estimate(self):
            return pd.DataFrame()

        def get_revenue_estimate(self):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", lambda _: Ticker())
    loaded = gf.load_company("EU")
    grid = gf.compute_company(loaded, "quarters")
    assert value(grid, "fcf") == 10
    assert grid["revenue"]["currency"] == "EUR"
    assert "limited history" in grid["revenue"]["source"]
    assert value(grid, "roic") is None


def test_estimates_only_supplied_eps_and_revenue_not_ltm_or_margins():
    bundle = company()
    bundle["estimates"] = {
        key: {
            "0q": {"value": 123, "analysts": 9, "as_of": "2026-11-06", "basis": "unknown"},
            "+1q": {"value": 124, "analysts": 8, "as_of": "2026-11-06", "basis": "unknown"},
        }
        for key in ("eps", "revenue")
    }
    # Fix the observation date through the latest fixture quarter rather than
    # assuming the test's wall-clock date will always be near these fixtures.
    from api import graph_fundamentals as module

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 15)

    original = module.date
    module.date = FixedDate
    try:
        grid = gf.compute_company(bundle, "quarters")
        for key in ("eps", "revenue"):
            forecasts = [p for p in grid[key]["points"] if p["estimate"]]
            assert [p["date"] for p in forecasts] == ["2026-03-31", "2026-06-30"]
            assert forecasts[0]["analysts"] == 9
            assert forecasts[0]["as_of"] == "2026-11-06"
        assert not any(p["estimate"] for p in grid["roic"]["points"])
        assert not any(p["estimate"] for p in gf.compute_company(bundle, "ltm")["eps"]["points"])
    finally:
        module.date = original


@pytest.fixture
def chart_state():
    return {
        "version": 1,
        "tickers": ["AAA"],
        "period": "quarters",
        "range": "5Y",
        "panes": [
            {
                "id": "pane1",
                "field": "revenue",
                "series": [
                    {
                        "id": "aaa-revenue",
                        "ticker": "AAA",
                        "field": "revenue",
                        "label": "",
                        "color": "#38bdf8",
                        "width": 2,
                        "visualization": "line",
                        "style": "solid",
                        "transform": "none",
                        "estimates": True,
                    }
                ],
            }
        ],
    }


@pytest.fixture
def isolated_charts(tmp_path, monkeypatch):
    from api import graph_fundamental_charts as store

    monkeypatch.setattr(store, "SQLITE_PATH", tmp_path / "charts.sqlite3")


def test_saved_layout_create_update_rename_roundtrip_and_delete(auth_client, isolated_charts, chart_state):
    saved = auth_client.post("/api/graph-fundamental-charts", json={"name": "Peers", "state": chart_state})
    assert saved.status_code == 201, saved.text
    saved = saved.json()
    identifier = saved["chart_id"]
    assert auth_client.get(f"/api/graph-fundamental-charts/{identifier}").json() == saved
    assert auth_client.get("/api/graph-fundamental-charts").json()["charts"][0]["name"] == "Peers"
    chart_state["panes"][0]["series"][0]["transform"] = "index"
    updated = auth_client.put(
        f"/api/graph-fundamental-charts/{identifier}", json={"name": "Renamed", "state": chart_state}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["state"]["panes"][0]["series"][0]["transform"] == "index"
    assert updated.json()["name"] == "Renamed"
    assert "owner_id" not in updated.json()
    assert auth_client.delete(f"/api/graph-fundamental-charts/{identifier}").status_code == 204
    assert auth_client.get(f"/api/graph-fundamental-charts/{identifier}").status_code == 404


def test_saved_charts_require_auth_and_are_owner_scoped(auth_client, client, isolated_charts, chart_state):
    from api.routers.auth import require_actor
    from ontology.policy import Actor

    saved = auth_client.post("/api/graph-fundamental-charts", json={"name": "Private", "state": chart_state}).json()
    identifier = saved["chart_id"]
    auth_client.app.dependency_overrides[require_actor] = lambda: Actor(actor_id="other", actor_type="human")
    try:
        assert auth_client.get("/api/graph-fundamental-charts").json() == {"charts": []}
        assert auth_client.get(f"/api/graph-fundamental-charts/{identifier}").status_code == 404
        assert (
            auth_client.put(
                f"/api/graph-fundamental-charts/{identifier}", json={"name": "Stolen", "state": chart_state}
            ).status_code
            == 404
        )
        assert auth_client.delete(f"/api/graph-fundamental-charts/{identifier}").status_code == 404
    finally:
        auth_client.app.dependency_overrides.pop(require_actor)
    client.cookies.clear()
    assert client.get("/api/graph-fundamental-charts").status_code == 401
    assert client.post("/api/graph-fundamentals", json={"tickers": ["AAA"], "fields": ["revenue"]}).status_code == 401


@pytest.mark.parametrize(
    "patch",
    [
        {"tickers": ["A"] * 7},
        {"fields": ["unknown"]},
        {"fields": ["revenue"] * 25},
        {"range": "Custom"},
        {"range": "Custom", "start_date": "2026-01-01", "end_date": "2025-01-01"},
    ],
)
def test_request_limits(auth_client, patch):
    response = auth_client.post("/api/graph-fundamentals", json={"tickers": ["AAA"], "fields": ["revenue"], **patch})
    assert response.status_code == 422


def test_chart_rejects_cycles_and_invalid_estimates(auth_client, isolated_charts, chart_state):
    chart_state["panes"][0]["series"][0]["field"] = "roic"
    assert (
        auth_client.post("/api/graph-fundamental-charts", json={"name": "bad", "state": chart_state}).status_code == 422
    )
    row = chart_state["panes"][0]["series"][0]
    row.update(ticker=None, field=None, operation="divide", a=row["id"], b=row["id"], estimates=False)
    assert (
        auth_client.post("/api/graph-fundamental-charts", json={"name": "bad", "state": chart_state}).status_code == 422
    )


def test_max_chart_one_fetch_per_ticker_cache_add_field_and_partial_failure(auth_client, monkeypatch):
    from api import cache
    from api.routers import graph_fundamentals as router

    calls = Counter()

    def load(ticker):
        calls[ticker] += 1
        if ticker == "BAD":
            raise ValueError("unsupported")
        return company(ticker)

    monkeypatch.setattr(gf, "load_company", load)
    cache.invalidate_all()
    request = {
        "tickers": ["AAA", "BBB", "CCC", "DDD", "EEE", "BAD"],
        "fields": ["revenue", "roic", "pe", "operating_margin"],
        "range": "10Y",
    }
    started = time.monotonic()
    response = auth_client.post("/api/graph-fundamentals", json=request)
    assert response.status_code == 200, response.text
    assert time.monotonic() - started < 10
    data = response.json()
    assert len(data["series"]) == 24
    assert data["series"][-1]["points"] == [] and data["series"][-1]["reason"]
    assert all(count == 1 for count in calls.values())
    response = auth_client.post(
        "/api/graph-fundamentals", json={**request, "tickers": ["AAA"], "fields": ["fcf_yield"]}
    )
    assert response.status_code == 200 and calls["AAA"] == 1
    # Raw facts are reused when switching between annual and quarterly grids.
    assert (
        auth_client.post(
            "/api/graph-fundamentals", json={**request, "tickers": ["AAA"], "fields": ["fcf_yield"], "period": "annual"}
        ).status_code
        == 200
    )
    assert calls["AAA"] == 1
    cache.invalidate_all()


def test_slow_ticker_budget_does_not_block_good_series(auth_client, monkeypatch):
    from api.routers import graph_fundamentals as router

    monkeypatch.setattr(router, "REQUEST_BUDGET_SECONDS", 0.05)

    def load(ticker, _):
        if ticker == "SLOW":
            time.sleep(0.25)
        return gf.compute_company(company(ticker), "quarters")

    monkeypatch.setattr(router, "_load", load)
    started = time.monotonic()
    data = auth_client.post("/api/graph-fundamentals", json={"tickers": ["AAA", "SLOW"], "fields": ["revenue"]}).json()
    assert time.monotonic() - started < 0.2
    assert data["series"][0]["points"] and not data["series"][1]["points"]


def test_migration_upgrades_and_downgrades(tmp_path):
    import importlib.util

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path("migrations/versions/20261106_0001_graph_fundamental_charts.py")
    spec = importlib.util.spec_from_file_location("graph_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        assert "graph_fundamental_charts" in sa.inspect(conn).get_table_names()
        module.downgrade()
        assert "graph_fundamental_charts" not in sa.inspect(conn).get_table_names()


def test_period_end_shares_win_over_newer_cover_page_and_concepts_fill_gaps():
    facts = companyfacts()
    facts["facts"]["dei"] = {
        "EntityCommonStockSharesOutstanding": {
            "units": {
                "shares": [
                    {"end": "2026-01-31", "val": 999, "filed": "2026-02-15", "fy": 2025, "fp": "FY", "form": "10-K"}
                ]
            }
        }
    }
    gaap = facts["facts"]["us-gaap"]
    # A filer switches the cash tag for its most recent period.
    row = gaap["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"].pop()
    gaap["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"] = {"units": {"USD": [row]}}
    extracted = gf._extract(facts, "USD", "quarters")
    assert extracted["shares"]["2025-12-31"]["val"] == 10
    assert extracted["shares"]["2026-01-31"]["val"] == 999
    assert extracted["cash"]["2025-12-31"]["val"] == 30
    assert extracted["cash"]["2025-12-31"]["concept"] == "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"


def test_missing_ytd_quarter_is_not_a_six_month_flow_reported_as_one_quarter():
    from portfolio.momentum.fundamental_momentum._edgar_periods import _quarterly_flow_entries

    rows = [
        {
            "start": "2025-01-01",
            "end": "2025-03-31",
            "val": 10,
            "fy": 2025,
            "fp": "Q1",
            "form": "10-Q",
            "filed": "2025-04-20",
        },
        {
            "start": "2025-01-01",
            "end": "2025-09-30",
            "val": 30,
            "fy": 2025,
            "fp": "Q3",
            "form": "10-Q",
            "filed": "2025-10-20",
        },
    ]
    normalized = _quarterly_flow_entries(rows)
    assert [(r["end"], r["val"]) for r in normalized] == [("2025-03-31", 10)]


def test_yfinance_statement_rows_accept_raw_camel_case_and_pretty_labels():
    import pandas as pd

    class Ticker:
        def get_balance_sheet(self, **kwargs):
            return pd.DataFrame(
                {
                    pd.Timestamp("2025-12-31"): {
                        "TotalDebt": 70,
                        "OrdinarySharesNumber": 12,
                        "Cash And Cash Equivalents": 8,
                    }
                }
            )

    rows = gf._yf_statements(Ticker(), "annual", "USD", getters=("get_balance_sheet",))
    assert rows["debt_total"]["2025-12-31"]["val"] == 70
    assert rows["shares"]["2025-12-31"]["val"] == 12
    assert rows["cash"]["2025-12-31"]["val"] == 8


def test_missing_sec_debt_can_use_reported_balance_fallback_without_overwriting_sec():
    bundle = company()
    end = "2025-12-31"
    before = "2025-09-30"
    for period in (before, end):
        bundle["quarters"]["debt_total"].pop(period)
    assert value(gf.compute_company(bundle, "quarters"), "roic") is None
    fallback = {
        "debt_total": {period: {"end": period, "val": 50, "source": "yfinance statements"} for period in (before, end)},
        "cash": {end: {"end": end, "val": 999, "source": "yfinance statements"}},
    }
    gf._merge_statement_fallback(bundle["quarters"], fallback)
    assert bundle["quarters"]["cash"][end]["val"] == 30
    # Yahoo's TotalDebt already includes short-term debt. Do not add it again.
    bundle["quarters"].setdefault("short_debt", {})[end] = {"val": 10}
    grid = gf.compute_company(bundle, "quarters")
    assert value(grid, "debt") == 50
    assert value(grid, "roic") == pytest.approx(12.5)
    assert "yfinance statement fallback" in grid["roic"]["source"]
    assert "yfinance statement fallback" in grid["roic"]["points"][-1]["source"]
    assert grid["revenue"]["source"] == "SEC EDGAR"


def test_balance_fallback_aligns_nearby_fiscal_month_ends_and_preserves_source_date():
    primary = {"revenue": {"2025-01-26": {"val": 100}, "2025-04-27": {"val": 110}}}
    fallback = {
        "shares": {
            "2025-01-31": {"end": "2025-01-31", "val": 10, "source": "yfinance statements"},
            "2025-02-28": {"end": "2025-02-28", "val": 99, "source": "yfinance statements"},
        }
    }
    gf._merge_statement_fallback(primary, fallback)
    assert set(primary["shares"]) == {"2025-01-26"}
    assert primary["shares"]["2025-01-26"]["source_period_end"] == "2025-01-31"
    assert primary["shares"]["2025-01-26"]["val"] == 10
    assert gf._needs_balance_fallback(primary, 8)


def test_balance_fallback_keeps_complete_sec_debt_components():
    primary = {
        "revenue": {"2025-12-31": {"val": 100}},
        "debt_current": {"2025-12-31": {"val": 10}},
        "debt_noncurrent": {"2025-12-31": {"val": 40}},
    }
    fallback = {"debt_total": {"2025-12-31": {"end": "2025-12-31", "val": 99, "source": "yfinance statements"}}}
    gf._merge_statement_fallback(primary, fallback)
    assert "debt_total" not in primary


def test_us_filings_can_supplement_missing_balance_inputs_once_per_frequency(monkeypatch):
    import pandas as pd
    import yfinance as yf

    facts = companyfacts()
    facts["facts"]["us-gaap"].pop("LongTermDebtAndFinanceLeaseObligationsIncludingCurrentMaturities")
    calls = []
    monkeypatch.setattr(gf, "get_cik_for_ticker", lambda _: "1")
    monkeypatch.setattr(gf, "fetch_companyfacts_by_cik", lambda *a, **kw: facts)

    class Ticker:
        def get_info(self):
            return {"financialCurrency": "USD"}

        def get_balance_sheet(self, **kwargs):
            calls.append(kwargs["freq"])
            return pd.DataFrame({pd.Timestamp(end): {"TotalDebt": 50} for end in ("2025-09-30", "2025-12-31")})

        def history(self, **kwargs):
            return pd.DataFrame()

        def get_history_metadata(self):
            return {"currency": "USD"}

        def get_earnings_estimate(self, **kwargs):
            return pd.DataFrame()

        def get_revenue_estimate(self):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", lambda _: Ticker())
    loaded = gf.load_company("AAA")
    assert calls == ["quarterly", "yearly"]
    assert value(gf.compute_company(loaded, "quarters"), "roic") == pytest.approx(12.5)


def test_balance_fallback_does_not_mix_statement_currencies(monkeypatch):
    import pandas as pd
    import yfinance as yf

    facts = companyfacts()
    facts["facts"]["us-gaap"].pop("LongTermDebtAndFinanceLeaseObligationsIncludingCurrentMaturities")
    monkeypatch.setattr(gf, "get_cik_for_ticker", lambda _: "1")
    monkeypatch.setattr(gf, "fetch_companyfacts_by_cik", lambda *a, **kw: facts)

    class Ticker:
        def get_info(self):
            return {"financialCurrency": "EUR"}

        def get_balance_sheet(self, **kwargs):
            raise AssertionError("Incompatible currency must not be fetched/merged")

        def history(self, **kwargs):
            return pd.DataFrame()

        def get_history_metadata(self):
            return {"currency": "USD"}

        def get_earnings_estimate(self, **kwargs):
            return pd.DataFrame()

        def get_revenue_estimate(self):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", lambda _: Ticker())
    assert value(gf.compute_company(gf.load_company("AAA"), "quarters"), "roic") is None


def test_missing_reported_pretax_income_uses_statement_fallback_with_source(monkeypatch):
    import pandas as pd
    import yfinance as yf

    facts = companyfacts()
    facts["facts"]["us-gaap"].pop(
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
    )
    calls = []
    monkeypatch.setattr(gf, "get_cik_for_ticker", lambda _: "1")
    monkeypatch.setattr(gf, "fetch_companyfacts_by_cik", lambda *a, **kw: facts)

    class Ticker:
        def get_info(self):
            return {"financialCurrency": "USD"}

        def get_income_stmt(self, **kwargs):
            calls.append(kwargs["freq"])
            return pd.DataFrame(
                {pd.Timestamp("2025-12-31"): {"PretaxIncome": 16 if kwargs["freq"] == "quarterly" else 64}}
            )

        def history(self, **kwargs):
            return pd.DataFrame()

        def get_history_metadata(self):
            return {"currency": "USD"}

        def get_earnings_estimate(self, **kwargs):
            return pd.DataFrame()

        def get_revenue_estimate(self):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", lambda _: Ticker())
    loaded = gf.load_company("AAA")
    assert calls == ["quarterly", "yearly"]
    grid = gf.compute_company(loaded, "quarters")
    assert value(grid, "roic") == pytest.approx(12.5)
    assert "yfinance statement fallback" in grid["roic"]["source"]
    assert grid["revenue"]["source"] == "SEC EDGAR"
