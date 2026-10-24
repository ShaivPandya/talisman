import type { AgentChartPart, AgentProposalPart, ChartYFormat } from "./agentChatShared"

const Y_FORMATS: ReadonlySet<string> = new Set<ChartYFormat>(["price", "percent", "yield", "ratio", "number"])
const CHART_KINDS: ReadonlySet<string> = new Set<AgentChartPart["kind"]>(["line", "curve", "bars"])

function text(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined
}

/** A chart as the API sends it (snake_case), or null when it can't be drawn. */
export function normalizeChart(value: unknown): AgentChartPart | null {
  if (!value || typeof value !== "object") return null
  const rec = value as Record<string, unknown>
  const id = text(rec.id)
  const kind = text(rec.kind)
  const xKey = text(rec.x_key)
  if (!id || !kind || !CHART_KINDS.has(kind) || !xKey || !Array.isArray(rec.series) || !Array.isArray(rec.rows)) return null
  const series = rec.series.flatMap(item => {
    const s = item as Record<string, unknown> | null
    const key = text(s?.key)
    return key ? [{ key, name: text(s?.name) ?? key }] : []
  })
  const rows = rec.rows.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
  if (!series.length || !rows.length) return null
  return {
    id,
    tool: text(rec.tool) ?? "",
    kind: kind as AgentChartPart["kind"],
    title: text(rec.title) ?? "Chart",
    subtitle: text(rec.subtitle),
    asOf: text(rec.as_of),
    xKey,
    yFormat: Y_FORMATS.has(String(rec.y_format)) ? (rec.y_format as ChartYFormat) : "number",
    unit: text(rec.unit),
    series,
    rows,
    sampledFrom: typeof rec.sampled_from === "number" ? rec.sampled_from : undefined,
  }
}

export function normalizeCharts(value: unknown): AgentChartPart[] {
  return Array.isArray(value) ? value.flatMap(item => normalizeChart(item) ?? []) : []
}

export function normalizeProposal(value: unknown): AgentProposalPart | null {
  if (!value || typeof value !== "object") return null
  const rec = value as Record<string, unknown>
  const id = text(rec.id)
  const approvalId = text(rec.approval_id)
  if (!id || !approvalId) return null
  return {
    id,
    tool: text(rec.tool) ?? "",
    approvalId,
    entityType: text(rec.entity_type),
    ticker: text(rec.ticker),
  }
}

export function normalizeProposals(value: unknown): AgentProposalPart[] {
  return Array.isArray(value) ? value.flatMap(item => normalizeProposal(item) ?? []) : []
}

/** Suggested questions: saved messages hold `{ text }` objects, the suggestions endpoint plain strings. */
export function normalizeSuggestions(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.flatMap(item => {
    const question = typeof item === "string" ? item : text((item as Record<string, unknown> | null)?.text)
    return question?.trim() ? [question.trim()] : []
  })
}

/** Adds the part, or replaces the one with the same id (a retried model call repeats its tool calls). */
export function upsertById<T extends { id: string }>(existing: T[] | undefined, part: T | null): T[] | undefined {
  if (!part) return existing
  const parts = existing ?? []
  return parts.some(item => item.id === part.id)
    ? parts.map(item => (item.id === part.id ? part : item))
    : [...parts, part]
}
