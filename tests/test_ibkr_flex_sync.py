from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from api import ibkr_flex_sync as sync
from ontology.policy import admin_actor
from portfolio.ibkr_flex_import import parse_ibkr_flex_statement
from utils.market_freshness import MARKET_TIMEZONE, previous_market_session

AS_OF = previous_market_session(datetime.now(MARKET_TIMEZONE).date() - timedelta(days=1)).isoformat()
DATE = AS_OF.replace("-", "")
XML = f'''<FlexQueryResponse><FlexStatements count="1"><FlexStatement accountId="U1" toDate="{DATE}">
<AccountInformation currency="USD" />
<OpenPositions>
<OpenPosition assetCategory="STK" symbol="SAP" position="10" side="Long" currency="EUR" fxRateToBase="1.2"
 costBasisPrice="100" costBasisMoney="1000" positionValue="1100" markPrice="110" fifoPnlUnrealized="100" reportDate="{DATE}" levelOfDetail="SUMMARY" />
<OpenPosition assetCategory="STK" symbol="SAP" position="4" side="Long" currency="EUR" fxRateToBase="1.2"
 costBasisPrice="100" costBasisMoney="400" positionValue="440" markPrice="110" fifoPnlUnrealized="40" reportDate="{DATE}" levelOfDetail="LOT" openDateTime="20260101;120000" originatingTransactionID="a" />
<OpenPosition assetCategory="STK" symbol="SAP" position="6" side="Long" currency="EUR" fxRateToBase="1.2"
 costBasisPrice="100" costBasisMoney="600" positionValue="660" markPrice="110" fifoPnlUnrealized="60" reportDate="{DATE}" levelOfDetail="LOT" openDateTime="20260201;120000" originatingTransactionID="b" />
<OpenPosition assetCategory="FUT" symbol="ESZ6" underlyingSymbol="ES" position="-2" currency="USD" multiplier="50" costBasisPrice="6000" markPrice="6010" reportDate="{DATE}" />
<OpenPosition assetCategory="STK" symbol="SPY" position="-5" side="Short" currency="USD" costBasisPrice="500" reportDate="{DATE}" />
</OpenPositions>
<CashReport><CashReportCurrency currency="USD" endingCash="20000" endingSettledCash="19000" /><CashReportCurrency currency="EUR" endingCash="-500" /><CashReportCurrency currency="BASE_SUMMARY" endingCash="19400" /></CashReport>
<EquitySummaryInBase><EquitySummaryByReportDateInBase reportDate="{DATE}" total="125000" /></EquitySummaryInBase>
</FlexStatement></FlexStatements></FlexQueryResponse>'''


def reader(positions=None, hedges=None):
    return SimpleNamespace(positions=lambda **_: positions or [], list_objects=lambda *_, **__: hedges or [])


def stage_statement(statement, *, existing=None, hedges=None, scheduled=True, pending=None):
    calls = []

    def stage(action, payload, **kwargs):
        calls.append({"action_id": action, "payload": payload, **kwargs})
        return {"approval_id": action, "action_id": action, "status": "pending_approval_created"}

    result = sync.stage_flex_statement(
        statement,
        actor=admin_actor(source="test"),
        read_service=reader(existing, hedges),
        stage=stage,
        scheduled=scheduled,
        pending=pending,
    )
    return result, calls


def test_statement_futures_lots_marks_nav_and_currency_balances():
    statement = parse_ibkr_flex_statement(XML)
    assert statement.as_of == AS_OF
    assert statement.base_currency == "USD"
    assert statement.net_liquidation == 125000
    assert len(statement.positions) == 3
    stock = statement.positions[0]
    assert stock["quantity"] == 10
    assert stock["source"] == "ibkr_flex"
    assert stock["broker_mark_price"] == 110
    assert stock["cost_basis_base"] == 1200
    assert stock["notional_base"] == 1320
    assert stock["broker_unrealized_pnl_base"] == 120
    assert len(stock["ibkr_lots"]) == 2
    assert stock["ibkr_lots"][0]["open_date"] == "2026-01-01"
    future = statement.positions[1]
    assert (future["ticker"], future["price_symbol"], future["contract_multiplier"]) == ("ESZ6", "ES=F", 50)
    assert future["direction"] == "short"
    assert future["quantity"] == 2
    assert [row["currency"] for row in statement.cash_balances] == ["USD", "EUR"]
    assert statement.cash_balances[1]["balance"] == -500


