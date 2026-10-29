from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api import action_item_execution as execution
from api import action_item_execution_store as store
from api.exceptions import AppError, ConflictError, NotFoundError
from ontology.action_registry import get_action
from ontology.policy import actor_to_dict, user_actor

URL = "https://investor.example/earnings"
OWNER = user_actor("research-owner", roles=("admin",))
TODAY = datetime.now(UTC).date().isoformat()


def task(kind="thesis", key="one"):
    return {
        "item_id": f"action_item:{key}",
        "ticker": "META",
        "action_type": "research",
        "status": "open",
        "description": {
            "thesis": "Rebuild the META thesis with capex and free cash flow evidence",
            "kill_conditions": "Convert META kill conditions to measurable triggers",
            "valuation": "Refresh META valuation with current consensus",
        }[kind],
        "created_at": datetime.now(UTC).isoformat(),
    }


def result(kind="thesis"):
    return {
        "report": "A cited research report with explicit facts and assumptions. " * 4,
        "checks": [
            {"requirement_index": 0, "satisfied": True, "evidence": "Dated primary filing", "source_urls": [URL]}
        ],
        "gaps": [],
        "thesis_content": "# Proposed thesis\n" + "Evidence of current capex and free cash flow. " * 8
        if kind == "thesis"
        else None,
        "kill_conditions": [
            {
                "condition": "Capex outruns cash flow",
                "metric": "capex / operating cash flow",
                "threshold": "> 0.8 for two quarters",
                "cadence": "quarterly",
                "source_url": URL,
            }
        ]
        if kind == "kill_conditions"
        else [],
        "valuation_inputs": [
            {"name": "price", "value": 220, "unit": "USD/share", "kind": "market", "as_of": TODAY, "source_url": URL},
            {
                "name": "earnings",
                "value": 10,
                "unit": "USD/share",
                "kind": "consensus",
                "as_of": TODAY,
                "source_url": URL,
            },
            {"name": "multiple", "value": 20, "unit": "x", "kind": "assumption", "as_of": TODAY, "source_url": None},
        ]
        if kind == "valuation"
        else [],
        "calculations": [
            {"name": "base_price", "operation": "multiply", "inputs": ["earnings", "multiple"], "result": 200},
            {"name": "sensitivity", "operation": "add", "inputs": ["base_price", "earnings"], "result": 210},
        ]
        if kind == "valuation"
        else [],
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SQLITE_PATH", tmp_path / "executions.sqlite3")
    monkeypatch.setattr(execution, "require_research_key", lambda: None)
    monkeypatch.setattr(execution, "research_model", lambda: "gpt-6.1-sol")
    monkeypatch.setenv("ACTION_ITEM_EXECUTION_ENABLED", "true")
    items = {"action_item:one": task()}
    proposals, workflow_records, provider_calls, responses = {}, {}, [], {}
    controls = {"kind": "thesis", "fail_review": False, "unobserved": False, "cancel_in_call": None}

    class Objects:
        def get_object(self, uid):
            item = items.get(uid)
            return {"object_uid": uid, "object_type": "ActionItem", "properties": copy.deepcopy(item)} if item else None

        def query_objects(self, object_type, filters=None, **_):
            if object_type != "ActionItem":
                return []
            return [
                {"object_uid": key, "properties": copy.deepcopy(item)}
                for key, item in items.items()
                if all(item.get(k) == v for k, v in (filters or {}).items())
            ]

    class Commands:
        def list_approvals(self, **_):
            return list(proposals.values())

        def get_approval(self, key, **_):
            return proposals[key]

        def propose_action(self, action, payload, context, **_):
            assert context.actor.actor_type == "agent"
            get_action(action).input_model.model_validate(payload)
            key = f"approval:{len(proposals)}"
            proposals[key] = {
                "id": key,
                "action_id": action,
                "proposed_change": payload,
                "status": "pending",
                "application_status": "pending",
                "source_id": context.source_id,
            }
            return proposals[key]

    def create_response(**kwargs):
        provider_calls.append(kwargs)
        schema = kwargs["text"]["format"]["name"]
        data = {
            "TaskPlan": {
                "scope": "Requested research",
                "requirements": ["Address requested evidence"],
                "needs_input": [],
                "fiscal_periods": ["FY2026 Q3"],
            },
            "EvidencePacket": {
                "findings": "Primary filing evidence",
                "sources": [
                    {
                        "url": URL,
                        "title": "Earnings release",
                        "published_on": TODAY,
                        "passage": "Capital expenditures were reported.",
                        "location": "Cash flow, page 4",
                    }
                ],
                "gaps": [],
            },
            "TaskResult": result(controls["kind"]),
            "EvidenceReview": {
                "supported": not controls["fail_review"],
                "issues": ["Unsupported claim"] if controls["fail_review"] else [],
            },
        }[schema]
        response = {
            "id": f"response-{len(responses)}",
            "status": "completed",
            "output_text": json.dumps(data),
            "usage": {"input_tokens": 1000, "output_tokens": 1000},
            "output": [],
        }
        if schema == "EvidencePacket" and not controls["unobserved"]:
            response["output"] = [{"type": "web_search_call", "action": {"sources": [{"url": URL}]}}]
        responses[response["id"]] = response
        if controls["cancel_in_call"] == schema:
            execution.cancel(store.runs(OWNER.actor_id)[0]["run_id"], OWNER)
        return response

    provider = SimpleNamespace(
        responses=SimpleNamespace(create=create_response, retrieve=lambda key: responses[key], cancel=lambda _: None)
    )
    provider.with_options = lambda **_: provider
    monkeypatch.setattr(execution, "get_llm_client", lambda _: provider)
    monkeypatch.setattr(execution, "prepare_model_egress", lambda **kwargs: (kwargs["stream_kwargs"], {}))
    monkeypatch.setattr(execution, "OntologyObjectService", Objects)
    monkeypatch.setattr(execution, "OntologyCommandService", Commands)
    monkeypatch.setattr(execution, "target_fingerprint", lambda _: "original-target")
    monkeypatch.setattr(
        execution, "enqueue_registered_job", lambda *args, **kwargs: ({"job_id": "test-job"}, "created")
    )
    monkeypatch.setattr(execution, "get_job", lambda _: {"job_id": "test-job", "status": "running"})
    monkeypatch.setattr(execution, "poll_registered_job", lambda *args, **kwargs: {"status": "running"})
    monkeypatch.setattr(execution, "cancel_job", lambda *args, **kwargs: None)
    from api import agent_tools, workflows

    monkeypatch.setattr(
        agent_tools,
        "execute_tool",
        lambda *args, **kwargs: json.dumps({"ticker": "META", "thesis": {"content": "Original thesis"}}),
    )
    monkeypatch.setattr(workflows, "create_workflow_run", lambda *args, **kwargs: {"run_id": "workflow:test"})
    monkeypatch.setattr(
        workflows,
        "complete_workflow_run",
        lambda key, synthesis, **kwargs: workflow_records.update({key: {"synthesis": synthesis, **kwargs}}),
    )
    return SimpleNamespace(
        items=items,
        proposals=proposals,
        records=workflow_records,
        calls=provider_calls,
        responses=responses,
        controls=controls,
    )


def run_task(world, kind="thesis"):
    world.items["action_item:one"] = task(kind)
    world.controls["kind"] = kind
    started = execution.start("one", OWNER)
    execution.run({"run_id": started["run_id"]}, job_id="test-job")
    return store.get(started["run_id"])


@pytest.mark.parametrize(
    "kind,action",
    [("thesis", "save_thesis_content"), ("kill_conditions", "create_kill_condition"), ("valuation", None)],
)
def test_full_research_then_required_approvals_then_completion(world, kind, action):
    state = run_task(world, kind)
    assert state["status"] == ("awaiting_approvals" if action else "ready_for_review")
    assert world.items["action_item:one"]["status"] == "open"
    assert len(world.calls) == 4
    assert "Private Talisman" not in world.calls[1]["input"]
    assert "Original thesis" not in world.calls[1]["input"]
    assert "FY2026 Q3" in world.calls[1]["input"]
    assert [p["action_id"] for p in world.proposals.values()] == ([action] if action else [])
    if action:
        with pytest.raises(ConflictError, match="every required change"):
            execution.propose_completion(state["run_id"], OWNER)
        for proposal in world.proposals.values():
            proposal.update(status="approved", application_status="applied")
    complete = execution.propose_completion(state["run_id"], OWNER)
    assert complete["status"] == "completion_proposed"
    proposal = world.proposals[complete["completion_approval_id"]]
    assert proposal["status"] == "pending"
    assert "workflow:test" in proposal["proposed_change"]["resolution_note"]
    count = len(world.proposals)
    execution.propose_completion(state["run_id"], OWNER)
    assert len(world.proposals) == count
    assert world.records["workflow:test"]["artifacts"]["action_item_execution"]["item_id"] == "action_item:one"


def test_duplicate_starts_are_serialized(world):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: execution.start("one", OWNER), range(4)))
    assert len({r["run_id"] for r in results}) == 1
    assert len(store.runs(OWNER.actor_id)) == 1


