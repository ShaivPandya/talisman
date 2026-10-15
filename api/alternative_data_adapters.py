"""Bounded official-source adapters. Provider payloads are data, never instructions."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any, BinaryIO
from urllib.parse import quote, urljoin, urlparse
from zipfile import ZipFile

import requests  # type: ignore[import-untyped]
from bs4 import BeautifulSoup


class SourceAccessError(RuntimeError):
    """Safe public failure: never include response bodies or credential-bearing URLs."""


_RATE_LOCK = threading.Lock()
_NEXT_REQUEST: dict[str, float] = {}


def _reserve_request(host: str, interval: float) -> None:
    from api.postgres import connect, use_postgres_state

    now = time.time()
    if use_postgres_state():
        with connect() as conn:
            row = conn.execute(
                """INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at
                WHERE app_settings.value::double precision <= %s RETURNING key""",
                (f"alternative_data.rate.{host}", str(now), datetime.now(UTC).isoformat(), now - interval),
            ).fetchone()
            conn.commit()
        if not row:
            raise SourceAccessError("Provider rate limit: retry after the configured interval.")
    else:
        with _RATE_LOCK:
            if _NEXT_REQUEST.get(host, 0) > now:
                raise SourceAccessError("Provider rate limit: retry after the configured interval.")
            _NEXT_REQUEST[host] = now + interval


class SourceClient:
    def __init__(self, spec: dict[str, Any]):
        self.spec = spec

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        max_bytes: int = 12_000_000,
        destination: BinaryIO | None = None,
        **kwargs: Any,
    ) -> bytes:
        for _ in range(4):
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in self.spec["allowed_hosts"]
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
            ):
                raise SourceAccessError("Upstream URL is not an approved HTTPS source.")
            host = str(parsed.hostname)
            interval = 60 if host == "data.aishub.net" else 2 if host == "comtradeapi.un.org" else 0.25
            try:
                _reserve_request(host, interval)
            except SourceAccessError:
                if interval >= 60:
                    raise
                time.sleep(interval)
                _reserve_request(host, interval)
            try:
                headers = {
                    "User-Agent": "TalismanResearch/1.0 (https://github.com/ShaivPandya/talisman; bounded research queries)",
                    **kwargs.pop("headers", {}),
                }
                with requests.request(
                    method, url, timeout=(10, 90), stream=True, allow_redirects=False, headers=headers, **kwargs
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, response.headers.get("Location", ""))
                        if response.status_code == 303:
                            method = "GET"
                            kwargs.pop("data", None)
                            kwargs.pop("json", None)
                        continue
                    if response.status_code != 200:
                        raise SourceAccessError(
                            f"Provider unavailable (HTTP {response.status_code}); no access bypass attempted."
                        )
                    length = response.headers.get("Content-Length", "")
                    if length.isdigit() and int(length) > max_bytes:
                        raise SourceAccessError("Provider download exceeds the bounded download limit.")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > max_bytes:
                            raise SourceAccessError("Provider download exceeds the bounded download limit.")
                        if destination is not None:
                            destination.write(chunk)
                        else:
                            chunks.append(chunk)
                    return b"".join(chunks)
            except requests.RequestException:
                raise SourceAccessError("Provider network request failed; retry later.") from None
        raise SourceAccessError("Provider redirected too many times.")

    def text(self, url: str, **kwargs: Any) -> str:
        return self.request(url, **kwargs).decode("utf-8-sig")

    def json(self, url: str, **kwargs: Any) -> Any:
        try:
            return json.loads(self.request(url, **kwargs))
        except (ValueError, UnicodeError):
            raise SourceAccessError("Provider schema changed: expected JSON.") from None


def number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def observation(day: Any, metric: str, value: Any, unit: str, **dimensions: Any) -> dict[str, Any]:
    return {"date": str(day)[:10], "metric": metric, "value": number(value), "unit": unit, "dimensions": dimensions}


def payload(
    rows: list[dict[str, Any]] | None = None,
    *,
    snapshot: Any = None,
    warnings: list[str] | None = None,
    citations: list[dict[str, str]] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    rows = rows or []
    dates = [row["date"] for row in rows if row.get("date") and row.get("value") is not None]
    return {
        "data_kind": "series" if rows else "snapshot",
        "observations": rows,
        "snapshot": snapshot,
        "as_of": as_of or (max(dates) if dates else None),
        "warnings": warnings or [],
        "citations": citations or [],
    }


def _rows_in_range(rows: list[dict[str, Any]], p: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted([r for r in rows if p["start_date"] <= r["date"] <= p["end_date"]], key=lambda r: r["date"])[
        -p["limit"] :
    ]


def tsa(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for year in range(date.fromisoformat(p["start_date"]).year, date.fromisoformat(p["end_date"]).year + 1):
        url = client.spec["url"] + (f"/{year}" if year < date.today().year else "")
        soup = BeautifulSoup(client.text(url), "html.parser")
        for tr in soup.select("table tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(cells) < 2:
                continue
            try:
                day = datetime.strptime(cells[0], "%m/%d/%Y").date().isoformat()
            except ValueError:
                continue
            if number(cells[1]) is not None:
                rows.append(observation(day, "checkpoint_travelers", cells[1], "people"))
    if not rows:
        raise SourceAccessError("Provider schema changed or no checkpoint table is available.")
    return payload(_rows_in_range(rows, p))


def indeed(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    country = p["country"]
    filename = f"job_postings_by_sector_{country}.csv" if p.get("sector") else f"aggregate_job_postings_{country}.csv"
    url = f"https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/{country}/{filename}"
    reader = csv.DictReader(io.StringIO(client.text(url)))
    if (
        not reader.fieldnames
        or "date" not in reader.fieldnames
        or not ({"indeed_job_postings_index_SA", "indeed_job_postings_index"} & set(reader.fieldnames))
    ):
        raise SourceAccessError("Indeed schema changed: observation columns are missing.")
    rows = []
    for row in reader:
        if p.get("sector") and row.get("display_name", "").casefold() != p["sector"].casefold():
            continue
        if row.get("variable", "total") not in {"total", "total postings"}:
            continue
        value = row.get("indeed_job_postings_index_SA", row.get("indeed_job_postings_index"))
        if number(value) is not None:
            rows.append(
                observation(
                    row["date"],
                    "job_postings_index",
                    value,
                    "index (2020-02-01=100)",
                    country=p["country"],
                    sector=row.get("display_name"),
                )
            )
    return payload(
        _rows_in_range(rows, p), warnings=["Sector hiring is a proxy; this does not measure company job postings."]
    )


def lca(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    soup = BeautifulSoup(client.text(client.spec["url"]), "html.parser")
    links = [
        (a.get_text(" ", strip=True), urljoin(client.spec["url"], str(a.get("href", ""))))
        for a in soup.select("a[href]")
    ]
    candidates = [
        (label, url)
        for label, url in links
        if re.search(r"LCA_Disclosure_Data_FY\d{4}.*\.xlsx", url, re.I)
        and (not p.get("fiscal_year") or f"FY{p['fiscal_year']}" in url)
    ]
    if not candidates:
        raise SourceAccessError("No matching official LCA disclosure workbook is available.")
    label, url = max(candidates, key=lambda item: item[1].split("LCA_Disclosure_Data_")[-1])
    # The agency's disclosure page currently emits a duplicated path slash.
    parsed_url = urlparse(url)
    url = parsed_url._replace(path=re.sub(r"/{2,}", "/", parsed_url.path)).geturl()
    # The current official workbook is ~252MB. Stream it and its shared-string
    # index to temporary storage instead of materializing the workbook in RAM.
    with tempfile.TemporaryDirectory(prefix="talisman-lca-") as temporary:
        with tempfile.TemporaryFile(dir=temporary) as workbook_file:
            client.request(url, max_bytes=300_000_000, destination=workbook_file)
            workbook_file.seek(0)
            result = aggregate_lca(workbook_file, p, temporary)
    result["citations"] = [{"title": label, "url": url}]
    return result


def aggregate_lca(workbook_file: BinaryIO, p: dict[str, Any], temporary: str) -> dict[str, Any]:
    from functools import lru_cache

    from lxml import etree
    from openpyxl.utils.datetime import from_excel

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    counts: Counter[tuple[str, str]] = Counter()
    positions: Counter[tuple[str, str]] = Counter()
    matches = 0
    dates = []
    source_as_of = None
    required = {"EMPLOYER_NAME", "CASE_STATUS", "TOTAL_WORKER_POSITIONS", "DECISION_DATE", "SOC_TITLE"}
    with ZipFile(workbook_file) as archive, sqlite3.connect(temporary + "/strings.sqlite") as strings:
        if sum(info.file_size for info in archive.infolist()) > 4_000_000_000:
            raise SourceAccessError("Disclosure workbook exceeds the bounded expanded-size limit.")
        strings.execute("CREATE TABLE strings (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        if "xl/sharedStrings.xml" in archive.namelist():
            with archive.open("xl/sharedStrings.xml") as stream:
                for index, (_, element) in enumerate(
                    etree.iterparse(stream, events=("end",), tag=ns + "si", resolve_entities=False, no_network=True)
                ):
                    value = "".join(element.itertext())[:16384]
                    strings.execute("INSERT INTO strings VALUES (?, ?)", (index, value))
                    element.clear()
                    while element.getprevious() is not None:
                        del element.getparent()[0]
            strings.commit()

        @lru_cache(maxsize=2048)
        def shared(index: str) -> str:
            row = strings.execute("SELECT value FROM strings WHERE id = ?", (int(index),)).fetchone()
            return str(row[0]) if row else ""

        def decoded(cell: Any) -> str:
            value = cell.findtext(ns + "v") or ""
            if cell.get("t") == "s":
                return shared(value)
            if cell.get("t") == "inlineStr":
                return "".join(cell.itertext())
            return str(value)

        headers: dict[str, str] = {}
        with archive.open("xl/worksheets/sheet1.xml") as stream:
            for _, element in etree.iterparse(
                stream, events=("end",), tag=ns + "row", resolve_entities=False, no_network=True
            ):
                cells = {re.sub(r"\d", "", c.get("r", "")): c for c in element.findall(ns + "c")}
                if not headers:
                    headers = {decoded(cell).strip().upper(): column for column, cell in cells.items()}
                    if not required.issubset(headers):
                        raise SourceAccessError("LCA disclosure schema changed; required columns are missing.")
                else:
                    raw_day = decoded(cells[headers["DECISION_DATE"]]) if headers["DECISION_DATE"] in cells else ""
                    if number(raw_day) is not None:
                        converted = from_excel(float(raw_day))
                        day = converted.date().isoformat() if isinstance(converted, datetime) else ""
                    else:
                        day = raw_day[:10]
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                        source_as_of = max(source_as_of or day, day)
                    employer = decoded(cells[headers["EMPLOYER_NAME"]]) if headers["EMPLOYER_NAME"] in cells else ""
                    if (
                        employer.strip().casefold() == p["employer"].strip().casefold()
                        and p["start_date"] <= day <= p["end_date"]
                    ):
                        values = {
                            key: decoded(cells[headers[key]]) if headers[key] in cells else "" for key in required
                        }
                        matches += 1
                        dates.append(day)
                        key = (values["CASE_STATUS"], values["SOC_TITLE"])
                        counts[key] += 1
                        positions[key] += int(number(values["TOTAL_WORKER_POSITIONS"]) or 0)
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
    covered = source_as_of is not None and p["start_date"] <= source_as_of
    warnings = ["Applications and requested positions are not actual hires or unique workers."]
    if source_as_of and p["end_date"] > source_as_of:
        warnings.append(f"The published disclosure ends {source_as_of}; later requested dates are not covered.")
    return payload(
        snapshot={
            "employer": p["employer"],
            "applications": matches if covered else None,
            "disclosure_through": source_as_of,
            "groups": [
                {"status": k[0], "occupation": k[1], "applications": count, "worker_positions": positions[k]}
                for k, count in counts.most_common(p["limit"])
            ],
        },
        as_of=max(dates) if dates else source_as_of,
        warnings=warnings,
    )


def copernicus(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    if p["operation"] == "indices":
        return sentinel_indices(client, p)
    west, south, east, north = p["bbox"]
    polygon = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    query = (
        f"Collection/Name eq '{p['mission']}' and ContentDate/Start ge {p['start_date']}T00:00:00.000Z "
        f"and ContentDate/Start le {p['end_date']}T23:59:59.999Z and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{polygon}')"
    )
    data = client.json(
        "https://catalogue.dataspace.copernicus.eu/odata/v1/Products",
        params={"$filter": query, "$top": min(p["limit"], 100), "$orderby": "ContentDate/Start desc"},
    )
    if not isinstance(data.get("value"), list):
        raise SourceAccessError("Copernicus scene schema changed.")
    scenes = [
        {
            "scene_id": r["Id"],
            "name": r.get("Name"),
            "observed_at": r.get("ContentDate", {}).get("Start"),
            "footprint": r.get("GeoFootprint"),
            "preview_url": "https://browser.dataspace.copernicus.eu/",
            "download_bytes": r.get("ContentLength"),
        }
        for r in data["value"]
    ]
    return payload(snapshot={"scenes": scenes}, as_of=max((str(s["observed_at"]) for s in scenes), default=None))


def landsat(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    data = client.json(
        "https://landsatlook.usgs.gov/stac-server/search",
        method="POST",
        json={
            "collections": ["landsat-c2l2-sr"],
            "bbox": p["bbox"],
            "datetime": f"{p['start_date']}T00:00:00Z/{p['end_date']}T23:59:59Z",
            "limit": min(p["limit"], 100),
        },
    )
    if not isinstance(data.get("features"), list):
        raise SourceAccessError("Landsat STAC schema changed.")
    scenes = [
        {
            "scene_id": f["id"],
            "observed_at": f.get("properties", {}).get("datetime"),
            "cloud_cover_percent": f.get("properties", {}).get("eo:cloud_cover"),
            "preview_url": f.get("assets", {}).get("thumbnail", {}).get("href"),
            "footprint": f.get("geometry"),
        }
        for f in data["features"]
    ]
    return payload(snapshot={"scenes": scenes}, as_of=max((str(s["observed_at"]) for s in scenes), default=None))


def osm(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    west, south, east, north = p["bbox"]
    tag = {"shops": "shop", "buildings": "building", "roads": "highway"}[p["feature"]]
    query = f"[out:json][timeout:25];nwr[{tag}]({south},{west},{north},{east});out tags center {p['limit']};"
    data = client.json("https://overpass.private.coffee/api/interpreter", method="POST", data={"data": query})
    if data.get("remark") or not isinstance(data.get("elements"), list):
        raise SourceAccessError("Overpass returned an incomplete query; retry a smaller area.")
    rows = [
        {
            "id": r["id"],
            "type": r["type"],
            "latitude": r.get("lat", r.get("center", {}).get("lat")),
            "longitude": r.get("lon", r.get("center", {}).get("lon")),
            "tags": r.get("tags", {}),
        }
        for r in data["elements"][: p["limit"]]
    ]
    return payload(
        snapshot={"features": rows, "limit": p["limit"], "possibly_truncated": len(rows) >= p["limit"]},
        as_of=data.get("osm3s", {}).get("timestamp_osm_base"),
        warnings=["Community mapping is incomplete; a mapped name does not establish company ownership."],
    )


def firms(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    bbox = ",".join(str(v) for v in p["bbox"])
    start, end = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
    # A bounded recent or historical interval; large histories require a separate archive workflow.
    if (end - start).days > 30:
        raise ValueError("FIRMS requests are limited to 30 days. Select a shorter interval.")
    rows = []
    while start <= end:
        days = min(10, (end - start).days + 1)
        url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{quote(os.environ['FIRMS_MAP_KEY'], safe='')}/"
            f"VIIRS_NOAA20_NRT/{bbox}/{days}/{start.isoformat()}"
        )
        reader = csv.DictReader(io.StringIO(client.text(url)))
        if not reader.fieldnames or "acq_date" not in reader.fieldnames:
            raise SourceAccessError("FIRMS schema changed or the selected dates are unavailable.")
        for row in reader:
            rows.append(
                observation(
                    row["acq_date"],
                    "fire_radiative_power",
                    row.get("frp"),
                    "MW",
                    latitude=number(row.get("latitude")),
                    longitude=number(row.get("longitude")),
                    confidence=row.get("confidence"),
                )
            )
        start += timedelta(days=days)
    return payload(_rows_in_range(rows, p))


def marinecadastre(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    url = "https://hub.marinecadastre.gov/pages/vesseltraffic"
    soup = BeautifulSoup(client.text(url), "html.parser")
    archives = [
        {"title": a.get_text(" ", strip=True), "url": urljoin(url, str(a["href"]))}
        for a in soup.select("a[href]")
        if re.search(r"AIS|\b20\d{2}\b|\.zip", a.get_text() + str(a["href"]), re.I)
    ]
    return payload(
        snapshot={"access": "bulk_only", "archives": archives[: p["limit"]], "official_archive_url": url},
        warnings=["Archive discovery only. No vessel-count or congestion observation was computed."],
    )


def census(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    flow, metric = ("imports", "GEN_VAL_MO") if p["flow"] == "imports" else ("exports", "ALL_VAL_MO")
    product_key = "I_COMMODITY" if flow == "imports" else "E_COMMODITY"
    data = client.json(
        f"https://api.census.gov/data/timeseries/intltrade/{flow}/hs",
        params={
            "get": f"CTY_CODE,{product_key},{metric}",
            "time": f"from {p['start_date'][:7]} to {p['end_date'][:7]}",
            "CTY_CODE": p["reporter"],
            product_key: p["product"],
            "key": os.environ["CENSUS_API_KEY"],
        },
    )
    if not isinstance(data, list) or not data:
        raise SourceAccessError("Census schema changed or the query has no data.")
    rows = [dict(zip(data[0], row, strict=True)) for row in data[1:]]
    return payload(
        [
            observation(r["time"] + "-01", flow, r[metric], "USD", country=r["CTY_CODE"], product=r[product_key])
            for r in rows
        ][: p["limit"]]
    )


def comtrade(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    start = date.fromisoformat(p["start_date"]).replace(day=1)
    periods = []
    while start.isoformat() <= p["end_date"]:
        periods.append(start.strftime("%Y%m"))
        start = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = []
    for period in periods:
        data = client.json(
            "https://comtradeapi.un.org/public/v1/preview/C/M/HS",
            params={
                "period": period,
                "reporterCode": p["reporter"],
                "partnerCode": p["partner"],
                "cmdCode": p["product"],
                "flowCode": "M" if p["flow"] == "imports" else "X",
                "maxRecords": min(p["limit"], 500),
            },
        )
        if data.get("error") or not isinstance(data.get("data"), list):
            raise SourceAccessError("Comtrade preview is unavailable or its schema changed.")
        rows.extend(
            [
                observation(
                    f"{str(r['period'])[:4]}-{str(r['period'])[4:6]}-01",
                    p["flow"],
                    r.get("primaryValue"),
                    "USD",
                    reporter=r.get("reporterDesc"),
                    partner=r.get("partnerDesc"),
                    product=r.get("cmdDesc"),
                )
                for r in data["data"]
            ]
        )
        if len(rows) >= p["limit"]:
            break
    return payload(
        rows[: p["limit"]],
        warnings=["Bounded public preview; completeness is not guaranteed. Missing trade values are not zero."],
    )


def comext(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    data = client.json(
        "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409",
        params={
            "lang": "EN",
            "freq": "M",
            "reporter": p["reporter"],
            "partner": p["partner"],
            "product": p["product"],
            "flow": "1" if p["flow"] == "imports" else "2",
            "indicators": "VALUE_IN_EUROS",
            "sinceTimePeriod": p["start_date"][:7],
            "untilTimePeriod": p["end_date"][:7],
        },
    )
    if data.get("error") or "dimension" not in data:
        raise SourceAccessError("Comext query is unavailable or its dimensions changed.")
    time_dim = data["dimension"].get("time", {}).get("category", {}).get("index", {})
    time_index = {int(v): k for k, v in time_dim.items()} if isinstance(time_dim, dict) else dict(enumerate(time_dim))
    ids, sizes = data.get("id", []), data.get("size", [])
    if "time" not in ids:
        raise SourceAccessError("Comext response does not have a time dimension.")
    stride = math.prod(sizes[ids.index("time") + 1 :])
    values = data.get("value", {})
    items = values.items() if isinstance(values, dict) else enumerate(values)
    rows = [
        observation(
            time_index[(int(k) // stride) % len(time_index)] + "-01", p["flow"], value, "EUR", product=p["product"]
        )
        for k, value in items
        if value is not None and time_index
    ]
    return payload(rows[: p["limit"]])


def _dated_table_rows(html: str, metric: str, unit: str, default_year: int | None = None) -> list[dict[str, Any]]:
    rows = []
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.select("table"):
        context = table.find_previous(["h1", "h2", "h3", "h4"])
        year_match = re.search(r"\b(20\d{2})\b", context.get_text() if context else "")
        year = int(year_match[1]) if year_match else default_year
        header = (
            [cell.get_text(" ", strip=True).lower() for cell in table.select("tr")[0].select("th,td")]
            if table.select("tr")
            else []
        )
        total_column = next((i for i, label in enumerate(header) if label == "total teus"), None)
        for tr in table.select("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.select("th,td")]
            if not cells:
                continue
            month = None
            for fmt in ("%B", "%b"):
                try:
                    month = datetime.strptime(cells[0], fmt).month
                    break
                except ValueError:
                    pass
            if month and year and total_column is not None:
                # Monthly rows include the month cell; some headers omit its blank heading.
                index = total_column + (1 if len(header) == len(cells) - 1 else 0)
                value = cells[index] if index < len(cells) else None
                if number(value) is not None:
                    rows.append(observation(f"{year}-{month:02d}-01", metric, value, unit))
    return rows


def ports(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    rows = []
    citations = []
    for year in range(date.fromisoformat(p["start_date"]).year, date.fromisoformat(p["end_date"]).year + 1):
        url = (
            f"https://portoflosangeles.org/business/statistics/container-statistics/historical-teu-statistics-{year}"
            if p["port"] == "los_angeles"
            else "https://polb.com/business/port-statistics/"
        )
        rows.extend(_dated_table_rows(client.text(url), "container_throughput", "TEU", year))
        citations.append({"title": f"{p['port'].replace('_', ' ').title()} {year}", "url": url})
    if not rows:
        raise SourceAccessError(
            "No supported official monthly TEU table is available. Consult the source's export page."
        )
    return payload(_rows_in_range(rows, p), citations=citations)


def panama(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    from pdfminer.high_level import extract_text

    soup = BeautifulSoup(client.text(client.spec["url"]), "html.parser")
    links = [
        (a.get_text(" ", strip=True), urljoin(client.spec["url"], str(a["href"])))
        for a in soup.select("a[href]")
        if re.search(r"\.pdf(?:\?|$)", str(a["href"]), re.I)
        and re.search(r"transit|tr.nsito|commercial|comercial", a.get_text(), re.I)
    ]
    if not links:
        raise SourceAccessError("No supported official canal transit release is currently available.")
    title, url = links[0]
    raw = client.request(url)
    rows = []
    for text in extract_text(io.BytesIO(raw), maxpages=10).split("\f"):
        years = re.findall(r"\b20\d{2}\b", text[:1600])
        if not years:
            continue
        year = int(max(years))
        for match in re.finditer(
            r"(October|November|December|January|February|March|April|May|June|July|August|September)\s+([\d,]+)",
            text,
        ):
            month = datetime.strptime(match[1], "%B").month
            actual_year = year - 1 if month >= 10 else year
            rows.append(observation(f"{actual_year}-{month:02d}-01", "oceangoing_transits", match[2], "transits"))
    if not rows:
        raise SourceAccessError("Canal release layout is not supported; no numbers were inferred.")
    return payload(
        _rows_in_range(rows, p),
        citations=[{"title": title, "url": url}],
        warnings=["Published fiscal-year transit table; publication may lag current conditions."],
    )


def portwatch(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    # Dataset IDs are fixed configuration, never caller-controlled URLs.
    dataset = "Daily_Chokepoints_Data" if p["dataset"] == "chokepoints" else "Daily_Port_Activity_Data"
    data = client.json(
        f"https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/{dataset}/FeatureServer/0/query",
        params={
            "where": f"portid = '{p['port_id']}' AND date >= DATE '{p['start_date']}' AND date <= DATE '{p['end_date']}'",
            "outFields": "*",
            "returnGeometry": "false",
            "resultRecordCount": p["limit"],
            "f": "json",
        },
    )
    if data.get("error") or "features" not in data:
        raise SourceAccessError("PortWatch dataset is unavailable or its schema changed.")
    rows = []
    for feature in data["features"]:
        r = feature["attributes"]
        day = datetime.fromtimestamp(r["date"] / 1000, UTC).date().isoformat()
        for key in ("n_total", "portcalls", "imports", "exports"):
            if key in r:
                rows.append(
                    observation(day, key, r[key], "vessels" if key in ("n_total", "portcalls") else "estimated tonnes")
                )
    return payload(
        rows[: p["limit"]],
        warnings=["AIS-derived estimates; incomplete coverage and publication lag may affect comparisons."],
    )


def aishub(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    west, south, east, north = p["bbox"]
    data = client.json(
        "https://data.aishub.net/ws.php",
        params={
            "username": os.environ["AISHUB_USERNAME"],
            "format": 1,
            "output": "json",
            "compress": 0,
            "latmin": south,
            "latmax": north,
            "lonmin": west,
            "lonmax": east,
        },
    )
    if not isinstance(data, list) or len(data) < 2 or data[0].get("ERROR"):
        raise SourceAccessError("AISHub contributor access is unavailable.")
    vessels = data[1]
    timestamps = [
        datetime.fromtimestamp(float(r["TIME"]), UTC).isoformat() for r in vessels if str(r.get("TIME", "")).isdigit()
    ]
    return payload(
        snapshot={"vessel_count": len(vessels), "types": dict(Counter(str(r.get("TYPE")) for r in vessels))},
        as_of=max(timestamps, default=None),
        warnings=["Aggregate contributor coverage only; raw AIS positions are not redistributed."],
    )


def opensky(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    token = client.json(
        "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token",
        method="POST",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["OPENSKY_CLIENT_ID"],
            "client_secret": os.environ["OPENSKY_CLIENT_SECRET"],
        },
    )
    west, south, east, north = p["bbox"]
    data = client.json(
        "https://opensky-network.org/api/states/all",
        params={"lamin": south, "lamax": north, "lomin": west, "lomax": east},
        headers={"Authorization": f"Bearer {token['access_token']}"},
    )
    return payload(
        snapshot={"aircraft_count": len(data.get("states") or [])},
        as_of=datetime.fromtimestamp(data["time"], UTC).isoformat(),
        warnings=["ADS-B coverage is incomplete; aircraft counts do not measure cargo tonnage."],
    )


# Fixed evalscript: callers cannot execute code or choose arbitrary bands.
SENTINEL_EVALSCRIPT = """//VERSION=3
function setup() { return {input:[{bands:['B03','B04','B08','B11','SCL','dataMask']}],
  output:[{id:'indices',bands:3,sampleType:'FLOAT32'},{id:'dataMask',bands:1}]}; }
