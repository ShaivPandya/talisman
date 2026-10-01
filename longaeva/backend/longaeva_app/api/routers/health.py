"""Health endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import HealthResponse
from longaeva_app.db.session import get_db

router = APIRouter(tags=["health"])


def _current_revision(session: Session) -> str | None:
    row = session.execute(text("SELECT version_num FROM alembic_version")).first()
    if row is None:
        return None
    return str(row[0])


@router.get("/health", response_model=HealthResponse)
def health(response: Response, session: Session = Depends(get_db)) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        revision = _current_revision(session)
        return HealthResponse(status="ok", database="ok", alembic_revision=revision)
    except Exception as exc:  # noqa: BLE001 — surface any DB failure as unhealthy
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="unhealthy",
            database="error",
            alembic_revision=None,
            detail=str(exc),
        )