def test_lot_only_statement_aggregates_quantity_cost_and_pnl():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(XML)
    positions = root.find(".//OpenPositions")
    positions.remove(positions[0])
    statement = parse_ibkr_flex_statement(ET.tostring(root))
    assert statement.positions[0]["quantity"] == 10
    assert statement.positions[0]["cost_basis"] == 100
    assert statement.positions[0]["broker_unrealized_pnl_base"] == 120


@pytest.mark.parametrize(
    "payload,match",
    [
        ("<FlexQueryResponse/>", "No supported"),
        (XML.replace('position="10"', 'position="nan"', 1), "quantity"),
        (XML.replace('assetCategory="FUT"', 'assetCategory="BOND"'), "Unsupported"),
        (XML.replace('position="4"', 'position="3"'), "Lot quantities"),
        ('<!DOCTYPE root [<!ENTITY a "x">]><root/>', "document types"),
        (XML.replace("</FlexStatements>", '<FlexStatement accountId="U2"/></FlexStatements>'), "single-account"),
    ],
)
def test_unsafe_or_incomplete_statements_are_rejected(payload, match):
    with pytest.raises(ValueError, match=match):
        parse_ibkr_flex_statement(payload)


def test_staging_preserves_metadata_and_manual_hedges_without_applying_book():
    statement = parse_ibkr_flex_statement(XML)
    metadata = {"conviction": 5, "contrarian": True, "group_name": "Europe", "group_conviction": 4}
    original = {**statement.positions[0], **metadata, "quantity": 5, "shares": 5}
    _, calls = stage_statement(
        statement, existing=[original], hedges=[{"ticker": "TLT", "direction": "short", "shares": 1}]
    )
    assert [row["action_id"] for row in calls] == [
        "update_portfolio_positions",
        "update_hedge_positions",
        "update_portfolio_settings",
    ]
    assert all(row["apply"] is False for row in calls)
    proposed = calls[0]["payload"]["positions"][0]
    assert all(proposed[key] == value for key, value in metadata.items())
    assert proposed["quantity"] == 10
    assert proposed["broker_mark_price"] == 110
    assert len(proposed["ibkr_lots"]) == 2
    assert original["quantity"] == 5
    assert {row["ticker"] for row in calls[1]["payload"]["positions"]} == {"TLT", "SPY"}
    assert calls[2]["payload"]["book_size"] == 125000


def test_unchanged_holdings_refresh_marks_without_new_proposals(monkeypatch):
    statement = parse_ibkr_flex_statement(XML)
    monkeypatch.setattr(sync, "get_configured_portfolio_book_size", lambda: 125000)
    stock, future, hedge = statement.positions
    existing = [{**stock, "broker_mark_price": 95, "as_of": "2000-01-01"}, future]
    result, calls = stage_statement(statement, existing=existing, hedges=[hedge])
    assert not calls
    assert result["status"] == "unchanged"


def test_matching_pending_proposals_are_reused():
    statement = parse_ibkr_flex_statement(XML)
    _, calls = stage_statement(statement)
    pending = [
        {"id": str(i), "action_id": call["action_id"], "proposed_change": call["payload"]}
        for i, call in enumerate(calls)
    ]
    result, again = stage_statement(statement, pending=pending)
    assert not again
    assert len(result["staged_proposals"]) == 3
    assert all(row["status"] == "pending_approval_reused" for row in result["staged_proposals"])


def test_absent_broker_hedge_removed_but_manual_hedge_preserved(monkeypatch):
    statement = parse_ibkr_flex_statement(XML)
    monkeypatch.setattr(sync, "get_configured_portfolio_book_size", lambda: 125000)
    existing_hedges = [
        {"ticker": "IWM", "source": "ibkr_flex", "direction": "short", "shares": 5},
        {"ticker": "TLT", "direction": "short", "shares": 1},
    ]
    _, calls = stage_statement(statement, hedges=existing_hedges)
    proposed = next(call["payload"] for call in calls if call["action_id"] == "update_hedge_positions")
    assert {row["ticker"] for row in proposed["positions"]} == {"SPY", "TLT"}


def test_invalid_nav_validated_before_any_proposal():
    statement = parse_ibkr_flex_statement(XML.replace('total="125000"', 'total="-1"'))
    calls = []
    with pytest.raises(ValueError, match="between"):
        sync.stage_flex_statement(
            statement, actor=admin_actor(), read_service=reader(), stage=lambda *a, **k: calls.append(a)
        )
    assert not calls