function evaluatePixel(s) {
  let valid = s.dataMask === 1 && [4,5,6].includes(s.SCL);
  function index(a,b) { if (Math.abs(a+b)<1e-6) {valid=false; return 0;} return (a-b)/(a+b); }
  let values=[index(s.B08,s.B04),index(s.B03,s.B08),index(s.B11,s.B08)];
  return {indices:values,dataMask:[valid?1:0]};
}
"""


def spectral_indices(green: float, red: float, nir: float, swir: float) -> dict[str, float | None]:
    def index(a: float, b: float) -> float | None:
        return (a - b) / (a + b) if math.isfinite(a + b) and abs(a + b) >= 1e-6 else None

    return {"NDVI": index(nir, red), "NDWI": index(green, nir), "NDBI": index(swir, nir)}


def normalize_sentinel_statistics(data: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data.get("data"), list):
        raise SourceAccessError("Sentinel statistics schema changed.")
    rows = []
    warnings = []
    for interval in data["data"]:
        if interval.get("error"):
            warnings.append("A satellite interval could not be processed.")
            continue
        bands = interval.get("outputs", {}).get("indices", {}).get("bands", {})
        for band, metric in zip(("B0", "B1", "B2"), ("NDVI", "NDWI", "NDBI"), strict=True):
            stats = bands.get(band, {}).get("stats", {})
            count = int(stats.get("sampleCount", 0))
            valid = max(0, count - int(stats.get("noDataCount", count)))
            coverage = valid / count if count else 0
            value = number(stats.get("mean")) if coverage >= 0.30 else None
            rows.append(
                observation(
                    interval["interval"]["from"],
                    metric,
                    value,
                    "index",
                    valid_coverage=round(coverage, 4),
                    sample_count=count,
                    valid_sample_count=valid,
                    resolution_m=20,
                    calculation_version="sentinel_spectral_v1",
                )
            )
    end = date.fromisoformat(p["end_date"])
    comparisons = {}
    for metric in ("NDVI", "NDWI", "NDBI"):
        recent, prior = [], []
        for row in rows:
            age = (end - date.fromisoformat(row["date"])).days
            if row["metric"] == metric and row["value"] is not None:
                if 0 <= age < 30:
                    recent.append(row["value"])
                elif 30 <= age < 60:
                    prior.append(row["value"])
        latest = sum(recent) / len(recent) if recent else None
        previous = sum(prior) / len(prior) if prior else None
        comparisons[metric] = {
            "latest_30d_mean": latest,
            "previous_30d_mean": previous,
            "change": latest - previous if latest is not None and previous is not None else None,
        }
    if any(row["value"] is None for row in rows):
        warnings.append("Intervals below 30% clear valid coverage are suppressed, not treated as zero.")
    return payload(
        rows,
        snapshot={"comparisons": comparisons, "site_id": p.get("site_id")},
        warnings=warnings
        + [
            "Spectral indices are physical-condition proxies; they do not establish construction completion, parking occupancy, output, or revenue."
        ],
    )


def sentinel_indices(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    from pyproj import Transformer

    west, south, east, north = p["bbox"]
    zone = min(60, max(1, int(((west + east) / 2 + 180) / 6) + 1))
    epsg = (32600 if (south + north) / 2 >= 0 else 32700) + zone
    projection = Transformer.from_crs(4326, epsg, always_xy=True)
    corners = [projection.transform(lon, lat) for lon in (west, east) for lat in (south, north)]
    projected_bbox = [
        min(c[0] for c in corners),
        min(c[1] for c in corners),
        max(c[0] for c in corners),
        max(c[1] for c in corners),
    ]
    token = client.json(
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        method="POST",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["COPERNICUS_CLIENT_ID"],
            "client_secret": os.environ["COPERNICUS_CLIENT_SECRET"],
        },
    )
    data = client.json(
        "https://sh.dataspace.copernicus.eu/api/v1/statistics",
        method="POST",
        headers={"Authorization": f"Bearer {token['access_token']}"},
        json={
            "input": {
                "bounds": {
                    "bbox": projected_bbox,
                    "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"},
                },
                "data": [{"type": "sentinel-2-l2a"}],
            },
            "aggregation": {
                "timeRange": {"from": p["start_date"] + "T00:00:00Z", "to": p["end_date"] + "T23:59:59Z"},
                "aggregationInterval": {"of": "P1D"},
                "resx": 20,
                "resy": 20,
                "evalscript": SENTINEL_EVALSCRIPT,
            },
            "calculations": {"indices": {}},
        },
    )
    return normalize_sentinel_statistics(data, p)
