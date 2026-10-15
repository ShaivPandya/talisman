from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest

from api import alternative_data as service
from api import alternative_data_adapters as adapters
from ontology.policy import admin_actor, agent_actor
from ontology.sources import source_registry


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("TALISMAN_ALLOW_SQLITE_STATE", "true")
    monkeypatch.setattr(service.snapshot_store, "_SQLITE_PATH", tmp_path / "snapshots.db")
    monkeypatch.setattr(service.provenance, "start_event", lambda **kwargs: None)
    monkeypatch.setattr(service.provenance, "finish_event", lambda *args, **kwargs: None)
    for spec in service.specs().values():
        for key in spec["required_credentials"]:
            monkeypatch.delenv(key, raising=False)
        if spec.get("permission_env"):
            monkeypatch.delenv(spec["permission_env"], raising=False)
    monkeypatch.delenv("COPERNICUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("COPERNICUS_CLIENT_SECRET", raising=False)


def test_all_sources_registered_grouped_and_license_gated():
    catalog = service.search_catalog()
    assert catalog["count"] == 17
    rows = {r["source_id"]: r for r in catalog["sources"]}
    assert set(catalog["groups"]) == {"demand", "physical", "labor", "trade"}
    assert rows["alternative_opensky"]["availability"]["status"] == "license_required"
    assert rows["alternative_firms"]["availability"]["status"] == "setup_required"
    assert rows["alternative_marinecadastre"]["availability"]["status"] == "bulk_only"
    assert rows["alternative_sonar"]["availability"]["status"] == "reference_only"
    assert rows["alternative_copernicus"]["operations"]["indices"]["status"] == "setup_required"
    assert all(row["license_url"].startswith("https://") and row["access_checked_at"] for row in rows.values())


def test_future_registration_needs_no_navigation_or_workflow_changes(monkeypatch):
    spec = copy.deepcopy(service.get_spec("alternative_tsa"))
    spec.update(source_id="alternative_new_source", name="New public series", question="A newly registered question")
    registry = source_registry.all_source_registry_entries()
    registry[spec["source_id"]] = source_registry.SourceRegistryEntry(
        spec["source_id"], spec["name"], "alternative", 1, 86400, False, alternative_data=spec
    )
    monkeypatch.setattr(source_registry, "_SOURCE_REGISTRY", registry)
    matches = service.search_catalog("newly registered")
    assert matches["sources"][0]["source_id"] == "alternative_new_source"


@pytest.mark.parametrize(
    "parameters",
    [
        {"limit": 1001},
        {"limit": True},
        {"url": "https://example.com"},
        {"start_date": "2026-10-14", "end_date": "2020-01-01"},
        {"start_date": "2020-01-01", "end_date": "2026-01-01"},
    ],
)
def test_parameter_bounds_reject_unsafe_or_invalid_input(parameters):
    with pytest.raises(ValueError):
        service.normalize_parameters(service.FetchRequest(source_id="alternative_tsa", parameters=parameters))


@pytest.mark.parametrize("bbox", [[0, 0, 1, 1], [1, 1, 0, 0], [0, 0, float("nan"), 1], [0, 86, 0.001, 87]])
def test_area_validation(bbox):
    with pytest.raises(ValueError):
        service.validate_bbox(bbox)


def test_company_geography_requires_confirmed_site(monkeypatch):
    req = service.FetchRequest(source_id="alternative_osm", ticker="MSFT", parameters={"bbox": [0, 0, 0.001, 0.001]})
    with pytest.raises(ValueError, match="confirmed"):
        service.normalize_parameters(req)
    monkeypatch.setattr(
        service,
        "get_site",
        lambda site_id: {"site_id": site_id, "ticker": "MSFT", "status": "confirmed", "bbox": [0, 0, 0.001, 0.001]},
    )
    req.parameters = {"site_id": "confirmed"}
    assert service.normalize_parameters(req)["bbox"] == [0, 0, 0.001, 0.001]
    req.ticker = "AAPL"
    with pytest.raises(ValueError, match="this company"):
        service.normalize_parameters(req)


def test_raw_coordinates_cannot_override_confirmed_site(monkeypatch):
    monkeypatch.setattr(
        service, "get_site", lambda _: {"ticker": "MSFT", "status": "confirmed", "bbox": [0, 0, 0.001, 0.001]}
    )
    req = service.FetchRequest(
        source_id="alternative_osm", ticker="MSFT", parameters={"site_id": "site", "bbox": [1, 1, 1.001, 1.001]}
    )
    with pytest.raises(ValueError, match="Coordinates must match"):
        service.normalize_parameters(req)


def test_sentinel_one_cannot_be_presented_as_spectral_index_measurements(monkeypatch):
    monkeypatch.setattr(
        service, "get_site", lambda _: {"ticker": "MSFT", "status": "confirmed", "bbox": [0, 0, 0.001, 0.001]}
    )
    with pytest.raises(ValueError, match="Sentinel-1 supports scene discovery only"):
        service.normalize_parameters(
            service.FetchRequest(
                source_id="alternative_copernicus",
                ticker="MSFT",
                parameters={"site_id": "site", "operation": "indices", "mission": "SENTINEL-1"},
            )
        )


def test_cache_reuse_and_failed_refresh_preserve_observation_and_retrieval_dates(monkeypatch):
    calls = []
    day = datetime.now(UTC).date().isoformat()

    def loader(client, p):
        calls.append(p)
        return adapters.payload([adapters.observation(day, "travelers", 12, "people")])

    monkeypatch.setattr(adapters, "tsa", loader)
    req = service.FetchRequest(source_id="alternative_tsa")
    first = service.query_source(req)
    second = service.query_source(req)
    assert len(calls) == 1 and second["cache"] == "hit"

    def fail(*_):
        raise adapters.SourceAccessError("Provider unavailable (HTTP 429)")

    monkeypatch.setattr(adapters, "tsa", fail)
    stale = service.query_source(req.model_copy(update={"force_refresh": True}))
    assert stale["status"] == "stale"
    assert (stale["as_of"], stale["fetched_at"]) == (first["as_of"], first["fetched_at"])
    assert stale["observations"] == first["observations"]
    catalog_source = service.search_catalog("TSA")["sources"][0]
    assert catalog_source["availability"]["status"] == "unavailable"
    assert catalog_source["latest_result"]["as_of"] == first["as_of"]
    assert service.search_catalog("TSA", available_only=True)["count"] == 0


def test_empty_results_do_not_invent_freshness_or_zero_values(monkeypatch):
    monkeypatch.setattr(adapters, "indeed", lambda *_: adapters.payload([]))
    result = service.query_source(service.FetchRequest(source_id="alternative_indeed"))
    assert result["status"] == "empty" and result["as_of"] is None
    assert result["freshness"]["status"] == "unknown" and result["observations"] == []


def test_license_gate_is_checked_before_upstream_fetch(monkeypatch):
    monkeypatch.setattr(adapters, "opensky", lambda *_: pytest.fail("License-gated source was fetched"))
    result = service.query_source(
        service.FetchRequest(source_id="alternative_opensky", parameters={"bbox": [0, 0, 0.001, 0.001]})
    )
    assert result["status"] == "license_required" and not result["observations"]


def test_citation_rejects_credentials_and_insecure_links():
    for url in ("http://example.com", "https://user:password@example.com", "https://example.com/?token=private"):
        with pytest.raises(ValueError):
            service.safe_citation({"url": url})


def test_http_allowlist_prevents_upstream_ssrf():
    client = adapters.SourceClient(service.get_spec("alternative_tsa"))
    for url in (
        "https://127.0.0.1/test",
        "https://www.tsa.gov.evil.example/test",
        "http://www.tsa.gov",
        "https://www.tsa.gov:8443",
    ):
        with pytest.raises(adapters.SourceAccessError, match="approved"):
            client.request(url)


def test_download_limit_and_429_messages_never_echo_response_secrets(monkeypatch):
    monkeypatch.setattr(adapters, "_reserve_request", lambda *_: None)

    class Response:
        headers = {"Content-Length": "200"}
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(adapters.requests, "request", lambda *_args, **_kwargs: Response())
    with pytest.raises(adapters.SourceAccessError, match="bounded"):
        adapters.SourceClient(service.get_spec("alternative_tsa")).request("https://www.tsa.gov/test", max_bytes=100)
    Response.status_code = 429
    with pytest.raises(adapters.SourceAccessError, match="HTTP 429"):
        adapters.SourceClient(service.get_spec("alternative_tsa")).request("https://www.tsa.gov/test")


def _satellite_interval(day, mean, invalid=0):
    return {
        "interval": {"from": day + "T00:00:00Z"},
        "outputs": {
            "indices": {
                "bands": {
                    band: {"stats": {"sampleCount": 100, "noDataCount": invalid, "mean": mean}}
                    for band in ("B0", "B1", "B2")
                }
            }
        },
    }


def test_spectral_formula_zero_denominators_and_cloud_coverage():
    indices = adapters.spectral_indices(0.1, 0.2, 0.8, 0.6)
    assert indices["NDVI"] == pytest.approx(0.6)
    assert indices["NDWI"] == pytest.approx(-7 / 9)
    assert indices["NDBI"] == pytest.approx(-1 / 7)
    assert adapters.spectral_indices(0, 0, 0, 0) == {"NDVI": None, "NDWI": None, "NDBI": None}
    result = adapters.normalize_sentinel_statistics(
        {"data": [_satellite_interval("2026-10-10", 0.9, invalid=71)]}, {"end_date": "2026-10-14"}
    )
    assert all(row["value"] is None for row in result["observations"])
    assert result["observations"][0]["dimensions"]["valid_coverage"] == 0.29


def test_imagery_compares_dated_windows_without_treating_missing_as_zero():
    result = adapters.normalize_sentinel_statistics(
        {
            "data": [
                _satellite_interval("2026-10-10", 0.6),
                _satellite_interval("2026-09-01", 0.2),
                _satellite_interval("2026-10-12", 0.9, invalid=100),
            ]
        },
        {"end_date": "2026-10-14"},
    )
    compare = result["snapshot"]["comparisons"]["NDVI"]
    assert compare["latest_30d_mean"] == 0.6 and compare["previous_30d_mean"] == 0.2
    assert compare["change"] == pytest.approx(0.4)


def test_sentinel_request_uses_metre_grid_fixed_mask_and_free_endpoint(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "test-id")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "test-secret")
    requests = []

    class Client:
        def json(self, url, **kwargs):
            requests.append((url, kwargs))
            return {"access_token": "redacted"} if len(requests) == 1 else {"data": []}

    adapters.sentinel_indices(
        Client(), {"bbox": [-118.25, 33.73, -118.24, 33.74], "start_date": "2026-07-14", "end_date": "2026-10-14"}
    )
    request = requests[-1][1]["json"]
    assert request["aggregation"]["resx"] == request["aggregation"]["resy"] == 20
    assert request["input"]["bounds"]["properties"]["crs"].endswith("32611")
    assert "[4,5,6].includes(s.SCL)" in request["aggregation"]["evalscript"]
    assert requests[-1][0] == "https://sh.dataspace.copernicus.eu/api/v1/statistics"


