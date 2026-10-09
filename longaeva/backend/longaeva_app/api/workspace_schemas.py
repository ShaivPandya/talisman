"""Read contracts for the browser workspace."""

from __future__ import annotations

from pydantic import BaseModel, Field

from longaeva_app.api.schemas import ParameterEvidence, ParameterUpdateDetailRead
from longaeva_app.companies.visa.starting_state import SourceRef, StateValue, SupportingLevel


class EvidenceExcerpt(BaseModel):
    source_id: str | None = None
    observation_id: str | None = None
    document_text_id: str | None = None
    url: str | None = None
    publication_ts: str | None = None
    content_hash: str | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    before: str = ""
    quote: str = ""
    after: str = ""
    unavailable_reason: str | None = None


class WorkspaceOriginRead(BaseModel):
    origin_date: str
    cutoff_ts: str
    label: str


class ParameterSpecRead(BaseModel):
    name: str
    unit: str
    lower: float
    upper: float
    default: float
    role: str
    description: str


class WorkspaceStateRead(WorkspaceOriginRead):
    values: dict[str, StateValue]
    supporting_levels: dict[str, SupportingLevel]
    evidence: dict[str, EvidenceExcerpt]
    sources: dict[str, SourceRef]
    post_cutoff_sources: dict[str, SourceRef]
    parameter_specs: list[ParameterSpecRead]
    notes: list[str]


class ParameterEvidenceRead(BaseModel):
    parameter: str
    evidence: ParameterEvidence
    excerpts: list[EvidenceExcerpt] = Field(default_factory=list)
    updates: list[ParameterUpdateDetailRead] = Field(default_factory=list)
