import {
  apiGet,
  apiPost,
  type EvidenceExcerpt,
  type ParameterSetRead,
  type ParameterUpdate,
} from "./api"

export type Decision = "accept" | "correct" | "reject"
export const semanticFields = [
  "statement_type",
  "activity_type",
  "geography",
  "period_start",
  "period_end",
  "value",
  "range_low",
  "range_high",
  "unit",
  "basis",
] as const
export type SemanticField = (typeof semanticFields)[number]
export type SemanticValues = Record<SemanticField, string | number | null>
export interface Observation extends SemanticValues {
  id: string
  company: string
  source_id: string | null
  document_text_id: string | null
  source_family: string | null
  review_status: string
  attributes: Record<string, unknown>
}
export interface ReviewDecision {
  id: string
  decision: Decision
  version: number
  corrected_payload: Partial<SemanticValues> | null
  rationale: string
  decided_at: string
  decided_by: string
}
export interface ObservationReview {
  observation: Observation
  decisions: ReviewDecision[]
  effective: SemanticValues | null
}
export interface ReviewRequest {
  observation_id: string
  decision: Decision
  decided_by: string
  rationale: string
  corrected_payload?: SemanticValues
}
export interface PassageHit {
  document_text_id: string
  source_id: string
  page: number
  char_start: number
  char_end: number
  text: string
  snippet: string
  company: string
  doc_type: string
  url: string
  publication_ts: string
  period_start: string | null
  period_end: string | null
}
export interface PassageSearch {
  hits: PassageHit[]
  cutoff_ts: string | null
}
export interface ContextItem {
  observation_id: string
  reason: string
  rule_key: string | null
  rule_id: string | null
}
export interface RuleUpdate extends Omit<ParameterUpdate, "id"> {
  target_parameter: string
  observation_id?: string
  observation_ids?: string[]
  assumption?: boolean
}
export interface RuleApplication {
  parameter_set_id: string
  result_parameter_set_id: string | null
  changed: boolean
  created: boolean
  updates: RuleUpdate[]
  context: ContextItem[]
}
export interface RuleRequest {
  observation_ids: string[]
  decided_by: string
  rationale: string
}
export interface MappingRule {
  id: string
  rule_key: string
  version: number
  kind: string
  target_parameter: string | null
  transform: Record<string, unknown>
  rationale: string
}
export type Filters = Record<string, string | number | undefined>
export function queryString(filters: Filters): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && String(value).trim() !== "")
      params.set(key, String(value).trim())
  }
  return params.toString()
}
export const listObservations = (filters: Filters) =>
  apiGet<Observation[]>(`/observations?${queryString(filters)}`)
export const getReview = (id: string) =>
  apiGet<ObservationReview>(`/observations/${encodeURIComponent(id)}/review`)
export const getObservationEvidence = (id: string, cutoff: string) =>
  apiGet<EvidenceExcerpt>(
    `/observations/${encodeURIComponent(id)}/evidence?${queryString({ cutoff_ts: cutoff })}`,
  )
export const saveReview = (body: ReviewRequest) =>
  apiPost<ReviewDecision>("/review-decisions", body)
export const searchPassages = (filters: Filters) =>
  apiGet<PassageSearch>(`/search/passages?${queryString(filters)}`)
export const listParameterSets = () =>
  apiGet<ParameterSetRead[]>("/parameter-sets?company=visa&limit=200")
export const previewRules = (id: string, body: RuleRequest) =>
  apiPost<RuleApplication>(
    `/parameter-sets/${encodeURIComponent(id)}/rule-preview`,
    body,
  )
export const applyRules = (id: string, body: RuleRequest) =>
  apiPost<RuleApplication>(
    `/parameter-sets/${encodeURIComponent(id)}/apply-rules`,
    body,
  )
export const getUpdates = (id: string) =>
  apiGet<RuleUpdate[]>(`/parameter-sets/${encodeURIComponent(id)}/updates`)
export const getContext = (id: string) =>
  apiGet<ContextItem[]>(`/parameter-sets/${encodeURIComponent(id)}/context`)
export const getLineage = (id: string) =>
  apiGet<ParameterSetRead[]>(
    `/parameter-sets/${encodeURIComponent(id)}/lineage`,
  )
export const getMappingRule = (id: string) =>
  apiGet<MappingRule>(`/mapping-rules/${encodeURIComponent(id)}`)

export function correctionDraft(
  review: ObservationReview,
): Record<SemanticField, string> {
  // Include prior corrections even when the latest decision is reject (effective=null).
  const correction = [...review.decisions]
    .reverse()
    .find((item) => item.corrected_payload)?.corrected_payload
  const values = { ...review.observation, ...correction, ...review.effective }
  return Object.fromEntries(
    semanticFields.map((key) => [
      key,
      values[key] == null ? "" : String(values[key]),
    ]),
  ) as Record<SemanticField, string>
}
export function correctionPayload(
  draft: Record<SemanticField, string>,
): SemanticValues {
  const result = {} as SemanticValues
  for (const key of semanticFields) {
    const value = draft[key].trim()
    if (["value", "range_low", "range_high"].includes(key)) {
      const number = value === "" ? null : Number(value)
      if (number !== null && !Number.isFinite(number))
        throw new Error(`${key} must be a finite number.`)
      result[key] = number
    } else result[key] = value || null
  }
  if (
    !result.statement_type ||
    !result.unit ||
    !result.period_start ||
    !result.period_end
  )
    throw new Error("Statement type, unit and both period dates are required.")
  if (String(result.period_start) > String(result.period_end))
    throw new Error("Period start must be on or before period end.")
  if (
    result.range_low !== null &&
    result.range_high !== null &&
    Number(result.range_low) > Number(result.range_high)
  )
    throw new Error("Range low must be on or below range high.")
  return result
}
export const reviewVersion = (review: ObservationReview) =>
  review.decisions.at(-1)?.version ?? 0
export const previewKey = (
  base: string,
  observation: string,
  version: number,
  reviewer: string,
  rationale: string,
) =>
  JSON.stringify([
    base,
    observation,
    version,
    reviewer.trim(),
    rationale.trim(),
  ])
export const sameCutoff = (a: string, b: string) =>
  Number.isFinite(Date.parse(a)) && Date.parse(a) === Date.parse(b)
