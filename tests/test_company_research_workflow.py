from __future__ import annotations

import calendar
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from api import company_research as legacy
from api import company_research_provider as provider
from api import company_research_store as store
from api import company_research_workflow as workflow
from api.company_research_context import ContextEvidence, ReadChoice, ReadSelection
from api.company_research_evidence import (
    CheckedCommitments,
    CheckedFacts,
    Commitment,
    EvidenceDecisions,
    Fact,
    OverviewPacket,
    Quarter,
    QuarterPacket,
    QuarterReview,
    ReportReview,
    ResearchPlan,
    Section,
    Source,
    Topic,
    WrittenSections,
    apply_decisions,
    merge_quarter_repair,
    prune_quarter_sources,
    render_tracker,
    validate_plan,
    validate_quarters,
    validate_reconciliation,
)
from ontology.policy import actor_to_dict, user_actor

AS_OF = date(2026, 10, 17)
URL = "https://issuer.example/filing"


def source(day=date(2021, 4, 30)):
    return Source(
        url=URL,
        title="Issuer filing",
        published_on=day,
        passage="The facility will open next year.",
        location="Operations, page 12",
    )


def plan():
    quarters = []
    for year in range(2021, 2026):
        for q in range(1, 5):
            ended = date(year, 3 * q, calendar.monthrange(year, 3 * q)[1])
            quarters.append(
                Quarter(
                    label=f"FY{year} Q{q}",
                    ended_on=ended,
                    reported_on=ended + timedelta(days=30),
                    source=source(ended + timedelta(days=30)),
                )
            )
    return ResearchPlan(
        issuer="Example issuer",
        fiscal_calendar="December year end",
        quarters=quarters,
        overview_topics=[
            Topic(key="business", title="Business", requirements="Business and revenue", sections=["Business"])
        ],
        management_sections=["Operational execution summary"],
    )


def commitment(label="FY2021 Q1"):
    values = {field: "Insufficient disclosure" for field in Commitment.model_fields}
    values.update(
        record_id=label,
        quarter=label,
        initiative="Facility",
        claim="Open facility",
        original_target="Next year",
        outcome="Not yet measurable",
        claim_sources=[source()],
        outcome_sources=[],
    )
    return Commitment.model_validate(values)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SQLITE_PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(legacy, "LOCAL_REPORTS_DIR", tmp_path / "reports")


def create_run(*, apply=False):
    snapshot = {
        "ticker": "EL",
        "kinds": ["overview", "management_quality"],
        "model": "gpt-6.1-sol",
        "prompts": {"overview": "Overview {ticker}", "management_quality": "Last 20 quarters {ticker}"},
        "actor": actor_to_dict(user_actor("researcher", roles=("admin",))),
        "prompt_version": "v1",
        "requested_at": AS_OF.isoformat(),
    }
    return store.create_run(snapshot, apply=apply)[0]


def claimed():
    state = create_run()
    assert store.claim_run(state["run_id"], "worker")
    return state["run_id"]


def test_atomic_reservations_never_oversubscribe_and_unknown_cost_is_retained():
    run_id = claimed()

    def reserve(index):
        try:
            store.reserve_call(run_id, "worker", str(index), 10, gathering=False, details={})
            return True
        except store.ResearchLimitReached:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 2
    state = store.get_run(run_id)
    assert store.reserved_usd(state) == 20
    for call_id in state["calls"]:
        store.settle_call(run_id, "worker", call_id, actual_usd=None, usage={}, status="unknown")
        store.settle_call(run_id, "worker", call_id, actual_usd=0, usage={}, status="completed")
    assert store.get_run(run_id)["charged_usd"] == 20
    with pytest.raises(store.ResearchLimitReached):
        store.reserve_call(run_id, "worker", "over", 5.01, gathering=False, details={})


def test_finishing_reserves_and_deadline_survive_resume():
    run_id = claimed()
    original = store.get_run(run_id)
    with pytest.raises(store.ResearchLimitReached):
        store.reserve_call(run_id, "worker", "sources", 18.01, gathering=True, details={})
    store.mutate_run(run_id, lambda s: s.update(status="incomplete", lease_until=0, charged_usd=2))
    resumed = store.resume_run(run_id)
    assert resumed["deadline"] == original["deadline"] and resumed["charged_usd"] == 2
    assert store.claim_run(run_id, "replacement")
    with pytest.raises(store.ResearchLeaseLost):
        store.check_run(run_id, "worker")
    store.mutate_run(run_id, lambda s: s.update(deadline=time.time() + 300))
    with pytest.raises(store.ResearchLimitReached):
        store.check_run(run_id, "replacement", gathering=True)
    store.check_run(run_id, "replacement")


def age_run(run_id, *, elapsed, allowance):
    now = time.time()
    store.mutate_run(run_id, lambda s: s.update(created_at=now - elapsed, deadline=now - elapsed + allowance))


def test_new_run_gets_eighty_minutes_with_fifteen_held_back_for_finishing():
    run_id = claimed()
    state = store.get_run(run_id)
    assert state["deadline"] - state["created_at"] == pytest.approx(80 * 60, abs=1)
    assert state["deadline"] - state["created_at"] - store.FINISH_RESERVE_S == pytest.approx(65 * 60, abs=1)
    assert store.budget_summary(state)["max_seconds"] == 80 * 60
    age_run(run_id, elapsed=65 * 60 - 5, allowance=80 * 60)
    store.check_run(run_id, "worker", gathering=True)
    age_run(run_id, elapsed=65 * 60 + 5, allowance=80 * 60)
    with pytest.raises(store.ResearchLimitReached, match="Source gathering"):
        store.check_run(run_id, "worker", gathering=True)
    store.check_run(run_id, "worker")
    age_run(run_id, elapsed=80 * 60 + 5, allowance=80 * 60)
    with pytest.raises(store.ResearchLimitReached, match="80-minute research limit"):
        store.check_run(run_id, "worker")


def test_run_created_under_the_old_allowance_keeps_its_55_minute_deadline():
    run_id = claimed()
    age_run(run_id, elapsed=10 * 60, allowance=55 * 60)
    original = store.get_run(run_id)
    assert store.budget_summary(original)["max_seconds"] == 55 * 60
    store.mutate_run(run_id, lambda s: s.update(status="incomplete", lease_until=0))
    assert store.resume_run(run_id)["deadline"] == original["deadline"]
    assert store.claim_run(run_id, "replacement")
    age_run(run_id, elapsed=55 * 60 + 5, allowance=55 * 60)
    with pytest.raises(store.ResearchLimitReached, match="55-minute research limit"):
        store.check_run(run_id, "replacement")
    with pytest.raises(store.ResearchLimitReached):
        store.resume_run(run_id)


@pytest.mark.parametrize("minutes", [80, 55])
def test_limit_reached_status_names_the_runs_own_allowance(minutes):
    from api.routers.company_research import _report_status

    run_id = claimed()
    age_run(run_id, elapsed=minutes * 60 + 5, allowance=minutes * 60)
    status = _report_status(store.get_run(run_id), "overview")
    assert status["status"] == "incomplete"
    assert status["error"] == f"Research reached its {minutes}-minute limit; completed evidence is retained."
    assert status["budget"]["max_seconds"] == minutes * 60


@pytest.mark.parametrize("expired", [False, True])
def test_finished_failure_is_not_replaced_by_later_deadline_expiry(expired):
    from api.routers.company_research import _report_status

    run_id = claimed()
    age_run(run_id, elapsed=(90 if expired else 30) * 60, allowance=80 * 60)
    original = store.get_run(run_id)
    error = "Source passages could not be independently supported: citation location was inaccurate."

    def fail(state):
        state.update(status="incomplete", finished_at=state["created_at"] + 1674, lease_until=0)
        state["reports"]["overview"].update(status="incomplete", error=error)
        state["reports"]["management_quality"].update(status="done", error=None)

    state = store.mutate_run(run_id, fail)
    status = _report_status(state, "overview", original["snapshot"]["actor"]["actor_id"])
    assert status["status"] == "incomplete"
    assert status["error"] == error
    assert status["resumable"] is (not expired)
    assert status["budget"]["elapsed_seconds"] == 1674
    assert _report_status(state, "management_quality")["error"] is None
    assert _report_status(state, "management_quality")["status"] == "done"


def test_fiscal_coverage_requires_consecutive_quarters_and_chronology():
    p = plan()
    validate_plan(p, as_of=AS_OF, overview=True, management=True)
    p.quarters[-1] = p.quarters[0]
    with pytest.raises(ValueError, match="consecutive"):
        validate_plan(p, as_of=AS_OF, overview=True, management=True)


def test_equivalent_fiscal_labels_and_descriptive_topic_keys_are_supported():
    quarter = plan().quarters[0].model_dump(mode="json")
    quarter["label"] = "Q1 FY2021"
    assert Quarter.model_validate(quarter).label == "FY2021 Q1"
    p = plan()
    p.overview_topics[0].key = "financial_resilience_exposures_catalysts_risks"
    validate_plan(p, as_of=AS_OF, overview=True, management=True)
    p = plan()
    p.quarters[-1].reported_on = AS_OF + timedelta(days=1)
    with pytest.raises(ValueError, match="dates"):
        validate_plan(p, as_of=AS_OF, overview=True, management=True)


def test_reconciliation_cannot_erase_promises_or_rewrite_targets():
    original = commitment()
    changed = original.model_copy(update={"original_target": "Two years later"})
    with pytest.raises(ValueError, match="preserve"):
        validate_reconciliation([original], CheckedCommitments(records=[changed], rejected=[]), as_of=AS_OF)
    with pytest.raises(ValueError, match="every"):
        validate_reconciliation([original], CheckedCommitments(records=[], rejected=[]), as_of=AS_OF)
    changed = original.model_copy(update={"outcome": "Achieved on time", "outcome_sources": [source(date(2020, 1, 1))]})
    with pytest.raises(ValueError, match="no earlier"):
        validate_reconciliation([original], CheckedCommitments(records=[changed], rejected=[]), as_of=AS_OF)


def test_missing_disclosure_rows_keep_sixteen_columns():
    quarter = QuarterReview(
        quarter="FY2021 Q1",
        coverage="source_unavailable",
        search_attempts=["Searched issuer and SEC archives"],
        sources=[],
        gap="Transcript unavailable",
        records=[],
    )
    validate_quarters(QuarterPacket(quarters=[quarter]), [quarter.quarter], as_of=AS_OF)
    table = render_tracker([quarter], [])
    assert "Transcript unavailable" in table
    assert all(len(line.split("|")) == 18 for line in table.splitlines() if line.startswith("|"))
    quarter.gap = None
    with pytest.raises(ValueError, match="explicit gap"):
        validate_quarters(QuarterPacket(quarters=[quarter]), [quarter.quarter], as_of=AS_OF)