def test_hiring_schema_drift_fails_without_fabricating_observations():
    with pytest.raises(adapters.SourceAccessError, match="schema"):
        adapters.indeed(SimpleNamespace(text=lambda _: "unexpected,column\n1,2"), {"country": "US"})


def test_lca_exact_legal_employer_aggregation_and_disclosure_caveat():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["EMPLOYER_NAME", "CASE_STATUS", "TOTAL_WORKER_POSITIONS", "DECISION_DATE", "SOC_TITLE"])
    sheet.append(["Example Inc", "Certified", 3, datetime(2026, 9, 1), "Engineer"])
    sheet.append(["Example Holdings", "Certified", 99, datetime(2026, 9, 1), "Engineer"])
    raw = BytesIO()
    workbook.save(raw)

    def download(*args, **kwargs):
        kwargs["destination"].write(raw.getvalue())
        return b""

    client = SimpleNamespace(
        spec={"url": "https://www.dol.gov/agencies/eta/foreign-labor/performance"},
        text=lambda _: '<a href="/LCA_Disclosure_Data_FY2026_Q3.xlsx">2026 Q3</a>',
        request=download,
    )
    p = {"employer": "Example Inc", "start_date": "2026-08-01", "end_date": "2026-10-14", "limit": 50}
    result = adapters.lca(client, p)
    assert result["snapshot"]["applications"] == 1 and result["snapshot"]["groups"][0]["worker_positions"] == 3
    assert "not actual hires" in result["warnings"][0]


