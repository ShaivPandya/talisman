import json

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

from api.cache import get_or_set_cached, short_cache, stamp_fresh
from api.exceptions import DataFetchError
from api.serializers import serialize_dataframe, serialize_value

router = APIRouter()


def _cache_key(*params: object) -> str:
    return "chart:v1:" + json.dumps(params, separators=(",", ":"))


def _serialize_chart(data: dict) -> dict:
    import pandas as pd

    if data.get("error"):
        raise HTTPException(status_code=400, detail=data["error"])
    return stamp_fresh(
        {
            key: serialize_dataframe(value.reset_index()) if isinstance(value, pd.DataFrame) else serialize_value(value)
            for key, value in data.items()
        }
    )


def _csv_download_filename(symbol: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in symbol.strip().upper()).strip("_")
    return f"{clean or 'ticker'}_price_history.csv"


class ChartRequest(BaseModel):
    ticker: str
    lookback: str = "2Y"


class RatioChartRequest(BaseModel):
    symbol_a: str
    symbol_b: str
    start_date: str | None = None
    end_date: str | None = None
    method: str = "price_ratio"


@router.post("/chart")
def run_chart(req: ChartRequest):
    ticker = req.ticker.strip().upper()

    def load():
        try:
            from portfolio.technical_analysis.technical_analysis import get_data

            data = get_data(ticker, lookback=req.lookback)
        except Exception as e:
            raise DataFetchError(source="chart", detail=str(e)) from e
        return _serialize_chart(data)

    return ORJSONResponse(get_or_set_cached(short_cache, _cache_key("price", ticker, req.lookback), load))


@router.get("/chart/price-history/{ticker}")
def download_price_history(ticker: str):
    normalized = ticker.strip().upper()
    if not normalized:
        raise HTTPException(status_code=400, detail="Ticker is required.")

    def load():
        try:
            from portfolio.technical_analysis.technical_analysis import fetch_full_price_history

            df = fetch_full_price_history(normalized)
        except Exception as e:
            raise DataFetchError(source="chart", detail=str(e)) from e
        return df.to_csv(index=False)

    csv_text = get_or_set_cached(short_cache, _cache_key("csv", normalized), load)
    filename = _csv_download_filename(normalized)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/chart/ratio")
def run_chart_ratio(req: RatioChartRequest):
    symbol_a = req.symbol_a.strip().upper()
    symbol_b = req.symbol_b.strip().upper()
    if not symbol_a or not symbol_b:
        raise HTTPException(status_code=400, detail="Both symbol_a and symbol_b are required.")

    def load():
        try:
            from portfolio.technical_analysis.technical_analysis import get_ratio_data

            data = get_ratio_data(
                symbol_a=symbol_a,
                symbol_b=symbol_b,
                start_date=req.start_date,
                end_date=req.end_date,
                method=req.method,
            )
        except Exception as e:
            raise DataFetchError(source="chart", detail=str(e)) from e
        return _serialize_chart(data)

    key = _cache_key("ratio", symbol_a, symbol_b, req.start_date, req.end_date, req.method)
    return ORJSONResponse(get_or_set_cached(short_cache, key, load))
