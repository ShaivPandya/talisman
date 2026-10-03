import type { RunResultSummary } from "./api"

export const QUANTILE_KEYS = ["0.05", "0.1", "0.25", "0.5", "0.75", "0.9", "0.95"] as const

export interface FanRow {
  period: string
  quarterIndex: number
  mean: number
  std: number
  stdError: number | null
  p05: number
  p10: number
  p25: number
  p50: number
  p75: number
  p90: number
  p95: number
  band05: number
  band10: number
  band25: number
  span05_95: number
  span10_90: number
  span25_75: number
}

export interface DriverGrowthRow {
  [key: string]: string | number | null
  period: string
  quarterIndex: number
  payments_volume_growth_constant: number | null
  cross_border_ex_intra_europe_growth_constant: number | null
  processed_transactions_growth: number | null
}

function quantile(row: RunResultSummary, key: string): number | null {
  const value = row.quantiles[key]
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

export function summariesForMetric(
  summaries: readonly RunResultSummary[],
  metric: string,
): RunResultSummary[] {
  return summaries
    .filter((row) => row.metric === metric)
    .slice()
    .sort((a, b) => a.quarter_index - b.quarter_index)
}

export function uniqueMetrics(summaries: readonly RunResultSummary[]): string[] {
  return [...new Set(summaries.map((row) => row.metric))]
}

export function toFanRows(summaries: readonly RunResultSummary[], metric: string): FanRow[] {
  const rows: FanRow[] = []
  for (const item of summariesForMetric(summaries, metric)) {
    const p05 = quantile(item, "0.05")
    const p10 = quantile(item, "0.1")
    const p25 = quantile(item, "0.25")
    const p50 = quantile(item, "0.5")
    const p75 = quantile(item, "0.75")
    const p90 = quantile(item, "0.9")
    const p95 = quantile(item, "0.95")
    if (p05 == null || p10 == null || p25 == null || p50 == null || p75 == null || p90 == null || p95 == null) {
      continue
    }
    rows.push({
      period: item.period_label,
      quarterIndex: item.quarter_index,
      mean: item.mean,
      std: item.std,
      stdError: item.std_error,
      p05,
      p10,
      p25,
      p50,
      p75,
      p90,
      p95,
      band05: p05,
      band10: p10,
      band25: p25,
      span05_95: p95 - p05,
      span10_90: p90 - p10,
      span25_75: p75 - p25,
    })
  }
  return rows
}

export function toDriverGrowthRows(summaries: readonly RunResultSummary[]): DriverGrowthRow[] {
  const periods = new Map<string, DriverGrowthRow>()
  for (const item of summaries) {
    let row = periods.get(item.period_label)
    if (row == null) {
      row = {
        period: item.period_label,
        quarterIndex: item.quarter_index,
        payments_volume_growth_constant: null,
        cross_border_ex_intra_europe_growth_constant: null,
        processed_transactions_growth: null,
      }
      periods.set(item.period_label, row)
    }
    const median = quantile(item, "0.5")
    if (item.metric === "payments_volume_growth_constant") {
      row.payments_volume_growth_constant = median
    } else if (item.metric === "cross_border_ex_intra_europe_growth_constant") {
      row.cross_border_ex_intra_europe_growth_constant = median
    } else if (item.metric === "processed_transactions_growth") {
      row.processed_transactions_growth = median
    }
  }
  return [...periods.values()].sort((a, b) => a.quarterIndex - b.quarterIndex)
}