def test_cancelled_worker_cannot_publish_or_propose(world):
    world.controls["cancel_in_call"] = "TaskResult"
    started = execution.start("one", OWNER)
    with pytest.raises(store.ExecutionConflict):
        execution.run({"run_id": started["run_id"]}, job_id="test-job")
    assert store.get(started["run_id"])["status"] == "cancelled"
    assert world.proposals == {}


def test_unknown_submission_keeps_reservation_and_does_not_resubmit(world):
    started = execution.start("one", OWNER)
    lease = "lease"
    state = store.claim(started["run_id"], lease)
    store.mutate(state["run_id"], lambda s: s["calls"].update(plan={"reserved_usd": 1}), lease=lease)
    with pytest.raises(ValueError, match="unknown outcome"):
        execution._request(state, lease, "plan", execution.TaskPlan, "Test")
    assert not world.calls


def test_retry_recovers_submitted_response_and_completed_steps(world):
    started = execution.start("one", OWNER)
    state = store.claim(started["run_id"], "old-worker")
    data = {"scope": "Retained plan", "requirements": ["Check evidence"], "needs_input": [], "fiscal_periods": []}
    world.responses["retained-response"] = {
        "id": "retained-response",
        "status": "completed",
        "output_text": json.dumps(data),
        "usage": {},
    }
    store.mutate(
        state["run_id"],
        lambda s: s.update(
            status="failed", charged_usd=1, calls={"plan": {"reserved_usd": 1, "response_id": "retained-response"}}
        ),
    )
    execution.retry(state["run_id"], OWNER)
    state = store.claim(state["run_id"], "new-worker")
    assert execution._request(state, "new-worker", "plan", execution.TaskPlan, "Retained") == data
    assert not world.calls


