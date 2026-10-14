from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from api import company_research as research
from api import job_queue, llm_settings
from api.routers import company_research as router
from ontology.policy import actor_to_dict, user_actor


@pytest.fixture(autouse=True)
def research_state(tmp_path, monkeypatch):
    job_queue.clear_memory_jobs()
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
    old = job_queue.get_job(first["reports"]["overview"]["job_id"])["payload_json"]
    new = job_queue.get_job(second["reports"]["overview"]["job_id"])["payload_json"]
    assert old["prompt"] == prompts["overview_prompt"]
    assert new["prompt"] == "UPDATED {ticker}"
    assert new["actor"]["actor_type"] == "user"
    assert new["actor"]["actor_id"]
    assert old["ticker"] == "MU" and new["ticker"] == "NVDA"


def test_duplicate_starts_reuse_active_jobs_but_completed_jobs_run_fresh(auth_client, monkeypatch):
    dispatched = []
    monkeypatch.setattr("api.async_job_runner._enqueue_local_job", dispatched.append)
    first = auth_client.post("/api/company-research/MU", json={}).json()
    again = auth_client.post("/api/company-research/MU", json={}).json()
    assert len(dispatched) == 2
    assert first["reports"] == again["reports"]
    for row in first["reports"].values():
        job_queue.complete_job(row["job_id"], {"report_available": True})
    fresh = auth_client.post("/api/company-research/MU", json={}).json()
    assert len(dispatched) == 4
    assert fresh["reports"]["overview"]["job_id"] != first["reports"]["overview"]["job_id"]
    status = auth_client.get("/api/company-research/MU").json()
    assert status["reports"]["overview"]["job_id"] == fresh["reports"]["overview"]["job_id"]


@pytest.mark.parametrize("failed_kind", ["overview", "management_quality"])
def test_dispatch_failure_still_starts_other_report(auth_client, monkeypatch, failed_kind):
    calls = []

    def enqueue(job_type, payload, **kwargs):
        calls.append(payload["kind"])
        if payload["kind"] == failed_kind:
            raise RuntimeError("private dispatch details")
        return job_queue.create_or_reuse_job(job_type, payload=payload, **kwargs)

    monkeypatch.setattr(router, "enqueue_registered_job", enqueue)
    result = auth_client.post("/api/company-research/MU", json={})
    assert result.status_code == 202
    assert calls == ["overview", "management_quality"]
    reports = result.json()["reports"]
    assert reports[failed_kind]["status"] == "error"
    assert "private" not in reports[failed_kind]["error"]
    assert reports["management_quality" if failed_kind == "overview" else "overview"]["status"] == "queued"


@pytest.mark.parametrize("failed_kind", ["overview", "management_quality"])
def test_jobs_run_concurrently_and_partial_success_survives_reload(auth_client, monkeypatch, failed_kind):
    barrier = threading.Barrier(3)
    release = threading.Event()

    def compute(req, *, job_id):
        barrier.wait(timeout=10)
        release.wait(timeout=10)
        if req.kind == failed_kind:
            raise RuntimeError("Source unavailable")
        return {"report_available": True, "application_status": "applied", "kind": req.kind}

    monkeypatch.setattr(research, "run_company_research_job", compute)
    started = auth_client.post("/api/company-research/MU", json={}).json()
    try:
        barrier.wait(timeout=10)
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        rows = [job_queue.get_job(row["job_id"]) for row in started["reports"].values()]
        if all(row["status"] in {"completed", "failed"} for row in rows):
            break
        time.sleep(0.01)
    status = auth_client.get("/api/company-research/MU").json()["reports"]
    assert status[failed_kind]["status"] == "error"
    other = "management_quality" if failed_kind == "overview" else "overview"
    assert status[other]["status"] == "done"
    assert status[other]["report_available"] is True


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
    assert calls[0].kwargs["reasoning"] == {"effort": "xhigh"}
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
