from __future__ import annotations

import pytest


def test_dismiss_alert_refreshes_workspace_projection_after_write(auth_client, monkeypatch):
    from api import continuous_optimizer
    from api.routers import optimization
    from ontology.read_model import TemporalReadModelRepository

    alert = {
        "id": "optimization_alert:gate_changed",
        "alert_id": "gate_changed",
        "status": "open",
        "created_at": "2026-10-14T12:00:00+00:00",
        "updated_at": "2026-10-14T12:00:00+00:00",
    }
    saved = {}
    workspace_projection = dict(alert)
    monkeypatch.setattr(optimization, "_get_optimization_object", lambda *_args: dict(alert))

    def write(object_type, key, props):
        assert object_type == "OptimizationAlert"
        assert key == alert["id"]
        saved.update(props)
        return {"id": key, **props}

    def refresh(_self):
        assert saved["status"] == "dismissed"
        workspace_projection.update(saved)

    monkeypatch.setattr(continuous_optimizer, "_write_runtime_object", write)
    monkeypatch.setattr(TemporalReadModelRepository, "refresh", refresh)

    response = auth_client.put(
        "/api/optimization/alerts/optimization_alert%3Agate_changed/dismiss", json={"note": "Read"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"
    assert workspace_projection["status"] == "dismissed"
    assert saved["alert_id"] == "gate_changed"
    assert saved["dismissal_note"] == "Read"
    assert saved["dismissed_at"]
    assert saved["updated_at"] != alert["updated_at"]


def test_dismiss_alert_does_not_report_success_if_projection_refresh_fails(monkeypatch):
    from api import continuous_optimizer
    from api.routers import optimization
    from ontology.read_model import TemporalReadModelRepository

    monkeypatch.setattr(optimization, "_get_optimization_object", lambda *_args: {"id": "optimization_alert:test"})
    monkeypatch.setattr(continuous_optimizer, "_write_runtime_object", lambda _type, _key, props: props)

    def fail_refresh(_self):
        raise RuntimeError("Read model refresh unavailable")

    monkeypatch.setattr(TemporalReadModelRepository, "refresh", fail_refresh)

    with pytest.raises(RuntimeError, match="Read model refresh unavailable"):
        optimization.dismiss_optimization_alert("optimization_alert:test")