def response(data, *, status="completed", web=True):
    return {
        "id": "resp_1",
        "status": status,
        "usage": {"input_tokens": 1000, "output_tokens": 500},
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(data)}]}]
        + ([{"type": "web_search_call", "action": {"sources": [{"url": URL}]}}] if web else []),
    }


def mock_client(monkeypatch, values):
    client = MagicMock()
    client.with_options.return_value = client
    client.responses.create.side_effect = values
    monkeypatch.setattr(provider, "get_llm_client", lambda _: client)
    monkeypatch.setattr(provider, "prepare_model_egress", lambda **kw: (kw["stream_kwargs"], {}))
    return client


def earnings_plan():
    result = plan()
    for quarter in result.quarters:
        quarter.source = quarter.source.model_copy(
            update={
                "url": "https://investor.cdw.com/news/news-details/"
                + quarter.label.replace(" ", "-")
                + "/earnings/default.aspx",
                "passage": f"Results for {quarter.label}, reported on {quarter.reported_on}.",
            }
        )
    return result


def check_sources_response(kwargs):
    assert kwargs["text"]["format"]["name"] == "SourceChecks"
    # Retried checks append validation feedback after the original source JSON.
    passages, _ = json.JSONDecoder().raw_decode(kwargs["input"].split("Sources:\n")[1])
    urls = sorted({p["url"] for p in passages})
    assert len(urls) <= provider.SOURCE_CHECK_BATCH_SIZE
    assert kwargs["max_tool_calls"] == 2 * len(urls)
    checked = response(
        {"checks": [{"url": url, "supported": True, "explanation": "Retrieved dated release."} for url in urls]}
    )
    checked["output"][-1]["action"]["sources"] = [{"url": url} for url in urls]
    return checked


@pytest.mark.parametrize("unobserved_count", [9, 20])
def test_twenty_quarter_plan_checks_all_unobserved_urls_in_bounded_batches(monkeypatch, unobserved_count):
    proposed = earnings_plan()
    initial = response(proposed.model_dump(mode="json"))
    initial["output"][-1]["action"]["sources"] = [
        {"url": "https://investor.cdw.com/financials/quarterly-results"},
        *[{"url": q.source.url} for q in proposed.quarters[unobserved_count:]],
    ]
    checked_urls = []

    def respond(**kwargs):
        if kwargs["text"]["format"]["name"] == "ResearchPlan":
            assert kwargs["max_tool_calls"] == 6
            return initial
        checked = check_sources_response(kwargs)
        checked_urls.extend(s["url"] for s in checked["output"][-1]["action"]["sources"])
        return checked

    client = mock_client(monkeypatch, respond)
    instance = workflow.Workflow(claimed(), "worker")
    accepted = instance.provider.request(
        "plan", ResearchPlan, web=True, gathering=True, tool_calls=6, prompt="Plan", instructions="Use sources"
    )
    assert accepted == proposed
    assert len(accepted.quarters) == 20
    assert set(checked_urls) == {q.source.url for q in proposed.quarters[:unobserved_count]}
    assert len(checked_urls) == unobserved_count
    assert client.responses.create.call_count == 1 + (unobserved_count + 5) // 6
    assert instance.provider.load("plan", ResearchPlan) == accepted
    assert all(call["settled"] for call in store.get_run(instance.run_id)["calls"].values())


def test_resume_old_plan_and_interrupted_checks_reuses_plan_and_successful_batches(monkeypatch):
    proposed = earnings_plan()
    initial = response(proposed.model_dump(mode="json"))
    client = mock_client(monkeypatch, lambda **kwargs: check_sources_response(kwargs))
    client.responses.retrieve.return_value = initial
    run_id = claimed()
    # An old run stopped at the former eight-URL ceiling after receiving a plan.
    store.reserve_call(
        run_id,
        "worker",
        "plan:0",
        1,
        gathering=True,
        details={"response_id": initial["id"], "error": "Source URLs not observed: old eight-URL ceiling"},
    )
    store.settle_call(run_id, "worker", "plan:0", actual_usd=0.1, usage={}, status="completed")
    deadline = store.get_run(run_id)["deadline"]
    original = provider.ResearchProvider.request
    check_calls = 0

    def interrupted(self, step, *args, **kwargs):
        nonlocal check_calls
        if "/source-check/" in step:
            check_calls += 1
            if check_calls == 2:
                raise store.ResearchLeaseLost("Worker stopped between source batches")
        return original(self, step, *args, **kwargs)

    monkeypatch.setattr(provider.ResearchProvider, "request", interrupted)
    with pytest.raises(store.ResearchLeaseLost):
        workflow.Workflow(run_id, "worker").plan()
    assert client.responses.create.call_count == 1
    assert not provider.ResearchProvider(run_id, "worker").load("plan", ResearchPlan)
    first_charge = store.get_run(run_id)["charged_usd"]
    monkeypatch.setattr(provider.ResearchProvider, "request", original)
    assert workflow.Workflow(run_id, "worker").plan() == proposed
    assert client.responses.create.call_count == 4
    requests = [c.kwargs["input"] for c in client.responses.create.call_args_list]
    assert len(set(requests)) == 4
    state = store.get_run(run_id)
    assert state["deadline"] == deadline
    assert state["calls"]["plan:0"]["charged_usd"] == 0.1
    assert state["charged_usd"] > first_charge


@pytest.mark.parametrize("limit", ["time", "spending"])
def test_source_batches_stop_at_original_run_limits(monkeypatch, limit):
    proposed = earnings_plan()
    run_id = claimed()

    def respond(**kwargs):
        if kwargs["text"]["format"]["name"] == "ResearchPlan":
            return response(proposed.model_dump(mode="json"))
        checked = check_sources_response(kwargs)
        if limit == "time":
            store.mutate_run(run_id, lambda s: s.update(deadline=time.time() + store.FINISH_RESERVE_S - 1))
        else:
            store.mutate_run(run_id, lambda s: s.update(max_cost_usd=store.FINISH_RESERVE_USD + 1))
        return checked

    client = mock_client(monkeypatch, respond)
    with pytest.raises(store.ResearchLimitReached):
        workflow.Workflow(run_id, "worker").plan()
    assert client.responses.create.call_count == 2
    assert not provider.ResearchProvider(run_id, "worker").load("plan", ResearchPlan)
    assert all(call["settled"] for call in store.get_run(run_id)["calls"].values())


@pytest.mark.parametrize("failure", ["unobserved", "unsupported"])
def test_failed_later_source_batch_never_accepts_plan(monkeypatch, failure):
    proposed = earnings_plan()
    first_batch = {q.source.url for q in proposed.quarters[: provider.SOURCE_CHECK_BATCH_SIZE]}

    def respond(**kwargs):
        if kwargs["text"]["format"]["name"] == "ResearchPlan":
            return response(proposed.model_dump(mode="json"))
        checked = check_sources_response(kwargs)
        observed = checked["output"][-1]["action"]["sources"]
        if {s["url"] for s in observed} != first_batch:
            if failure == "unobserved":
                observed.pop()
            else:
                text = checked["output"][0]["content"][0]
                data = json.loads(text["text"])
                data["checks"][-1].update(supported=False, explanation="This release does not support the date.")
                text["text"] = json.dumps(data)
        return checked

    mock_client(monkeypatch, respond)
    instance = provider.ResearchProvider(claimed(), "worker")
    with pytest.raises(provider.ResearchValidationFailed, match="not observed|could not be independently supported"):
        instance.request(
            "plan",
            ResearchPlan,
            prompt="Plan 20 quarters",
            instructions="Use primary sources",
            web=True,
            gathering=True,
            tool_calls=6,
            attempts=1,
        )
    assert instance.load("plan", ResearchPlan) is None
    # The first batch is reusable even though no partial plan is accepted.
    checkpoints = store.get_run(instance.run_id)["steps"]
    assert any("/source-check/" in step and saved["completed"] for step, saved in checkpoints.items())


def test_source_failure_status_is_concise_and_full_url_diagnostics_are_retained(monkeypatch):
    urls = [q.source.url for q in earnings_plan().quarters]
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": u}) for u in urls])
    mock_client(monkeypatch, [response(packet.model_dump(mode="json"))])
    instance = provider.ResearchProvider(claimed(), "worker")
    with pytest.raises(provider.ResearchValidationFailed) as error:
        instance.request(
            "plan/source-check/example",
            OverviewPacket,
            prompt="Check",
            instructions="Check",
            web=True,
            resolve_unobserved=False,
            attempts=1,
        )
    status = workflow._error(error.value)
    assert "20 cited URL(s)" in status
    assert "https" not in status and len(status) < 600
    detail = legacy._read_json(instance.artifact_key("plan/source-check/example", "validation-0"))["error"]
    assert all(url in detail for url in urls)
    assert len(detail) > 1200


def test_provider_checkpoint_avoids_rebilling_completed_work(monkeypatch):
    client = mock_client(monkeypatch, [response({"supported": True, "issues": []})])
    run_id = claimed()
    first = provider.ResearchProvider(run_id, "worker")
    args = dict(prompt="Check", instructions="Check", web=True)
    first.request("audit", ReportReview, **args)
    cost = store.get_run(run_id)["charged_usd"]
    provider.ResearchProvider(run_id, "worker").request("audit", ReportReview, **args)
    assert client.responses.create.call_count == 1
    assert store.get_run(run_id)["charged_usd"] == cost > 0
    assert client.with_options.call_args.kwargs["max_retries"] == 0


@pytest.mark.parametrize("legacy_checkpoint", [False, True])
def test_private_checkpoint_replays_unfiltered_evidence_without_provider_calls(monkeypatch, legacy_checkpoint):
    packet = OverviewPacket(
        facts=[Fact(record_id="upload", section="Business", claim="Makes products", sources=[source()])],
        gaps=[],
        searched_sources=[],
    )
    client = mock_client(monkeypatch, [response(packet.model_dump(mode="json"), web=False)])
    run_id = claimed()
    instance = provider.ResearchProvider(run_id, "worker")
    args = dict(prompt="Extract", instructions="Extract", private=True, replay_private_evidence=True)

    def old_filter(value):
        value.facts = []
        value.gaps = ["Old validator excluded a supported quote"]

    first = instance.request("private/evidence", OverviewPacket, validate=old_filter, **args)
    assert not first.facts
    cost = store.get_run(run_id)["charged_usd"]
    key = instance.artifact_key("private/evidence")
    if legacy_checkpoint:
        artifact = legacy._read_json(key)
        artifact.pop("raw_data")
        legacy._write_json(key, artifact)
    client.responses.create.reset_mock()
    replayed = provider.ResearchProvider(run_id, "worker").request("private/evidence", OverviewPacket, **args)
    assert replayed == packet
    assert legacy._read_json(key)["data"] == packet.model_dump(mode="json")
    assert store.get_run(run_id)["charged_usd"] == cost
    client.responses.create.assert_not_called()
    client.responses.retrieve.assert_not_called()