@pytest.fixture
def scheduled(monkeypatch, tmp_path):
    import api.action_execution as actions
    import api.snapshot_store as snapshots
    import ontology.runtime_read_service as reads
    from ontology.command_service import OntologyCommandService
    from portfolio.ibkr_flex_client import FlexClient

    monkeypatch.setattr(snapshots, "_SQLITE_PATH", tmp_path / "snapshots.db")
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "test-token")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "123")
    monkeypatch.setattr(FlexClient, "fetch_statement", lambda self: XML.encode())
    monkeypatch.setattr(reads, "OntologyRuntimeReadService", lambda: reader())
    monkeypatch.setattr(OntologyCommandService, "list_approvals", lambda *a, **k: [])
    calls = []

    def stage(action, payload, **kwargs):
        calls.append((action, payload))
        return {"action_id": action, "approval_id": action}

    monkeypatch.setattr(actions, "stage_api_action", stage)
    return calls


def test_scheduled_pull_records_snapshot_and_stages_approvals(scheduled):
    sync.sync_ibkr_flex()
    assert len(scheduled) == 3
    status = sync.ibkr_flex_status()
    assert status["status"] == "ok"
    assert status["as_of"] == AS_OF
    assert len(status["positions"]) == 3
    assert "test-token" not in str(status)


def test_status_only_links_currently_pending_statement_proposals(scheduled, monkeypatch):
    from ontology.command_service import OntologyCommandService

    sync.sync_ibkr_flex()
    pending = [
        {"id": action, "action_id": action} for action, _ in scheduled if action != "update_portfolio_settings"
    ] + [{"id": "unrelated", "action_id": "update_portfolio_positions"}]
    monkeypatch.setattr(OntologyCommandService, "list_approvals", lambda *a, **k: pending)
    status = sync.ibkr_flex_status()
    assert {row["action_id"] for row in status["pending_proposals"]} == {
        "update_portfolio_positions",
        "update_hedge_positions",
    }
    assert status["last_attempt_at"]
    pending.clear()
    assert sync.ibkr_flex_status()["pending_proposals"] == []


@pytest.mark.parametrize("now", ["2026-10-31T07:00:00-04:00", "2026-11-01T07:00:00-05:00"])
def test_weekend_pull_catches_friday_statement(scheduled, monkeypatch, now):
    from portfolio.ibkr_flex_client import FlexClient

    class WeekendClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(now).astimezone(tz)

    monkeypatch.setattr(sync, "datetime", WeekendClock)
    monkeypatch.setattr(FlexClient, "fetch_statement", lambda self: XML.replace(DATE, "20261029").encode())
    with pytest.raises(RuntimeError, match="expected 2026-10-30"):
        sync.sync_ibkr_flex()
    assert not scheduled
    monkeypatch.setattr(FlexClient, "fetch_statement", lambda self: XML.replace(DATE, "20261030").encode())
    sync.sync_ibkr_flex()
    assert len(scheduled) == 3
    assert sync.ibkr_flex_status()["status"] == "ok"
    assert sync.ibkr_flex_status()["as_of"] == "2026-10-30"


@pytest.mark.parametrize("day_offset", [0, 1])
def test_postgres_snapshot_roundtrip_compares_report_days(scheduled, monkeypatch, day_offset):
    from api.snapshot_store import _row_to_record

    sync.sync_ibkr_flex()
    record = sync.read_snapshot(sync.SNAPSHOT_KEY)
    postgres_record = _row_to_record(
        {
            "snapshot_key": record.snapshot_key,
            "payload_json": record.payload,
            "as_of": (datetime.fromisoformat(AS_OF) + timedelta(days=day_offset)).replace(tzinfo=UTC),
            "load_time": datetime.fromisoformat(record.fetched_at),
            "status": "ok",
        }
    )
    monkeypatch.setattr(sync, "read_snapshot", lambda key: postgres_record)
    scheduled.clear()
    if day_offset:
        with pytest.raises(RuntimeError, match="older than the last successful sync"):
            sync.sync_ibkr_flex()
        assert not scheduled
    else:
        sync.sync_ibkr_flex()
        assert sync.ibkr_flex_status()["status"] == "ok"
        assert sync.ibkr_flex_status()["stale"] is False


@pytest.mark.parametrize("failure", ["empty", "network", "stale"])
def test_failed_pull_retains_last_success_and_stages_nothing(scheduled, monkeypatch, failure):
    from portfolio.ibkr_flex_client import FlexClient, FlexServiceError

    sync.sync_ibkr_flex()
    scheduled.clear()
    previous = sync.ibkr_flex_status()

    def fetch(self):
        if failure == "network":
            raise FlexServiceError("Unable to reach IBKR Flex Web Service.")
        if failure == "stale":
            return XML.replace(DATE, "20200101").encode()
        return b"<FlexQueryResponse/>"

    monkeypatch.setattr(FlexClient, "fetch_statement", fetch)
    with pytest.raises(RuntimeError):
        sync.sync_ibkr_flex()
    assert not scheduled
    status = sync.ibkr_flex_status()
    assert status["status"] == "failed"
    assert status["positions"] == previous["positions"]
    assert status["last_success_at"] == previous["last_success_at"]
    assert status["error"]