def test_source_trace_and_evidence_review_fail_closed(world):
    world.controls["unobserved"] = True
    with pytest.raises(ValueError, match="not observed"):
        run_task(world)
    state = store.runs(OWNER.actor_id)[0]
    assert state["status"] == "failed"
    assert world.proposals == {}


def test_failed_audit_retains_report_and_never_proposes(world):
    world.controls["fail_review"] = True
    state = run_task(world)
    assert state["status"] == "needs_input"
    assert "Unsupported claim" in state["error"]
    assert world.proposals == {}
    assert world.records


def test_changed_item_blocks_completion(world):
    state = run_task(world, "valuation")
    world.items[state["item_id"]]["description"] += " plus a new requirement"
    with pytest.raises(ConflictError, match="changed or closed"):
        execution.propose_completion(state["run_id"], OWNER)
    assert not world.proposals


def test_expired_worker_cannot_update_checkpoints(world):
    state = execution.start("one", OWNER)
    store.claim(state["run_id"], "old")
    store.mutate(state["run_id"], lambda s: s.update(lease_until=time.time() - 1))
    with pytest.raises(store.ExecutionConflict, match="no longer owns"):
        store.mutate(state["run_id"], lambda s: s["steps"].update(result={}), lease="old")
    recovered = execution.recover(store.get(state["run_id"]))
    assert recovered["status"] == "failed"


def test_budgets_and_concurrency_apply_to_new_starts_and_retries(world):
    execution.save_settings(OWNER, execution.ExecutionSettings(max_cost_usd=5, daily_budget_usd=5))
    first = execution.start("one", OWNER)
    world.items["action_item:two"] = task(key="two")
    with pytest.raises(ConflictError, match="daily research budget"):
        execution.start("two", OWNER)
    execution.cancel(first["run_id"], OWNER)
    state = execution.retry(first["run_id"], OWNER)
    assert state["charged_usd"] == 0
    assert len(store.runs(OWNER.actor_id)) == 1


def test_cross_owner_access_is_hidden(world):
    started = execution.start("one", OWNER)
    with pytest.raises(NotFoundError):
        execution.cancel(started["run_id"], user_actor("another-owner", roles=("admin",)))


@pytest.mark.parametrize("action_type", ["enter", "exit", "resize", "hedge", "other"])
def test_trading_and_unsupported_types_are_ineligible(world, action_type):
    world.items["action_item:one"]["action_type"] = action_type
    assert execution.execution_kind(world.items["action_item:one"]) is None


def test_valuation_checks_reproduce_math_and_reject_stale_inputs(world):
    state = run_task(world, "valuation")
    assert execution.validate_result(state) == []
    state["steps"]["result"]["calculations"][0]["result"] = 999
    assert any("could not be reproduced" in issue for issue in execution.validate_result(state))
    state["steps"]["result"]["valuation_inputs"][0]["as_of"] = (
        datetime.now(UTC).date() - timedelta(days=100)
    ).isoformat()
    assert any("stale" in issue for issue in execution.validate_result(state))


def test_automatic_research_excludes_backlog_and_disabled_kinds(world):
    old = datetime.now(UTC) - timedelta(days=1)
    world.items["action_item:one"]["created_at"] = old.isoformat()
    assert execution.process_automatic({"actor": actor_to_dict(OWNER)}) == {"started": 0}
    execution.save_settings(OWNER, execution.ExecutionSettings(automatic=True))
    world.items["action_item:two"] = task(key="two")
    assert execution.process_automatic({"actor": actor_to_dict(OWNER)}) == {"started": 1}
    assert [s["item_id"] for s in store.runs(OWNER.actor_id)] == ["action_item:two"]
    assert execution.process_automatic({"actor": actor_to_dict(OWNER)}) == {"started": 0}