def test_raw_private_replay_cannot_bypass_public_source_checks(monkeypatch):
    client = mock_client(monkeypatch, [])
    with pytest.raises(ValueError, match="restricted to private"):
        provider.ResearchProvider(claimed(), "worker").request(
            "public/evidence",
            OverviewPacket,
            prompt="Extract",
            instructions="Extract",
            web=True,
            replay_private_evidence=True,
        )
    client.responses.create.assert_not_called()


@pytest.mark.parametrize("resumed", [False, True])
def test_background_and_resumed_responses_keep_search_result_trace(monkeypatch, resumed):
    proposed = earnings_plan()
    queued = {"id": "resp_background", "status": "queued"}
    completed = response(proposed.model_dump(mode="json"))
    completed["id"] = queued["id"]
    completed["output"][-1]["action"]["sources"] = [{"url": q.source.url} for q in proposed.quarters]
    client = mock_client(monkeypatch, [queued])

    def retrieve(response_id, **kwargs):
        assert response_id == queued["id"]
        assert kwargs["include"] == ["web_search_call.action.sources"]
        return completed

    client.responses.retrieve.side_effect = retrieve
    monkeypatch.setattr(provider.time, "sleep", lambda _: None)
    run_id = claimed()
    if resumed:
        store.reserve_call(run_id, "worker", "plan:0", 1, gathering=True, details={"response_id": queued["id"]})
    assert (
        provider.ResearchProvider(run_id, "worker").request(
            "plan", ResearchPlan, web=True, gathering=True, tool_calls=6, prompt="Plan", instructions="Use sources"
        )
        == proposed
    )
    assert client.responses.create.call_count == (0 if resumed else 1)
    assert client.responses.retrieve.call_count == 1


def test_all_bad_source_batches_reach_the_single_repair(monkeypatch):
    proposed = earnings_plan()
    repaired = proposed.model_copy(deep=True)
    failed_urls = {proposed.quarters[0].source.url, proposed.quarters[-1].source.url}
    for quarter in repaired.quarters:
        if quarter.source.url in failed_urls:
            quarter.source.url += "?corrected=1"
    plan_calls = 0
    checked_urls = set()

    def respond(**kwargs):
        nonlocal plan_calls
        if kwargs["text"]["format"]["name"] == "ResearchPlan":
            plan_calls += 1
            if plan_calls == 1:
                result = response(proposed.model_dump(mode="json"))
                result["output"][-1]["action"]["sources"] = [{"url": q.source.url} for q in proposed.quarters]
                return result
            assert checked_urls == {q.source.url for q in proposed.quarters}
            feedback = kwargs["input"].split("Retained evidence:")[0]
            assert all(url in feedback for url in failed_urls)
            result = response(repaired.model_dump(mode="json"))
            result["output"][-1]["action"]["sources"] = [{"url": q.source.url} for q in repaired.quarters]
            return result
        result = check_sources_response(kwargs)
        content = result["output"][0]["content"][0]
        data = json.loads(content["text"])
        for check in data["checks"]:
            checked_urls.add(check["url"])
            if check["url"] in failed_urls:
                check.update(supported=False, explanation="Archive has no dated entries. " + "detail " * 180)
        content["text"] = json.dumps(data)
        return result

    client = mock_client(monkeypatch, respond)
    assert workflow.Workflow(claimed(), "worker").plan() == repaired
    assert plan_calls == 2
    assert client.responses.create.call_count == 8


def test_resume_can_revalidate_saved_response_after_parser_fix_without_another_call(monkeypatch):
    client = mock_client(monkeypatch, [])
    client.responses.retrieve.return_value = response({"supported": True, "issues": []})
    run_id = claimed()
    store.reserve_call(
        run_id,
        "worker",
        "audit:0",
        1,
        gathering=False,
        details={"response_id": "resp_1", "error": "Old parser rejected equivalent labels"},
    )
    store.settle_call(run_id, "worker", "audit:0", actual_usd=0.1, usage={}, status="completed")
    result = provider.ResearchProvider(run_id, "worker").request(
        "audit", ReportReview, prompt="Check", instructions="Check", web=True
    )
    assert result.supported
    client.responses.create.assert_not_called()
    assert store.get_run(run_id)["charged_usd"] == 0.1


def test_truncated_response_is_retained_and_not_accepted(monkeypatch):
    client = mock_client(monkeypatch, [response({}, status="incomplete")])
    run_id = claimed()
    instance = provider.ResearchProvider(run_id, "worker")
    for _ in range(2):
        with pytest.raises(provider.ResearchTruncated):
            instance.request("sources", ReportReview, prompt="Research", instructions="Research", web=True)
    assert client.responses.create.call_count == 1
    assert legacy._read_json(instance.artifact_key("sources", "attempt-0"))["status"] == "incomplete"
    assert store.get_run(run_id)["charged_usd"] > 0


def test_provider_rejects_unobserved_sources(monkeypatch):
    packet = OverviewPacket(
        facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": "https://invented.example/"})]
    )
    mock_client(monkeypatch, [response(packet.model_dump(mode="json"))] * 2)
    run_id = claimed()
    with pytest.raises(RuntimeError, match="not observed"):
        provider.ResearchProvider(run_id, "worker").request(
            "sources", OverviewPacket, prompt="Research", instructions="Research", web=True, resolve_unobserved=False
        )


def test_tracking_parameters_do_not_change_source_identity_but_document_ids_do():
    assert provider._canonical(URL + "?utm_source=openai#page=4") == provider._canonical(URL)
    assert provider._canonical(URL + "?id=1&utm_source=openai") != provider._canonical(URL + "?id=2")


def test_escaped_document_filenames_match_without_merging_encoded_path_separators():
    assert provider._canonical(URL + "/CDW (signed).pdf") == provider._canonical(URL + "/CDW%20%28signed%29.pdf")
    assert provider._canonical(URL + "/report%2fone") != provider._canonical(URL + "/report/one")
    assert provider._canonical(URL + "/report%2fone") == provider._canonical(URL + "/report%2Fone")
    assert provider._canonical(URL + "/report%3Fid=1") != provider._canonical(URL + "/report?id=1")


def test_observed_escaped_pdf_does_not_trigger_another_search(monkeypatch):
    document_url = URL + "/Contract%20-%20(signed).pdf"
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": document_url})])
    research = response(packet.model_dump(mode="json"))
    research["output"][-1]["action"] = {"type": "open_page", "url": document_url.replace("(signed)", "%28signed%29")}
    client = mock_client(monkeypatch, [research])
    result = provider.ResearchProvider(claimed(), "worker").request(
        "sources", OverviewPacket, prompt="Research", instructions="Research", web=True
    )
    assert result == packet
    assert client.responses.create.call_count == 1


def test_negative_source_check_repairs_retained_evidence_instead_of_rechecking_the_same_failure(monkeypatch):
    missing = "https://issuer.example/unavailable"
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": missing})])
    checked = response({"checks": [{"url": missing, "supported": False, "explanation": "The filing is inaccessible."}]})
    repaired = OverviewPacket(
        facts=[], gaps=["Original filing inaccessible; used the issuer release."], searched_sources=[source()]
    )
    client = mock_client(
        monkeypatch, [response(packet.model_dump(mode="json")), checked, response(repaired.model_dump(mode="json"))]
    )
    run_id = claimed()
    result = provider.ResearchProvider(run_id, "worker").request(
        "sources", OverviewPacket, prompt="Research", instructions="Research", web=True
    )
    assert result == repaired
    requests = [call.kwargs for call in client.responses.create.call_args_list]
    assert [request["text"]["format"]["name"] for request in requests] == [
        "OverviewPacket",
        "SourceChecks",
        "OverviewPacket",
    ]
    assert "The filing is inaccessible" in requests[2]["input"]
    assert "Retained evidence" in requests[2]["input"]
    assert missing in requests[2]["input"]
    state = store.get_run(run_id)
    assert len([key for key in state["calls"] if "/source-check/" in key]) == 1
    assert all(call["settled"] for call in state["calls"].values())
    assert state["charged_usd"] > 0


def test_positive_source_check_still_requires_an_observed_url(monkeypatch):
    checked = response(
        {
            "checks": [
                {"url": "https://invented.example/", "supported": True, "explanation": "Claimed support"},
                {"url": URL, "supported": True, "explanation": "Opened and supported"},
            ]
        }
    )
    client = mock_client(monkeypatch, [checked])
    result = provider.ResearchProvider(claimed(), "worker").request(
        "check",
        provider.SourceChecks,
        prompt="Check",
        instructions="Check",
        web=True,
        resolve_unobserved=False,
        attempts=1,
    )
    # The unopened page is reported unconfirmed; the opened one keeps its result without a repair call.
    assert [(check.url, check.supported) for check in result.checks] == [
        ("https://invented.example/", False),
        (URL, True),
    ]
    assert result.checks[0].explanation.startswith("The URL was not opened during this check.")
    assert client.responses.create.call_count == 1


def test_source_check_corrects_locations_without_researching_or_rewriting_facts(monkeypatch):
    extra_url = "https://issuer.example/annual"
    original = source().model_copy(update={"url": extra_url, "location": "Page 35"})
    packet = OverviewPacket(
        facts=[Fact(record_id="fact", section="Business", claim="Facility opens next year", sources=[original])],
        gaps=[],
        searched_sources=[original],
    )
    checked = response(
        {
            "checks": [
                {
                    "url": extra_url,
                    "supported": True,
                    "explanation": "Passage and date are supported on page 36.",
                    "location_corrections": [{"source_index": 0, "location": "Page 36"}],
                }
            ]
        }
    )
    checked["output"][-1]["action"]["sources"] = [{"url": extra_url}]
    client = mock_client(monkeypatch, [response(packet.model_dump(mode="json")), checked])
    instance = provider.ResearchProvider(claimed(), "worker")
    result = instance.request("sources", OverviewPacket, prompt="Research", instructions="Research", web=True)
    assert result.facts[0].claim == packet.facts[0].claim
    assert result.facts[0].sources[0] == original.model_copy(update={"location": "Page 36"})
    assert result.searched_sources[0] == result.facts[0].sources[0]
    assert packet.searched_sources[0].location == "Page 35"
    assert client.responses.create.call_count == 2
    assert instance.load("sources", OverviewPacket) == result
    supplied = client.responses.create.call_args_list[1].kwargs["input"].split("Sources:\n")[1]
    assert len(json.loads(supplied)) == 1


