"""Save and revisit completed results without rerunning a screen."""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from api import screener_runs
from api.routers.auth import ActorDep

router = APIRouter()
ScreenName = Literal["Quality", "Short", "Long", "Price Momentum", "Fundamental Momentum", "Digest Presets"]


class SaveScreenerRunRequest(BaseModel):
    screen: ScreenName
    name: str = Field(min_length=1, max_length=160)
    request: dict[str, Any]
    result: dict[str, Any]
    captured_at: datetime
    benchmark: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a name for this run.")
        return value.strip()


@router.post("/screener-runs", status_code=201)
def save_screener_run(body: SaveScreenerRunRequest, actor: ActorDep):
    snapshot = body.model_dump(mode="json", exclude={"screen", "name"})
    return screener_runs.save(actor.actor_id, body.screen, body.name, snapshot)


@router.get("/screener-runs")
def list_screener_runs(
    actor: ActorDep,
    screen: ScreenName,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return {"runs": screener_runs.list_runs(actor.actor_id, screen, limit=limit, offset=offset)}


@router.get("/screener-runs/{run_id}")
def get_screener_run(run_id: str, actor: ActorDep):
    try:
        return screener_runs.get(actor.actor_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Saved run not found.") from exc


@router.delete("/screener-runs/{run_id}", status_code=204)
def delete_screener_run(run_id: str, actor: ActorDep):
    if not screener_runs.delete(actor.actor_id, run_id):
        raise HTTPException(status_code=404, detail="Saved run not found.")
    return Response(status_code=204)
