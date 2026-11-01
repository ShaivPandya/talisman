from __future__ import annotations

import pytest
from fastapi.responses import JSONResponse

from api.idea_scan import store
from api.idea_scan.presets import default_settings
from tests.test_idea_lifecycle_history import ideas_store  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _runs_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCAL_ROOT", tmp_path / "runs")


def saved_run(**overrides):
    run = {
        "run_id": "20261024T120000Z-abc123",
        "week": "2026-W43",
        "status": "completed",
        "source": "scheduler",
        "created_at": "2026-10-24T12:00:00+00:00",
        "stats": {"candidates": 1, "reviewed": 1},
        "cost": {"spent_usd": 1.62},
        "candidates": [
            {
                "ticker": "EXP",
                "direction": "short",
                "company": "Expensive Co",
                "presets": [{"id": "short-expensive-deteriorating", "name": "Short · Expensive & deteriorating"}],
                "signals": [{"preset_id": "short-expensive-deteriorating", "label": "Operating Loss"}],
                "agreement_score": 1.9,
                "macro_boost": 0.25,
                "macro_fit": {"sector": "Energy", "score": -1, "confidence": "high", "reason": "oil glut"},
                "review": {
                    "why_now": "Guidance cut.",
                    "headlines": [{"title": "Cut", "url": "https://news.example.com/c", "date": "2026-10-21"}],
                    "missing_inputs": ["Borrow cost"],
                },
                "card_state": "open",
                "idea_id": None,
            }
        ],
        **overrides,
    }
    return store.save_run(run)