def test_source_selection_is_bounded_and_uses_shared_fetch_service(monkeypatch):
    import llm_utils

    monkeypatch.setattr(llm_utils, "has_llm_api_key", lambda: True)
    selected = [
        {"source_id": source, "parameters": {}, "reason": "relevant"}
        for source in ("alternative_tsa", "alternative_indeed", "alternative_ports", "alternative_comext")
    ]
    monkeypatch.setattr(llm_utils, "call_llm_json", lambda **kwargs: ({"fetches": selected}, [], None, {}))
    calls = []

    def fetch(req):
        calls.append(req.source_id)
        return {
            "source_id": req.source_id,
            "status": "ok",
            "citations": [{"title": "Official", "url": "https://example.com"}],
            "warnings": [],
        }

    monkeypatch.setattr(service, "query_source", fetch)
    result = service.build_company_evidence("DAL", "airline and hiring demand")
    assert len(calls) == 3 and len(result["evidence"]) == 3


def test_agents_cannot_confirm_company_ownership():
    with pytest.raises(ValueError, match="person"):
        service.confirm_site(service.SiteRequest(ticker="MSFT", name="Site", bbox=[0, 0, 0.001, 0.001]), agent_actor())


def test_automatic_evidence_does_not_invent_employer_mapping(monkeypatch):
    import llm_utils

    monkeypatch.setattr(llm_utils, "has_llm_api_key", lambda: True)
    monkeypatch.setattr(
        llm_utils,
        "call_llm_json",
        lambda **kw: (
            {"fetches": [{"source_id": "alternative_lca", "parameters": {"employer": "Guessed Legal Entity"}}]},
            [],
            None,
            {},
        ),
    )
    calls = []
    monkeypatch.setattr(service, "query_source", lambda req: calls.append(req))
    result = service.build_company_evidence("MSFT", "Hiring evidence")
    assert not calls and not result["evidence"]
    assert any("mapping is unresolved" in warning for warning in result["coverage_warnings"])


