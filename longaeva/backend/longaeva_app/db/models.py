"""SQLAlchemy models: job queue (LON-9) plus core domain records (LON-10)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from longaeva_app.db.base import Base

JOB_STATUSES = ("queued", "running", "succeeded", "failed")
STATEMENT_TYPES = ("measured", "guidance", "qualitative", "analyst_assumption", "intervention")
REVIEW_STATUSES = ("pending", "accepted", "rejected", "corrected")
REVIEW_DECISIONS = ("accept", "reject", "correct")
RUN_STATUSES = ("queued", "running", "succeeded", "failed")
FORECAST_KINDS = ("retrospective", "prospective")
EXTRACTION_CALL_STATUSES = ("succeeded", "invalid_response", "provider_error")


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="status",
        ),
        Index("ix_job_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (
        CheckConstraint("publication_ts < retrieval_ts", name="publication_before_retrieval"),
        Index("ix_source_company_publication_ts", "company", "publication_ts"),
        Index("ix_source_publication_ts", "publication_ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    publication_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieval_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source.id", name="fk_source_supersedes_id_source"),
        nullable=True,
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    retrievals: Mapped[list[SourceRetrieval]] = relationship(back_populates="source")
    passages: Mapped[list[DocumentText]] = relationship(back_populates="source")
    observations: Mapped[list[Observation]] = relationship(back_populates="source")


class SourceRetrieval(Base):
    __tablename__ = "source_retrieval"
    __table_args__ = (Index("ix_source_retrieval_source_id_retrieved_at", "source_id", "retrieved_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source.id", ondelete="CASCADE", name="fk_source_retrieval_source_id_source"),
        nullable=False,
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[Source] = relationship(back_populates="retrievals")


class DocumentText(Base):
    __tablename__ = "document_text"
    __table_args__ = (
        UniqueConstraint("source_id", "page", "char_start", name="uq_document_text_source_page_start"),
        CheckConstraint("char_end >= char_start", name="char_span_order"),
        CheckConstraint("page >= 0", name="page_nonneg"),
        Index("ix_document_text_tsv", "tsv", postgresql_using="gin"),
        Index("ix_document_text_text_hash", "text_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source.id", ondelete="CASCADE", name="fk_document_text_source_id_source"),
        nullable=False,
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
        nullable=True,
    )
    text_hash: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "md5(lower(btrim(regexp_replace(text, '\\s+', ' ', 'g'))))",
            persisted=True,
        ),
        nullable=True,
    )

    source: Mapped[Source] = relationship(back_populates="passages")


class Observation(Base):
    __tablename__ = "observation"
    __table_args__ = (
        CheckConstraint(
            "statement_type IN ('measured', 'guidance', 'qualitative', 'analyst_assumption', 'intervention')",
            name="statement_type",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'corrected')",
            name="review_status",
        ),
        CheckConstraint(
            "(statement_type IN ('analyst_assumption', 'intervention')) OR (source_id IS NOT NULL)",
            name="source_required_unless_assumption",
        ),
        CheckConstraint(
            "(statement_type = 'qualitative') OR (value IS NOT NULL) OR (range_low IS NOT NULL)",
            name="value_or_range_unless_qualitative",
        ),
        CheckConstraint(
            "(range_low IS NULL) OR (range_high IS NULL) OR (range_low <= range_high)",
            name="range_order",
        ),
        Index("ix_observation_company_period", "company", "period_start", "period_end"),
        Index("ix_observation_source_id", "source_id"),
        Index("ix_observation_review_status", "review_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source.id", ondelete="SET NULL", name="fk_observation_source_id_source"),
        nullable=True,
    )
    document_text_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_text.id", ondelete="SET NULL", name="fk_observation_document_text_id_document_text"),
        nullable=True,
    )
    span_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statement_type: Mapped[str] = mapped_column(Text, nullable=False)
    activity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    geography: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    range_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    range_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_family: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    source: Mapped[Source | None] = relationship(back_populates="observations")
    review_decisions: Mapped[list[ReviewDecision]] = relationship(back_populates="observation")


class ReviewDecision(Base):
    __tablename__ = "review_decision"
    __table_args__ = (
        CheckConstraint("decision IN ('accept', 'reject', 'correct')", name="decision"),
        CheckConstraint(
            "(decision <> 'correct') OR (corrected_payload IS NOT NULL)",
            name="corrected_payload_required",
        ),
        UniqueConstraint("observation_id", "version", name="uq_review_decision_observation_version"),
        Index("ix_review_decision_observation_id", "observation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("observation.id", ondelete="CASCADE", name="fk_review_decision_observation_id_observation"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    corrected_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)

    observation: Mapped[Observation] = relationship(back_populates="review_decisions")


class ExtractionCall(Base):
    """One provider call. Succeeded rows are the (provider, model, prompt hash) cache."""

    __tablename__ = "extraction_call"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'invalid_response', 'provider_error')",
            name="status",
        ),
        Index(
            "uq_extraction_call_succeeded",
            "provider",
            "model",
            "prompt_hash",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
        Index("ix_extraction_call_document_text_id", "document_text_id"),
        Index("ix_extraction_call_job_id", "job_id"),
        Index("ix_extraction_call_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    document_text_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_text.id",
            ondelete="SET NULL",
            name="fk_extraction_call_document_text_id_document_text",
        ),
        nullable=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job.id", ondelete="SET NULL", name="fk_extraction_call_job_id_job"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    item_errors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MappingRule(Base):
    __tablename__ = "mapping_rule"
    __table_args__ = (UniqueConstraint("rule_key", "version", name="uq_mapping_rule_key_version"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    rule_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_parameter: Mapped[str] = mapped_column(Text, nullable=False)
    transform: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ParameterSet(Base):
    __tablename__ = "parameter_set"
    __table_args__ = (Index("ix_parameter_set_company_cutoff_ts", "company", "cutoff_ts"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company: Mapped[str] = mapped_column(Text, nullable=False)
    cutoff_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ranges: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    evidence_links: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    assumption_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parameter_set.id", name="fk_parameter_set_parent_id_parameter_set"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ParameterUpdate(Base):
    __tablename__ = "parameter_update"
    __table_args__ = (Index("ix_parameter_update_parameter_set_id", "parameter_set_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mapping_rule.id", ondelete="SET NULL", name="fk_parameter_update_rule_id_mapping_rule"),
        nullable=True,
    )
    parameter_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parameter_set.id", ondelete="CASCADE", name="fk_parameter_update_parameter_set_id_parameter_set"),
        nullable=False,
    )
    target_parameter: Mapped[str] = mapped_column(Text, nullable=False)
    before_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    size: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ParameterUpdateObservation(Base):
    __tablename__ = "parameter_update_observation"

    parameter_update_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "parameter_update.id",
            ondelete="CASCADE",
            name="fk_parameter_update_observation_parameter_update_id_parameter_update",
        ),
        primary_key=True,
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "observation.id",
            ondelete="CASCADE",
            name="fk_parameter_update_observation_observation_id_observation",
        ),
        primary_key=True,
    )


class Scenario(Base):
    __tablename__ = "scenario"
    __table_args__ = (Index("ix_scenario_parameter_set_id", "parameter_set_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parameter_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parameter_set.id", ondelete="RESTRICT", name="fk_scenario_parameter_set_id_parameter_set"),
        nullable=False,
    )
    interventions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    pair_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Run(Base):
    __tablename__ = "run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="status",
        ),
        CheckConstraint("n_paths >= 1", name="n_paths_positive"),
        CheckConstraint("seed >= 0", name="seed_nonneg"),
        CheckConstraint("n_quarters >= 1 AND n_quarters <= 8", name="n_quarters_range"),
        CheckConstraint(
            "status <> 'succeeded' OR (outputs_hash IS NOT NULL AND outputs_path IS NOT NULL AND summary IS NOT NULL)",
            name="succeeded_has_outputs",
        ),
        Index("ix_run_scenario_id", "scenario_id"),
        Index("ix_run_status_created_at", "status", "created_at"),
        Index("ix_run_baseline_run_id", "baseline_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenario.id", ondelete="RESTRICT", name="fk_run_scenario_id_scenario"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job.id", ondelete="SET NULL", name="fk_run_job_id_job"),
        nullable=True,
    )
    cutoff_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_manifest: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source_manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    parameter_set_hash: Mapped[str] = mapped_column(Text, nullable=False)
    code_version: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    n_paths: Mapped[int] = mapped_column(Integer, nullable=False)
    n_quarters: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("4"))
    origin_label: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    starting_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    starting_state_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    switches: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    interventions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    interventions_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945'"),
    )
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="SET NULL", name="fk_run_baseline_run_id_run"),
        nullable=True,
    )
    lib_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    outputs_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    outputs_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Forecast(Base):
    __tablename__ = "forecast"
    __table_args__ = (
        CheckConstraint("kind IN ('retrospective', 'prospective')", name="kind"),
        UniqueConstraint("run_id", "metric", "target_period_start", name="uq_forecast_run_metric_period"),
        Index("ix_forecast_kind_origin_ts", "kind", "origin_ts"),
        Index("ix_forecast_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="RESTRICT", name="fk_forecast_run_id_run"),
        nullable=False,
    )
    origin_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    target_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    quantiles: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_result"
    __table_args__ = (
        Index("ix_evaluation_result_suite_origin", "suite_version", "origin_ts"),
        Index("ix_evaluation_result_config_hash", "config_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    suite_version: Mapped[str] = mapped_column(Text, nullable=False)
    origin_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_variant: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