def test_list_and_get_runs(auth_client):
    assert auth_client.get("/api/idea-scan/runs").json() == {"runs": []}
    saved_run()
    runs = auth_client.get("/api/idea-scan/runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["20261024T120000Z-abc123"]
    assert runs[0]["spent_usd"] == 1.62
    detail = auth_client.get("/api/idea-scan/runs/20261024T120000Z-abc123").json()
    assert detail["candidates"][0]["ticker"] == "EXP"
    assert auth_client.get("/api/idea-scan/runs/nope").status_code == 404
    assert auth_client.get("/api/idea-scan/runs/..%2Fsecret").status_code == 404


def test_runs_require_auth(client):
    assert client.get("/api/idea-scan/runs").status_code == 401


def test_settings_can_be_edited_without_a_deploy(auth_client):
    body = auth_client.get("/api/idea-scan/settings").json()
    assert body["settings"] == body["defaults"] == default_settings().model_dump()

    edited = body["settings"]
    edited["presets"][0]["params"]["pb_threshold"] = 1.2
    edited["config"]["max_reviews"] = 8
    saved = auth_client.put("/api/idea-scan/settings", json=edited)
    assert saved.status_code == 200
    again = auth_client.get("/api/idea-scan/settings").json()["settings"]
    assert again["presets"][0]["params"]["pb_threshold"] == 1.2
    assert again["config"]["max_reviews"] == 8

    edited["presets"][0]["screen"] = "breakdown"
    assert auth_client.put("/api/idea-scan/settings", json=edited).status_code == 422

    reset = auth_client.post("/api/idea-scan/settings/reset").json()["settings"]
    assert reset == default_settings().model_dump()


def test_dismiss_card(auth_client):
    saved_run()
    response = auth_client.post("/api/idea-scan/runs/20261024T120000Z-abc123/candidates/short/exp/dismiss")
    assert response.status_code == 200
    assert response.json()["candidate"]["card_state"] == "dismissed"
    assert store.get_run("20261024T120000Z-abc123")["candidates"][0]["card_state"] == "dismissed"
    assert (
        auth_client.post("/api/idea-scan/runs/20261024T120000Z-abc123/candidates/long/EXP/dismiss").status_code == 404
    )


def test_promote_card_creates_one_idea(auth_client, monkeypatch):
    created = []

    def fake_create(body):
        created.append(body)
        return {"idea": {"id": "investment_idea:exp-1", "ticker": body.ticker}, "documents": {}}

    monkeypatch.setattr("api.routers.ideas.create_idea", fake_create)
    saved_run()
    url = "/api/idea-scan/runs/20261024T120000Z-abc123/candidates/short/EXP/promote"
    first = auth_client.post(url).json()
    assert first == {
        "candidate": {**first["candidate"], "card_state": "promoted"},
        "idea_id": "investment_idea:exp-1",
        "created": True,
    }
    body = created[0]
    assert body.ticker == "EXP" and body.analyzer_direction == "short" and body.status == "watching"
    assert body.tags == ["Short · Expensive & deteriorating"]
    assert "Why now: Guidance cut." in body.user_notes
    assert "[Cut](https://news.example.com/c)" in body.user_notes
    assert "Macro fit: Energy -1 (high)" in body.user_notes

    second = auth_client.post(url).json()
    assert second["created"] is False and second["idea_id"] == "investment_idea:exp-1"
    assert len(created) == 1


def test_manual_run_enqueues_the_job(auth_client, monkeypatch):
    calls = []

    def fake_enqueue(job_type, payload, **kwargs):
        calls.append((job_type, payload, kwargs))
        return {"job_id": "job-1", "status": "queued"}, "created"

    monkeypatch.setattr("api.routers.idea_scan.enqueue_registered_job", fake_enqueue)
    monkeypatch.setattr(
        "api.routers.idea_scan.enqueue_response",
        lambda row, path: JSONResponse(
            {"job_id": row["job_id"], "poll": path.format(job_id=row["job_id"])}, status_code=202
        ),
    )
    response = auth_client.post("/api/idea-scan/runs", json={"tickers": ["AAPL"], "max_reviews": 1})
    assert response.status_code == 202
    assert response.json()["poll"] == "/api/idea-scan/jobs/job-1"
    job_type, payload, kwargs = calls[0]
    assert job_type == "weekly_idea_scan"
    assert payload["source"] == "manual" and payload["tickers"] == ["AAPL"] and payload["max_reviews"] == 1
    assert kwargs["reuse_completed"] is False and kwargs["cache_key"].startswith("idea_scan:manual:v2:")
    assert auth_client.post("/api/idea-scan/runs", json={"source": "scheduler"}).status_code == 422


def test_scheduler_endpoint_needs_the_secret(client, monkeypatch):
    calls = []
    monkeypatch.setenv("SCHEDULER_SECRET", "s3cret")
    monkeypatch.setattr(
        "api.routers.admin_jobs.enqueue_registered_job",
        lambda job_type, payload, **kw: (
            calls.append((job_type, payload, kw)) or ({"job_id": "j", "status": "queued"}, "created")
        ),
    )
    monkeypatch.setattr(
        "api.routers.admin_jobs.enqueue_response", lambda row, path: JSONResponse({"ok": True}, status_code=202)
    )
    assert client.post("/api/admin/jobs/enqueue-weekly-idea-scan").status_code in {401, 403}
    response = client.post("/api/admin/jobs/enqueue-weekly-idea-scan", headers={"X-Scheduler-Secret": "s3cret"})
    assert response.status_code == 202
    assert calls == [
        (
            "weekly_idea_scan",
            {"source": "scheduler"},
            {"cache_key": "maintenance:weekly_idea_scan:v2", "reuse_completed": False},
        )
    ]


def test_promote_card_through_the_real_idea_create(auth_client, ideas_store):  # noqa: F811 - imported fixture
    saved_run()
    out = auth_client.post("/api/idea-scan/runs/20261024T120000Z-abc123/candidates/short/EXP/promote")
    assert out.status_code == 200, out.text
    idea_id = out.json()["idea_id"]
    assert idea_id.startswith("investment_idea:")
    stored = ideas_store.get_object(idea_id)
    assert stored is not None
    props = stored.get("properties") or stored
    assert props["ticker"] == "EXP"
    assert props["tags"] == ["Short · Expensive & deteriorating"]
    assert props["metadata"]["analyzer_direction"] == "short"
    assert "Why now: Guidance cut." in props["user_notes"]
    assert store.get_run("20261024T120000Z-abc123")["candidates"][0]["idea_id"] == idea_id


def test_screen_runs_a_preset_on_the_latest_saved_frame(auth_client):
    from tests.test_idea_scan_screening import liquidity_rows, make_frame

    preset = next(p for p in default_settings().model_dump()["presets"] if p["id"] == "long-liquid-covered")
    assert auth_client.post("/api/idea-scan/screen", json={"preset": preset}).status_code == 409

    saved_run(data={"fetched_at": "2026-10-24T00:00:00+00:00"})
    store.save_frame("20261024T120000Z-abc123", make_frame(liquidity_rows()))
    body = auth_client.post("/api/idea-scan/screen", json={"preset": preset}).json()
    assert body["week"] == "2026-W43" and body["evaluated"] == 12
    assert {h["ticker"] for h in body["hits"]} == {"S7", "S8", "S9", "TINY1"}
    hit = next(h for h in body["hits"] if h["ticker"] == "S9")
    assert hit["industry"] == "Semiconductors" and hit["dollar_volume"] == 1e8 and hit["analyst_count"] == 9
    assert "S6" in {m["ticker"] for m in body["near_misses"]}

    # The filter on another preset, sent as edited in the Screeners tab.
    other = next(p for p in default_settings().model_dump()["presets"] if p["id"] == "long-momentum-quality")
    other.update(params={"min_composite_pct": 0.0}, liquidity_coverage={"min_dollar_volume_industry_pct": 0.75})
    body = auth_client.post("/api/idea-scan/screen", json={"preset": other}).json()
    assert {h["ticker"] for h in body["hits"]} == {"S7", "S8", "S9", "TINY1"}


def test_screen_rejects_legacy_frames_without_rewriting_the_run(auth_client):
    from tests.test_idea_scan_screening import make_frame

    saved_run()
    frame = make_frame({"AAA": {}})
    frame.attrs.clear()
    store.save_frame("20261024T120000Z-abc123", frame)
    preset = default_settings().presets[0].model_dump()
    response = auth_client.post("/api/idea-scan/screen", json={"preset": preset})
    assert response.status_code == 409
    assert "Run a new idea scan" in response.json()["detail"]
    assert auth_client.get("/api/idea-scan/runs/20261024T120000Z-abc123").status_code == 200