@pytest.mark.parametrize(
    "corrections",
    [
        [{"source_index": 9, "location": "Page 36"}],
        [{"source_index": 0, "location": "Page 36"}, {"source_index": 0, "location": "Page 37"}],
    ],
)
def test_invalid_source_location_corrections_are_not_applied(monkeypatch, corrections):
    extra_url = "https://issuer.example/annual"
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": extra_url})])
    instance = provider.ResearchProvider.__new__(provider.ResearchProvider)

    def invalid_check(*args, **kwargs):
        checked = provider.SourceChecks.model_validate(
            {
                "checks": [
                    {
                        "url": extra_url,
                        "supported": True,
                        "explanation": "Supported",
                        "location_corrections": corrections,
                    }
                ]
            }
        )
        kwargs["validate"](checked)
        return checked

    monkeypatch.setattr(instance, "request", invalid_check)
    with pytest.raises(ValueError, match="Location corrections"):
        instance.resolve_sources("sources", packet, {extra_url}, gathering=True)
    assert packet.searched_sources[0].location == source().location


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (provider.ResearchValidationFailed, ValueError),
        (store.ResearchLimitReached, store.ResearchLimitReached),
        (store.ResearchLeaseLost, store.ResearchLeaseLost),
    ],
)
def test_source_check_repair_only_catches_validation_failures(monkeypatch, failure, expected):
    extra_url = "https://issuer.example/annual"
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": extra_url})])
    instance = provider.ResearchProvider.__new__(provider.ResearchProvider)

    def fail(*args, **kwargs):
        raise failure("Stop this check")

    monkeypatch.setattr(instance, "request", fail)
    with pytest.raises(expected, match="Stop this check"):
        instance.resolve_sources("sources", packet, {extra_url}, gathering=True)


def test_unobserved_citation_is_checked_without_regenerating_the_evidence_packet(monkeypatch):
    extra_url = "https://issuer.example/annual"
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": extra_url})])
    checked = response(
        {"checks": [{"url": extra_url, "supported": True, "explanation": "The filing supports the passage."}]}
    )
    checked["output"][-1]["action"]["sources"] = [{"url": extra_url}]
    client = mock_client(monkeypatch, [response(packet.model_dump(mode="json")), checked])
    run_id = claimed()
    result = provider.ResearchProvider(run_id, "worker").request(
        "sources", OverviewPacket, prompt="Research", instructions="Research", web=True
    )
    assert result == packet
    assert client.responses.create.call_count == 2
    assert client.responses.create.call_args_list[1].kwargs["text"]["format"]["name"] == "SourceChecks"


def test_unknown_provider_outcome_keeps_concurrency_slot_until_terminal_recovery():
    run_id = claimed()
    for key in ("one", "two", "three"):
        store.reserve_call(run_id, "worker", key, 2, gathering=False, details={})
        store.settle_call(run_id, "worker", key, actual_usd=None, usage={}, status="unknown")
    with pytest.raises(store.ResearchLimitReached, match="in flight"):
        store.reserve_call(run_id, "worker", "four", 2, gathering=False, details={})
    store.settle_call(run_id, "worker", "one", actual_usd=0.25, usage={}, status="completed")
    assert store.get_run(run_id)["charged_usd"] == 6
    store.reserve_call(run_id, "worker", "four", 2, gathering=False, details={})


def test_resume_recovers_all_pending_calls_before_new_work_and_preserves_accounting(monkeypatch):
    run_id = claimed()
    steps = ["overview/business/source-check/a", "quarters/FY2021_Q1", "overview/other"]
    responses = {}
    for index, step in enumerate(steps):
        response_id = f"resp_pending_{index}"
        call_id = f"{step}:0"
        store.reserve_call(
            run_id,
            "worker",
            call_id,
            2,
            gathering=False,
            details={"step": step, "response_id": response_id},
        )
        saved_response = response({"supported": True, "issues": []})
        saved_response["id"] = response_id
        responses[response_id] = saved_response
    # A previously unknown outcome keeps its conservative charged liability.
    store.settle_call(run_id, "worker", f"{steps[-1]}:0", actual_usd=None, usage={}, status="unknown")
    store.mutate_run(run_id, lambda s: s.update(deadline=time.time() + store.FINISH_RESERVE_S - 1))
    client = mock_client(monkeypatch, [])
    client.responses.retrieve.side_effect = lambda response_id, **_: responses[response_id]
    instance = provider.ResearchProvider(run_id, "worker")
    instance.recover_pending()
    state = store.get_run(run_id)
    assert store.reserved_usd(state) == 0
    assert state["calls"][f"{steps[-1]}:0"]["charged_usd"] == 2
    assert all(call["settled"] and not call["inflight_unknown"] for call in state["calls"].values())
    for step in steps:
        assert legacy._read_json(instance.artifact_key(step, "attempt-0"))["status"] == "completed"
    client.responses.create.assert_not_called()
    client.responses.cancel.assert_not_called()
    assert client.responses.retrieve.call_count == 3
    instance.recover_pending()
    assert client.responses.retrieve.call_count == 3
    store.reserve_call(run_id, "worker", "finishing:0", 1, gathering=False, details={})


def test_compact_verification_preserves_full_ledger_and_original_promises():
    original = commitment()
    checked = EvidenceDecisions.model_validate(
        {
            "decisions": [
                {
                    "record_id": original.record_id,
                    "supported": True,
                    "reason": "Supported",
                    "corrections": [],
                    "replacement_sources": None,
                }
            ]
        }
    )
    accepted, rejected = apply_decisions([original], checked, management=True, as_of=AS_OF)
    assert accepted == [original] and not rejected
    changed = checked.model_dump()
    changed["decisions"][0]["corrections"] = [{"field": "claim", "value": "Different promise"}]
    with pytest.raises(ValueError, match="cannot be rewritten"):
        apply_decisions([original], EvidenceDecisions.model_validate(changed), management=True, as_of=AS_OF)


def test_gathering_cutoff_cancels_inflight_request_without_releasing_unknown_liability(monkeypatch):
    client = mock_client(monkeypatch, [])
    pending = response({}, status="in_progress")
    client.responses.cancel.return_value = pending
    run_id = claimed()
    store.reserve_call(run_id, "worker", "sources:0", 5, gathering=True, details={"response_id": "resp_1"})
    store.mutate_run(run_id, lambda s: s.update(deadline=time.time() + store.FINISH_RESERVE_S - 1))
    with pytest.raises(store.ResearchLimitReached):
        provider.ResearchProvider(run_id, "worker")._wait(pending, "sources:0", gathering=True)
    client.responses.cancel.assert_called_once_with("resp_1")
    assert store.get_run(run_id)["charged_usd"] == 5


class FakeProvider:
    calls: list[str] = []

    def __init__(self, run_id, owner):
        self.run_id, self.owner = run_id, owner

    def recover_pending(self):
        pass

    def request(self, step, model, **kwargs):
        self.calls.append(step)
        prompt = kwargs["prompt"]
        if model is ResearchPlan:
            result = plan()
        elif model is ReadSelection:
            result = ReadSelection(reads=[])
        elif model is QuarterPacket:
            assigned = json.loads(prompt.split("Assigned quarters:\n")[1])
            result = QuarterPacket(
                quarters=[
                    QuarterReview(
                        quarter=q["label"],
                        coverage="researched",
                        search_attempts=["Reviewed filing"],
                        sources=[source()],
                        gap=None,
                        records=[commitment(q["label"])],
                    )
                    for q in assigned
                ]
            )
        elif model is OverviewPacket and step == workflow.OWNER_STEP:
            result = OverviewPacket(
                facts=[
                    Fact(record_id="fact", section=section, claim=f"Owner evidence: {section}", sources=[source()])
                    for section in workflow.OWNER_SECTIONS
                ],
                gaps=[],
                searched_sources=[source()],
            )
        elif model is OverviewPacket:
            result = OverviewPacket(
                facts=[Fact(record_id="fact", section="Business", claim="Makes products", sources=[source()])],
                gaps=[],
                searched_sources=[source()],
            )
        elif model is EvidenceDecisions:
            records = json.loads(prompt.split("Packet:\n")[1])
            result = EvidenceDecisions.model_validate(
                {
                    "decisions": [
                        {
                            "record_id": r["record_id"],
                            "supported": True,
                            "reason": "Supported by filing",
                            "corrections": [],
                            "replacement_sources": None,
                        }
                        for r in records
                    ]
                }
            )
        elif model is WrittenSections:
            titles = json.loads(prompt.split("preserving exact titles and order: ")[1].split(". Use the supplied")[0])
            records = json.loads(prompt.split("\nEvidence:\n")[1].split("\nGaps:\n")[0])["records"]
            result = WrittenSections(
                sections=[
                    Section(
                        title=title,
                        markdown=f"Supported claim [filing]({URL}).",
                        evidence_ids=[r["record_id"] for r in records],
                    )
                    for title in titles
                ]
            )
        elif model is ReportReview:
            result = ReportReview(supported=True, issues=[])
        elif model is workflow.SheetSummary:
            result = workflow.SheetSummary(
                markdown=f"# EL\n\n## Financials\n\nSupported claim [filing]({URL}).\n\n## Sensitivity to Extrinsic Factors\n\nInsufficient evidence.\n\n## Industry\n\nMakes products."
            )
        else:
            raise AssertionError(model)
        if kwargs.get("validate"):
            kwargs["validate"](result)
        return result


def test_truncated_quarter_packet_splits_without_losing_coverage(monkeypatch):
    class SplittingProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is QuarterPacket:
                assigned = json.loads(kwargs["prompt"].split("Assigned quarters:\n")[1])
                if len(assigned) > 1:
                    raise provider.ResearchTruncated("Output cap")
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", SplittingProvider)
    run_id = claimed()
    labels = [q.label for q in plan().quarters[:4]]
    packet = workflow.Workflow(run_id, "worker").gather_quarters(plan(), labels)
    assert [q.quarter for q in packet.quarters] == labels
    assert all(len(q.records) == 1 for q in packet.quarters)


def test_complete_workflow_covers_all_quarters_and_eval_never_publishes(monkeypatch):
    FakeProvider.calls = []
    monkeypatch.setattr(workflow, "ResearchProvider", FakeProvider)
    publish = MagicMock()
    monkeypatch.setattr(legacy, "stage_api_action", publish)
    state = create_run()
    result = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="test"
    )
    assert result["status"] == "done"
    publish.assert_not_called()
    report = legacy.read_research_report("EL", "management_quality", state["run_id"])
    assert report["complete"] and not report["summary_applied"]
    assert all(q.label in report["content"] for q in plan().quarters)
    # Twenty quarterly commitments plus the proxy/filing evidence for "do they act like owners?"
    assert len(report["evidence"]) == 20 + len(workflow.OWNER_SECTIONS)
    assert workflow.OWNER_STEP in FakeProvider.calls
    assert f"## {workflow.OWNER_REPORT_SECTION}" in report["content"]
    assert legacy._read_json("EL/management_quality/latest.json") is None