def test_confirmed_sites_use_ontology_write_boundary(monkeypatch):
    writes = []
    monkeypatch.setattr(service, "use_postgres_state", lambda: True)
    monkeypatch.setattr(service, "list_sites", lambda _: [])
    monkeypatch.setattr(service.provenance, "start_event", lambda **kwargs: {"event_id": "event"})
    monkeypatch.setattr(
        service, "OntologyObjectService", lambda: SimpleNamespace(write_object=lambda *a, **kw: writes.append((a, kw)))
    )
    result = service.confirm_site(
        service.SiteRequest(ticker="MSFT", name="Site", bbox=[0, 0, 0.001, 0.001]), admin_actor()
    )
    assert result["status"] == "confirmed"
    assert writes[0][0][0] == "SourceManifest" and writes[0][1]["provenance"] == "event"
    assert writes[0][0][2]["dataset"] == "alternative_data_sites"


def test_confirmed_site_lookup_uses_the_canonical_normalized_identity(monkeypatch):
    from ontology.object_service import normalize_object_payload, object_uid_for

    site_id = "alt-site-" + "a" * 32
    site = {"site_id": site_id, "ticker": "MSFT", "status": "confirmed", "bbox": [0, 0, 0.001, 0.001]}
    uid = object_uid_for("SourceManifest", site_id)
    row = normalize_object_payload(
        uid,
        "SourceManifest",
        site_id,
        {
            "manifest_id": site_id,
            "name": "Reviewed site",
            "source_kind": "company_site",
            "dataset": "alternative_data_sites",
            "metadata": site,
        },
    )
    assert uid == "source_manifest:alt_site_" + "a" * 32
    monkeypatch.setattr(service, "use_postgres_state", lambda: True)
    monkeypatch.setattr(
        service,
        "OntologyObjectService",
        lambda: SimpleNamespace(
            get_object=lambda key: row if key == uid else None,
        ),
    )
    assert service.get_site(site_id) == site
    parameters = service.normalize_parameters(
        service.FetchRequest(
            source_id="alternative_osm",
            ticker="MSFT",
            parameters={"site_id": site_id},
        )
    )
    assert parameters["bbox"] == site["bbox"]


