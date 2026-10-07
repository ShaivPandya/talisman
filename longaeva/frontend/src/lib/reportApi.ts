import { apiGet, apiPost } from "./api"

export interface ReportMetadata {
  key: string
  title: string
  kind: "forecast" | "ablations" | "portfolio" | "extraction" | "prospective" | "pending"
  status: "available" | "pending"
  reason: string | null
  owner_issue: string
}
export interface DocumentMetadata {
  key: string
  title: string
  filename: string
  status: "available" | "pending"
  reason: string | null
  owner_issue: string
}
export interface ScoreAggregate {
  n: number
  bias: number | null
  mae: number | null
  mape: number | null
  coverage: string | null
  covered_k: number
  covered_n: number
  mean_crps: number | null
  mean_wis: number | null
}
export interface OriginScore {
  origin_date: string
  label: string
  window: string
  run_id: string | null
  error: string | null
  scores: Record<string, number>
  skipped_drivers: Record<string, string>
}
export interface ForecastReport {
  config: Record<string, unknown>
  config_hash: string
  n_scored: number
  n_excluded: number
  exclusions: { origin_date: string; label: string | null; reason: string }[]
  aggregates: Record<string, Record<string, ScoreAggregate>>
  four_quarter: Record<string, ScoreAggregate>
  origins: OriginScore[]
}
export interface AblationComparison {
  n: number
  full_wins: number
  ablated_wins: number
  ties: number
  mean_ablated_minus_full: number
  full_covered: number
  ablated_covered: number
  full_coverage: number
  ablated_coverage: number
}
export interface AblationReport {
  suite_version: string
  content_hash: string
  delta_convention: string
  profile_policy: string
  settings: Record<string, Record<string, string | number>>
  summaries: Record<string, Record<string, AblationComparison>>
  robustness: Record<
    string,
    {
      profiles: number
      full_better: number
      ablated_better: number
      ties: number
    }
  >
  config_hashes: Record<string, Record<string, string>>
}
export interface PortfolioSeries {
  status: string
  label: string | null
  reason: string | null
  estimated: boolean
  metrics: {
    total_return: number
    max_drawdown: number
    average_invested_exposure: number
  } | null
  n_scored: number | null
}
export interface PortfolioReport {
  suite_version: string
  config: Record<string, unknown>
  config_hash: string
  rule_frozen_at: string
  label: string
  labels: Record<string, string>
  n_eligible: number
  n_excluded: number
  aggregates: Record<
    string,
    {
      n_scored: number
      n_unavailable: number
      n_estimated: number
      mean_return: number | null
      worst_window_drawdown: number | null
    }
  >
  exclusions: { origin_date: string; label: string | null; reason: string }[]
  origins: {
    origin_date: string
    label: string
    cutoff_ts: string
    entry_date: string | null
    exit_date: string | null
    benchmarks: Record<string, PortfolioSeries>
    visa_strategy: PortfolioSeries
    visa_buy_and_hold: PortfolioSeries
  }[]
  overlap: Record<string, number>
  sources: Record<string, unknown>[]
  drift_diagnostic: Record<string, unknown>
  visa_strategy: PortfolioSeries
  visa_buy_and_hold: PortfolioSeries
}
export interface ExtractionErrorRate {
  errors: number
  denominator: number
  rate: number | null
}
export interface ExtractionObservation {
  statement_type: string
  activity_type: string | null
  geography: string | null
  period_start: string
  period_end: string
  value: number | null
  range_low: number | null
  range_high: number | null
  unit: string
  basis: string | null
  quote: string
}
export interface ExtractionReport {
  suite_version: string
  content_hash: string
  corpus_hash: string
  provider: string
  model: string
  prompt_version: string
  numeric_tolerance: number
  coverage: {
    total_passages: number
    succeeded_passages: number
    failed_passages: number
    missing_passages: number
    total_labels: number
    disputed_labels: number
    scored_labels: number
    unavailable_labels: number
    matched_labels: number
    correct_labels: number
    predictions: number
  }
  review: {
    status: "pending" | "reviewed"
    author: string
    reviewer: string | null
    reviewed_labels: number
    selected_label_ids: string[]
    decisions: Record<string, unknown>[]
  }
  errors: Record<string, ExtractionErrorRate>
  by_family: Record<string, Record<string, ExtractionErrorRate>>
  by_category: Record<string, Record<string, ExtractionErrorRate>>
  failures: { passage_id: string; family: string; status: string; error: string | null }[]
  disagreements: {
    label_id: string | null
    passage_id: string
    company: string
    family: string
    categories: string[]
    errors: string[]
    expected: ExtractionObservation | null
    actual: ExtractionObservation | null
    source_url: string
    page: number
    rationale: string
  }[]
  calls: {
    passage_id: string
    extraction_call_id: string
    provider: string
    model: string
    prompt_version: string
    prompt_hash: string
    status: string
    error: string | null
    attempts: number
    cache_hit: boolean
    input_tokens: number | null
    output_tokens: number | null
    source_sha256: string
    text_sha256: string
    created_at: string
  }[]
  limitations: string[]
}
export interface ProspectiveMetric {
  metric: string
  period_label: string
  target_period_start: string
  target_period_end: string
  quantiles: Record<string, number>
  unit: string
  basis: string
  growth_convention: string
}
export interface ProspectiveReport {
  kind: "prospective"
  target: "FY2026Q4"
  scoring_status: "Not yet scored"
  cutoff_ts: string
  registered_at: string
  run_id: string
  n_paths: number
  n_quarters: number
  seed: number
  content_hash: string
  outputs_hash: string
  parameter_set_hash: string
  source_manifest_hash: string
  code_version: string
  lib_versions: Record<string, unknown>
  replay_status: "exact_match"
  publication_check_url: string
  publication_checked_at: string
  forecasts: ProspectiveMetric[]
}
export interface SavedReport extends ReportMetadata {
  forecast: ForecastReport | null
  ablations: AblationReport | null
  portfolio: PortfolioReport | null
  extraction: ExtractionReport | null
  prospective: ProspectiveReport | null
}
export interface ReportCatalog {
  reports: ReportMetadata[]
  documents: DocumentMetadata[]
}
export interface SavedDocument extends DocumentMetadata {
  markdown: string | null
  document_links: Record<string, string>
}
export interface ReplayReport {
  run_id: string
  status:
    | "exact_match"
    | "numerically_equivalent"
    | "mismatch"
    | "inputs_changed"
  recorded_outputs_hash: string
  recomputed_outputs_hash: string | null
  max_relative_difference: number | null
  recorded_code_version: string
  recomputed_code_version: string | null
  recorded_lib_versions: Record<string, unknown>
  recomputed_lib_versions: Record<string, unknown> | null
  differences: string[]
  llm_provider: string
}
export const getReportCatalog = () =>
  apiGet<ReportCatalog>("/evaluation/reports")
export const getSavedReport = (key: string) =>
  apiGet<SavedReport>(`/evaluation/reports/${encodeURIComponent(key)}`)
export const getSavedDocument = (key: string) =>
  apiGet<SavedDocument>(`/evaluation/documents/${encodeURIComponent(key)}`)
export const replayRun = (id: string) =>
  apiPost<ReplayReport>(`/runs/${encodeURIComponent(id)}/replay`)
