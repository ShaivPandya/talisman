"""Cited observations and publisher forecasts, separate from market regime scores."""

from __future__ import annotations

import csv
import io
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import pandas as pd

from api.alternative_data_adapters import SourceAccessError, SourceClient, number
from api.performance import ContextThreadPoolExecutor

FRED_SERIES = {
    "payrolls": ("PAYEMS", "Nonfarm payrolls", "thousands of persons"),
    "unemployment": ("UNRATE", "Unemployment rate", "%"),
    "retail_sales": ("RSAFS", "Advance retail sales", "millions USD, seasonally adjusted"),
    "real_consumption": ("PCEC96", "Real personal consumption", "billions chained 2017 USD, SAAR"),
    "industrial_production": ("INDPRO", "Industrial production", "index, 2017=100"),
    "case_shiller": ("CSUSHPISA", "Case-Shiller national house prices", "index, Jan 2000=100"),
    "fhfa_hpi": ("USSTHPI", "FHFA national house prices", "index, 1980 Q1=100"),
    "consumer_credit": ("TOTALSL", "Consumer credit", "millions USD, seasonally adjusted"),
    "lending_standards": (
        "DRTSCILM",
        "SLOOS C&I lending standards: large and middle-market firms",
        "net % tightening, NSA",
    ),
}
NY_BASE = "https://www.newyorkfed.org/medialibrary/Research/Interactives/Data/NowCast/data"
GSCPI_CSV = "https://www.newyorkfed.org/medialibrary/research/interactives/data/gscpi/gscpi_interactive_data.csv"
CLEVELAND_BASE = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting"
COUNTRIES = {
    "US": "USA",
    "Canada": "CAN",
    "United Kingdom": "GBR",
    "EU": "EU",
    "Germany": "DEU",
    "Japan": "JPN",
    "France": "FRA",
    "Switzerland": "CHE",
    "Australia": "AUS",
}


def client(host: str) -> SourceClient:
    return SourceClient({"allowed_hosts": [host]})


def reading(key: str, label: str, unit: str, url: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": None,
        "unit": unit,
        "as_of": None,
        "source_url": url,
        "status": "missing",
        "kind": "observation",
        **kwargs,
    }


def fred_reading(key: str, *, fred: Any = None) -> dict[str, Any]:
    from fredapi import Fred

    from utils.retry import fred_get_series

    series_id, label, unit = FRED_SERIES[key]
    result = reading(key, label, unit, "https://fred.stlouisfed.org/series/" + series_id, series_id=series_id)
    if key == "case_shiller" and os.getenv("ALTERNATIVE_DATA_CASE_SHILLER_PERMISSION_CONFIRMED", "").lower() != "true":
        return {
            **result,
            "status": "license_required",
            "note": "FRED marks this copyrighted index as pre-approval required. Configure only after written reuse permission is confirmed.",
        }
    if fred is None and not os.getenv("FRED_API_KEY"):
        return {**result, "status": "setup_required", "note": "FRED_API_KEY is required on the server."}
    try:
        fred = fred or Fred(api_key=os.environ["FRED_API_KEY"])
        series = fred_get_series(fred, series_id, observation_start=date.today() - timedelta(days=365 * 5)).sort_index()
        dates = [d.strftime("%Y-%m-%d") for d in series.index]
        values = [number(value) for value in series.values]
        if dates:
            result.update(value=values[-1], as_of=dates[-1], status="ok" if values[-1] is not None else "missing")
        result.update(dates=dates, values=values)
    except Exception:
        result.update(status="unavailable", note="FRED refresh unavailable; no value was inferred.")
    return result


