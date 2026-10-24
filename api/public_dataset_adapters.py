"""Bounded public datasets sharing the alternative-data result contract."""

from __future__ import annotations

import io
import os
import re
from datetime import date, datetime
from typing import Any, cast
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from api.alternative_data_adapters import SourceAccessError, SourceClient, number, observation, payload


def records(data: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise SourceAccessError("Provider schema changed: expected a record list.")
    rows = data[key]
    if any(not isinstance(row, dict) for row in rows):
        raise SourceAccessError("Provider schema changed: expected object records.")
    return cast(list[dict[str, Any]], rows)


def require(row: dict[str, Any], *keys: str) -> None:
    if any(key not in row for key in keys):
        raise SourceAccessError("Provider schema changed: required fields are missing.")


def exact(left: Any, right: str) -> bool:
    return isinstance(left, str) and left.strip().casefold() == right.strip().casefold()


def in_range(day: str, p: dict[str, Any]) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)) and p["start_date"] <= day <= p["end_date"]


def snapshot(rows: list[dict[str, Any]], p: dict[str, Any], *, warnings: list[str] | None = None) -> dict[str, Any]:
    rows = rows[: p["limit"]]
    return payload(
        snapshot={"records": rows} if rows else None,
        warnings=warnings,
        as_of=max((r["date"] for r in rows if r.get("date")), default=None),
        citations=[{"title": "Source record", "url": r["url"]} for r in rows if r.get("url")][:20],
    )


def recent_filings(p: dict[str, Any], forms: set[str], cap: int) -> tuple[dict[str, Any], list[dict[str, str]]]:
    from portfolio.momentum.fundamental_momentum import edgar_fetcher as edgar

    data = edgar.fetch_submissions_by_cik(p["cik"])
    if data is None:
        raise SourceAccessError("SEC submissions unavailable; no company evidence was inferred.")
    recent = data.get("filings", {}).get("recent", {})
    keys = ("form", "accessionNumber", "primaryDocument", "filingDate")
    if any(not isinstance(recent.get(key), list) for key in keys):
        raise SourceAccessError("SEC submissions schema changed.")
    if len({len(recent[key]) for key in keys}) != 1:
        raise SourceAccessError("SEC submissions columns no longer align.")
    rows = [dict(zip(keys, values, strict=True)) for values in zip(*(recent[key] for key in keys), strict=True)]
    selected = [r for r in rows if r["form"] in forms and in_range(r["filingDate"], p)]
    return data, selected[:cap]


