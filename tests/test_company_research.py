from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from api import company_research as research
from api import company_research_store as run_store
from api import job_queue, llm_settings
from api.routers import company_research as router
from ontology.policy import actor_to_dict, user_actor


@pytest.fixture(autouse=True)
def research_state(tmp_path, monkeypatch):
    job_queue.clear_memory_jobs()
    monkeypatch.setattr(run_store, "SQLITE_PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(research, "LOCAL_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("COMPANY_RESEARCH_MODEL", raising=False)
    yield
    job_queue.clear_memory_jobs()


def request(kind="overview", prompt="Research {ticker}") -> research.CompanyResearchJobRequest:
    return research.CompanyResearchJobRequest(
        ticker="MU",
        kind=kind,
        prompt=prompt,
        prompt_version="v1",
        model="gpt-6.1-sol",
        actor=actor_to_dict(user_actor("researcher", roles=("admin",))),
        requested_at=datetime.now(UTC).isoformat(),
    )


def response(text, *, status="completed", web=False, response_id="response-1", annotations=None):
    output = [{"type": "message", "content": [{"type": "output_text", "text": text, "annotations": annotations or []}]}]
    if web:
        output.append(
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"sources": [{"title": "Issuer filing", "url": "https://example.com/filing"}]},
            }
        )
    return {
        "id": response_id,
        "status": status,
        "output": output,
        "incomplete_details": {"reason": "max_output_tokens"},
    }


def mock_provider(monkeypatch, responses):
    client = MagicMock()
    client.with_options.return_value = client
    client.responses.create.side_effect = responses
    monkeypatch.setattr(research, "get_llm_client", lambda provider: client)
    egress = []

    def prepare(**kwargs):
        egress.append(kwargs)
        return kwargs["stream_kwargs"], {}

    monkeypatch.setattr(research, "prepare_model_egress", prepare)
    return client, egress


def test_settings_are_global_persisted_and_do_not_change_regular_models(auth_client):
    original = auth_client.get("/api/settings/company-research").json()
    assert original["model"] == "gpt-6.1-sol"
    assert "last 20 fiscal quarters" in original["management_quality_prompt"]
    assert llm_settings.get_setting(research.PROMPTS_KEY)["value"] == research.ResearchPrompts().model_dump_json()
    assert original["updated_at"]
    llm_settings.set_llm_provider_setting("anthropic")
    prompts = {
        "overview_prompt": 'Overview {ticker}, literal JSON {"x": 1}',
        "management_quality_prompt": "Operational evidence for {ticker}",
    }
    result = auth_client.put("/api/settings/company-research", json=prompts)
    assert result.status_code == 200
    llm_settings._close_conn()
    loaded = auth_client.get("/api/settings/company-research").json()
    assert loaded["overview_prompt"] == prompts["overview_prompt"]
    assert loaded["management_quality_prompt"] == prompts["management_quality_prompt"]
    assert loaded["updated_at"]
    llm_settings.ensure_setting(research.PROMPTS_KEY, research.ResearchPrompts().model_dump_json())
    assert auth_client.get("/api/settings/company-research").json()["overview_prompt"] == prompts["overview_prompt"]
    assert llm_settings.get_setting(llm_settings.LLM_PROVIDER_KEY)["value"] == "anthropic"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"overview_prompt": "", "management_quality_prompt": "Research {ticker}"},
        {"overview_prompt": "Research {ticker}", "management_quality_prompt": " "},
        {"overview_prompt": "Research MU", "management_quality_prompt": "Research {ticker}"},
    ],
)
def test_prompt_updates_validate_both_templates(auth_client, body):
    assert auth_client.put("/api/settings/company-research", json=body).status_code == 422


def test_research_endpoints_require_authentication(client):
    assert client.get("/api/settings/company-research").status_code == 401
    assert client.get("/api/company-research/MU").status_code == 401
    assert client.post("/api/company-research/MU", json={}).status_code == 401
    assert client.get("/api/company-research/MU/reports/overview").status_code == 401


def test_missing_key_and_invalid_ticker_do_not_dispatch(auth_client, monkeypatch):
    enqueue = MagicMock()
    monkeypatch.setattr(router, "enqueue_registered_job", enqueue)
    monkeypatch.delenv("OPENAI_API_KEY")
    assert auth_client.post("/api/company-research/MU", json={}).status_code == 503
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert auth_client.post("/api/company-research/BAD%24", json={}).status_code == 422
    enqueue.assert_not_called()


