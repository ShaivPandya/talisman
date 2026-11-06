"""Versioned, bounded chart configuration shared by saved charts and share URLs."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.graph_fundamentals import CATALOG

Period = Literal["quarters", "ltm", "annual"]
Range = Literal["Auto", "1Y", "3Y", "5Y", "10Y", "Custom"]
Transform = Literal["none", "yoy", "change", "index", "cagr"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def normalized_tickers(values: list[str]) -> list[str]:
    import re

    clean = [v.strip().upper() for v in values]
    if len(set(clean)) != len(clean) or any(not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,19}", v) for v in clean):
        raise ValueError("Enter distinct valid ticker symbols.")
    return clean


class SeriesRequest(StrictModel):
    ticker: str
    field: str


class GraphRequest(StrictModel):
    tickers: list[str] = Field(min_length=1, max_length=6)
    fields: list[str] = Field(min_length=1, max_length=40)
    series: list[SeriesRequest] | None = Field(default=None, min_length=1, max_length=24)
    period: Period = "quarters"
    range: Range = "5Y"
    start_date: date | None = None
    end_date: date | None = None

    _tickers = field_validator("tickers")(normalized_tickers)

    @field_validator("fields")
    @classmethod
    def _fields(cls, values):
        if len(set(values)) != len(values) or any(v not in CATALOG for v in values):
            raise ValueError("Choose distinct fields from the Graph Fundamentals catalog.")
        return values

    @model_validator(mode="after")
    def _range(self):
        if self.series and any(s.ticker not in self.tickers or s.field not in self.fields for s in self.series):
            raise ValueError("Requested series must use the supplied tickers and fields.")
        if self.series is None and len(self.tickers) * len(self.fields) > 24:
            raise ValueError("A chart supports at most 24 ticker × field series.")
        if self.range == "Custom" and (self.start_date is None or self.end_date is None):
            raise ValueError("Custom range requires start and end dates.")
        if any(day and day.year < 1900 for day in (self.start_date, self.end_date)):
            raise ValueError("Dates must be 1900 or later.")
        if self.start_date and self.end_date:
            if self.end_date < self.start_date or (self.end_date - self.start_date).days > 3660:
                raise ValueError("Choose an ordered date range no longer than ten years.")
        return self


class ChartSeries(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    ticker: str | None = None
    field: str | None = None
    a: str | None = None
    b: str | None = None
    operation: Literal["subtract", "divide", "add", "multiply"] | None = None
    label: str = Field(default="", max_length=160)
    color: str = Field(default="#38bdf8", pattern=r"^#[0-9a-fA-F]{6}$")
    width: int = Field(default=2, ge=1, le=5)
    visualization: Literal["line", "bar"] = "line"
    style: Literal["solid", "dashed"] = "solid"
    transform: Transform = "none"
    estimates: bool = False

    @model_validator(mode="after")
    def _series(self):
        if self.operation:
            if not self.a or not self.b or self.ticker or self.field:
                raise ValueError("Arithmetic needs two series inputs and no ticker/field.")
        elif not self.ticker or self.field not in CATALOG or self.a or self.b:
            raise ValueError("A base series needs a ticker and a catalog field.")
        elif self.estimates and not CATALOG[self.field].estimates:
            raise ValueError("Only EPS and revenue support estimates.")
        return self


class ChartPane(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    field: str | None = None
    series: list[ChartSeries] = Field(min_length=1, max_length=24)

    @field_validator("field")
    @classmethod
    def _field(cls, value):
        if value is not None and value not in CATALOG:
            raise ValueError("Unknown pane field.")
        return value


class ChartState(StrictModel):
    version: Literal[1] = 1
    tickers: list[str] = Field(min_length=1, max_length=6)
    period: Period = "quarters"
    range: Range = "5Y"
    start_date: date | None = None
    end_date: date | None = None
    panes: list[ChartPane] = Field(min_length=1, max_length=4)

    _tickers = field_validator("tickers")(normalized_tickers)

    @model_validator(mode="after")
    def _state(self):
        series = [s for p in self.panes for s in p.series]
        ids = [s.id for s in series]
        if len(series) > 24 or len(ids) != len(set(ids)) or len({p.id for p in self.panes}) != len(self.panes):
            raise ValueError("Choose unique IDs and at most 24 series / 4 panes.")
        by_id = {s.id: s for s in series}

        def visit(identifier, seen):
            if identifier in seen or identifier not in by_id:
                raise ValueError("Arithmetic inputs must exist and must not form a cycle.")
            seen.add(identifier)
            item = by_id[identifier]
            if item.operation:
                visit(item.a, seen)
                visit(item.b, seen)
            seen.remove(identifier)

        for s in series:
            if s.ticker and s.ticker not in self.tickers:
                raise ValueError("A series ticker must belong to the chart.")
            visit(s.id, set())
        # Validate period/range without applying the request's Cartesian-product
        # cap: custom charts may contain sparse ticker/field combinations.
        GraphRequest(
            tickers=[self.tickers[0]],
            fields=["revenue"],
            period=self.period,
            range=self.range,
            start_date=self.start_date,
            end_date=self.end_date,
        )
        return self


class SaveChart(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    state: ChartState

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        if not value.strip():
            raise ValueError("Enter a chart name.")
        return value.strip()
