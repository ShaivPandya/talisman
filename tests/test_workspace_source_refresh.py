from __future__ import annotations

import pytest


def test_workspace_source_refresh_runs_persisted_backend_refreshes(monkeypatch):
    import api.macro_snapshots as macro_snapshots
    import api.maintenance_jobs as maintenance_jobs
    import api.market_snapshots as market_snapshots
    import api.position_risk as position_risk
    import api.risk_dashboard as risk_dashboard

    monkeypatch.setattr(market_snapshots, "refresh_market_snapshots", lambda: {"snapshots": ["market"]})
    monkeypatch.setattr(macro_snapshots, "refresh_macro_snapshots", lambda: {"snapshots": ["macro"]})

    def refresh_risk(*, refresh_optional_sources):
        assert refresh_optional_sources is True
        return {"result_id": "portfolio-risk:1"}

    def refresh_dashboard(payload, *, stress_snapshot):
        assert payload == {"holdings": []}
        assert stress_snapshot == {"result_id": "portfolio-risk:1"}
        return {"quality": "ok"}

    monkeypatch.setattr(position_risk, "refresh_portfolio_risk", refresh_risk)
    monkeypatch.setattr(risk_dashboard, "dashboard_request", lambda: {"holdings": []})
    monkeypatch.setattr(risk_dashboard, "compute_dashboard", refresh_dashboard)

    result = maintenance_jobs.refresh_workspace_sources()

    assert [step["step"] for step in result["steps"]] == [
        "market_snapshot_refresh",
        "macro_snapshot_refresh",
        "portfolio_risk_refresh",
        "portfolio_risk_dashboard_refresh",
    ]
    assert all(step["status"] == "ok" for step in result["steps"])


def test_workspace_source_refresh_fails_if_a_backend_refresh_fails(monkeypatch):
    import api.macro_snapshots as macro_snapshots
    import api.maintenance_jobs as maintenance_jobs
    import api.market_snapshots as market_snapshots
    import api.position_risk as position_risk
    import api.risk_dashboard as risk_dashboard

    def fail_market():
        raise RuntimeError("market unavailable")

    monkeypatch.setattr(market_snapshots, "refresh_market_snapshots", fail_market)
    monkeypatch.setattr(macro_snapshots, "refresh_macro_snapshots", lambda: {"snapshots": ["macro"]})
    monkeypatch.setattr(position_risk, "refresh_portfolio_risk", lambda **kwargs: {"result_id": "portfolio-risk:1"})
    monkeypatch.setattr(risk_dashboard, "dashboard_request", lambda: {"holdings": []})
    dashboard_calls = []
    monkeypatch.setattr(
        risk_dashboard,
        "compute_dashboard",
        lambda *args, **kwargs: dashboard_calls.append(True) or {"quality": "ok"},
    )

    with pytest.raises(RuntimeError, match="market unavailable"):
        maintenance_jobs.refresh_workspace_sources()
    assert dashboard_calls == [True]


def test_workspace_source_refresh_reports_nested_source_failures(monkeypatch):
    from api import maintenance_jobs

    monkeypatch.setattr(
        "api.market_snapshots.refresh_market_snapshots",
        lambda: {"snapshots": [{"snapshot_key": "market_breadth:sp500:1y", "status": "error", "error": "offline"}]},
    )
    monkeypatch.setattr("api.macro_snapshots.refresh_macro_snapshots", lambda: {"snapshots": []})
    monkeypatch.setattr(
        "api.position_risk.refresh_portfolio_risk",
        lambda **kwargs: {"quality": "degraded", "degraded_modules": [{"module": "sentiment", "status": "partial"}]},
    )
    monkeypatch.setattr("api.risk_dashboard.dashboard_request", lambda: {"holdings": []})
    monkeypatch.setattr("api.risk_dashboard.compute_dashboard", lambda *args, **kwargs: {"quality": "degraded"})

    result = maintenance_jobs.refresh_workspace_sources()
    assert result["status"] == "degraded"
    assert result["steps"][0]["status"] == "degraded"
    assert result["steps"][0]["issues"][0]["error"] == "offline"
    assert result["steps"][2]["issues"][0]["module"] == "sentiment"
    assert result["steps"][3]["status"] == "degraded"