def test_catalog_and_fetch_are_authenticated_and_schema_checked(client, auth_client):
    # client/auth_client share the same fixture object; create a separate unauthenticated session.
    from fastapi.testclient import TestClient

    from api.main import app

    assert TestClient(app).get("/api/alternative-data/catalog").status_code == 401
    response = auth_client.get("/api/alternative-data/catalog")
    assert response.status_code == 200 and response.json()["count"] == 17
    response = auth_client.post("/api/alternative-data/fetch", json={"source_id": "unknown"})
    assert response.status_code == 422
    assert auth_client.get("/api/alternative-data/jobs/nonexistent").status_code == 404


def test_both_agent_tools_are_discoverable_and_company_chat_selects_them():
    from api.agent_tools import search_agent_capabilities
    from api.routers.agent import _select_tool_names

    names = {r["name"] for r in search_agent_capabilities("alternative data")["matches"]}
    assert {"search_alternative_data_catalog", "fetch_alternative_data"} <= names
    assert "search_alternative_data_catalog" in _select_tool_names("Evaluate MSFT with hiring evidence")


def test_enriched_brief_does_not_mutate_or_rescore_analyzer_action(monkeypatch):
    import llm_utils
    from api.routers import analyzer

    action = {"ticker": "MSFT", "score": 72, "action_type": "hold"}
    original = copy.deepcopy(action)
    monkeypatch.setattr(
        service,
        "build_company_evidence",
        lambda *a, **kw: {"citations": [], "evidence": [], "coverage_warnings": ["No source available"]},
    )
    prompts = []

    def summarize(**kwargs):
        prompts.append(kwargs["prompt"])
        return "Hold. Coverage is incomplete.", [], None

    monkeypatch.setattr(llm_utils, "call_llm_text", summarize)
    result = analyzer.run_enriched_analyzer_brief(analyzer.EnrichedAnalyzerBriefRequest(action=action))
    assert action == original and "Do not rescore" in prompts[0]
    assert result["alternative_data"]["coverage_warnings"]


def test_production_snapshots_link_temporal_source_records(monkeypatch):
    source_writes, snapshot_writes = [], []
    source_id = "21b797ec-3591-4932-8c08-a1b58202db01"
    monkeypatch.setattr(service, "use_postgres_state", lambda: True)

    def write_source(write):
        source_writes.append(write)
        return {"source_record_id": source_id}

    monkeypatch.setattr(
        service,
        "TemporalOntologyRepository",
        lambda: SimpleNamespace(
            write_source_record_version=write_source,
            write_computed_snapshot_version=snapshot_writes.append,
        ),
    )
    result = {
        **adapters.payload([adapters.observation("2026-10-13", "travelers", 12, "people")]),
        "source_id": "alternative_tsa",
        "fetched_at": "2026-10-14T12:00:00Z",
        "provenance": {},
    }
    service._store_result("query-key", result, service.get_spec("alternative_tsa"), "event-id")
    assert source_writes[0].record_key == "query-key"
    assert source_writes[0].dataset == "alternative_data"
    assert snapshot_writes[0].source_record_ids == [source_id]
    assert snapshot_writes[0].provenance_event_id == "event-id"
    assert result["provenance"]["source_record_id"] == source_id


