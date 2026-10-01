"""Pydantic API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database: str
    alembic_revision: str | None = None
    detail: str | None = None


class JobCreate(BaseModel):
    type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class JobRead(BaseModel):
    id: uuid.UUID
    type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    result: dict[str, Any] | None = None
    error: str | None = None
    worker_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}
