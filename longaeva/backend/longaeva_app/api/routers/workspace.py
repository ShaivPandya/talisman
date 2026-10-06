"""Browser-ready bundled state and calibration endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterSetRead
from longaeva_app.api.workspace_schemas import WorkspaceOriginRead, WorkspaceStateRead
from longaeva_app.db.session import get_db
from longaeva_app.workspace import available_origins, prepare_origin, workspace_state

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/origins", response_model=list[WorkspaceOriginRead])
def list_origins() -> list[WorkspaceOriginRead]:
    return available_origins()


@router.get("/origins/{origin_date}", response_model=WorkspaceStateRead)
def get_state(origin_date: str) -> WorkspaceStateRead:
    return workspace_state(origin_date)


@router.post("/origins/{origin_date}/prepare", response_model=ParameterSetRead)
def prepare(origin_date: str, session: Session = Depends(get_db)) -> ParameterSetRead:
    return prepare_origin(session, origin_date)
