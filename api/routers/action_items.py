"""Action item CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.action_execution import stage_api_action
from api.action_item_execution_models import ExecutionSettings
from api.exceptions import NotFoundError
from api.routers.auth import ActorDep
from ontology.object_service import OntologyObjectService

router = APIRouter()


class CreateActionRequest(BaseModel):
    description: str
    action_type: str = "review"
    ticker: str | None = None
    urgency: str = "normal"
    reason: str | None = None
    apply: bool = False
    approval_note: str | None = None


class CompleteActionRequest(BaseModel):
    resolution_note: str = ""
    reason: str | None = None
    apply: bool = False
    approval_note: str | None = None


class DismissActionRequest(BaseModel):
    reason: str | None = None
    apply: bool = False
    approval_note: str | None = None


class ReviseExecutionRequest(BaseModel):
    instructions: str = Field(min_length=1, max_length=4000)


@router.get("/action-execution/settings")
def execution_settings(actor: ActorDep):
    from api.action_item_execution import settings

    return settings(actor)


@router.put("/action-execution/settings")
def update_execution_settings(body: ExecutionSettings, actor: ActorDep):
    from api.action_item_execution import save_settings

    return save_settings(actor, body)


@router.get("/action-execution/runs")
def execution_runs(actor: ActorDep):
    from api.action_item_execution import public_state, refresh
    from api.action_item_execution_store import runs

    return {"runs": [public_state(refresh(state), details=False) for state in runs(actor.actor_id)]}


@router.get("/action-execution/runs/{run_id}")
def execution_run(run_id: str, actor: ActorDep):
    from api.action_item_execution import owned_run, public_state, refresh

    return public_state(refresh(owned_run(run_id, actor)))


@router.post("/actions/{item_id}/execute", status_code=202)
def execute_action_item(item_id: str, actor: ActorDep):
    from api.action_item_execution import start

    return start(item_id, actor)


@router.post("/action-execution/runs/{run_id}/retry", status_code=202)
def retry_execution(run_id: str, actor: ActorDep):
    from api.action_item_execution import retry

    return retry(run_id, actor)


@router.post("/action-execution/runs/{run_id}/cancel")
def cancel_execution(run_id: str, actor: ActorDep):
    from api.action_item_execution import cancel

    return cancel(run_id, actor)


@router.post("/action-execution/runs/{run_id}/revise", status_code=202)
def revise_execution(run_id: str, body: ReviseExecutionRequest, actor: ActorDep):
    from api.action_item_execution import revise

    return revise(run_id, actor, body.instructions)


@router.post("/action-execution/runs/{run_id}/completion")
def propose_execution_completion(run_id: str, actor: ActorDep):
    from api.action_item_execution import propose_completion

    return propose_completion(run_id, actor)


@router.post("/action-execution/batch", status_code=202)
def execute_action_item_batch(actor: ActorDep):
    from api.action_item_execution import execution_kind, start
    from api.exceptions import AppError

    results = []
    for row in OntologyObjectService().query_objects("ActionItem", filters={"status": "open"}, limit=500):
        item = dict(row.get("properties") or row.get("properties_json") or {})
        if not execution_kind(item):
            continue
        try:
            results.append(start(str(row["object_uid"]), actor))
        except AppError as exc:
            return {"runs": results, "message": str(exc)}
    return {"runs": results}


@router.get("/actions")
def list_actions(
    status: str | None = None,
    ticker: str | None = None,
):
    filters = {}
    if status:
        filters["status"] = status
    if ticker:
        filters["ticker"] = ticker.strip().upper()
    items = [_flatten_object(row) for row in OntologyObjectService().query_objects("ActionItem", filters=filters)]
    return {"actions": items, "count": len(items)}


@router.get("/actions/{item_id}")
def get_action(item_id: str):
    item = OntologyObjectService().get_object(
        item_id if item_id.startswith("action_item:") else f"action_item:{item_id}"
    )
    if item:
        return _flatten_object(item)
    raise NotFoundError("Action item", str(item_id))


@router.post("/actions")
def create_action(body: CreateActionRequest, actor: ActorDep):
    return stage_api_action(
        "create_action_item",
        body.model_dump(exclude={"reason", "apply", "approval_note"}),
        source_id="action_items.create_action",
        actor=actor,
        reason=body.reason or "Create action item",
        apply=body.apply,
        approval_note=body.approval_note,
    )


@router.put("/actions/{item_id}/complete")
def complete_action(item_id: str, actor: ActorDep, body: CompleteActionRequest | None = None):
    return stage_api_action(
        "complete_action_item",
        {"item_id": item_id, "resolution_note": body.resolution_note if body else ""},
        source_id="action_items.complete_action",
        actor=actor,
        reason=(body.reason if body else None) or f"Complete action item {item_id}",
        apply=body.apply if body else False,
        approval_note=body.approval_note if body else None,
        entity_id=item_id,
    )


@router.put("/actions/{item_id}/dismiss")
def dismiss_action(item_id: str, actor: ActorDep, body: DismissActionRequest | None = None):
    return stage_api_action(
        "dismiss_action_item",
        {"item_id": item_id},
        source_id="action_items.dismiss_action",
        actor=actor,
        reason=(body.reason if body else None) or f"Dismiss action item {item_id}",
        apply=body.apply if body else False,
        approval_note=body.approval_note if body else None,
        entity_id=item_id,
    )


def _flatten_object(row: dict) -> dict:
    props = dict(row.get("properties") or row.get("properties_json") or {})
    props["id"] = str(row.get("object_uid") or props.get("id") or "")
    props["object_uid"] = props["id"]
    return props