def test_next_company_snapshots_saved_prompts_and_actor(auth_client, monkeypatch):
    monkeypatch.setattr("api.async_job_runner._enqueue_local_job", lambda job_id: None)
    prompts = {
        "overview_prompt": 'Research {ticker} and {"literal": "braces"}',
        "management_quality_prompt": "Management at {ticker}",
    }
    auth_client.put("/api/settings/company-research", json=prompts)
    first = auth_client.post("/api/company-research/mu", json={}).json()
    auth_client.put("/api/settings/company-research", json={**prompts, "overview_prompt": "UPDATED {ticker}"})
    second = auth_client.post("/api/company-research/NVDA", json={}).json()
    old = run_store.get_run(first["reports"]["overview"]["run_id"])["snapshot"]
    new = run_store.get_run(second["reports"]["overview"]["run_id"])["snapshot"]
    assert old["prompts"]["overview"] == prompts["overview_prompt"]
    assert new["prompts"]["overview"] == "UPDATED {ticker}"
    assert new["actor"]["actor_type"] == "user"
    assert new["actor"]["actor_id"]
    assert old["ticker"] == "MU" and new["ticker"] == "NVDA"


def test_duplicate_starts_share_one_budget_but_explicit_new_runs_get_new_allowances(auth_client, monkeypatch):
    dispatched = []
    monkeypatch.setattr("api.async_job_runner._enqueue_local_job", dispatched.append)
    first = auth_client.post("/api/company-research/MU", json={}).json()
    again = auth_client.post("/api/company-research/MU", json={}).json()
    assert len(dispatched) == 1
    run_id = first["reports"]["overview"]["run_id"]
    assert again["reports"]["management_quality"]["run_id"] == run_id
    state = run_store.get_run(run_id)
    job_queue.complete_job(state["job_id"], {})
    run_store.mutate_run(run_id, lambda s: s.update(status="done"))
    fresh = auth_client.post("/api/company-research/MU", json={}).json()
    assert len(dispatched) == 2
    assert fresh["reports"]["overview"]["run_id"] != run_id
    status = auth_client.get("/api/company-research/MU").json()
    assert status["reports"]["overview"]["run_id"] == fresh["reports"]["overview"]["run_id"]


