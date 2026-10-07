"""Read-only, bounded projections of saved evaluation artifacts (LON-36)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ReportMetadata(BaseModel):
    key: str
    title: str
    kind: Literal["forecast", "ablations", "portfolio", "pending"]
    status: Literal["available", "pending"]
    reason: str | None = None
    owner_issue: str


class ReportExclusion(BaseModel):
    origin_date: str
    label: str | None = None
    reason: str


class ScoreAggregate(BaseModel):
    n: int
    bias: float | None = None
    mae: float | None = None
    mape: float | None = None
    coverage: str | None = None
    covered_k: int
    covered_n: int
    mean_crps: float | None = None
    mean_wis: float | None = None


class OriginScore(BaseModel):
    origin_date: str
    label: str
    window: str
    run_id: str | None = None
    error: str | None = None
    scores: dict[str, float]
    skipped_drivers: dict[str, str]


class ForecastReport(BaseModel):
    config: dict[str, Any]
    config_hash: str
    n_scored: int
    n_excluded: int
    exclusions: list[ReportExclusion]
    aggregates: dict[str, dict[str, ScoreAggregate]]
    four_quarter: dict[str, ScoreAggregate]
    origins: list[OriginScore]


class AblationComparison(BaseModel):
    n: int
    full_wins: int
    ablated_wins: int
    ties: int
    mean_ablated_minus_full: float
    full_covered: int
    ablated_covered: int
    full_coverage: float
    ablated_coverage: float


class RobustnessCount(BaseModel):
    profiles: int
    full_better: int
    ablated_better: int
    ties: int


class AblationReport(BaseModel):
    suite_version: str
    content_hash: str
    delta_convention: str
    profile_policy: str
    settings: dict[str, dict[str, str | float]]
    summaries: dict[str, dict[str, AblationComparison]]
    robustness: dict[str, RobustnessCount]
    # Config hashes retain traceability without shipping duplicated model outputs.
    config_hashes: dict[str, dict[str, str]]


class BenchmarkAggregate(BaseModel):
    n_scored: int
    n_unavailable: int
    n_estimated: int
    mean_return: float | None
    worst_window_drawdown: float | None


class PortfolioMetrics(BaseModel):
    total_return: float
    max_drawdown: float
    average_invested_exposure: float


class PortfolioSeries(BaseModel):
    status: str
    label: str | None = None
    reason: str | None = None
    estimated: bool = False
    metrics: PortfolioMetrics | None
    n_scored: int | None = None


class PortfolioOrigin(BaseModel):
    origin_date: str
    label: str
    cutoff_ts: str
    entry_date: str | None
    exit_date: str | None
    benchmarks: dict[str, PortfolioSeries]
    visa_strategy: PortfolioSeries
    visa_buy_and_hold: PortfolioSeries


class PortfolioReport(BaseModel):
    suite_version: str
    config: dict[str, Any]
    config_hash: str
    rule_frozen_at: str
    label: str
    labels: dict[str, str]
    n_eligible: int
    n_excluded: int
    aggregates: dict[str, BenchmarkAggregate]
    exclusions: list[ReportExclusion]
    origins: list[PortfolioOrigin]
    overlap: dict[str, int]
    sources: list[dict[str, Any]]
    drift_diagnostic: dict[str, Any]
    visa_strategy: PortfolioSeries
    visa_buy_and_hold: PortfolioSeries


class SavedReportRead(ReportMetadata):
    forecast: ForecastReport | None = None
    ablations: AblationReport | None = None
    portfolio: PortfolioReport | None = None


class ReportCatalog(BaseModel):
    reports: list[ReportMetadata]
    documents: list["DocumentMetadata"]


class DocumentMetadata(BaseModel):
    key: str
    title: str
    filename: str
    status: Literal["available", "pending"]
    owner_issue: str
    reason: str | None = None


class SavedDocumentRead(DocumentMetadata):
    markdown: str | None = None
    # Only explicitly registered document links can become browser navigation.
    document_links: dict[str, str] = Field(default_factory=dict)
