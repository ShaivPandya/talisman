"""Graph Fundamentals data, catalog, search and owner-scoped layouts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Response

from api import graph_fundamental_charts as charts
from api import graph_fundamentals as service
from api.cache import get_or_set_cached, long_cache, short_cache
from api.graph_fundamental_models import GraphRequest, SaveChart
from api.routers.auth import ActorDep
from ontology.sources.source_registry import attach_source_registry_metadata

router = APIRouter()
_ticker_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="graph-fundamentals")
REQUEST_BUDGET_SECONDS = 50


@router.get("/graph-fundamentals/catalog")
def get_catalog():
    return {"fields": service.catalog()}


@router.get("/graph-fundamentals/securities")
def search_securities(q: str = Query(min_length=1, max_length=80)):
    def loader():
        import yfinance as yf

        try:
            results = yf.Search(q, max_results=8, news_count=0, timeout=5).quotes
            return [
                {"ticker": row["symbol"], "name": row.get("shortname") or row.get("longname") or row["symbol"]}
                for row in results
                if row.get("symbol") and row.get("quoteType") == "EQUITY"
            ]
        except Exception:
            return []

    return {
        "securities": get_or_set_cached(
            short_cache, f"graph-securities:v1:{q.strip().upper()}", loader, wait_timeout_s=6
        )
    }


def _load(ticker: str, period: str):
    # The raw bundle and computed grid are independent of fields and visible
    # range, so adding a field never refetches companyfacts, prices or estimates.
    def loader():
        company = get_or_set_cached(
            long_cache, f"graph-company:v1:{ticker}", lambda: service.load_company(ticker), wait_timeout_s=48
        )
        return service.compute_company(company, period)

    return get_or_set_cached(long_cache, f"graph-grid:v1:{ticker}:{period}", loader, wait_timeout_s=50)


@router.post("/graph-fundamentals")
def graph_fundamentals(body: GraphRequest):
    today = date.today()
    end = body.end_date
    anchor = end or today
    start = (
        body.start_date
        if body.range == "Custom"
        else service.shift_year(anchor, -int(body.range[:-1]))
        if body.range.endswith("Y")
        else service.shift_year(anchor, -10)
    )
    # Transforms run client-side and need three years before the visible start.
    assert start is not None  # Custom dates are required by GraphRequest.
    warmup = service.shift_year(start, -3).isoformat()
    series: list[dict] = []
    pending = {_ticker_pool.submit(_load, ticker, body.period): ticker for ticker in body.tickers}
    by_ticker = {}
    completed, _ = wait(pending, timeout=REQUEST_BUDGET_SECONDS)
    for future in completed:
        ticker = pending[future]
        try:
            by_ticker[ticker] = future.result()
        except Exception:
            by_ticker[ticker] = None
    for ticker in body.tickers:
        grid = by_ticker.get(ticker)
        for field_id in body.fields:
            if body.series is not None and not any(s.ticker == ticker and s.field == field_id for s in body.series):
                continue
            definition = service.CATALOG[field_id]
            if grid is None:
                series.append(
                    {
                        "ticker": ticker,
                        "field": field_id,
                        "unit": definition.unit,
                        "currency": None,
                        "source": None,
                        "as_of": None,
                        "points": [],
                        "reason": "Could not load SEC or yfinance data for this ticker. Other tickers are unaffected.",
                        "estimate_coverage": {"supported": definition.estimates, "reason": "Ticker data unavailable."},
                    }
                )
                continue
            item = {**grid[field_id]}
            item["points"] = [
                p for p in item["points"] if p["date"] >= warmup and (end is None or p["date"] <= end.isoformat())
            ]
            if not any(p["value"] is not None for p in item["points"]):
                item["reason"] = f"No usable {definition.label} inputs in this range. {definition.formula}."
            series.append(item)
    return attach_source_registry_metadata(
        {
            "series": series,
            "start_date": start.isoformat(),
            "end_date": end.isoformat() if end else None,
            "period": body.period,
            "history_policy": "Period-owned filings and explicit amendments; descriptive history, not a point-in-time backtest.",
        },
        source_id="graph_fundamentals",
    )


@router.post("/graph-fundamental-charts", status_code=201)
def save_chart(body: SaveChart, actor: ActorDep):
    return charts.save(actor.actor_id, body.name, body.state.model_dump(mode="json"))


@router.get("/graph-fundamental-charts")
def list_charts(actor: ActorDep, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return {"charts": charts.list_charts(actor.actor_id, limit, offset)}


@router.get("/graph-fundamental-charts/{chart_id}")
def get_chart(chart_id: str, actor: ActorDep):
    try:
        return charts.get(actor.actor_id, chart_id)
    except KeyError as exc:
        raise HTTPException(404, "Saved chart not found.") from exc


@router.put("/graph-fundamental-charts/{chart_id}")
def update_chart(chart_id: str, body: SaveChart, actor: ActorDep):
    try:
        return charts.save(actor.actor_id, body.name, body.state.model_dump(mode="json"), chart_id)
    except KeyError as exc:
        raise HTTPException(404, "Saved chart not found.") from exc


@router.delete("/graph-fundamental-charts/{chart_id}", status_code=204)
def delete_chart(chart_id: str, actor: ActorDep):
    if not charts.delete(actor.actor_id, chart_id):
        raise HTTPException(404, "Saved chart not found.")
    return Response(status_code=204)
