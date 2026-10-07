"""Read-only, bounded projections of saved evaluation artifacts (LON-36)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ReportMetadata(BaseModel):
    key: str
    title: str
    kind: Literal["forecast", "ablations", "portfolio", "extraction", "prospective", "pending"]
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


class ExtractionErrorRate(BaseModel):
    errors: int
    denominator: int
    rate: float | None


class ExtractionCoverage(BaseModel):
    total_passages: int
    succeeded_passages: int
    failed_passages: int
    missing_passages: int
    total_labels: int
    disputed_labels: int
    scored_labels: int
    unavailable_labels: int
    matched_labels: int
    correct_labels: int
    predictions: int


class ExtractionReview(BaseModel):
    status: Literal["pending", "reviewed"]
    author: str
    reviewer: str | None
    reviewed_labels: int
    selected_label_ids: list[str]
    decisions: list[dict[str, Any]]


class ExtractionDisagreement(BaseModel):
    label_id: str | None
    passage_id: str
    company: str
    family: str
    categories: list[str]
    errors: list[str]
    expected: dict[str, Any] | None
    actual: dict[str, Any] | None
    source_url: str
    page: int
    rationale: str


class ExtractionFailure(BaseModel):
    passage_id: str
    family: str
    status: str
    error: str | None


class ExtractionCallMetadata(BaseModel):
    passage_id: str
    extraction_call_id: str
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str
    status: str
    error: str | None
    item_errors: list[dict[str, Any]]
    attempts: int
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: str
    cache_hit: bool
    source_sha256: str
    text_sha256: str


class ExtractionReport(BaseModel):
    suite_version: str
    content_hash: str
    corpus_hash: str
    provider: str
    model: str
    prompt_version: str
    numeric_tolerance: float
    coverage: ExtractionCoverage
    review: ExtractionReview
    errors: dict[str, ExtractionErrorRate]
    by_family: dict[str, dict[str, ExtractionErrorRate]]
    by_category: dict[str, dict[str, ExtractionErrorRate]]
    failures: list[ExtractionFailure]
    disagreements: list[ExtractionDisagreement]
    calls: list[ExtractionCallMetadata]
    limitations: list[str]


class ProspectiveMetric(BaseModel):
    metric: str
    period_label: str
    target_period_start: str
    target_period_end: str
    quantiles: dict[str, float]
    unit: str
    basis: str
    growth_convention: str


class ProspectiveReport(BaseModel):
    kind: Literal["prospective"]
    target: Literal["FY2026Q4"]
    scoring_status: Literal["Not yet scored"]
    cutoff_ts: str
    registered_at: str
    run_id: str
    n_paths: int
    n_quarters: int
    seed: int
    content_hash: str
    outputs_hash: str
    parameter_set_hash: str
    source_manifest_hash: str
    code_version: str
    lib_versions: dict[str, Any]
    replay_status: Literal["exact_match"]
    publication_check_url: str
    publication_checked_at: str
    forecasts: list[ProspectiveMetric]


class SavedReportRead(ReportMetadata):
    forecast: ForecastReport | None = None
    ablations: AblationReport | None = None
    portfolio: PortfolioReport | None = None
    extraction: ExtractionReport | None = None
    prospective: ProspectiveReport | None = None


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
