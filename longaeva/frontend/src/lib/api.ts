export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

export interface HealthResponse {
  status: string
  database: string
  alembic_revision: string | null
  detail: string | null
}

export interface ScenarioRead {
  id: string
  company: string
  name: string
  parameter_set_id: string
  interventions: unknown[]
  pair_group_id: string | null
  created_at: string
}

export interface RunRead {
  id: string
  scenario_id: string
  job_id: string | null
  cutoff_ts: string
  origin_label: string
  n_quarters: number
  source_manifest: unknown[]
  source_manifest_hash: string
  parameter_set_hash: string
  starting_state_hash: string
  code_version: string
  seed: number
  n_paths: number
  switches: Record<string, unknown>
  baseline_run_id: string | null
  interventions: Intervention[]
  interventions_hash: string
  lib_versions: Record<string, unknown>
  status: string
  outputs_path: string | null
  outputs_hash: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface RunResultSummary {
  metric: string
  quarter_index: number
  period_label: string
  mean: number
  std: number
  std_error: number | null
  quantiles: Record<string, number>
  quantile_std_errors: Record<string, number>
}

function detailFromBody(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === "string") return detail
    if (Array.isArray(detail)) return JSON.stringify(detail)
    if (detail != null) return String(detail)
  }
  return "Request failed"
}