def normalize_gscpi(text: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    fields = reader.fieldnames or []
    if len(fields) < 2 or fields[0] != "Date":
        raise SourceAccessError("NY Fed GSCPI CSV schema changed.")
    vintage = fields[-1]
    datetime.strptime(vintage, "%b-%y")
    rows = []
    for row in reader:
        if not row.get("Date") and not any(row.values()):
            continue  # The official CSV includes blank spreadsheet padding rows.
        day = datetime.strptime(row["Date"], "%d-%b-%Y").date().isoformat()
        # The last column is the publisher's latest vintage, not an average across vintages.
        if day <= date.today().isoformat():
            rows.append((day, number(row[vintage])))
    if not rows:
        return reading(
            "supply_chain_pressure",
            "NY Fed global supply-chain pressure",
            "standard deviations from historical mean",
            "https://www.newyorkfed.org/research/policy/gscpi",
        )
    day, value = max(rows)
    return reading(
        "supply_chain_pressure",
        "NY Fed global supply-chain pressure",
        "standard deviations from historical mean",
        "https://www.newyorkfed.org/research/policy/gscpi",
        value=value,
        as_of=day,
        vintage=vintage,
        status="ok" if value is not None else "missing",
        data_url=GSCPI_CSV,
    )


def gscpi() -> list[dict[str, Any]]:
    return [normalize_gscpi(client("www.newyorkfed.org").text(GSCPI_CSV))]


def normalize_nyfed(text: str, period: str, release_note: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not {"Update", "Year", "Nowcast"} <= set(reader.fieldnames or []):
        raise SourceAccessError("NY Fed nowcast CSV schema changed.")
    rows = list(reader)
    values = []
    for row in rows:
        if not row.get("Year") and not any(value for key, value in row.items() if key != "Update"):
            continue  # Undated next-release placeholders are not observations.
        if row.get("Note") and not row.get("Nowcast"):
            continue  # Narrative rows share a vintage but do not contain a nowcast.
        day = datetime.strptime(row["Update"] + "-" + row["Year"], "%d-%b-%Y").date().isoformat()
        if day <= date.today().isoformat():
            values.append((day, number(row["Nowcast"])))
    latest = max(values, key=lambda row: row[0]) if values else (None, None)
    return [
        reading(
            "nyfed_gdp",
            "New York Fed Staff Nowcast: real GDP growth",
            "% quarter-on-quarter, annualized",
            "https://www.newyorkfed.org/research/policy/nowcast",
            kind="publisher_nowcast",
            publisher="New York Fed",
            value=latest[1],
            as_of=latest[0],
            vintage_date=latest[0],
            forecast_period=period,
            next_release_note=release_note,
            status="ok" if latest[1] is not None else "missing",
        )
    ]


def nyfed() -> list[dict[str, Any]]:
    source = client("www.newyorkfed.org")
    history = list(csv.DictReader(io.StringIO(source.text(NY_BASE + "/nowcast-history-meta-data.csv"))))
    current = [row for row in history if row.get("landingQuarter") == "1"]
    if (
        len(current) != 1
        or not re.fullmatch(r"20\d\d", current[0].get("year", ""))
        or not re.fullmatch(r"Q[1-4]", current[0].get("quarter", ""))
    ):
        raise SourceAccessError("NY Fed landing-quarter metadata changed.")
    period = current[0]["year"] + current[0]["quarter"]
    content = source.json(NY_BASE + "/nowcast-content.json")
    notes = content["overview"]["left"]["releaseSchedule"]["description"]
    if not isinstance(notes, list) or not notes or any(not isinstance(note, str) for note in notes):
        raise SourceAccessError("NY Fed release-schedule metadata changed.")
    return normalize_nyfed(source.text(NY_BASE + "/" + period + ".csv"), period, " ".join(notes))


def normalize_cleveland(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list) or not data:
        raise SourceAccessError("Cleveland Fed nowcast schema changed.")
    chart = max(data, key=lambda row: tuple(int(part) for part in row["chart"]["subcaption"].split("-")))
    vintage = datetime.fromisoformat(chart["chart"]["_comment"]).date().isoformat()
    period = datetime.strptime(chart["chart"]["subcaption"], "%Y-%m").strftime("%Y-%m")
    rows = []
    datasets = {series["seriesname"]: series["data"] for series in chart["dataset"]}
    for name in ("CPI Inflation", "Core CPI Inflation", "PCE Inflation", "Core PCE Inflation"):
        if name not in datasets or not isinstance(datasets[name], list):
            raise SourceAccessError("Cleveland Fed inflation series changed.")
        values = datasets[name]
        value = number(values[-1]["value"]) if values else None
        rows.append(
            reading(
                "cleveland_" + name.lower().replace(" ", "_"),
                "Cleveland Fed " + name + " nowcast",
                "% year-on-year",
                "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting",
                value=value,
                as_of=vintage,
                vintage_date=vintage,
                forecast_period=period,
                kind="publisher_nowcast",
                publisher="Cleveland Fed",
                next_release_note="Updated each business day; publisher does not specify the next release date in this feed.",
                status="ok" if value is not None else "missing",
            )
        )
    return rows


def cleveland() -> list[dict[str, Any]]:
    return normalize_cleveland(client("www.clevelandfed.org").json(CLEVELAND_BASE + "/nowcast_year.json?sc_lang=en"))


def imf() -> list[dict[str, Any]]:
    from fx.model.src.data_imf import fetch_imf_datamapper_indicator, fetch_imf_datamapper_json
    from paths import PROJECT_ROOT

    metadata = fetch_imf_datamapper_json("indicators")["indicators"]
    result = []
    current_year = date.today().year
    for indicator in ("NGDP_RPCH", "PCPIPCH"):
        info = metadata[indicator]
        if info.get("dataset") != "WEO" or not info.get("source") or not info.get("last-modified"):
            raise SourceAccessError("IMF WEO edition metadata is missing.")
        updated = datetime.fromisoformat(info["last-modified"]).date().isoformat()
        data = fetch_imf_datamapper_json(indicator + "/USA")
        if not isinstance(data, dict) or not isinstance(data.get("values", {}).get(indicator), dict):
            raise SourceAccessError("IMF WEO series schema changed.")
        for country, iso in COUNTRIES.items():
            try:
                series = fetch_imf_datamapper_indicator(
                    indicator, iso, PROJECT_ROOT / "data_cache" / "economic_backdrop", payload=data
                )
            except Exception:
                series = pd.Series(dtype=float)
            for year in (current_year, current_year + 1):
                value = next((number(value) for timestamp, value in series.items() if timestamp.year == year), None)
                result.append(
                    reading(
                        f"imf_{indicator}_{iso}_{year}",
                        f"IMF WEO {info['label']} · {country}",
                        info["unit"],
                        f"https://www.imf.org/external/datamapper/{indicator}@WEO/{iso}",
                        value=value,
                        as_of=updated,
                        vintage=info["source"],
                        vintage_date=updated,
                        vintage_date_kind="publisher metadata last-modified",
                        forecast_period=str(year),
                        country=country,
                        publisher="IMF",
                        kind="publisher_forecast",
                        next_release_note="WEO databases are published in April and October; DataMapper provides no next release date.",
                        status="ok" if value is not None else "missing",
                    )
                )
    return result


def get_data() -> dict[str, Any]:
    # Independent failures preserve the other sources; no forecast feeds a regime score.
    def load_fred(key: str) -> list[dict[str, Any]]:
        return [fred_reading(key)]

    tasks: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
        (key, partial(load_fred, key)) for key in FRED_SERIES
    ]
    tasks += [
        ("supply_chain_pressure", gscpi),
        ("nyfed_gdp", nyfed),
        ("cleveland_inflation", cleveland),
        ("imf_weo", imf),
    ]

    def load(task: tuple[str, Callable[[], list[dict[str, Any]]]]) -> list[dict[str, Any]]:
        key, fetch = task
        try:
            return fetch()
        except Exception:
            urls = {
                "supply_chain_pressure": "https://www.newyorkfed.org/research/policy/gscpi",
                "nyfed_gdp": "https://www.newyorkfed.org/research/policy/nowcast",
                "cleveland_inflation": "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting",
                "imf_weo": "https://www.imf.org/external/datamapper/NGDP_RPCH@WEO",
            }
            label, unit, kind = {
                "supply_chain_pressure": (
                    "NY Fed global supply-chain pressure",
                    "standard deviations from historical mean",
                    "observation",
                ),
                "nyfed_gdp": (
                    "New York Fed Staff Nowcast: real GDP growth",
                    "% quarter-on-quarter, annualized",
                    "publisher_nowcast",
                ),
                "cleveland_inflation": ("Cleveland Fed inflation nowcast", "% year-on-year", "publisher_nowcast"),
                "imf_weo": (
                    "IMF WEO real GDP growth and inflation forecasts",
                    "annual percent change",
                    "publisher_forecast",
                ),
            }.get(key, (key.replace("_", " "), "publisher units unavailable", "observation"))
            return [
                reading(
                    key,
                    label,
                    unit,
                    urls.get(key, "https://fred.stlouisfed.org"),
                    status="unavailable",
                    kind=kind,
                    note="Publisher unavailable or schema changed; no observation or forecast was inferred.",
                )
            ]

    with ContextThreadPoolExecutor(max_workers=4) as pool:
        rows = [row for group in pool.map(load, tasks) for row in group]
    return {
        "readings": rows,
        "as_of": max((row["as_of"] for row in rows if row.get("as_of")), default=None),
        "fetched_at": datetime.now(UTC).isoformat(),
        "note": "Published forecasts belong to their publishers. Market returns and the market-stress regime are separate.",
    }