@pytest.mark.parametrize("talisman_enabled", [False, True])
def test_private_data_reaches_both_reports_with_snapshot_citations_and_without_web_egress(
    monkeypatch, talisman_enabled
):
    from api import company_research_context as local

    private_claim = "Private plant throughput is 37 units."
    private_requests = []
    selections = []

    class PrivateProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is ReadSelection:
                selections.append(step)
                result = ReadSelection(
                    reads=[
                        ReadChoice(
                            tool="get_industry_monitor",
                            arguments_json="{}",
                            reason="Company operating capacity",
                        )
                    ]
                    if talisman_enabled and step.endswith("/0")
                    else []
                )
            elif model is ContextEvidence:
                snapshot = legacy._read_json(f"runs/{self.run_id}/talisman/context.json")["sources"][0]
                citation = Source(
                    url=snapshot["url"],
                    title=snapshot["title"],
                    published_on=AS_OF,
                    passage=private_claim,
                    location="transcript",
                )
                if "/overview/" in step:
                    result = ContextEvidence(
                        facts=[Fact(record_id="local", section="Business", claim=private_claim, sources=[citation])],
                        commitments=[],
                        gaps=[],
                    )
                else:
                    record = commitment("FY2025 Q4")
                    record.claim, record.claim_sources = private_claim, [citation]
                    result = ContextEvidence(
                        facts=[
                            Fact(
                                record_id="context",
                                section="Business",
                                claim="Attributed context: " + private_claim,
                                sources=[citation],
                            )
                        ],
                        commitments=[record],
                        gaps=[],
                    )
            elif model is WrittenSections:
                titles = json.loads(
                    kwargs["prompt"].split("preserving exact titles and order: ")[1].split(". Use the supplied")[0]
                )
                bundle = json.loads(kwargs["prompt"].split("\nEvidence:\n")[1].split("\nGaps:\n")[0])
                result = WrittenSections(
                    sections=[
                        Section(
                            title=title,
                            markdown=" ".join(r["claim"] for r in bundle["records"])
                            + " "
                            + " ".join(f"[{s['title']}]({s['url']})" for s in bundle["sources"].values()),
                            evidence_ids=[r["record_id"] for r in bundle["records"]],
                        )
                        for title in titles
                    ]
                )
            else:
                result = super().request(step, model, **kwargs)
            if private_claim in kwargs["prompt"]:
                assert kwargs.get("private") and not kwargs.get("web")
                private_requests.append(step)
            if kwargs.get("validate"):
                kwargs["validate"](result)
            return result

    read = MagicMock(return_value=json.dumps({"transcript": private_claim, "observed_on": AS_OF.isoformat()}))
    monkeypatch.setattr(local, "execute_tool", read)
    monkeypatch.setattr(workflow, "ResearchProvider", PrivateProvider)
    state = create_run()
    result = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="private"
    )
    assert result["status"] == "done"
    for kind in ("overview", "management_quality"):
        report = legacy.read_research_report("EL", kind, state["run_id"])
        assert (private_claim in report["content"]) == talisman_enabled
        assert any(s["url"].startswith("/api/company-research/EL/runs/") for s in report["sources"]) == talisman_enabled
        assert any("Private Talisman snapshot" in s["title"] for s in report["sources"]) == talisman_enabled
        assert any(step.startswith(f"{kind}/verification-decisions/") for step in private_requests) == talisman_enabled
        if kind == "management_quality":
            assert ("Attributed context:" in report["content"]) == talisman_enabled
    assert len(selections) == (2 if talisman_enabled else 1) and read.call_count == int(talisman_enabled)


def test_provider_private_egress_is_classified_and_cannot_enable_web(monkeypatch):
    client = mock_client(monkeypatch, [response({"supported": True, "issues": []}, web=False)])
    seen = []

    def prepare(**kwargs):
        from api.agent_governance import classify_model_payload

        seen.append(classify_model_payload(kwargs["stream_kwargs"]))
        return kwargs["stream_kwargs"], {}

    monkeypatch.setattr(provider, "prepare_model_egress", prepare)
    instance = provider.ResearchProvider(claimed(), "worker")
    instance.request("private-audit", ReportReview, prompt="Read capacity", instructions="Audit", private=True)
    assert seen == ["portfolio_private"]
    assert "tools" not in client.responses.create.call_args.kwargs
    with pytest.raises(ValueError, match="cannot be sent to web"):
        instance.request("unsafe", ReportReview, prompt="Private data", instructions="Audit", private=True, web=True)


def test_public_research_cannot_forge_private_citations(monkeypatch):
    run_id = claimed()
    private_url = f"/api/company-research/EL/runs/{run_id}/sources/" + "a" * 24
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": private_url})])
    mock_client(monkeypatch, [response(packet.model_dump(mode="json"))] * 2)
    with pytest.raises(RuntimeError, match="cannot introduce private"):
        provider.ResearchProvider(run_id, "worker").request(
            "forged", OverviewPacket, prompt="Research", instructions="Research", web=True
        )


def test_failed_report_does_not_discard_completed_report(monkeypatch):
    monkeypatch.setattr(workflow, "ResearchProvider", FakeProvider)

    def fail(*args):
        raise RuntimeError("Transient search failure")

    monkeypatch.setattr(workflow.Workflow, "gather_quarters", fail)
    state = create_run()
    workflow.run_company_research_run(workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="test")
    saved = store.get_run(state["run_id"])
    assert saved["reports"]["overview"]["status"] == "done"
    assert saved["reports"]["management_quality"]["status"] == "incomplete"
    overview = legacy.read_research_report("EL", "overview", state["run_id"])
    store.resume_run(state["run_id"])
    FakeProvider.calls = []
    workflow.run_company_research_run(workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="resumed")
    assert not any(c.startswith("overview/") for c in FakeProvider.calls)
    assert legacy.read_research_report("EL", "overview", state["run_id"]) == overview


def test_partial_coverage_is_verified_and_retained_without_publication(monkeypatch):
    monkeypatch.setattr(workflow, "ResearchProvider", FakeProvider)
    gather = workflow.Workflow.gather_quarters

    def first_packet_only(self, research_plan, labels):
        if labels != [q.label for q in research_plan.quarters[:4]]:
            raise store.ResearchLimitReached("Source gathering allowance reached")
        return gather(self, research_plan, labels)

    monkeypatch.setattr(workflow.Workflow, "gather_quarters", first_packet_only)
    publish = MagicMock(return_value={"application_status": "applied"})
    monkeypatch.setattr(legacy, "stage_api_action", publish)
    state = create_run(apply=True)
    result = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="partial"
    )
    assert result["status"] == "incomplete"
    report = legacy.read_research_report("EL", "management_quality", state["run_id"])
    assert report["verified_partial"] and not report["complete"] and not report["summary_applied"]
    assert len(report["evidence"]) == 4 + len(workflow.OWNER_SECTIONS)
    assert all(f"## {section}" in report["content"] for section in workflow.OWNER_SECTIONS)
    assert "Not researched: FY2025 Q4" in report["content"]
    assert all(call.args[0] == "save_overview_content" for call in publish.call_args_list)
    assert legacy._read_json("EL/management_quality/latest.json") is None


def test_verified_reports_publish_as_requesting_actor_once_and_pending_approval_is_not_success(monkeypatch):
    monkeypatch.setattr(workflow, "ResearchProvider", FakeProvider)
    published = []

    def publish(action, payload, **kwargs):
        published.append((action, payload, kwargs))
        return {
            "application_status": "applied" if action == "save_overview_content" else "pending",
            "approval_id": "approval",
        }

    monkeypatch.setattr(legacy, "stage_api_action", publish)
    state = create_run(apply=True)
    request = workflow.CompanyResearchRunRequest(run_id=state["run_id"])
    workflow.run_company_research_run(request, job_id="publish")
    saved = store.get_run(state["run_id"])
    assert saved["reports"]["overview"]["status"] == "done"
    assert saved["reports"]["management_quality"]["status"] == "incomplete"
    assert legacy.read_research_report("EL", "overview", state["run_id"])["summary_applied"]
    assert not legacy.read_research_report("EL", "management_quality", state["run_id"])["summary_applied"]
    assert all(kwargs["actor"].actor_id == "researcher" and kwargs["apply"] for _, _, kwargs in published)
    assert all(payload["preserve_exact_content"] for _, payload, _ in published)
    store.resume_run(state["run_id"])
    workflow.run_company_research_run(request, job_id="resume-publish")
    assert sum(action == "save_overview_content" for action, _, _ in published) == 1


def test_overview_sheet_uses_the_uploaded_markdown_loader(monkeypatch):
    from api.routers.overview import _MARKDOWN_USER_PROMPT, _SYSTEM_PROMPT, _finish_llm_overview

    seen: dict[str, dict] = {}

    class RecordingProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if step in {"overview/business", "overview/sections/0", "overview/summary"}:
                seen[step] = kwargs
            return super().request(step, model, **kwargs)

    FakeProvider.calls = []
    monkeypatch.setattr(workflow, "ResearchProvider", RecordingProvider)
    published = []

    def publish(action, payload, **kwargs):
        published.append((action, payload))
        return {"application_status": "applied", "approval_id": "approval"}

    monkeypatch.setattr(legacy, "stage_api_action", publish)
    state = create_run(apply=True)
    result = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="overview-loader"
    )
    assert result["status"] == "done"
    gather = seen["overview/business"]
    assert gather["web"] and gather["effort"] == "high" and gather["tool_calls"] == 12
    assert "deep-research report" in gather["prompt"]
    assert "The facility will open next year." in seen["overview/sections/0"]["prompt"]
    loaded = seen["overview/summary"]
    assert loaded["instructions"] == _SYSTEM_PROMPT.format(ticker="EL")
    assert loaded["prompt"].startswith(_MARKDOWN_USER_PROMPT)
    assert "<uploaded_markdown>" in loaded["prompt"]
    assert "Prepare the company-sheet summary" not in loaded["prompt"]
    assert not loaded.get("web")
    assert "overview/summary-audit" not in FakeProvider.calls
    saved = next(payload["content"] for action, payload in published if action == "save_overview_content")
    assert saved == _finish_llm_overview(
        "EL",
        f"# EL\n\n## Financials\n\nSupported claim [filing]({URL}).\n\n"
        "## Sensitivity to Extrinsic Factors\n\nInsufficient evidence.\n\n## Industry\n\nMakes products.",
    )


def test_in_order_returns_results_in_input_order_within_the_inflight_cap():
    lock = threading.Lock()
    first_wave = threading.Barrier(store.MAX_INFLIGHT, timeout=5)
    running, peak = 0, 0

    def work(n):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        if n < store.MAX_INFLIGHT:
            first_wave.wait()
        time.sleep(0.01 * (6 - n))  # later units finish first
        with lock:
            running -= 1
        return n

    assert workflow._in_order(work, range(6)) == list(range(6))
    assert peak == store.MAX_INFLIGHT


