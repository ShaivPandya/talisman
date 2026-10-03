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

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`)
  const contentType = response.headers.get("content-type") ?? ""
  const body: unknown = contentType.includes("application/json")
    ? await response.json()
    : await response.text()
  if (!response.ok) {
    const detail = typeof body === "string" && body ? body : detailFromBody(body)
    throw new ApiError(response.status, detail)
  }
  return body as T
}

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