export async function apiGet<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = options
    ? await fetch(`/api${path}`, options)
    : await fetch(`/api${path}`)
  const contentType = response.headers.get("content-type") ?? ""
  const body: unknown = contentType.includes("application/json")
    ? await response.json()
    : await response.text()
  if (!response.ok) {
    const detail =
      typeof body === "string" && body ? body : detailFromBody(body)
    throw new ApiError(response.status, detail)
  }
  return body as T
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiGet(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export type Intervention =
  | {
      type: "mix_shift_conserving_total"
      cross_border_change: number
      start_quarter: number
    }
  | { type: "total_spend_reduction"; reduction: number; start_quarter: number }

export interface EvidenceLink {
  observation_ids: string[]
  assumption: boolean
  rationale: string | null
}
export interface ParameterSetRead {
  id: string
  company: string
  cutoff_ts: string
  values: Record<string, number>
  ranges: Record<string, [number, number]>
  evidence_links: Record<string, EvidenceLink>
  assumption_flags: Record<string, unknown>
  content_hash: string
  parent_id: string | null
}
export interface ParameterSpec {
  name: string
  unit: string
  lower: number
  upper: number
  default: number
  role: string
  description: string
}
export interface WorkspaceOrigin {
  origin_date: string
  cutoff_ts: string
  label: string
}
export interface SourceRef {
  source_id: string
  document: string
  form: string
  acceptance_utc: string
  url: string
  role: string
  note: string
}
export interface StateValue {
  name: string
  status: string
  value: number | null
  unit: string
  basis: string
  period_label: string | null
  period_start: string | null
  period_end: string | null
  source_id: string | null
  unavailable_reason: string | null
  note: string
  derivation: {
    formula: string
    inputs: Record<string, number>
    rounding_band: number | null
  } | null
}
export interface EvidenceExcerpt {
  source_id: string | null
  observation_id: string | null
  document_text_id: string | null
  url: string | null
  publication_ts: string | null
  content_hash: string | null
  page: number | null
  char_start: number | null
  char_end: number | null
  before: string
  quote: string
  after: string
  unavailable_reason: string | null
}
export interface WorkspaceState extends WorkspaceOrigin {
  values: Record<string, StateValue>
  supporting_levels: Record<string, Omit<StateValue, "name"> & { key: string }>
  evidence: Record<string, EvidenceExcerpt>
  sources: Record<string, SourceRef>
  post_cutoff_sources: Record<string, SourceRef>
  parameter_specs: ParameterSpec[]
  notes: string[]
}
export interface ParameterUpdate {
  id: string
  rule_id: string | null
  rule_key: string | null
  rule_version: number | null
  before_value: Record<string, unknown>
  after_value: Record<string, unknown>
  size: number | null
  rationale: string
}
export interface ParameterEvidenceRead {
  parameter: string
  evidence: EvidenceLink
  excerpts: EvidenceExcerpt[]
  updates: ParameterUpdate[]
}
export interface ComparisonRow {
  metric: string
  quarter_index: number
  period_label: string
  baseline_mean: number
  variant_mean: number
  difference_mean: number
  difference_std: number
  difference_std_error: number | null
  quantiles: Record<string, number>
  quantile_std_errors: Record<string, number>
}
export interface ComparisonRead {
  run_id: string
  baseline_run_id: string
  seed: number
  items: ComparisonRow[]
}
export interface QuarterEffect {
  quarter_index: number
  period_label: string
  mean_difference: number
}
export interface ProvenanceIds {
  rule_ids: string[]
  source_ids: string[]
  observation_ids: string[]
}
export interface Contribution extends ProvenanceIds {
  kind: "parameter" | "intervention"
  name: string
  key: string
  label: string
  before: number | null
  after: number | null
  size: number | null
  intervention: Intervention | null
  by_metric: Record<
    string,
    {
      one_at_a_time: QuarterEffect[]
      sequential: QuarterEffect[]
      one_at_a_time_horizon: number
      sequential_horizon: number
    }
  >
}
export interface Sensitivity extends ProvenanceIds {
  parameter: string
  range_low: number
  range_high: number
  swing: number
  normalized_sensitivity: number
  support_score: number
  flag: string | null
}
export interface AttributionRead {
  run_id: string
  baseline_run_id: string
  conditional_on_model: boolean
  order_note: string
  sequential_order: string[]
  metrics: {
    metric: string
    total: QuarterEffect[]
    horizon_total: number
    joint_residual: QuarterEffect[]
    joint_residual_horizon: number
  }[]
  contributions: Contribution[]
  sensitivity: Sensitivity[]
  sensitivity_metric: string
  verification: string[]
}
export interface ScenarioCreate {
  company: string
  name: string
  parameter_set_id: string
  pair_group_id: string
  interventions: Intervention[]
  parameter_overrides: Record<string, { value: number; rationale: string }>
}
export interface PairRunsCreate {
  scenario_ids: string[]
  baseline_scenario_id: string
  cutoff_ts: string
  seed: number
  n_paths: number
  n_quarters: number
}

export const listOrigins = () => apiGet<WorkspaceOrigin[]>("/workspace/origins")
export const getWorkspace = (origin: string) =>
  apiGet<WorkspaceState>(`/workspace/origins/${encodeURIComponent(origin)}`)
export const prepareOrigin = (origin: string) =>
  apiPost<ParameterSetRead>(
    `/workspace/origins/${encodeURIComponent(origin)}/prepare`,
  )
export const getScenario = (id: string) =>
  apiGet<ScenarioRead>(`/scenarios/${id}`)
export const getParameterSet = (id: string) =>
  apiGet<ParameterSetRead>(`/parameter-sets/${id}`)
export const getParameterEvidence = (id: string, parameter: string) =>
  apiGet<ParameterEvidenceRead>(
    `/parameter-sets/${id}/evidence?parameter=${encodeURIComponent(parameter)}`,
  )
export const createScenario = (body: ScenarioCreate) =>
  apiPost<ScenarioRead>("/scenarios", body)
export const createPairRuns = (body: PairRunsCreate) =>
  apiPost<RunRead[]>("/scenarios/pair-runs", body)
export const getComparison = (run: string, baseline: string) =>
  apiGet<ComparisonRead>(
    `/scenarios/comparison?run_id=${run}&baseline_run_id=${baseline}`,
  )
export const getAttribution = (run: string, baseline: string) =>
  apiGet<AttributionRead>(
    `/scenarios/attribution?run_id=${run}&baseline_run_id=${baseline}`,
  )

export function getHealth(): Promise<HealthResponse> {
  return apiGet("/health")
}

export function listRuns(limit = 50): Promise<RunRead[]> {
  return apiGet(`/runs?limit=${limit}`)
}

export function getRun(runId: string): Promise<RunRead> {
  return apiGet(`/runs/${runId}`)
}

export function getRunResults(runId: string): Promise<RunResultSummary[]> {
  return apiGet(`/runs/${runId}/results`)
}

export function listScenarios(): Promise<ScenarioRead[]> {
  return apiGet("/scenarios")
}

export function isActiveRunStatus(status: string): boolean {
  return status === "queued" || status === "running"
}