def test_in_order_raises_the_first_failure_in_input_order():
    def work(n):
        if n:
            raise ValueError(f"unit {n}")
        time.sleep(0.05)
        return n

    with pytest.raises(ValueError, match="unit 1"):
        workflow._in_order(work, range(4))


def test_verification_batches_run_concurrently_and_keep_record_order(monkeypatch):
    in_flight = threading.Barrier(store.MAX_INFLIGHT, timeout=5)
    checked = []

    class ConcurrentProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is EvidenceDecisions:
                checked.append(step)
                in_flight.wait()  # passes only when MAX_INFLIGHT batches are checked at the same time
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", ConcurrentProvider)
    # Each record exceeds half the 75 KB batch limit, so each one is its own batch.
    records = [
        commitment(q.label).model_copy(update={"claim": "Open facility " + "x" * 40_000}) for q in plan().quarters[:6]
    ]
    accepted, rejected = workflow.Workflow(claimed(), "worker").verify("management_quality", records)
    assert len(checked) == 6
    assert [r.record_id for r in accepted] == sorted(r.record_id for r in records)
    assert rejected == []


def test_section_pairs_are_written_concurrently_in_order(monkeypatch):
    in_flight = threading.Barrier(3, timeout=5)

    class ConcurrentProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is WrittenSections:
                in_flight.wait()  # passes only when all three section pairs are written at the same time
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", ConcurrentProvider)
    titles = [f"Section {n}" for n in range(6)]
    rendered = workflow.Workflow(claimed(), "worker").write("management_quality", titles, [commitment()], [])
    assert [part.splitlines()[0] for part in rendered] == [f"## {title}" for title in titles]


def test_background_responses_are_polled_every_two_seconds(monkeypatch):
    client = mock_client(monkeypatch, [])
    client.responses.retrieve.side_effect = [response({}, status="in_progress"), response({})]
    sleeps = []
    monkeypatch.setattr(provider.time, "sleep", sleeps.append)
    research = provider.ResearchProvider(claimed(), "worker")
    assert research._wait(response({}, status="in_progress"), "unit:0")["status"] == "completed"
    assert sleeps == [2, 2]


def status_error(code):
    import httpx
    from openai import APIStatusError

    return APIStatusError(
        "Status read failed", response=httpx.Response(code, request=httpx.Request("GET", URL)), body=None
    )


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504, None])
def test_transient_status_reads_retry_the_same_response_without_cancelling_or_resubmitting(monkeypatch, code):
    import httpx

    failure = status_error(code) if code else provider.APIConnectionError(request=httpx.Request("GET", URL))
    client = mock_client(monkeypatch, [])
    client.responses.retrieve.side_effect = [failure, response({})]
    sleeps = []
    monkeypatch.setattr(provider.time, "sleep", sleeps.append)
    run_id = claimed()
    store.reserve_call(run_id, "worker", "unit:0", 2, gathering=False, details={"response_id": "resp_1"})
    research = provider.ResearchProvider(run_id, "worker")
    assert research._wait(response({}, status="in_progress"), "unit:0")["status"] == "completed"
    assert sleeps == [2, 1]
    assert client.responses.retrieve.call_count == 2
    assert all(call.args == ("resp_1",) for call in client.responses.retrieve.call_args_list)
    client.responses.cancel.assert_not_called()
    client.responses.create.assert_not_called()
    assert len(store.get_run(run_id)["calls"]) == 1


def test_status_read_retries_are_bounded_and_nontransient_errors_are_not_retried(monkeypatch):
    client = mock_client(monkeypatch, [])
    monkeypatch.setattr(provider.time, "sleep", lambda _: None)
    research = provider.ResearchProvider(claimed(), "worker")
    failure = status_error(500)
    client.responses.retrieve.side_effect = failure
    with pytest.raises(type(failure)):
        research._retrieve("resp_1")
    assert client.responses.retrieve.call_count == 4
    client.responses.retrieve.reset_mock()
    client.responses.retrieve.side_effect = status_error(401)
    with pytest.raises(type(failure)):
        research._retrieve("resp_1")
    assert client.responses.retrieve.call_count == 1


def test_status_read_backoff_respects_the_original_gathering_deadline(monkeypatch):
    client = mock_client(monkeypatch, [])
    client.responses.retrieve.side_effect = [status_error(500), response({})]
    client.responses.cancel.return_value = response({}, status="cancelled")
    run_id = claimed()
    store.reserve_call(run_id, "worker", "unit:0", 2, gathering=True, details={"response_id": "resp_1"})

    def sleep(seconds):
        if seconds == 1:
            store.mutate_run(run_id, lambda s: s.update(deadline=time.time() + store.FINISH_RESERVE_S - 1))

    monkeypatch.setattr(provider.time, "sleep", sleep)
    with pytest.raises(store.ResearchLimitReached):
        provider.ResearchProvider(run_id, "worker")._wait(response({}, status="in_progress"), "unit:0", gathering=True)
    assert client.responses.retrieve.call_count == 1
    client.responses.cancel.assert_called_once_with("resp_1")


def quarter_repair_packets():
    quarters = [
        QuarterReview(
            quarter=q.label,
            coverage="researched",
            search_attempts=["Read issuer filing"],
            sources=[source()],
            gap=None,
            records=[commitment(q.label)],
        )
        for q in plan().quarters[:4]
    ]
    bad = commitment(quarters[-1].quarter).model_copy(
        update={"record_id": "needs-repair", "claim": "Launch a service", "outcome": "Partially achieved"}
    )
    quarters[-1].records.append(bad)
    original = QuarterPacket(quarters=quarters)
    correction = quarters[-1].model_copy(
        update={
            "records": [bad.model_copy(update={"outcome": "Insufficient disclosure"})],
            "gap": "Later execution evidence was unavailable.",
        }
    )
    return original, QuarterPacket(quarters=[correction])


@pytest.mark.parametrize("pending_repair", [False, True])
def test_resume_applies_saved_partial_repair_without_repeating_quarter_research(monkeypatch, pending_repair):
    original, repair = quarter_repair_packets()
    labels = [q.quarter for q in original.quarters]
    step = "quarters/" + "/".join(label.replace(" ", "_") for label in labels)
    run_id = claimed()
    for index in (0, 1):
        call_id = f"{step}:{index}"
        store.reserve_call(run_id, "worker", call_id, 1, gathering=True, details={"response_id": f"resp_{index}"})
        if index == 0 or not pending_repair:
            store.settle_call(run_id, "worker", call_id, actual_usd=0, usage={}, status="completed")
    client = mock_client(monkeypatch, [])
    client.responses.retrieve.side_effect = lambda response_id, **_: response(
        (original if response_id == "resp_0" else repair).model_dump(mode="json")
    )
    result = workflow.Workflow(run_id, "worker").gather_quarters(plan(), labels)
    assert [q.quarter for q in result.quarters] == labels
    assert sum(len(q.records) for q in result.quarters) == 5
    assert result.quarters[-1].records[-1].outcome == "Insufficient disclosure"
    assert result.quarters[0].records[0].claim == original.quarters[0].records[0].claim
    client.responses.create.assert_not_called()
    assert store.get_run(run_id)["steps"][step]["completed"]


def test_partial_quarter_repairs_cannot_introduce_unknown_ids_or_hide_invalid_outcomes():
    original, repair = quarter_repair_packets()
    repair.quarters[0].records[0].record_id = "unknown"
    with pytest.raises(ValueError, match="original record IDs"):
        merge_quarter_repair(original, repair)
    original, repair = quarter_repair_packets()
    repair.quarters[0].quarter = "FY2099 Q1"
    with pytest.raises(ValueError, match="existing quarters"):
        merge_quarter_repair(original, repair)
    original, repair = quarter_repair_packets()
    repair.quarters[0].records[0].outcome = "Achieved on time"
    merged = merge_quarter_repair(original, repair)
    with pytest.raises(ValueError, match="supporting later evidence"):
        validate_quarters(merged, [q.quarter for q in original.quarters], as_of=AS_OF)


def test_single_quarter_repair_retains_other_records():
    original, repair = quarter_repair_packets()
    original = QuarterPacket(quarters=[original.quarters[-1]])
    merged = merge_quarter_repair(original, repair)
    validate_quarters(merged, [original.quarters[0].quarter], as_of=AS_OF)
    assert len(merged.quarters[0].records) == 2
    assert merged.quarters[0].records[-1].outcome == "Insufficient disclosure"


@pytest.mark.parametrize("finishing_reserve", [False, True])
def test_cancelled_transport_attempt_does_not_consume_the_evidence_repair(monkeypatch, finishing_reserve):
    run_id = claimed()
    store.reserve_call(run_id, "worker", "unit:0", 1, gathering=True, details={"response_id": "cancelled"})
    store.settle_call(run_id, "worker", "unit:0", actual_usd=0, usage={}, status="cancelled")
    # The older cancellation must not consume the pending evidence's repair.
    store.reserve_call(run_id, "worker", "unit:1", 1, gathering=True, details={"response_id": "retained"})
    if finishing_reserve:
        store.mutate_run(run_id, lambda s: s.update(deadline=time.time() + store.FINISH_RESERVE_S - 1))
    client = mock_client(monkeypatch, [response({"supported": True, "issues": []})])
    client.responses.retrieve.return_value = response({"supported": False, "issues": ["Correct this citation"]})

    def validate(result):
        if not result.supported:
            raise ValueError("Correct this citation")

    result = provider.ResearchProvider(run_id, "worker").request(
        "unit",
        ReportReview,
        web=True,
        gathering=True,
        tool_calls=12,
        repair_tool_calls=4,
        prompt="Research",
        instructions="Check evidence",
        validate=validate,
    )
    assert result.supported
    client.responses.create.assert_called_once()
    request = client.responses.create.call_args.kwargs
    assert request["max_tool_calls"] == 4
    assert "Correct this citation" in request["input"]
    assert "Retained evidence" in request["input"]
    calls = store.get_run(run_id)["calls"]
    assert len(calls) == 3
    assert calls["unit:2"]["tool_limit"] == 4


def test_evidence_validation_still_has_only_one_repair(monkeypatch):
    client = mock_client(monkeypatch, [response({"supported": False, "issues": []})] * 4)

    def invalid(result):
        raise ValueError("Unsupported evidence")

    with pytest.raises(provider.ResearchValidationFailed):
        provider.ResearchProvider(claimed(), "worker").request(
            "unit", ReportReview, prompt="Research", instructions="Check", validate=invalid
        )
    assert client.responses.create.call_count == 2


