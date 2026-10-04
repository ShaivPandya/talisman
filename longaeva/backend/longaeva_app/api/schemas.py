"""Pydantic API schemas (job queue + core domain contracts for LON-10)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from longaeva_app.hashing import content_hash as hash_payload
from longaeva_app.hashing import utc_isoformat

StatementType = Literal["measured", "guidance", "qualitative", "analyst_assumption", "intervention"]
ReviewStatus = Literal["pending", "accepted", "rejected", "corrected"]
ReviewDecisionKind = Literal["accept", "reject", "correct"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
ForecastKind = Literal["retrospective", "prospective"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(BaseModel):
    status: str
    database: str
    alembic_revision: str | None = None
    detail: str | None = None


class JobCreate(StrictModel):
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

    model_config = ConfigDict(from_attributes=True)


# --- Sources / documents ---


class SourceCreate(StrictModel):
    provider: str = Field(min_length=1)
    company: str = Field(min_length=1)
    doc_type: str = Field(min_length=1)
    url: str = Field(min_length=1)
    publication_ts: AwareDatetime
    retrieval_ts: AwareDatetime
    period_start: date | None = None
    period_end: date | None = None
    content_hash: str = Field(min_length=1)
    original_path: str = Field(min_length=1)
    license_note: str | None = None
    supersedes_id: uuid.UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _publication_before_retrieval(self) -> SourceCreate:
        if self.publication_ts >= self.retrieval_ts:
            raise ValueError("publication_ts must be strictly before retrieval_ts")
        return self


class SourceRead(BaseModel):
    id: uuid.UUID
    provider: str
    company: str
    doc_type: str
    url: str
    publication_ts: datetime
    retrieval_ts: datetime
    period_start: date | None = None
    period_end: date | None = None
    content_hash: str
    original_path: str
    license_note: str | None = None
    supersedes_id: uuid.UUID | None = None
    attributes: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentTextCreate(StrictModel):
    source_id: uuid.UUID
    page: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _span_order(self) -> DocumentTextCreate:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        return self


class DocumentTextRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    page: int
    char_start: int
    char_end: int
    text: str

    model_config = ConfigDict(from_attributes=True)


class SourceRetrievalCreate(StrictModel):
    source_id: uuid.UUID
    retrieved_at: AwareDatetime
    url: str = Field(min_length=1)
    http_status: int | None = None
    etag: str | None = None
    notes: str | None = None


class SourceRetrievalRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    retrieved_at: datetime
    url: str
    http_status: int | None = None
    etag: str | None = None
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Observations / review ---


class ObservationCreate(StrictModel):
    company: str = Field(min_length=1)
    source_id: uuid.UUID | None = None
    document_text_id: uuid.UUID | None = None
    span_page: int | None = None
    span_char_start: int | None = None
    span_char_end: int | None = None
    statement_type: StatementType
    activity_type: str | None = None
    geography: str | None = None
    period_start: date
    period_end: date
    value: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    unit: str = Field(min_length=1)
    basis: str | None = None
    source_family: str | None = None
    extractor_id: str | None = None
    extractor_version: str | None = None
    review_status: ReviewStatus = "pending"
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_observation(self) -> ObservationCreate:
        if self.statement_type not in {"analyst_assumption", "intervention"} and self.source_id is None:
            raise ValueError("source_id is required unless statement_type is analyst_assumption or intervention")
        if self.statement_type != "qualitative" and self.value is None and self.range_low is None:
            raise ValueError("value or range_low is required unless statement_type is qualitative")
        if self.range_low is not None and self.range_high is not None and self.range_low > self.range_high:
            raise ValueError("range_low must be <= range_high")
        if "confidence" in self.attributes or "probability" in self.attributes:
            raise ValueError("confidence/probability fields are not allowed on observations (MR-12)")
        return self


class ObservationRead(BaseModel):
    id: uuid.UUID
    company: str
    source_id: uuid.UUID | None = None
    document_text_id: uuid.UUID | None = None
    span_page: int | None = None
    span_char_start: int | None = None
    span_char_end: int | None = None
    statement_type: str
    activity_type: str | None = None
    geography: str | None = None
    period_start: date
    period_end: date
    value: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    unit: str
    basis: str | None = None
    source_family: str | None = None
    extractor_id: str | None = None
    extractor_version: str | None = None
    review_status: str
    attributes: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewDecisionCreate(StrictModel):
    observation_id: uuid.UUID
    decision: ReviewDecisionKind
    corrected_payload: dict[str, Any] | None = None
    rationale: str = Field(min_length=1)
    decided_by: str = Field(min_length=1)
    decided_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _corrected_required(self) -> ReviewDecisionCreate:
        if self.decision == "correct" and self.corrected_payload is None:
            raise ValueError("corrected_payload is required when decision is correct")
        return self


class ReviewDecisionRead(BaseModel):
    id: uuid.UUID
    observation_id: uuid.UUID
    decision: str
    version: int
    corrected_payload: dict[str, Any] | None = None
    rationale: str
    decided_at: datetime
    decided_by: str

    model_config = ConfigDict(from_attributes=True)


class ExtractionRequest(StrictModel):
    document_text_ids: list[uuid.UUID] = Field(min_length=1)
    provider: str | None = None
    model: str | None = None


class ExtractionStatusRead(BaseModel):
    enabled: bool
    provider: str
    model: str
    configured_providers: list[str]
    disabled_reason: str | None = None
    max_passages: int
    max_passage_chars: int
    prompt_version: str


class ExtractionCallRead(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str
    document_text_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    status: str
    response_text: str | None = None
    parsed: dict[str, Any] | None = None
    item_errors: list[Any]
    error: str | None = None
    attempts: int
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ObservationReviewRead(BaseModel):
    observation: ObservationRead
    decisions: list[ReviewDecisionRead]
    effective: dict[str, Any] | None = None


# --- Parameters / mapping ---


class ParameterEvidence(StrictModel):
    observation_ids: list[uuid.UUID] = Field(default_factory=list)
    assumption: bool = False
    rationale: str | None = None

    @model_validator(mode="after")
    def _evidence_or_assumption(self) -> ParameterEvidence:
        if not self.observation_ids and not self.assumption:
            raise ValueError("each parameter needs >=1 observation_id or assumption=true")
        if self.assumption and not (self.rationale and self.rationale.strip()):
            raise ValueError("assumption=true requires a non-empty rationale")
        return self


class ParameterSetCreate(StrictModel):
    company: str = Field(min_length=1)
    cutoff_ts: AwareDatetime
    values: dict[str, float] = Field(default_factory=dict)
    ranges: dict[str, list[float]] = Field(default_factory=dict)
    evidence_links: dict[str, ParameterEvidence] = Field(default_factory=dict)
    assumption_flags: dict[str, Any] = Field(default_factory=dict)
    parent_id: uuid.UUID | None = None
    content_hash: str | None = None

    @model_validator(mode="after")
    def _every_parameter_has_evidence(self) -> ParameterSetCreate:
        for name in self.values:
            link = self.evidence_links.get(name)
            if link is None:
                raise ValueError(f"parameter {name!r} missing evidence_links entry")
        return self

    def computed_content_hash(self) -> str:
        payload = {
            "company": self.company,
            "cutoff_ts": utc_isoformat(self.cutoff_ts),
            "values": self.values,
            "ranges": self.ranges,
            "evidence_links": {key: link.model_dump(mode="json") for key, link in sorted(self.evidence_links.items())},
            "assumption_flags": self.assumption_flags,
            "parent_id": str(self.parent_id) if self.parent_id else None,
        }
        return hash_payload(payload)


class ParameterSetRead(BaseModel):
    id: uuid.UUID
    company: str
    cutoff_ts: datetime
    values: dict[str, Any]
    ranges: dict[str, Any]
    evidence_links: dict[str, Any]
    assumption_flags: dict[str, Any]
    content_hash: str
    parent_id: uuid.UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MappingRuleCreate(StrictModel):
    rule_key: str = Field(min_length=1)
    version: int = Field(ge=1)
    input_type: str = Field(min_length=1)
    target_parameter: str = Field(min_length=1)
    transform: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)


class MappingRuleRead(BaseModel):
    id: uuid.UUID
    rule_key: str
    version: int
    input_type: str
    target_parameter: str
    transform: dict[str, Any]
    rationale: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParameterUpdateRead(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None = None
    parameter_set_id: uuid.UUID
    target_parameter: str
    before_value: dict[str, Any] | None = None
    after_value: dict[str, Any] | None = None
    size: float | None = None
    rationale: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Scenarios / runs / forecasts / evaluation ---


class ScenarioCreate(StrictModel):
    company: str = Field(min_length=1)
    name: str = Field(min_length=1)
    parameter_set_id: uuid.UUID
    interventions: list[dict[str, Any]] = Field(default_factory=list)
    pair_group_id: uuid.UUID | None = None


class ScenarioRead(BaseModel):
    id: uuid.UUID
    company: str
    name: str
    parameter_set_id: uuid.UUID
    interventions: list[Any]
    pair_group_id: uuid.UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SourceManifestEntry(StrictModel):
    document_key: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    publication_ts: str = Field(min_length=1)
    source_id: uuid.UUID | None = None


class RunCreate(StrictModel):
    scenario_id: uuid.UUID
    cutoff_ts: AwareDatetime
    seed: int = Field(ge=0, le=2**31 - 1)
    n_paths: int = Field(default=5000, ge=1, le=50_000)
    n_quarters: int = Field(default=4, ge=1, le=8)
    switches: dict[str, bool] = Field(default_factory=dict)


class RunResultSummary(StrictModel):
    metric: str
    quarter_index: int
    period_label: str
    mean: float
    std: float
    std_error: float | None = None
    quantiles: dict[str, float] = Field(default_factory=dict)
    quantile_std_errors: dict[str, float] = Field(default_factory=dict)


class RunRead(BaseModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    job_id: uuid.UUID | None = None
    cutoff_ts: datetime
    origin_label: str
    n_quarters: int
    source_manifest: list[Any]
    source_manifest_hash: str
    parameter_set_hash: str
    starting_state_hash: str
    code_version: str
    seed: int
    n_paths: int
    switches: dict[str, Any]
    lib_versions: dict[str, Any]
    status: str
    outputs_path: str | None = None
    outputs_hash: str | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ReplayReport(BaseModel):
    run_id: uuid.UUID
    status: Literal["exact_match", "numerically_equivalent", "mismatch", "inputs_changed"]
    recorded_outputs_hash: str
    recomputed_outputs_hash: str | None = None
    max_relative_difference: float | None = None
    recorded_code_version: str
    recomputed_code_version: str | None = None
    recorded_lib_versions: dict[str, Any]
    recomputed_lib_versions: dict[str, Any] | None = None
    differences: list[str] = Field(default_factory=list)
    llm_provider: str = ""


class ForecastArchiveRequest(StrictModel):
    kind: ForecastKind


class ForecastCreate(StrictModel):
    run_id: uuid.UUID
    origin_ts: AwareDatetime
    cutoff_ts: AwareDatetime
    target_period_start: date
    target_period_end: date
    metric: str = Field(min_length=1)
    quantiles: dict[str, float] = Field(default_factory=dict)
    kind: ForecastKind


class ForecastRead(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    origin_ts: datetime
    cutoff_ts: datetime
    target_period_start: date
    target_period_end: date
    metric: str
    quantiles: dict[str, Any]
    kind: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvaluationResultCreate(StrictModel):
    suite_version: str = Field(min_length=1)
    origin_ts: AwareDatetime
    model_variant: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    value: float
    config_hash: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationResultRead(BaseModel):
    id: uuid.UUID
    suite_version: str
    origin_ts: datetime
    model_variant: str
    metric: str
    value: float
    config_hash: str
    details: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Schemas that must appear in the published OpenAPI contract even before write routes exist.
OPENAPI_CONTRACT_SCHEMAS: tuple[type[BaseModel], ...] = (
    SourceCreate,
    SourceRead,
    DocumentTextCreate,
    DocumentTextRead,
    SourceRetrievalCreate,
    SourceRetrievalRead,
    ObservationCreate,
    ObservationRead,
    ReviewDecisionCreate,
    ReviewDecisionRead,
    ExtractionRequest,
    ExtractionStatusRead,
    ExtractionCallRead,
    ObservationReviewRead,
    ParameterSetCreate,
    ParameterSetRead,
    MappingRuleCreate,
    MappingRuleRead,
    ParameterUpdateRead,
    ScenarioCreate,
    ScenarioRead,
    RunCreate,
    RunRead,
    RunResultSummary,
    ReplayReport,
    ForecastCreate,
    ForecastRead,
    ForecastArchiveRequest,
    EvaluationResultCreate,
    EvaluationResultRead,
)
