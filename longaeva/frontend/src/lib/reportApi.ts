import { apiGet, apiPost } from "./api"

export interface ReportMetadata {
  key: string
  title: string
  kind: "forecast" | "ablations" | "portfolio" | "pending"
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
export interface SavedReport extends ReportMetadata {
  forecast: ForecastReport | null
  ablations: AblationReport | null
  portfolio: PortfolioReport | null
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
