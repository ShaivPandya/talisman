import pytest


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    from api import screener_runs

    monkeypatch.setattr(screener_runs, "SQLITE_PATH", tmp_path / "runs.db")


def snapshot(screen="Long"):
    return {
        "screen": screen,
        "name": "November pullbacks",
        "request": {"tickers": "AAA", "check_min_drawdown": True, "min_drawdown_pct": 5},
        "result": {"results_df": [{"Ticker": "AAA", "P/B Ratio": None}], "final_count": 1},
        "captured_at": "2026-11-04T12:00:00Z",
        "benchmark": "SPY",
    }


@pytest.mark.parametrize(
    "screen", ["Long", "Short", "Quality", "Price Momentum", "Fundamental Momentum", "Digest Presets"]
)
def test_save_reopen_and_delete_survives_job_cache_cleanup(auth_client, screen):
    from api import cache
    from api.job_queue import clear_memory_jobs

    body = snapshot(screen)
    if screen == "Fundamental Momentum":
        body["result"] = {"eps": {"results_df": [{"ticker": "AAA"}]}, "rev": {"results_df": []}}
    if screen == "Digest Presets":
        body["result"] = {"hits": [{"ticker": "AAA"}], "near_misses": [], "week": "2026-W45"}
        body["request"] = {"preset": {"id": "long-liquid-covered", "params": {"min_dollar_volume_industry_pct": 0.75}}}
    response = auth_client.post("/api/screener-runs", json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    run_id = saved["run_id"]

    cache.invalidate_all()
    clear_memory_jobs()
    history = auth_client.get("/api/screener-runs", params={"screen": screen}).json()["runs"]
    assert [row["run_id"] for row in history] == [run_id]
    assert "result" not in history[0]  # Listing doesn't load every result table.
    reopened = auth_client.get(f"/api/screener-runs/{run_id}").json()
    assert reopened == saved
    assert reopened["result"] == body["result"]
    assert reopened["request"] == body["request"]
    assert "snapshot_json" not in reopened

    assert auth_client.delete(f"/api/screener-runs/{run_id}").status_code == 204
    assert auth_client.get(f"/api/screener-runs/{run_id}").status_code == 404
    assert auth_client.get("/api/screener-runs", params={"screen": screen}).json() == {"runs": []}


def test_saved_runs_are_private_to_the_authenticated_actor(auth_client):
    from api.routers.auth import require_actor
    from ontology.policy import Actor

    saved = auth_client.post("/api/screener-runs", json=snapshot()).json()
    run_id = saved["run_id"]
    auth_client.app.dependency_overrides[require_actor] = lambda: Actor(actor_id="other-user", actor_type="human")
    try:
        assert auth_client.get("/api/screener-runs", params={"screen": "Long"}).json() == {"runs": []}
        assert auth_client.get(f"/api/screener-runs/{run_id}").status_code == 404
        assert auth_client.delete(f"/api/screener-runs/{run_id}").status_code == 404
    finally:
        auth_client.app.dependency_overrides.pop(require_actor)
    assert auth_client.get(f"/api/screener-runs/{run_id}").status_code == 200


def test_saved_runs_require_authentication(client):
    assert client.get("/api/screener-runs?screen=Long").status_code == 401
    assert client.post("/api/screener-runs", json=snapshot()).status_code == 401
    assert client.get("/api/screener-runs/unknown").status_code == 401
    assert client.delete("/api/screener-runs/unknown").status_code == 401


def test_saved_runs_validate_names_and_screen_and_paginate(auth_client):
    for patch in ({"name": "  "}, {"name": "x" * 161}, {"screen": "unsupported"}):
        assert auth_client.post("/api/screener-runs", json={**snapshot(), **patch}).status_code == 422
    first = auth_client.post("/api/screener-runs", json=snapshot()).json()
    second = auth_client.post("/api/screener-runs", json={**snapshot(), "name": "Second"}).json()
    auth_client.post("/api/screener-runs", json=snapshot("Quality"))
    page = auth_client.get("/api/screener-runs?screen=Long&limit=1&offset=0").json()["runs"]
    assert [row["run_id"] for row in page] == [second["run_id"]]
    page = auth_client.get("/api/screener-runs?screen=Long&limit=1&offset=1").json()["runs"]
    assert [row["run_id"] for row in page] == [first["run_id"]]
