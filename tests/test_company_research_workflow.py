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
    assert len(report["evidence"]) == 20
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
                    result = ContextEvidence(facts=[], commitments=[record], gaps=[])
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
    assert len(report["evidence"]) == 4
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