def sec_form4(_client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    from portfolio.momentum.fundamental_momentum import edgar_fetcher as edgar

    submissions, filings = recent_filings(p, {"4", "4/A"}, 10)
    rows: list[dict[str, Any]] = []
    warnings = ["Insider disclosures are not buy/sell signals; amendments can repeat previously reported transactions."]
    for filing in filings:
        raw = edgar.fetch_primary_document(
            p["cik"], filing["accessionNumber"], filing["primaryDocument"], max_bytes=1_000_000
        )
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise SourceAccessError("SEC XML contains unsupported declarations.")
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            raise SourceAccessError("SEC Form 4 schema changed: expected ownership XML.") from None
        if root.tag != "ownershipDocument":
            raise SourceAccessError("SEC Form 4 schema changed: expected ownershipDocument.")
        names = [n.text for n in root.findall("./reportingOwner/reportingOwnerId/rptOwnerName") if n.text]
        for element in [
            *root.findall("./nonDerivativeTable/nonDerivativeTransaction"),
            *root.findall("./derivativeTable/derivativeTransaction"),
        ]:
            day = element.findtext("./transactionDate/value")
            code = element.findtext("./transactionCoding/transactionCode")
            disposition = element.findtext("./transactionAmounts/transactionAcquiredDisposedCode/value")
            shares = element.findtext("./transactionAmounts/transactionShares/value")
            if not day or not names or shares is None or disposition not in {"A", "D"}:
                raise SourceAccessError("SEC Form 4 transaction schema changed.")
            if in_range(day, p):
                rows.append(
                    {
                        "date": day,
                        "insider": "; ".join(names),
                        "direction": "acquired" if disposition == "A" else "disposed",
                        "shares": number(shares),
                        "transaction_code": code,
                        "instrument": element.tag,
                        "url": edgar.build_filing_url(p["cik"], filing["accessionNumber"], submissions),
                    }
                )
    return snapshot(rows, p, warnings=warnings)


def sec_filings(_client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    from portfolio.momentum.fundamental_momentum import edgar_fetcher as edgar

    submissions, filings = recent_filings(p, {"10-K", "10-Q", "8-K"}, 3)
    rows = []
    for filing in filings:
        raw = edgar.fetch_primary_document(p["cik"], filing["accessionNumber"], filing["primaryDocument"])
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup.select("script, style, ix\\:hidden"):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        for match in list(re.finditer(re.escape(p["query"]), text, re.I))[:6]:
            rows.append(
                {
                    "date": filing["filingDate"],
                    "form": filing["form"],
                    "passage": text[max(0, match.start() - 220) : match.end() + 380],
                    "url": edgar.build_filing_url(p["cik"], filing["accessionNumber"], submissions),
                }
            )
    return snapshot(
        rows,
        p,
        warnings=[
            "Literal query passages from at most three recent filings; absence of a match is not evidence of absence."
        ],
    )


def usaspending(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    result = []
    # Contracts and assistance have distinct allowed field sets and award types.
    for types, extra in [(["A", "B", "C", "D"], ["Contract Award Type"]), (["02", "03", "04", "05"], ["Award Type"])]:
        data = client.json(
            "https://api.usaspending.gov/api/v2/search/spending_by_award/",
            method="POST",
            json={
                "filters": {
                    "recipient_search_text": [p["recipient"]],
                    "award_type_codes": types,
                    "time_period": [{"start_date": p["start_date"], "end_date": p["end_date"]}],
                },
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Award Amount",
                    "Start Date",
                    "End Date",
                    "Description",
                    *extra,
                ],
                "sort": "Award Amount",
                "order": "desc",
                "page": 1,
                "limit": min(p["limit"], 100),
            },
        )
        for row in records(data, "results"):
            require(row, "Recipient Name", "Award ID", "Award Amount", "Start Date", "generated_internal_id")
            if exact(row["Recipient Name"], p["recipient"]):
                result.append(
                    {
                        "date": None,
                        "award_start_date": row["Start Date"],
                        "recipient": row["Recipient Name"],
                        "award_id": row["Award ID"],
                        "obligated_amount": number(row["Award Amount"]),
                        "unit": "USD",
                        "description": str(row.get("Description") or "")[:600],
                        "url": "https://www.usaspending.gov/award/" + quote(str(row["generated_internal_id"]), safe=""),
                    }
                )
    return snapshot(
        result,
        p,
        warnings=[
            "One bounded page per award category; award amounts are obligations, not revenue. The activity window can include old awards. Award start dates are not freshness dates; this endpoint supplies no observation vintage."
        ],
    )


def federal_register(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "per_page": min(p["limit"], 20),
        "order": "newest",
        "conditions[publication_date][gte]": p["start_date"],
        "conditions[publication_date][lte]": p["end_date"],
    }
    if p.get("company"):
        params["conditions[term]"] = '"' + p["company"].replace('"', "") + '"'
    elif p.get("agency"):
        params["conditions[agencies][]"] = p["agency"]
    else:
        raise ValueError("Supply an exact agency or reviewed company mapping.")
    data = client.json("https://www.federalregister.gov/api/v1/documents.json", params=params)
    result = []
    for row in records(data, "results"):
        require(row, "publication_date", "title", "html_url", "document_number")
        if p.get("company"):
            # Do not promote a full-text search hit to a company link without the actual named text.
            if not row.get("body_html_url"):
                detail = client.json(
                    "https://www.federalregister.gov/api/v1/documents/"
                    + quote(row["document_number"], safe="")
                    + ".json"
                )
                require(detail, "body_html_url")
                row["body_html_url"] = detail["body_html_url"]
            body = BeautifulSoup(client.text(row["body_html_url"], max_bytes=2_000_000), "html.parser").get_text(
                " ", strip=True
            )
            match = re.search(r"(?<!\w)" + re.escape(p["company"]) + r"(?!\w)", body, re.I)
            if not match:
                continue
            passage = body[max(0, match.start() - 160) : match.end() + 300]
        else:
            passage = str(row.get("abstract") or "")[:600]
        result.append(
            {
                "date": row["publication_date"],
                "title": row["title"],
                "passage": passage,
                "document_number": row["document_number"],
                "url": row["html_url"],
                "relevance": "named_in_document" if p.get("company") else "agency_context",
            }
        )
    return snapshot(
        result, p, warnings=["A name occurrence establishes a mention, not that the company is the document's subject."]
    )


def uspto(_client: SourceClient, _p: dict[str, Any]) -> dict[str, Any]:
    raise SourceAccessError(
        "PatentsView search APIs paused during the USPTO ODP migration; no verified bounded exact-assignee replacement is available."
    )


def clinical_trials(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    data = client.json(
        "https://clinicaltrials.gov/api/v2/studies",
        params={
            "format": "json",
            "query.spons": '"' + p["sponsor"].replace('"', "") + '"',
            "pageSize": min(p["limit"], 100),
            "sort": "LastUpdatePostDate:desc",
            "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{p['start_date']}, {p['end_date']}]",
        },
    )
    rows = []
    for study in records(data, "studies"):
        require(study, "protocolSection")
        section = study["protocolSection"]
        require(section, "identificationModule", "sponsorCollaboratorsModule", "statusModule")
        identity, sponsors, status = (
            section["identificationModule"],
            section["sponsorCollaboratorsModule"],
            section["statusModule"],
        )
        require(identity, "nctId", "briefTitle")
        require(sponsors, "leadSponsor")
        require(sponsors["leadSponsor"], "name")
        require(status, "overallStatus", "lastUpdatePostDateStruct")
        if exact(sponsors["leadSponsor"]["name"], p["sponsor"]):
            rows.append(
                {
                    "date": status["lastUpdatePostDateStruct"].get("date"),
                    "nct_id": identity["nctId"],
                    "title": identity["briefTitle"],
                    "sponsor": sponsors["leadSponsor"]["name"],
                    "status": status["overallStatus"],
                    "url": "https://clinicaltrials.gov/study/" + quote(identity["nctId"], safe=""),
                }
            )
    return snapshot(
        rows,
        p,
        warnings=[
            "Exact lead sponsor only; trial registration/status does not establish efficacy or regulatory approval. Results are capped at one page."
        ],
    )


def fda_query(client: SourceClient, endpoint: str, search: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    # openFDA signals an empty search with HTTP 404, so handle only that documented status.
    try:
        data = client.json(
            f"https://api.fda.gov/drug/{endpoint}.json", params={"search": search, "limit": min(p["limit"], 100)}
        )
    except SourceAccessError as exc:
        if "HTTP 404" in str(exc):
            return []
        raise
    return records(data, "results")


def fda_phrase(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def openfda_events(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    field = "patient.drug.medicinalproduct"
    query = f"{field}:{fda_phrase(p['drug'])} AND receivedate:[{p['start_date'].replace('-', '')} TO {p['end_date'].replace('-', '')}]"
    result = []
    for row in fda_query(client, "event", query, p):
        require(row, "safetyreportid", "receivedate", "patient")
        drugs = records(row["patient"], "drug")
        if any(exact(drug.get("medicinalproduct"), p["drug"]) for drug in drugs):
            day = datetime.strptime(row["receivedate"], "%Y%m%d").date().isoformat()
            result.append(
                {
                    "date": day,
                    "report_id": row["safetyreportid"],
                    "drug": p["drug"],
                    "serious": row.get("serious"),
                    "url": "https://api.fda.gov/drug/event.json?search=safetyreportid:"
                    + quote(fda_phrase(row["safetyreportid"]), safe=""),
                }
            )
    return snapshot(
        result,
        p,
        warnings=[
            "Adverse event reports do not establish causation or incidence; duplicates and reporting bias are possible. One bounded page, not a total count."
        ],
    )


def openfda_approvals(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    query = "sponsor_name:" + fda_phrase(p["applicant"])
    result = []
    for row in fda_query(client, "drugsfda", query, p):
        require(row, "sponsor_name", "application_number", "submissions")
        if not exact(row["sponsor_name"], p["applicant"]):
            continue
        for submission in records(row, "submissions"):
            require(submission, "submission_status")
            raw_day = submission.get("submission_status_date")
            if submission["submission_status"] == "AP" and raw_day:
                day = datetime.strptime(raw_day, "%Y%m%d").date().isoformat()
                if in_range(day, p):
                    result.append(
                        {
                            "date": day,
                            "applicant": row["sponsor_name"],
                            "application": row["application_number"],
                            "submission_type": submission.get("submission_type"),
                            "submission_number": submission.get("submission_number"),
                            "url": "https://api.fda.gov/drug/drugsfda.json?search=application_number:"
                            + quote(fda_phrase(row["application_number"]), safe=""),
                        }
                    )
    return snapshot(result, p)


def wikimedia(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        + p["project"]
        + "/all-access/user/"
        + quote(p["article"].replace(" ", "_"), safe="")
        + "/daily/"
        + p["start_date"].replace("-", "")
        + "/"
        + p["end_date"].replace("-", "")
    )
    try:
        data = client.json(url)
    except SourceAccessError as exc:
        if "HTTP 404" in str(exc):
            return payload([])
        raise
    result = []
    for row in records(data, "items"):
        require(row, "timestamp", "views", "article")
        if not exact(row["article"].replace("_", " "), p["article"].replace("_", " ")):
            raise SourceAccessError("Wikimedia returned a different article title.")
        day = datetime.strptime(row["timestamp"][:8], "%Y%m%d").date().isoformat()
        result.append(
            observation(day, "human_pageviews", row["views"], "views", article=row["article"], project=p["project"])
        )
    return payload(
        result,
        warnings=["Article attention is a proxy; it does not measure demand, customers, or revenue."],
        citations=[{"title": "Exact article pageviews", "url": url}],
    )


EIA_SERIES = {
    "petroleum_stocks": "PET.WCESTUS1.W",
    "natural_gas_storage": "NG.NW2_EPG0_SWO_R48_BCF.W",
    "electricity_sales": "ELEC.SALES.ALL-US-99.M",
}


def eia(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    data = client.json(
        "https://api.eia.gov/v2/seriesid/" + EIA_SERIES[p["series"]],
        params={
            "api_key": os.environ["EIA_API_KEY"],
            "start": p["start_date"],
            "end": p["end_date"],
            "length": min(p["limit"], 500),
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        },
    )
    if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
        raise SourceAccessError("EIA response schema changed.")
    rows = []
    for row in records(data["response"], "data"):
        require(row, "period", "value", "units")
        period = row["period"]
        day = period + "-01" if len(period) == 7 else period
        if in_range(day, p):
            rows.append(
                observation(
                    day, p["series"], row["value"], row["units"], period=period, series_id=EIA_SERIES[p["series"]]
                )
            )
    return payload(
        sorted(rows, key=lambda r: r["date"]),
        warnings=["National sector proxy; no company facility or revenue relationship is established."],
    )


def noaa_cdo(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    data = client.json(
        "https://www.ncei.noaa.gov/cdo-web/api/v2/data",
        headers={"token": os.environ["NOAA_CDO_TOKEN"]},
        params={
            "datasetid": "GHCND",
            "stationid": p["station"],
            "datatypeid": p["metric"],
            "startdate": p["start_date"],
            "enddate": p["end_date"],
            "units": "metric",
            "limit": min(p["limit"], 1000),
        },
    )
    if data == {}:  # Documented empty CDO response.
        return payload([])
    result = []
    for row in records(data, "results"):
        require(row, "date", "datatype", "station", "value")
        if row["station"] != p["station"] or row["datatype"] != p["metric"]:
            raise SourceAccessError("NOAA returned a different station or measurement.")
        if in_range(row["date"][:10], p):
            result.append(
                observation(
                    row["date"],
                    p["metric"],
                    row["value"],
                    "mm" if p["metric"] == "PRCP" else "degrees C",
                    station=p["station"],
                )
            )
    return payload(
        result,
        warnings=[
            "Station weather is a geographic proxy; it does not establish conditions at a company site, store traffic, or revenue."
        ],
    )


def normalize_wasde(raw: bytes, commodity: str, released: str, month: str) -> dict[str, Any]:
    import pandas as pd

    workbook = pd.ExcelFile(io.BytesIO(raw))
    rows = []
    crop = "Soybean" if commodity == "Soybeans" else commodity
    matched_table = False
    for sheet in workbook.sheet_names[:40]:
        frame = pd.read_excel(workbook, sheet_name=sheet, header=None, nrows=250).fillna("")
        table = frame.values.tolist()
        if not any(f"World {crop} Supply and Use" in str(value) for line in table[:8] for value in line):
            continue
        unit = next(
            (str(value).strip("() ") for line in table[:8] for value in line if str(value).startswith("(Million")), None
        )
        if not unit:
            raise SourceAccessError("USDA workbook schema changed: units missing.")
        header: dict[str, Any] | None = None
        geography = ""
        for line in table:
            labels = [re.sub(r"\s+", " ", str(value)).strip() for value in line]
            if "Production" in labels and "Ending Stocks" in labels:
                header = {
                    "year": labels[0],
                    "production": labels.index("Production"),
                    "ending_stocks": labels.index("Ending Stocks"),
                }
                geography = ""
                continue
            if not header or "Proj." not in header["year"]:
                continue
            matched_table = True
            if labels[0]:
                geography = re.sub(r"\s+\d+/.*$", "", labels[0]).strip()
            if geography not in {"World", "United States"} or labels[1] != month:
                continue
            for metric in ("production", "ending_stocks"):
                rows.append(
                    observation(
                        released,
                        metric,
                        line[header[metric]],
                        unit,
                        commodity=commodity,
                        geography=geography,
                        marketing_year=header["year"],
                        publisher="USDA WASDE",
                    )
                )
    if not matched_table:
        raise SourceAccessError("USDA workbook schema changed: projected world supply/use table missing.")
    return payload(rows, warnings=["USDA marketing-year projections are commodity context, not company revenue."])


def wasde(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    soup = BeautifulSoup(client.text(client.spec["url"]), "html.parser")
    link = soup.find("a", href=re.compile(r"/wasde\d{4}\.xls$"))
    if not isinstance(link, Tag):
        raise SourceAccessError("USDA current Excel link changed.")
    href = str(link["href"])
    stamp = re.search(r"wasde(\d{2})(\d{2})\.xls$", href)
    assert stamp is not None
    month_no, year = int(stamp[1]), 2000 + int(stamp[2])
    full_month = date(year, month_no, 1).strftime("%B")
    release = re.search(
        re.escape(full_month)
        + r" "
        + str(year)
        + r" WASDE Report.*?Release time:.*?,\s*"
        + full_month
        + r"\s+(\d{1,2})",
        soup.get_text(" ", strip=True),
        re.I,
    )
    if not release:
        raise SourceAccessError("USDA release date was not published in the expected format.")
    released = date(year, month_no, int(release[1])).isoformat()
    if not in_range(released, p):
        return payload(
            [],
            warnings=["The current report is outside the requested date range; no historical corpus was downloaded."],
        )
    url = urljoin(client.spec["url"], href)
    result = normalize_wasde(client.request(url, max_bytes=2_000_000), p["commodity"], released, full_month[:3])
    result["citations"] = [{"title": "USDA monthly WASDE workbook", "url": url}]
    return result


def normalize_rig_count(raw: bytes, p: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    workbook = pd.ExcelFile(io.BytesIO(raw))
    sheet = next((name for name in workbook.sheet_names if name.casefold() == "nam weekly"), None)
    if sheet is None:
        raise SourceAccessError("Baker Hughes workbook schema changed: NAM Weekly sheet missing.")
    frame = pd.read_excel(workbook, sheet_name=sheet, header=None, nrows=100_000).fillna("")
    if len(frame) >= 100_000:
        raise SourceAccessError(
            "Baker Hughes workbook exceeds the bounded row limit; incomplete totals were suppressed."
        )
    table = frame.values.tolist()
    headers = next(
        (
            i
            for i, row in enumerate(table[:30])
            if "US_PublishDate" in row and "Rig Count Value" in row and "Country" in row
        ),
        None,
    )
    if headers is None:
        raise SourceAccessError("Baker Hughes weekly column schema changed.")
    fields = table[headers]
    totals: dict[tuple[str, str], float] = {}
    for values in table[headers + 1 :]:
        row = dict(zip(fields, values, strict=True))
        if any(str(value).strip().casefold() in {"total", "all", "grand total"} for value in values):
            raise SourceAccessError("Baker Hughes workbook contains aggregate rows; unverified totals were suppressed.")
        raw_day, country, count = row["US_PublishDate"], str(row["Country"]), number(row["Rig Count Value"])
        if not isinstance(raw_day, datetime) or count is None:
            continue
        day = raw_day.date().isoformat()
        if in_range(day, p):
            totals[day, country] = totals.get((day, country), 0) + count
    return payload(
        [
            observation(day, "active_rigs", count, "rigs", country=country)
            for (day, country), count in sorted(totals.items())
        ],
        warnings=["Baker Hughes active rigs are an energy-activity proxy, not company output or revenue."],
    )


def rig_count(client: SourceClient, p: dict[str, Any]) -> dict[str, Any]:
    soup = BeautifulSoup(client.text(client.spec["url"]), "html.parser")
    link = next(
        (
            a
            for a in soup.select("a[href]")
            if "North America Rig Count Report - New Report" in a.get_text(" ", strip=True)
        ),
        None,
    )
    if link is None:
        raise SourceAccessError("Baker Hughes current weekly download link changed.")
    url = urljoin(client.spec["url"], str(link["href"]))
    result = normalize_rig_count(client.request(url, max_bytes=12_000_000), p)
    result["citations"] = [{"title": "Baker Hughes weekly workbook", "url": url}]
    return result


ADAPTERS = {
    "sec_form4": sec_form4,
    "sec_filings": sec_filings,
    "usaspending": usaspending,
    "federal_register": federal_register,
    "uspto": uspto,
    "clinical_trials": clinical_trials,
    "openfda_events": openfda_events,
    "openfda_approvals": openfda_approvals,
    "wikimedia": wikimedia,
    "eia": eia,
    "noaa_cdo": noaa_cdo,
    "wasde": wasde,
    "rig_count": rig_count,
}