def test_http_contract_start_poll_cancel_and_ownership(world):
    from api.routers.action_items import router
    from api.routers.auth import require_actor

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[require_actor] = lambda: OWNER

    @app.exception_handler(AppError)
    async def app_error(_request, error):
        return JSONResponse({"detail": error.message}, status_code=error.status_code)

    client = TestClient(app)
    response = client.post("/api/actions/one/execute")
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert client.get("/api/action-execution/runs").json()["runs"][0]["run_id"] == run_id
    assert "result" not in client.get("/api/action-execution/runs").json()["runs"][0]
    assert client.post(f"/api/action-execution/runs/{run_id}/cancel").json()["status"] == "cancelled"
    app.dependency_overrides[require_actor] = lambda: user_actor("another", roles=("admin",))
    assert client.get(f"/api/action-execution/runs/{run_id}").status_code == 404


def test_rejected_changes_are_visible_and_cannot_complete(world):
    state = run_task(world)
    world.proposals[state["approval_ids"][0]].update(status="rejected", application_status="not_applicable")
    refreshed = execution.refresh(state)
    assert refreshed["status"] == "needs_input"
    with pytest.raises(ConflictError):
        execution.propose_completion(state["run_id"], OWNER)


def test_clarification_retains_prior_attempt_and_original_budget(world):
    world.controls["fail_review"] = True
    state = run_task(world)
    previous_charge = state["charged_usd"]
    execution.revise(state["run_id"], OWNER, "Use the reported capex figure and explain its period.")
    resumed = store.get(state["run_id"])
    assert resumed["generation"] == 1
    assert resumed["charged_usd"] == previous_charge
    assert resumed["history"][0]["steps"]["result"]["report"]
    world.controls["fail_review"] = False
    execution.run({"run_id": state["run_id"]}, job_id="test-job")
    assert store.get(state["run_id"])["status"] == "awaiting_approvals"
    assert any("reported capex" in call["input"] for call in world.calls)


def test_retry_does_not_bypass_concurrency_limit(world):
    state = execution.start("one", OWNER)
    execution.cancel(state["run_id"], OWNER)
    world.items["action_item:two"] = task(key="two")
    execution.start("two", OWNER)
    with pytest.raises(ConflictError, match="concurrency"):
        execution.retry(state["run_id"], OWNER)


def test_completion_state_tracks_applied_owner_decision(world):
    state = run_task(world, "valuation")
    completed = execution.propose_completion(state["run_id"], OWNER)
    world.proposals[completed["completion_approval_id"]].update(status="approved", application_status="applied")
    assert execution.refresh(store.get(state["run_id"]))["status"] == "completed"


def test_target_change_during_research_preserves_work_without_proposals(world, monkeypatch):
    calls = 0

    def target(_):
        nonlocal calls
        calls += 1
        return "original" if calls == 1 else "edited"

    monkeypatch.setattr(execution, "target_fingerprint", target)
    with pytest.raises(ValueError, match="changed during research"):
        run_task(world)
    assert store.runs(OWNER.actor_id)[0]["steps"]["result"]
    assert not world.proposals


def test_authenticated_app_routes_and_request_schema_headers(world, auth_client):
    saved = auth_client.put("/api/action-execution/settings", json=execution.ExecutionSettings().model_dump())
    assert saved.status_code == 200
    assert saved.json()["automatic"] is False
    started = auth_client.post("/api/actions/one/execute")
    assert started.status_code == 202
    response = auth_client.get(f"/api/action-execution/runs/{started.json()['run_id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_execution_endpoints_require_authentication(world, client):
    assert client.get("/api/action-execution/runs").status_code == 401
    assert client.post("/api/actions/one/execute").status_code == 401


def test_automatic_dispatch_stays_idle_until_owner_opt_in(world, client, monkeypatch):
    from api.routers import admin_jobs

    monkeypatch.setenv("SCHEDULER_SECRET", "test-scheduler")
    monkeypatch.setattr(admin_jobs, "enqueue_registered_job", lambda *args, **kwargs: pytest.fail("Idle dispatch launched a job"))
    response = client.post("/api/admin/jobs/enqueue-action-item-research", headers={"X-Scheduler-Secret": "test-scheduler"})
    assert response.status_code == 200
    assert response.json() == {"status": "idle", "started": 0}
    execution.save_settings(OWNER, execution.ExecutionSettings(automatic=True))
    assert execution.automatic_enabled()