def test_settings_proposal_requires_approval_and_rejects_stale_book():
    from api.portfolio_settings import (
        get_configured_portfolio_book_size,
        get_portfolio_book_size,
        set_portfolio_book_size,
    )
    from ontology.command_service import OntologyCommandConflict, OntologyCommandContext, OntologyCommandService
    from tests.test_ontology_command_service import FakeObjectService

    service = OntologyCommandService(FakeObjectService())
    context = OntologyCommandContext(actor=admin_actor(source="test"), source_type="test", source_id="test")
    approval = service.propose_action(
        "update_portfolio_settings", {"book_size": 125000, "source": "ibkr_flex", "as_of": AS_OF}, context
    )
    assert get_configured_portfolio_book_size() is None
    assert get_portfolio_book_size() == 100000
    applied = service.resolve_approval(approval["id"], "approved", "Approve broker NAV", context)
    assert applied["application_status"] == "applied"
    assert get_portfolio_book_size() == 125000
    approval = service.propose_action("update_portfolio_settings", {"book_size": 130000}, context)
    set_portfolio_book_size(140000)
    with pytest.raises(OntologyCommandConflict, match="changed"):
        service.resolve_approval(approval["id"], "approved", "old", context)
    assert get_portfolio_book_size() == 140000


def test_broker_metadata_survives_real_approval_and_does_not_touch_research():
    from ontology.command_service import OntologyCommandContext, OntologyCommandService
    from tests.test_ontology_command_service import FakeObjectService

    service = OntologyCommandService(FakeObjectService())
    context = OntologyCommandContext(actor=admin_actor(source="test"), source_type="test", source_id="test")
    stock = parse_ibkr_flex_statement(XML).positions[0]
    approval = service.propose_action("update_portfolio_positions", {"positions": [stock]}, context)
    assert "position:SAP" not in service.objects.objects
    service.resolve_approval(approval["id"], "approved", "Approve holdings", context)
    row = service.objects.objects["position:SAP"]["properties"]
    assert row["broker_mark_price"] == 110
    assert row["broker_unrealized_pnl_base"] == 120
    assert len(row["ibkr_lots"]) == 2
    assert not any(
        r["object_type"] in {"Thesis", "Catalyst", "KillCondition", "DocumentArtifact"}
        for r in service.objects.objects.values()
    )


def test_system_actor_can_stage_real_portfolio_and_nav_proposals():
    from ontology.command_service import OntologyCommandContext, OntologyCommandService
    from ontology.policy import system_actor
    from tests.test_ontology_command_service import FakeObjectService

    service = OntologyCommandService(FakeObjectService())
    context = OntologyCommandContext(
        actor=system_actor("ibkr_flex"),
        source_type="user",
        source_id="portfolio_edit.import_ibkr_flex_portfolio_positions",
    )
    stock = parse_ibkr_flex_statement(XML).positions[0]
    holdings = service.propose_action("update_portfolio_positions", {"positions": [stock]}, context)
    nav = service.propose_action("update_portfolio_settings", {"book_size": 125000}, context)
    assert holdings["status"] == nav["status"] == "pending"
    assert holdings["risk_class"] == nav["risk_class"] == "financial"
    assert len(service.list_approvals(status="pending", actor=context.actor)) == 2
    assert "position:SAP" not in service.objects.objects


def test_manual_upload_and_status_route(auth_client, monkeypatch, tmp_path):
    import api.snapshot_store as snapshots
    from api.routers import portfolio_edit

    monkeypatch.setattr(snapshots, "_SQLITE_PATH", tmp_path / "status.db")
    monkeypatch.setattr(portfolio_edit, "OntologyRuntimeReadService", lambda: reader())
    calls = []

    def stage(action, payload, **kwargs):
        calls.append((action, payload))
        return {"action_id": action, "approval_id": action, "status": "pending_approval_created"}

    monkeypatch.setattr(portfolio_edit, "stage_api_action", stage)
    response = auth_client.post(
        "/api/portfolio-positions/import/ibkr-flex", files={"file": ("statement.xml", XML, "application/xml")}
    )
    assert response.status_code == 200
    assert len(calls) == 3
    assert response.json()["import_summary"]["as_of"] == AS_OF
    assert calls[0][1]["positions"][0]["broker_mark_price"] == 110
    status = auth_client.get("/api/portfolio-positions/ibkr-flex-status")
    assert status.status_code == 200
    assert status.json()["status"] == "never_synced"