def test_dispatch_failure_retains_run_and_safe_resume(auth_client, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private dispatch details")

    monkeypatch.setattr(router, "enqueue_registered_job", fail)
    result = auth_client.post("/api/company-research/MU", json={})
    assert result.status_code == 503
    status = auth_client.get("/api/company-research/MU").json()["reports"]
    assert status["overview"]["status"] == "incomplete"
    assert "private" not in status["overview"]["error"]
    assert status["overview"]["resumable"]
    assert status["overview"]["budget"] == status["management_quality"]["budget"]


def test_resume_keeps_original_snapshot_deadline_and_spend(auth_client, monkeypatch):
    monkeypatch.setattr("api.async_job_runner._enqueue_local_job", lambda job_id: None)
    started = auth_client.post("/api/company-research/MU", json={}).json()
    run_id = started["reports"]["overview"]["run_id"]
    before = run_store.get_run(run_id)
    run_store.mutate_run(run_id, lambda s: s.update(status="incomplete", charged_usd=3.25))
    job_queue.complete_job(before["job_id"], {})
    resumed = auth_client.post("/api/company-research/MU", json={"resume_run_id": run_id})
    assert resumed.status_code == 202
    after = run_store.get_run(run_id)
    assert after["deadline"] == before["deadline"]
    assert after["snapshot"] == before["snapshot"]
    assert after["charged_usd"] == 3.25
    assert after["job_id"] != before["job_id"]
    run_store.mutate_run(run_id, lambda s: s.update(deadline=time.time() - 1))
    assert auth_client.post("/api/company-research/MU", json={"resume_run_id": run_id}).status_code == 409
    assert not auth_client.get("/api/company-research/MU").json()["reports"]["overview"]["resumable"]


def test_explicit_time_continuation_reuses_run_and_budget_without_duplicate_dispatch(auth_client, monkeypatch):
    monkeypatch.setattr("api.async_job_runner._enqueue_local_job", lambda job_id: None)
    started = auth_client.post("/api/company-research/MU", json={}).json()
    run_id = started["reports"]["overview"]["run_id"]
    original = run_store.get_run(run_id)
    job_queue.complete_job(original["job_id"], {})
    run_store.mutate_run(
        run_id,
        lambda s: s.update(
            status="incomplete",
            deadline=time.time() - 1,
            charged_usd=7.5,
            calls={"retained:0": {"reserved_usd": 2, "settled": False, "response_id": "resp_retained"}},
            steps={"plan": {"completed": True, "artifact_key": "retained-plan"}},
        ),
    )
    before = run_store.get_run(run_id)
    status = auth_client.get("/api/company-research/MU").json()["reports"]["overview"]
    assert status["continuable"] and not status["resumable"]
    body = {"resume_run_id": run_id, "extend_time": True}
    assert auth_client.post("/api/company-research/MU", json=body).status_code == 202
    after = run_store.get_run(run_id)
    for field in ("run_id", "created_at", "snapshot", "calls", "steps", "charged_usd", "max_cost_usd"):
        assert after[field] == before[field]
    assert after["deadline"] - after["window_started_at"] == 30 * 60
    assert after["continuation_used"]
    assert after["dispatch_generation"] == before.get("dispatch_generation", 0) + 1
    assert run_store.budget_summary(after)["max_seconds"] == 30 * 60
    assert run_store.budget_summary(after)["reserved_usd"] == 2
    assert auth_client.post("/api/company-research/MU", json=body).status_code == 202
    repeated = run_store.get_run(run_id)
    assert repeated["deadline"] == after["deadline"] and repeated["job_id"] == after["job_id"]
    run_store.mutate_run(run_id, lambda s: s.update(deadline=time.time() - 1, status="incomplete"))
    assert auth_client.post("/api/company-research/MU", json=body).status_code == 409
    assert not auth_client.get("/api/company-research/MU").json()["reports"]["overview"]["continuable"]


@pytest.mark.parametrize("blocked", ["spent", "live_worker", "other_actor"])
def test_time_continuation_cannot_reset_cost_or_take_over_another_worker_or_actor(auth_client, monkeypatch, blocked):
    monkeypatch.setattr("api.async_job_runner._enqueue_local_job", lambda job_id: None)
    started = auth_client.post("/api/company-research/MU", json={}).json()
    run_id = started["reports"]["overview"]["run_id"]

    def stop(state):
        state.update(status="incomplete", deadline=time.time() - 1)
        if blocked == "spent":
            state["charged_usd"] = state["max_cost_usd"]
        elif blocked == "live_worker":
            state["lease_until"] = time.time() + 60
        else:
            state["snapshot"]["actor"]["actor_id"] = "another-user"

    run_store.mutate_run(run_id, stop)
    before = run_store.get_run(run_id)
    result = auth_client.post("/api/company-research/MU", json={"resume_run_id": run_id, "extend_time": True})
    assert result.status_code == (404 if blocked == "other_actor" else 409)
    assert run_store.get_run(run_id) == before


def test_citation_spans_become_clickable_without_losing_facts():
    text = "Revenue grew. [1] Debt declined. [2]"
    annotations = [
        {
            "type": "url_citation",
            "start_index": text.index("[1]"),
            "end_index": text.index("[1]") + 3,
            "title": "Filing",
            "url": "https://example.com/filing",
        },
        {
            "type": "url_citation",
            "start_index": text.index("[2]"),
            "end_index": text.index("[2]") + 3,
            "title": "Release",
            "url": "https://example.com/release",
        },
    ]
    result = research.cited_response_text(response(text, annotations=annotations))
    assert "Revenue grew. [Filing](https://example.com/filing)" in result
    assert "Debt declined. [Release](https://example.com/release)" in result


def test_citation_annotations_covering_claim_text_preserve_the_claim():
    text = "Reported revenue was $10 billion."
    cited = response(
        text,
        annotations=[
            {
                "type": "url_citation",
                "start_index": 0,
                "end_index": len(text),
                "title": "Filing",
                "url": "https://example.com/filing",
            }
        ],
    )
    assert research.cited_response_text(cited) == f"{text} [Filing](https://example.com/filing)"


def test_worker_uses_live_search_archives_report_and_applies_as_requesting_actor(monkeypatch):
    client, egress = mock_provider(
        monkeypatch,
        [
            response("Evidence", web=True, response_id="sources"),
            response("Checked evidence", web=True, response_id="verification"),
            response("# MU research\n\nFull evidence [filing](https://example.com/filing)", response_id="report"),
            response("# MU Overview\n\n## Financials\n- Growth", response_id="formatting"),
        ],
    )
    saves = []

    def save(action, payload, **kwargs):
        saves.append((action, payload, kwargs))
        return {"application_status": "applied", "approval_id": "approval-1"}

    monkeypatch.setattr(research, "stage_api_action", save)
    job_id = str(uuid4())
    result = research.run_company_research_job(request(prompt='Research {ticker} with {"x": 1}'), job_id=job_id)
    calls = client.responses.create.call_args_list
    assert 'Research MU with {"x": 1}' == calls[0].kwargs["input"]
    assert all(call.kwargs["model"] == "gpt-6.1-sol" and call.kwargs["background"] for call in calls)
    assert calls[0].kwargs["tools"][0]["type"] == "web_search"
    assert calls[1].kwargs["previous_response_id"] == "sources"
    assert calls[2].kwargs["max_output_tokens"] == 64_000
    assert all(call.kwargs["reasoning"] == {"effort": "xhigh"} for call in calls[:3])
    assert calls[3].kwargs["reasoning"] == {"effort": "high"}
    assert all(call["actor"].actor_id == "researcher" for call in egress)
    assert saves[0][0] == "save_overview_content"
    assert saves[0][2]["apply"] is True and saves[0][2]["approval_note"]
    assert saves[0][2]["actor"].actor_id == "researcher"
    archived = research.read_research_report("MU", "overview")
    assert archived["content"].startswith("# MU research")
    assert archived["summary_applied"] is True
    assert archived["response_ids"]["formatting"] == "formatting"
    assert result["source_count"] == 1


def test_background_response_is_polled_and_checkpoint_reuses_completed_phases(monkeypatch):
    client, _egress = mock_provider(
        monkeypatch,
        [
            response("", status="queued", response_id="background"),
            response("Verified", web=True, response_id="verification"),
            response("Full report", response_id="report"),
            response("# MU Overview", response_id="format"),
        ],
    )
    client.responses.retrieve.return_value = response("Evidence", web=True, response_id="background")
    monkeypatch.setattr(research.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(research, "stage_api_action", lambda *args, **kwargs: {"application_status": "applied"})
    job_id = str(uuid4())
    research.run_company_research_job(request(), job_id=job_id)
    client.responses.retrieve.assert_called_once_with("background")
    research.run_company_research_job(request(), job_id=job_id)
    assert client.responses.create.call_count == 4


@pytest.mark.parametrize("phase_index", [0, 2, 3])
@pytest.mark.parametrize("failure", ["empty", "incomplete"])
def test_empty_or_truncated_output_is_not_applied_and_finished_report_is_retained(monkeypatch, phase_index, failure):
    responses = [
        response("Evidence", web=True),
        response("Verified", web=True),
        response("Full report"),
        response("Structured summary"),
    ]
    responses[phase_index] = response(
        "" if failure == "empty" else "Partial",
        status="completed" if failure == "empty" else "incomplete",
        web=phase_index < 2,
    )
    mock_provider(monkeypatch, responses)
    save = MagicMock()
    monkeypatch.setattr(research, "stage_api_action", save)
    with pytest.raises(RuntimeError, match="empty|did not complete"):
        research.run_company_research_job(request(), job_id=str(uuid4()))
    save.assert_not_called()
    if phase_index == 3:
        assert research.read_research_report("MU", "overview")["content"].startswith("Full report")
        assert research.archived_report_status("MU", "overview")["status"] == "error"


def test_management_requires_twenty_distinct_quarters_and_keeps_gap_rows():
    text = "\n".join(
        f"| FY{year} Q{quarter} | Insufficient disclosure |" for year in range(2022, 2027) for quarter in range(1, 5)
    )
    research.validate_management_coverage(text, "Evaluate the last 20 fiscal quarters")
    with pytest.raises(RuntimeError, match="20 fiscal quarters"):
        research.validate_management_coverage("| Q1 FY2026 | Insufficient disclosure |", "last 20 fiscal quarters")


def test_management_save_failure_retains_full_report_for_authenticated_retrieval(auth_client, monkeypatch):
    mock_provider(
        monkeypatch,
        [
            response("Evidence", web=True),
            response("Verified", web=True),
            response("Full operational tracker"),
            response("# MU Management Quality"),
        ],
    )
    monkeypatch.setattr(research, "stage_api_action", lambda *args, **kwargs: {"application_status": "failed"})
    job_id = str(uuid4())
    with pytest.raises(RuntimeError, match="was not applied"):
        research.run_company_research_job(request("management_quality"), job_id=job_id)
    report = auth_client.get(f"/api/company-research/MU/reports/management_quality?job_id={job_id}")
    assert report.status_code == 200
    assert "Full operational tracker" in report.json()["content"]
    assert report.json()["summary_applied"] is False
    status = auth_client.get("/api/company-research/MU").json()
    assert status["reports"]["management_quality"]["report_available"] is True
    assert auth_client.get("/api/company-research/MU/reports/overview").status_code == 404
    assert auth_client.get("/api/company-research/MU/reports/overview?job_id=../secret").status_code == 422
