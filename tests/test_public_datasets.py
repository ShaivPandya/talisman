from __future__ import annotations

import copy
import io
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from api import alternative_data as service
from api import public_dataset_adapters as adapters
from api.alternative_data_adapters import SourceAccessError
from ontology.policy import admin_actor, agent_actor

TODAY = datetime.now(UTC).date().isoformat()
MAPPING = "alt-mapping-" + "a" * 32


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setenv("TALISMAN_ALLOW_SQLITE_STATE", "true")
    monkeypatch.setattr(service.snapshot_store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite")
    monkeypatch.setattr(service.provenance, "start_event", lambda **kwargs: None)
    monkeypatch.setattr(service.provenance, "finish_event", lambda *args, **kwargs: None)
    for key in ("NOAA_CDO_TOKEN", "EIA_API_KEY"):
        monkeypatch.delenv(key, raising=False)


class FixtureClient:
    def __init__(self, data=None, text="", raw=b""):
        self.data, self.body, self.raw = data, text, raw
        self.spec = {"url": "https://www.usda.gov/oce/commodity/wasde"}
        self.calls = []

    def json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return copy.deepcopy(self.data)

    def text(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.body

    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.raw


def params(**extra):
    return {"start_date": TODAY, "end_date": TODAY, "limit": 10, **extra}


@pytest.mark.parametrize("key", adapters.ADAPTERS)
def test_every_public_adapter_is_registered_and_cited(key):
    spec = service.get_spec("alternative_" + key)
    assert spec["adapter"] == "public:" + key
    assert spec["license_url"].startswith("https://") and spec["freshness_days"] > 0
    assert spec["access_checked_at"] == "2026-10-24"


@pytest.mark.parametrize(
    "key", [key for key in adapters.ADAPTERS if service.get_spec("alternative_" + key).get("reviewed_field")]
)
def test_ticker_or_model_name_cannot_establish_a_reviewed_relationship(key):
    spec = service.get_spec("alternative_" + key)
    field = spec["reviewed_field"]
    for raw in ({}, {field: "A model proposed this name"}, {field: "Example", "mapping_id": MAPPING}):
        with pytest.raises(ValueError, match="human-reviewed"):
            service.normalize_parameters(
                service.FetchRequest(source_id=spec["source_id"], ticker="EXAMPLE", parameters=raw)
            )


def test_mapping_is_scoped_to_source_company_and_exact_spelling(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_mapping",
        lambda _: {"source_id": "alternative_clinical_trials", "ticker": "ABC", "value": "Reviewed Sponsor"},
    )
    req = service.FetchRequest(
        source_id="alternative_clinical_trials", ticker="ABC", parameters={"mapping_id": MAPPING}
    )
    assert service.normalize_parameters(req)["sponsor"] == "Reviewed Sponsor"
    for change in (
        {"ticker": "OTHER"},
        {"source_id": "alternative_usaspending"},
        {"parameters": {"mapping_id": MAPPING, "sponsor": "Other"}},
    ):
        with pytest.raises(ValueError):
            service.normalize_parameters(req.model_copy(update=change))
    monkeypatch.setattr(service, "get_mapping", lambda _: None)
    with pytest.raises(ValueError):
        service.normalize_parameters(req)


def test_agents_cannot_confirm_or_remove_name_mappings():
    with pytest.raises(ValueError, match="Only a person"):
        service.confirm_mapping(
            service.MappingRequest(
                ticker="ABC",
                source_id="alternative_wikimedia",
                value="Example",
                citations=[{"url": "https://example.com"}],
            ),
            agent_actor(),
        )
    with pytest.raises(ValueError, match="Only a person"):
        service.remove_mapping(MAPPING, agent_actor())


def test_person_confirmations_use_the_ontology_write_boundary(monkeypatch):
    writes = []
    monkeypatch.setattr(service, "use_postgres_state", lambda: True)
    monkeypatch.setattr(service, "list_mappings", lambda _: [])
    monkeypatch.setattr(service.provenance, "start_event", lambda **kwargs: {"event_id": "review-event"})

    monkeypatch.setattr(
        service, "OntologyObjectService", lambda: SimpleNamespace(write_object=lambda *a, **kw: writes.append((a, kw)))
    )
    result = service.confirm_mapping(
        service.MappingRequest(
            ticker="ABC",
            source_id="alternative_wikimedia",
            value="Example Inc.",
            citations=[{"url": "https://example.com/report"}],
        ),
        admin_actor(),
    )
    assert result["confirmed_by"] == admin_actor().actor_id
    assert writes[0][0][0] == "SourceManifest" and writes[0][0][2]["dataset"] == "alternative_data_mappings"
    assert writes[0][1]["provenance"] == "review-event"


def test_award_start_date_is_not_reported_as_a_fresh_observation():
    row = {
        "Recipient Name": "Example Inc",
        "Award ID": "award",
        "Award Amount": "10",
        "Start Date": "2018-01-01",
        "generated_internal_id": "id",
    }
    result = adapters.usaspending(FixtureClient({"results": [row]}), params(recipient="Example Inc"))
    assert result["as_of"] is None and result["snapshot"]["records"][0]["award_start_date"] == "2018-01-01"


@pytest.mark.parametrize(
    "source,key,parameters",
    [
        ("alternative_eia", "EIA_API_KEY", {}),
        ("alternative_noaa_cdo", "NOAA_CDO_TOKEN", {"station": "GHCND:USW00094728"}),
    ],
)
def test_missing_credentials_do_not_call_provider(monkeypatch, source, key, parameters):
    monkeypatch.setattr(adapters, "eia", lambda *_: pytest.fail("provider called"))
    result = service.query_source(service.FetchRequest(source_id=source, parameters=parameters))
    assert result["status"] == "setup_required" and result["availability"]["missing_credentials"] == [key]
    assert result["observations"] == [] and result["as_of"] is None


def test_paused_patent_source_is_not_falsely_advertised_as_ready():
    spec = service.get_spec("alternative_uspto")
    assert service.availability(spec)["status"] == "unavailable"
    assert not spec["storage_allowed"]
    with pytest.raises(SourceAccessError, match="paused"):
        adapters.uspto(FixtureClient(), params())


@pytest.mark.parametrize(
    "name,empty,p",
    [
        ("usaspending", {"results": []}, {"recipient": "Example Inc"}),
        ("federal_register", {"results": []}, {"agency": "energy-department"}),
        ("clinical_trials", {"studies": []}, {"sponsor": "Example"}),
        ("openfda_events", {"results": []}, {"drug": "Example"}),
        ("openfda_approvals", {"results": []}, {"applicant": "Example"}),
        ("wikimedia", {"items": []}, {"article": "Example", "project": "en.wikipedia.org"}),
        ("eia", {"response": {"data": []}}, {"series": "petroleum_stocks"}),
        ("noaa_cdo", {}, {"station": "GHCND:USW00094728", "metric": "TMAX"}),
    ],
)
def test_empty_and_schema_changed_provider_fixtures(monkeypatch, name, empty, p):
    monkeypatch.setenv("EIA_API_KEY", "test-key")
    monkeypatch.setenv("NOAA_CDO_TOKEN", "test-token")
    result = adapters.ADAPTERS[name](FixtureClient(empty), params(**p))
    assert result["as_of"] is None and not result["observations"] and result["snapshot"] is None
    with pytest.raises((SourceAccessError, KeyError, ValueError)):
        adapters.ADAPTERS[name](FixtureClient({"changed": []}), params(**p))


def test_exact_clinical_sponsor_filter_and_dated_citation():
    def study(sponsor):
        return {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT12345678", "briefTitle": "A trial"},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
                "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": TODAY}},
            }
        }

    result = adapters.clinical_trials(
        FixtureClient({"studies": [study("Example"), study("Example Subsidiary")]}), params(sponsor="Example")
    )
    assert len(result["snapshot"]["records"]) == 1
    assert result["as_of"] == TODAY and result["citations"][0]["url"].endswith("NCT12345678")