def test_scheduler_route_auth_and_registered_job(client, monkeypatch):
    from api.job_registry import get_job_spec
    from api.routers import admin_jobs

    monkeypatch.setenv("SCHEDULER_SECRET", "test-scheduler")
    seen = []

    def enqueue(job, payload, **kwargs):
        seen.append((job, kwargs))
        return {"job_id": "flex-job", "status": "queued"}, "created"

    monkeypatch.setattr(admin_jobs, "enqueue_registered_job", enqueue)
    monkeypatch.setattr(admin_jobs, "enqueue_response", lambda row, path: row)
    assert client.post("/api/admin/jobs/enqueue-ibkr-flex-sync").status_code == 401
    response = client.post("/api/admin/jobs/enqueue-ibkr-flex-sync", headers={"X-Scheduler-Secret": "test-scheduler"})
    assert response.status_code == 200
    assert seen[0][0] == "ibkr_flex_sync"
    assert seen[0][1]["reuse_completed"] is False
    assert get_job_spec("ibkr_flex_sync").compute_func == "api.ibkr_flex_sync.sync_ibkr_flex"


def test_old_success_is_reported_as_stale_without_another_pull(scheduled):
    sync.sync_ibkr_flex()
    record = sync.read_snapshot(sync.SNAPSHOT_KEY)
    sync.write_snapshot_success(sync.SNAPSHOT_KEY, record.payload, as_of_date="2020-01-01")
    assert sync.ibkr_flex_status()["status"] == "stale"
    assert sync.ibkr_flex_status()["stale"] is True


def test_missing_credentials_surface_failure_without_staging(scheduled, monkeypatch):
    monkeypatch.delenv("IBKR_FLEX_TOKEN")
    with pytest.raises(RuntimeError, match="not configured"):
        sync.sync_ibkr_flex()
    assert not scheduled
    assert sync.ibkr_flex_status()["status"] == "failed"
    assert sync.ibkr_flex_status()["configured"] is False


def test_duplicate_lots_are_rejected():
    with pytest.raises(ValueError, match="Duplicate lot"):
        parse_ibkr_flex_statement(XML.replace('originatingTransactionID="b"', 'originatingTransactionID="a"'))


def test_broker_nav_can_be_rejected_without_configuring_book_size():
    from api.portfolio_settings import get_configured_portfolio_book_size, get_portfolio_book_size
    from ontology.command_service import OntologyCommandContext, OntologyCommandService
    from tests.test_ontology_command_service import FakeObjectService

    service = OntologyCommandService(FakeObjectService())
    context = OntologyCommandContext(actor=admin_actor(source="test"), source_type="test", source_id="test")
    approval = service.propose_action("update_portfolio_settings", {"book_size": 125000}, context)
    service.resolve_approval(approval["id"], "rejected", "Keep configured sizing", context)
    assert get_configured_portfolio_book_size() is None
    assert get_portfolio_book_size() == 100000


def test_broker_approval_keeps_statement_fx_and_values(monkeypatch):
    import portfolio.valuation as valuation
    from ontology.action_registry import UpdatePortfolioPositionsInput, _position_rows

    monkeypatch.setattr(
        valuation, "enrich_position_valuations", lambda *a, **k: pytest.fail("Broker rows must not query Yahoo")
    )
    stock = parse_ibkr_flex_statement(XML).positions[0]
    approved_rows = _position_rows(UpdatePortfolioPositionsInput(positions=[stock]))
    assert approved_rows[0]["fx_rate_to_base"] == 1.2
    assert approved_rows[0]["notional_base"] == 1320
    assert approved_rows[0]["as_of"] == AS_OF


def test_stale_pending_proposal_is_not_reused(monkeypatch):
    import ontology.action_registry as registry

    statement = parse_ibkr_flex_statement(XML)
    _, calls = stage_statement(statement)
    pending = [
        {
            "id": "old",
            "action_id": calls[0]["action_id"],
            "proposed_change": calls[0]["payload"],
            "base_state_hash": "old-book",
        }
    ]
    monkeypatch.setattr(registry, "compute_action_base_state_hash", lambda *a: "new-book")
    result, restaged = stage_statement(statement, pending=pending)
    assert len(restaged) == 3
    assert all(row["status"] != "pending_approval_reused" for row in result["staged_proposals"])