@pytest.mark.parametrize("missing", ["claim", "outcome"])
def test_undated_outcome_fallback_preserves_promise_and_marks_result_unverified(missing):
    original = commitment()
    original.outcome = "Partially achieved"
    original.outcome_sources = [source(date(2022, 4, 30))]
    (original.claim_sources if missing == "claim" else original.outcome_sources)[0].published_on = None
    checked = EvidenceDecisions.model_validate(
        {
            "decisions": [
                {
                    "record_id": original.record_id,
                    "supported": True,
                    "reason": "Source supports the promise",
                    "corrections": [],
                    "replacement_sources": None,
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="Concluded outcomes"):
        apply_decisions([original], checked, management=True, as_of=AS_OF)
    accepted, gaps = apply_decisions(
        [original],
        checked,
        management=True,
        as_of=AS_OF,
        allow_unverified_outcomes=True,
    )
    retained = accepted[0]
    assert retained.outcome == "Insufficient disclosure"
    assert retained.claim == original.claim and retained.original_target == original.original_target
    assert retained.claim_sources == original.claim_sources and retained.outcome_sources == original.outcome_sources
    assert "publication dates are missing" in gaps[0]
    assert original.outcome == "Partially achieved"
    original.claim_sources[0].published_on = date(2022, 4, 30)
    original.outcome_sources[0].published_on = date(2021, 4, 30)
    with pytest.raises(ValueError, match="Concluded outcomes"):
        apply_decisions([original], checked, management=True, as_of=AS_OF)
    # After the one repair, an out-of-order chronology marks this outcome unverified instead
    # of failing every other record in the verification batch.
    accepted, gaps = apply_decisions([original], checked, management=True, as_of=AS_OF, allow_unverified_outcomes=True)
    assert accepted[0].outcome == "Insufficient disclosure"
    assert "predates the original promise" in gaps[0]


def test_semantic_fallback_only_follows_completed_repair_and_is_checkpointed(monkeypatch):
    client = mock_client(monkeypatch, [response({"supported": False, "issues": ["Missing date"]}, web=False)] * 2)
    fallback = MagicMock()

    def strict(value):
        raise ValueError("Missing date")

    instance = provider.ResearchProvider(claimed(), "worker")
    kwargs = dict(prompt="Check", instructions="Check", validate=strict, validation_fallback=fallback)
    instance.request("verification", ReportReview, **kwargs)
    assert client.responses.create.call_count == 2
    assert fallback.call_count == 1
    instance.request("verification", ReportReview, **kwargs)
    assert client.responses.create.call_count == 2 and fallback.call_count == 2


def test_semantic_fallback_cannot_accept_unobserved_sources(monkeypatch):
    packet = OverviewPacket(facts=[], gaps=[], searched_sources=[source().model_copy(update={"url": URL + "/unseen"})])
    mock_client(monkeypatch, [response(packet.model_dump(mode="json"))] * 2)
    fallback = MagicMock()
    with pytest.raises(provider.ResearchValidationFailed):
        provider.ResearchProvider(claimed(), "worker").request(
            "verification",
            OverviewPacket,
            prompt="Check",
            instructions="Check",
            web=True,
            validate=lambda value: None,
            validation_fallback=fallback,
            resolve_unobserved=False,
        )
    fallback.assert_not_called()


def test_private_coverage_notes_are_scoped_to_their_report_and_shared_with_audits(monkeypatch):
    overview_note = "The CEO is not identified in the supplied private excerpts."
    management_note = "The private excerpts contain no original management promises."
    seen = {}

    class RecordingProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model in (WrittenSections, ReportReview):
                seen[step] = kwargs["prompt"]
            return super().request(step, model, **kwargs)

    def private_evidence(self, kind, *args):
        return ContextEvidence(
            facts=[], commitments=[], gaps=[overview_note if kind == "overview" else management_note]
        )

    monkeypatch.setattr(workflow, "ResearchProvider", RecordingProvider)
    monkeypatch.setattr(workflow.ResearchContext, "evidence", private_evidence)
    state = create_run()
    result = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="scoped-notes"
    )
    assert result["status"] == "done"
    for kind, own_note, unrelated_note in (
        ("overview", overview_note, management_note),
        ("management_quality", management_note, overview_note),
    ):
        report = legacy.read_research_report("EL", kind, state["run_id"])
        assert unrelated_note not in report["content"]
        assert f"Private-source review only: {own_note}" in report["content"]
        assert own_note in seen[f"{kind}/sections/0"]
        assert own_note in seen[f"{kind}/sections-audit/0"]
        assert "not evidence" in seen[f"{kind}/sections-audit/0"]
        assert unrelated_note not in seen[f"{kind}/sections/0"]


def test_finishing_window_preserves_source_cutoff_cost_and_checkpoints(monkeypatch):
    run_id = claimed()
    original = store.get_run(run_id)
    store.mutate_run(
        run_id,
        lambda s: s.update(
            charged_usd=12, calls={"saved": {"settled": True, "reserved_usd": 0}}, steps={"plan": {"completed": True}}
        ),
    )
    now = original["deadline"] - 300
    monkeypatch.setattr(store.time, "time", lambda: now)
    before = store.get_run(run_id)
    after = store.begin_finishing(run_id, "worker")
    assert after["deadline"] == now + store.FINISH_WINDOW_S
    assert after["gathering_deadline"] == original["deadline"] - store.FINISH_RESERVE_S
    for field in ("calls", "steps", "charged_usd", "max_cost_usd", "created_at", "snapshot"):
        assert after[field] == before[field]
    with pytest.raises(store.ResearchLimitReached, match="Source gathering"):
        store.check_run(run_id, "worker", gathering=True)
    with pytest.raises(store.ResearchLimitReached, match="time allowance"):
        store.reserve_call(run_id, "worker", "new-sources", 1, gathering=True, details={})
    store.reserve_call(run_id, "worker", "writing", 2, gathering=False, details={})
    with pytest.raises(store.ResearchLimitReached, match="spending allowance"):
        store.reserve_call(run_id, "worker", "overspend", 14, gathering=False, details={})
    now += 600
    assert store.begin_finishing(run_id, "worker")["deadline"] == after["deadline"]
    store.mutate_run(run_id, lambda s: s.update(status="incomplete", lease_until=0))
    store.resume_run(run_id)
    assert store.claim_run(run_id, "replacement")
    assert store.begin_finishing(run_id, "replacement")["deadline"] == after["deadline"]


@pytest.mark.parametrize(
    "markdown",
    [
        "[unreviewed]( https://unreviewed.example/release )",
        "[unreviewed](<https://unreviewed.example/release>)",
        "[unreviewed][release]\n\n[release]: https://unreviewed.example/release",
        "<https://unreviewed.example/release>",
    ],
)
def test_section_source_checks_follow_rendered_markdown_links(markdown):
    written = WrittenSections(sections=[Section(title="Business", markdown=markdown, evidence_ids=["fact"])])
    with pytest.raises(ValueError, match="https://unreviewed.example/release"):
        workflow.validate_sections(written, ["Business"], {"fact"}, {URL})


def test_section_source_checks_accept_equivalent_document_urls():
    original = "https://issuer.example/Results (final).pdf?doc=2"
    written = WrittenSections(
        sections=[
            Section(
                title="Business",
                markdown="[report]( <https://issuer.example/Results%20%28final%29.pdf?doc=2&utm_source=email> )",
                evidence_ids=["fact"],
            )
        ]
    )
    workflow.validate_sections(written, ["Business"], {"fact"}, {original})
    with pytest.raises(ValueError, match="not researched"):
        workflow.validate_sections(written, ["Business"], {"fact"}, {original.replace("doc=2", "doc=1")})


def test_unverified_followup_links_can_be_removed_without_accepting_new_evidence():
    written = WrittenSections(
        sections=[
            Section(
                title="Business",
                markdown=f"Supported claim [filing]({URL}). Follow-up reading: [unreviewed release](https://unreviewed.example/release).",
                evidence_ids=["fact"],
            )
        ]
    )
    workflow.remove_unverified_report_links(written, {URL})
    assert written.sections[0].markdown == f"Supported claim [filing]({URL}). Follow-up reading: unreviewed release."
    assert written.sections[0].evidence_ids == ["fact"]
    workflow.validate_sections(written, ["Business"], {"fact"}, {URL})
    with pytest.raises(ValueError, match="missing evidence: fact"):
        workflow.validate_sections(written, ["Business"], set(), {URL})
    workflow.remove_unverified_report_links(written, set())
    with pytest.raises(ValueError, match="must include source links"):
        workflow.validate_sections(written, ["Business"], {"fact"}, set())


def test_cleaning_unverified_links_does_not_bypass_factual_audit(monkeypatch):
    audited = []

    class UnsupportedProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is WrittenSections:
                written = WrittenSections(
                    sections=[
                        Section(
                            title="Business",
                            markdown=f"Unsupported conclusion [filing]({URL}). See [unverified](https://unreviewed.example).",
                            evidence_ids=["FY2021 Q1"],
                        )
                    ]
                )
                kwargs["validation_fallback"](written)
                return written
            if model is ReportReview:
                audited.append(step)
                return ReportReview(supported=False, issues=["The conclusion is unsupported."])
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", UnsupportedProvider)
    [part] = workflow.Workflow(claimed(), "worker").write("management_quality", ["Business"], [commitment()], [])
    assert audited == ["management_quality/sections-audit/0", "management_quality/sections-audit/0/repair"]
    # The repaired text is kept with the reviewer's unresolved finding beside it, and the unverified link is gone.
    assert "https://unreviewed.example" not in part
    assert part.endswith("**Unresolved evidence-review notes:**\n- The conclusion is unsupported.")


def test_link_cleanup_does_not_turn_an_unverified_url_label_into_an_autolink():
    written = WrittenSections(
        sections=[
            Section(
                title="Business",
                markdown=f"[known]({URL}) and [https://unreviewed.example](https://unreviewed.example)",
                evidence_ids=["fact"],
            )
        ]
    )
    original = written.sections[0].markdown
    workflow.remove_unverified_report_links(written, {URL})
    assert written.sections[0].markdown == original
    with pytest.raises(ValueError, match="not researched"):
        workflow.validate_sections(written, ["Business"], {"fact"}, {URL})


UNITED = "https://united.mediaroom.com/2026-10-20-United-Delivers-Record-17-Revenue-Growth-in-Q3"


def topic_plan():
    return plan().model_copy(
        update={
            "overview_topics": [
                Topic(
                    key="industry", title="Industry", requirements="Industry history", sections=["Industry", "History"]
                )
            ]
        }
    )


def topic_packet(bad_url):
    return OverviewPacket(
        facts=[
            Fact(record_id="a", section="Industry", claim="Four carriers hold most capacity.", sources=[source()]),
            Fact(
                record_id="b",
                section="History",
                claim="A competitor grew revenue 17%.",
                sources=[source().model_copy(update={"url": bad_url})],
            ),
        ],
        gaps=[],
        searched_sources=[source()],
    )


@pytest.mark.parametrize(
    ("bad_url", "claimed_support"),
    [(UNITED, True), ("", False)],
    ids=["check-claims-support-without-opening", "empty-url"],
)
def test_one_unconfirmed_citation_drops_only_its_claim_not_the_topic(monkeypatch, bad_url, claimed_support):
    # DAL run eb6e6229: 62 and 47 facts were discarded over one United link and one empty URL.
    checked = response({"checks": [{"url": bad_url, "supported": claimed_support, "explanation": "Checked"}]})
    client = mock_client(monkeypatch, [response(topic_packet(bad_url).model_dump(mode="json")), checked])
    instance = workflow.Workflow(claimed(), "worker")
    result = instance.gather_overview(topic_plan(), 0)
    assert [fact.claim for fact in result.facts] == ["Four carriers hold most capacity."]
    assert result.facts[0].record_id.startswith("fact_")
    assert any(gap.startswith("History: removed a claim") for gap in result.gaps)
    # No repair round-trip: the paid packet is kept, minus the claim that could not be confirmed.
    assert client.responses.create.call_count == 2
    assert instance.provider.load("overview/industry", OverviewPacket) == result
    assert legacy._read_json(instance.provider.artifact_key("overview/industry", "pruned-0"))


def test_pruning_that_leaves_an_invalid_packet_still_gets_the_one_repair(monkeypatch):
    bad = source().model_copy(update={"url": UNITED})
    packet = OverviewPacket(
        facts=[Fact(record_id="b", section="History", claim="Claim", sources=[bad])],
        gaps=["Industry: not disclosed."],
        searched_sources=[bad],
    )
    repaired = OverviewPacket(
        facts=[Fact(record_id="a", section="History", claim="Repaired claim", sources=[source()])],
        gaps=["Industry: not disclosed."],
        searched_sources=[source()],
    )
    checked = response({"checks": [{"url": UNITED, "supported": True, "explanation": "Claimed"}]})
    client = mock_client(
        monkeypatch,
        [response(packet.model_dump(mode="json")), checked, response(repaired.model_dump(mode="json"))],
    )
    result = workflow.Workflow(claimed(), "worker").gather_overview(topic_plan(), 0)
    assert [fact.claim for fact in result.facts] == ["Repaired claim"]
    repair_prompt = client.responses.create.call_args_list[2].kwargs["input"]
    assert "sources consulted" in repair_prompt and "not opened during this check" in repair_prompt


def test_quarter_pruning_keeps_confirmed_commitments_and_unverifies_outcomes():
    bad = source().model_copy(update={"url": UNITED})
    lost = commitment().model_copy(update={"initiative": "Lounge", "claim_sources": [bad]})
    kept = commitment().model_copy(
        update={
            "initiative": "Fleet",
            "outcome": "Achieved on time",
            "outcome_sources": [bad],
        }
    )
    packet = QuarterPacket(
        quarters=[
            QuarterReview(
                quarter="FY2021 Q1",
                coverage="researched",
                search_attempts=["Read release"],
                sources=[bad],
                gap=None,
                records=[lost, kept],
            )
        ]
    )
    pruned = prune_quarter_sources(packet, {UNITED + "?utm_source=openai"})
    quarter = pruned.quarters[0]
    assert [r.initiative for r in quarter.records] == ["Fleet"]
    assert quarter.records[0].outcome == "Insufficient disclosure" and not quarter.records[0].outcome_sources
    assert quarter.sources == [source()] and "Lounge" in quarter.gap
    validate_quarters(pruned, ["FY2021 Q1"], as_of=AS_OF)


def test_quarter_batch_ignores_quarters_owned_by_another_batch_and_accepts_label_variants(monkeypatch):
    class ExtraQuarterProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is QuarterPacket:
                extra = QuarterReview(
                    quarter="Q1 FY2026",
                    coverage="researched",
                    search_attempts=["Read release"],
                    sources=[source()],
                    gap=None,
                    records=[],
                )
                packet = super().request(step, model, **{**kwargs, "validate": None})
                data = packet.model_dump(mode="json")
                data["quarters"][0]["quarter"] = "Q1 FY2021"
                data["quarters"][0]["records"][0]["quarter"] = "Q1 FY2021"
                packet = QuarterPacket.model_validate({"quarters": [*data["quarters"], extra.model_dump(mode="json")]})
                kwargs["validate"](packet)
                return packet
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", ExtraQuarterProvider)
    labels = [q.label for q in plan().quarters[:4]]
    packet = workflow.Workflow(claimed(), "worker").gather_quarters(plan(), labels)
    assert [q.quarter for q in packet.quarters] == labels


def decision(record_id, **values):
    return {
        "record_id": record_id,
        "supported": False,
        "reason": "Not reviewed",
        "corrections": [],
        "replacement_sources": None,
        **values,
    }


def test_verifier_cannot_reject_a_record_only_because_it_did_not_reopen_the_source():
    # DAL run eb6e6229: 86 of 88 rejections were "not independently inspected", leaving 20 of 72 commitments.
    unread, wrong, legacy_reject = (commitment(label) for label in ("FY2021 Q1", "FY2021 Q2", "FY2021 Q3"))
    unread.outcome, unread.outcome_sources = "Achieved on time", [source(date(2022, 4, 30))]
    checked = EvidenceDecisions.model_validate(
        {
            "decisions": [
                decision(unread.record_id, rejection_basis=None),
                decision(wrong.record_id, reason="Release says 2027", rejection_basis="contradicted_by_source"),
                decision(legacy_reject.record_id),
            ]
        }
    )
    assert "rejection_basis" not in checked.decisions[2].model_fields_set
    accepted, rejected = apply_decisions([unread, wrong, legacy_reject], checked, management=True, as_of=AS_OF)
    assert accepted == [unread] and accepted[0].outcome == "Achieved on time"
    assert [line.split(":")[0] for line in rejected] == [wrong.record_id, legacy_reject.record_id]
    # An unread record whose chronology cannot be shown is kept as unverified, not failed or dropped.
    unread.outcome_sources[0].published_on = None
    accepted, rejected = apply_decisions([unread, wrong, legacy_reject], checked, management=True, as_of=AS_OF)
    assert accepted[0].outcome == "Insufficient disclosure"
    assert "publication dates are missing" in rejected[0]


def test_stalled_provider_response_is_cancelled_and_resubmitted(monkeypatch):
    # DAL run eb6e6229: a repair sat queued for 40 minutes until the run's deadline cancelled the topic.
    stalled = {"id": "resp_stalled", "status": "queued", "created_at": time.time() - provider.STALLED_RESPONSE_S - 1}
    client = mock_client(monkeypatch, [stalled, response({"supported": True, "issues": []})])
    client.responses.cancel.return_value = {"id": "resp_stalled", "status": "cancelled"}
    run_id = claimed()
    result = provider.ResearchProvider(run_id, "worker").request(
        "audit", ReportReview, prompt="Check", instructions="Check", web=True
    )
    assert result.supported
    client.responses.cancel.assert_called_once_with("resp_stalled")
    client.responses.retrieve.assert_not_called()
    calls = store.get_run(run_id)["calls"]
    assert calls["audit:0"]["status"] == "cancelled" and calls["audit:1"]["status"] == "completed"


def test_owner_mindset_failure_leaves_a_gap_instead_of_failing_management(monkeypatch):
    class NoOwnerProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if step == workflow.OWNER_STEP:
                raise provider.ResearchValidationFailed("Proxy statements unavailable")
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", NoOwnerProvider)
    state = create_run()
    result = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="test"
    )
    assert result["status"] == "done"
    report = legacy.read_research_report("EL", "management_quality", state["run_id"])
    assert len(report["evidence"]) == 20
    assert any(gap.startswith("Owner-mindset research did not complete") for gap in report["gaps"])
    assert workflow.OWNER_REPORT_SECTION not in report["content"]


def test_owner_research_reads_filings_and_uses_fixed_sections(monkeypatch):
    FakeProvider.calls = []
    prompts = {}

    class RecordingProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            prompts[step] = kwargs
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", RecordingProvider)
    packet = workflow.Workflow(claimed(), "worker").gather_owner_mindset(plan())
    request = prompts[workflow.OWNER_STEP]
    assert request["web"] and request["gathering"] and request["prune"] is not None
    for term in ("DEF 14A", "Form 4", "share repurchases", "FY2021 Q1 to FY2025 Q4"):
        assert term in request["prompt"]
    assert {fact.section for fact in packet.facts} == set(workflow.OWNER_SECTIONS)
    assert all(fact.record_id.startswith("owner_") for fact in packet.facts)


def test_report_audit_accepts_a_full_twenty_quarter_ledger_but_still_bounds_requests(monkeypatch):
    # DAL run c324b24f: the section audit (60 KB draft + ~150 KB ledger) exceeded the old 200 KB cap.
    client = mock_client(monkeypatch, [response({"supported": True, "issues": []}, web=False)])
    instance = provider.ResearchProvider(claimed(), "worker")
    assert instance.request("audit", ReportReview, prompt="x" * 250_000, instructions="Audit").supported
    with pytest.raises(provider.ResearchTruncated):
        instance.request("too-large", ReportReview, prompt="x" * provider.PROMPT_BYTES, instructions="Audit")
    with pytest.raises(provider.ResearchTruncated):
        instance.request("web", ReportReview, prompt="x" * provider.WEB_PROMPT_BYTES, instructions="Audit", web=True)
    assert client.responses.create.call_count == 1


def test_unresolved_summary_review_is_published_as_evidence_notes(monkeypatch):
    # DAL run c324b24f: two minor wording findings left after the one repair failed the whole report.
    class NitpickingProvider(FakeProvider):
        def request(self, step, model, **kwargs):
            if model is ReportReview and step.startswith("management_quality/summary-audit"):
                return ReportReview(supported=False, issues=["Q1 and Q3 targets should be distinguished."])
            if model is workflow.SheetSummary and step.startswith("management_quality/summary"):
                return workflow.SheetSummary(markdown="# EL Management Quality\n\n## Executive Summary\n- Mixed.")
            return super().request(step, model, **kwargs)

    monkeypatch.setattr(workflow, "ResearchProvider", NitpickingProvider)
    state = create_run()
    result = workflow.run_company_research_run(
        workflow.CompanyResearchRunRequest(run_id=state["run_id"]), job_id="test"
    )
    assert result["status"] == "done"
    summary = legacy.read_research_report("EL", "management_quality", state["run_id"])["summary"]
    notes = summary.split("## Evidence Notes")[-1]
    assert "Unresolved evidence-review notes" in notes and "Q1 and Q3 targets" in notes