def test_durable_fetch_normalizes_job_keys_reuses_and_polls_only_its_source(monkeypatch):
    from api import async_job_runner, job_queue

    calls = []
    row = {
        "job_id": "fetch-job",
        "job_type": "alternative_data_fetch",
        "status": "queued",
        "payload_json": {"source_id": "alternative_tsa"},
    }

    def enqueue(job_type, payload, **kwargs):
        calls.append((job_type, payload, kwargs))
        return row, "reused_active" if len(calls) > 1 else "created"

    monkeypatch.setattr(async_job_runner, "enqueue_registered_job", enqueue)
    monkeypatch.setattr(job_queue, "get_job", lambda _: row)
    monkeypatch.setattr(async_job_runner, "poll_registered_job", lambda *a, **kw: {"status": "running"})
    req = service.FetchRequest(source_id="alternative_tsa")
    first = service.enqueue_fetch(req)
    second = service.enqueue_fetch(req)
    assert first["job_id"] == second["job_id"] == "fetch-job"
    assert service.cache_key(service.FetchRequest(**calls[0][1])) == service.cache_key(
        service.FetchRequest(**calls[1][1])
    )
    assert calls[0][2]["reuse_completed"] is True
    service.enqueue_fetch(req.model_copy(update={"force_refresh": True}))
    assert calls[-1][2]["reuse_completed"] is False
    assert service.poll_job("fetch-job", source_id="alternative_tsa")["status"] == "running"
    with pytest.raises(KeyError):
        service.poll_job("fetch-job", source_id="alternative_firms")


def test_deactivating_site_uses_canonical_boundary_and_prevents_later_fetches(monkeypatch):
    site = {"site_id": "alt-site-" + "a" * 32, "ticker": "MSFT", "bbox": [0, 0, 0.001, 0.001]}
    row = {"properties": {"metadata": site, "status": "active"}}
    writes = []
    monkeypatch.setattr(service, "get_site", lambda _: site if row["properties"]["status"] == "active" else None)
    monkeypatch.setattr(service.provenance, "start_event", lambda **kw: {"event_id": "remove-event"})

    def write(*args, **kwargs):
        writes.append((args, kwargs))
        row["properties"] = args[2]

    monkeypatch.setattr(
        service, "OntologyObjectService", lambda: SimpleNamespace(get_object=lambda _: row, write_object=write)
    )
    service.remove_site(site["site_id"], admin_actor())
    assert writes[0][0][2]["status"] == "inactive"
    assert writes[0][1]["provenance"] == "remove-event"
    with pytest.raises(ValueError, match="not confirmed"):
        service.normalize_parameters(
            service.FetchRequest(source_id="alternative_osm", ticker="MSFT", parameters={"site_id": site["site_id"]})
        )


def test_credential_gated_adapters_normalize_fixture_units_and_source_dates(monkeypatch):
    parameters = {
        "start_date": "2026-06-01",
        "end_date": "2026-06-02",
        "limit": 10,
        "bbox": [0, 0, 0.001, 0.001],
        "flow": "imports",
        "reporter": "0000",
        "product": "870322",
    }
    monkeypatch.setenv("FIRMS_MAP_KEY", "fixture-only-key")
    fire = adapters.firms(
        SimpleNamespace(text=lambda _: "latitude,longitude,acq_date,frp,confidence\n0,0,2026-06-01,5.5,n\n"), parameters
    )
    assert fire["observations"][0]["unit"] == "MW" and fire["as_of"] == "2026-06-01"
    monkeypatch.setenv("CENSUS_API_KEY", "fixture-only-key")
    trade = adapters.census(
        SimpleNamespace(
            json=lambda *a, **kw: [
                ["CTY_CODE", "I_COMMODITY", "GEN_VAL_MO", "time"],
                ["0000", "870322", "12345", "2026-06"],
            ]
        ),
        parameters,
    )
    assert trade["observations"][0]["unit"] == "USD" and trade["as_of"] == "2026-06-01"
    monkeypatch.setenv("AISHUB_USERNAME", "fixture-contributor")
    ais = adapters.aishub(
        SimpleNamespace(
            json=lambda *a, **kw: [{"ERROR": False}, [{"TYPE": 70, "TIME": 1780272000, "MMSI": 123456789}]]
        ),
        parameters,
    )
    assert ais["snapshot"]["vessel_count"] == 1 and ais["as_of"].startswith("2026-06-01")
    assert "123456789" not in str(ais)  # raw identifiers and positions are not retained
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "fixture-secret")
    replies = iter([{"access_token": "fixture-token"}, {"time": 1780272000, "states": [["private-vector"]]}])
    air = adapters.opensky(SimpleNamespace(json=lambda *a, **kw: next(replies)), parameters)
    assert air["snapshot"]["aircraft_count"] == 1 and air["as_of"].startswith("2026-06-01")
    assert "private-vector" not in str(air) and "fixture-token" not in str(air)
