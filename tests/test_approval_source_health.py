from __future__ import annotations

import api.routers.approvals as approvals_router


def test_approval_summary_includes_source_health_review_and_blocks_approval(auth_client, monkeypatch):
    approval = {
        "id": "approval:source-blocked",
        "status": "pending",
        "application_status": "pending",
        "entity_type": "action_item",
        "ticker": "MU",
        "reason": "Review MU",
        "created_at": "2026-05-14T18:00:00",
        "proposed_change": {"description": "Review MU", "action_type": "review", "ticker": "MU"},
    }
    source_health = {
        "generated_at": "2026-05-14T18:00:00",
        "domains": [
            {
                "domain": "portfolio",
                "sources": [
                    {
                        "id": "portfolio",
                        "source_name": "portfolio",
                        "domain": "portfolio",
                        "status": "missing",
                        "quality_state": "missing",
                        "required": True,
                        "freshness_timestamp": None,
                        "detail": "source has no freshness record yet",
                    }
                ],
            }
        ],
    }

    monkeypatch.setattr(approvals_router, "_list_approval_records", lambda **_kwargs: [approval])
    monkeypatch.setattr(approvals_router, "_current_source_health_context", lambda: source_health)

    response = auth_client.get("/api/approvals/summary")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["source_health_review"]["status"] == "blocked"
    assert item["source_health_review"]["blockers"][0]["id"] == "portfolio"
    assert item["can_approve"] is False


def test_approvals_and_workspace_share_warm_snapshot_inputs(auth_client, monkeypatch, tmp_path):
    from datetime import datetime

    import api.agent_tools as agent_tools
    import api.position_risk as position_risk
    import api.position_risk_store as risk_store
    import api.routers.workspace as workspace_router
    import api.snapshot_store as store
    import api.source_health as health
    from api.snapshot_keys import SNAPSHOT_MARKET_BREADTH, SNAPSHOT_SIGNAL_AGGREGATOR

    monkeypatch.setattr(store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite3")
    monkeypatch.setattr(risk_store, "_SQLITE_PATH", tmp_path / "risk.sqlite3")
    # Exercise the production no-live-fallback path with isolated SQLite data.
    monkeypatch.setattr(store, "snapshots_required", lambda: True)
    now = datetime.now().isoformat()
    store.write_snapshot_success(
        SNAPSHOT_SIGNAL_AGGREGATOR,
        {"regime": {"label": "neutral", "score": 0}, "raw_modules": {"large": ["x"] * 1000}},
        as_of_date=now,
        fetched_at=now,
    )
    store.write_snapshot_success(SNAPSHOT_MARKET_BREADTH, {"quality": "ok"}, as_of_date=now, fetched_at=now)
    risk_store.write_portfolio_risk_snapshot({"result_id": "risk:1", "as_of": now, "computed_at": now})
    portfolio = {"positions": [{"ticker": "MU"}], "as_of": now}
    monkeypatch.setattr(agent_tools, "execute_tool", lambda *a, **kw: portfolio)
    monkeypatch.setattr(workspace_router, "get_setting", lambda *a: None)

    class Reads:
        def workspace_bundle(self):
            return {}

    monkeypatch.setattr(workspace_router, "OntologyRuntimeReadService", Reads)
    approval = {"id": "approval:1", "status": "pending", "proposed_change": {}}
    monkeypatch.setattr(approvals_router, "_list_approval_records", lambda **kw: [approval.copy()])
    monkeypatch.setattr(approvals_router, "_get_approval_record", lambda *a, **kw: approval.copy())

    calls = {"snapshot": 0, "risk": 0, "metadata": 0}
    original_record = store._row_to_record
    original_risk = position_risk.read_latest_portfolio_risk
    original_metadata = health.list_snapshot_records

    def record(row):
        calls["snapshot"] += 1
        return original_record(row)

    def risk():
        calls["risk"] += 1
        return original_risk()

    def metadata():
        calls["metadata"] += 1
        return original_metadata()

    monkeypatch.setattr(store, "_row_to_record", record)
    monkeypatch.setattr(position_risk, "read_latest_portfolio_risk", risk)
    monkeypatch.setattr(health, "list_snapshot_records", metadata)

    assert auth_client.get("/api/approvals").status_code == 200
    assert calls["snapshot"] > 0 and calls["risk"] == 1 and calls["metadata"] == 1
    calls.update(snapshot=0, risk=0, metadata=0)
    for _ in range(3):
        for path in ("/api/approvals", "/api/approvals/summary", "/api/approvals/1", "/api/workspace"):
            response = auth_client.get(path)
            assert response.status_code == 200, response.text
    assert calls == {"snapshot": 0, "risk": 0, "metadata": 0}
    assert response.json()["regime"]["regime"] == "neutral"

    # The live portfolio view remains uncached by the source-health cache.
    portfolio["positions"].append({"ticker": "NVDA"})
    assert auth_client.get("/api/workspace").json()["portfolio"]["position_count"] == 2
    assert calls == {"snapshot": 0, "risk": 0, "metadata": 0}

    store.write_snapshot_failure(SNAPSHOT_MARKET_BREADTH, "vendor timeout")
    refreshed = auth_client.get("/api/workspace").json()["source_health"]
    sources = {s["id"]: s for d in refreshed["domains"] for s in d["sources"]}
    assert sources[SNAPSHOT_MARKET_BREADTH]["error"] == "vendor timeout"
    assert calls["metadata"] == 1 and calls["risk"] == 1
    calls.update(snapshot=0, risk=0, metadata=0)
    assert auth_client.get("/api/approvals").status_code == 200
    assert calls == {"snapshot": 0, "risk": 0, "metadata": 0}