def test_federal_register_requires_name_in_document_not_just_search_hit():
    record = {
        "publication_date": TODAY,
        "title": "A notice",
        "html_url": "https://www.federalregister.gov/documents/2026/notice",
        "body_html_url": "https://www.federalregister.gov/documents/full_text/notice.html",
        "document_number": "2026-1",
    }
    assert (
        adapters.federal_register(
            FixtureClient({"results": [record]}, text="Unrelated company"), params(company="Example")
        )["snapshot"]
        is None
    )
    result = adapters.federal_register(
        FixtureClient({"results": [record]}, text="The Example company applied."), params(company="Example")
    )
    assert result["snapshot"]["records"][0]["relevance"] == "named_in_document"


def test_fda_exact_names_and_missing_values_are_not_zero():
    data = {
        "results": [
            {
                "safetyreportid": "42",
                "receivedate": TODAY.replace("-", ""),
                "patient": {"drug": [{"medicinalproduct": "Example"}]},
            }
        ]
    }
    result = adapters.openfda_events(FixtureClient(data), params(drug="Example"))
    assert result["as_of"] == TODAY and result["snapshot"]["records"][0]["serious"] is None
    assert adapters.openfda_events(FixtureClient(data), params(drug="Example Plus"))["snapshot"] is None
    client = FixtureClient({"results": []})
    adapters.openfda_events(client, params(drug='Example" OR *'))
    assert '" OR *' not in client.calls[0][1]["params"]["search"].split(" AND ")[0].replace('\\"', "")


def test_eia_units_and_noaa_station_identity(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", "test-key")
    monkeypatch.setenv("NOAA_CDO_TOKEN", "test-token")
    result = adapters.eia(
        FixtureClient({"response": {"data": [{"period": TODAY, "value": None, "units": "thousand barrels"}]}}),
        params(series="petroleum_stocks"),
    )
    assert result["observations"][0]["value"] is None and result["as_of"] is None
    with pytest.raises(SourceAccessError, match="different station"):
        adapters.noaa_cdo(
            FixtureClient({"results": [{"date": TODAY, "datatype": "TMAX", "station": "OTHER", "value": 20}]}),
            params(station="GHCND:USW00094728", metric="TMAX"),
        )


@pytest.fixture
def sec(monkeypatch):
    from portfolio.momentum.fundamental_momentum import edgar_fetcher

    recent = {
        "form": ["4"],
        "accessionNumber": ["0000000001-26-000001"],
        "primaryDocument": ["primary.xml"],
        "filingDate": [TODAY],
    }
    monkeypatch.setattr(edgar_fetcher, "fetch_submissions_by_cik", lambda _: {"filings": {"recent": recent}})
    return edgar_fetcher, recent


def test_sec_form4_is_a_transaction_disclosure_not_a_signal(sec, monkeypatch):
    edgar, recent = sec
    xml = f"""<ownershipDocument><reportingOwner><reportingOwnerId><rptOwnerName>Example Insider</rptOwnerName></reportingOwnerId></reportingOwner><nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>{TODAY}</value></transactionDate><transactionCoding><transactionCode>F</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>12</value></transactionShares><transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    monkeypatch.setattr(edgar, "fetch_primary_document", lambda *args, **kwargs: xml.encode())
    result = adapters.sec_form4(FixtureClient(), params(cik="0000000001"))
    assert result["snapshot"]["records"][0]["direction"] == "disposed"
    assert result["snapshot"]["records"][0]["transaction_code"] == "F"
    assert "not buy/sell" in result["warnings"][0]
    recent["form"] = []
    with pytest.raises(SourceAccessError, match="align"):
        adapters.sec_form4(FixtureClient(), params(cik="0000000001"))


@pytest.mark.parametrize("name", ["sec_form4", "sec_filings"])
def test_sec_empty_and_schema_change_fixtures(sec, monkeypatch, name):
    edgar, recent = sec
    for key in recent:
        recent[key] = []
    assert adapters.ADAPTERS[name](FixtureClient(), params(cik="0000000001", query="supply chain"))["snapshot"] is None
    monkeypatch.setattr(edgar, "fetch_submissions_by_cik", lambda _: {"renamed": []})
    with pytest.raises(SourceAccessError, match="schema changed"):
        adapters.ADAPTERS[name](FixtureClient(), params(cik="0000000001", query="supply chain"))


def test_filing_passages_are_bounded_and_cited(sec, monkeypatch):
    edgar, recent = sec
    recent["form"] = ["10-Q"]
    monkeypatch.setattr(
        edgar,
        "fetch_primary_document",
        lambda *args, **kwargs: b"<p>Our supply chain is changing.</p><script>ignored</script>",
    )
    result = adapters.sec_filings(FixtureClient(), params(cik="0000000001", query="supply chain"))
    assert result["snapshot"]["records"][0]["passage"] == "Our supply chain is changing."
    assert result["citations"][0]["url"].startswith("https://www.sec.gov/Archives/")


def workbook_bytes(sheets):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False, header=False)
    return buffer.getvalue()


def test_wasde_publisher_units_current_month_and_empty_schema_fixtures():
    raw = workbook_bytes(
        {
            "Page 23": [
                ["October 2026"],
                ["World Corn Supply and Use"],
                ["(Million Metric Tons)"],
                ["2026/27 Proj.", "", "Beginning Stocks", "Production", "Ending Stocks"],
                ["World  3/", "Sep", 1, 100, 20],
                ["", "Oct", 1, 110, None],
            ]
        }
    )
    result = adapters.normalize_wasde(raw, "Corn", "2026-10-09", "Oct")
    assert [row["value"] for row in result["observations"]] == [110, None]
    assert result["observations"][0]["dimensions"]["marketing_year"] == "2026/27 Proj."
    assert adapters.normalize_wasde(raw, "Corn", "2026-10-09", "Nov")["observations"] == []
    with pytest.raises(SourceAccessError, match="schema changed"):
        adapters.normalize_wasde(workbook_bytes({"changed": [["schema"]]}), "Corn", "2026-10-09", "Oct")


def test_rig_count_empty_and_schema_fixtures():
    raw = workbook_bytes(
        {"NAM Weekly": [["US_PublishDate", "Country", "Rig Count Value"], [datetime.fromisoformat(TODAY), "US", 10]]}
    )
    assert adapters.normalize_rig_count(raw, params())["observations"][0]["value"] == 10
    assert (
        adapters.normalize_rig_count(raw, params(start_date="2000-01-01", end_date="2000-01-02"))["observations"] == []
    )
    with pytest.raises(SourceAccessError, match="schema changed"):
        adapters.normalize_rig_count(workbook_bytes({"changed": [["schema"]]}), params())
