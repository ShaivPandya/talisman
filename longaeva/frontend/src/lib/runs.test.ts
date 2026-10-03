import { describe, expect, it } from "vitest"

import type { RunResultSummary } from "./api"
import { summariesForMetric, toDriverGrowthRows, toFanRows, uniqueMetrics } from "./runs"

function row(
  metric: string,
  quarter_index: number,
  period_label: string,
  extras?: Partial<RunResultSummary>,
): RunResultSummary {
  return {
    metric,
    quarter_index,
    period_label,
    mean: 100 + quarter_index,
    std: 10,
    std_error: 1,
    quantiles: {
      "0.05": 80,
      "0.1": 85,
      "0.25": 90,
      "0.5": 100,
      "0.75": 110,
      "0.9": 115,
      "0.95": 120,
    },
    quantile_std_errors: {},
    ...extras,
  }
}

describe("run summaries", () => {
  const summaries: RunResultSummary[] = [
    row("net_revenue", 1, "FY2025Q1"),
    row("net_revenue", 0, "FY2024Q4"),
    row("operating_profit_ex_special_items", 0, "FY2024Q4"),
    row("payments_volume_growth_constant", 0, "FY2024Q4", {
      quantiles: { "0.5": 0.1, "0.05": 0, "0.1": 0, "0.25": 0, "0.75": 0, "0.9": 0, "0.95": 0 },
    }),
    row("processed_transactions_growth", 0, "FY2024Q4", {
      quantiles: { "0.5": 0.05, "0.05": 0, "0.1": 0, "0.25": 0, "0.75": 0, "0.9": 0, "0.95": 0 },
    }),
  ]

  it("orders fan rows by quarter_index", () => {
    const fan = toFanRows(summaries, "net_revenue")
    expect(fan.map((item) => item.period)).toEqual(["FY2024Q4", "FY2025Q1"])
    expect(fan[0]?.p50).toBe(100)
    expect(fan[0]?.span05_95).toBe(40)
  })

  it("skips metrics without a complete quantile set", () => {
    const incomplete = row("net_revenue", 2, "FY2025Q2", { quantiles: { "0.5": 1 } })
    expect(toFanRows([...summaries, incomplete], "net_revenue")).toHaveLength(2)
  })

  it("lists unique metrics and filters by metric", () => {
    expect(uniqueMetrics(summaries)).toEqual([
      "net_revenue",
      "operating_profit_ex_special_items",
      "payments_volume_growth_constant",
      "processed_transactions_growth",
    ])
    expect(summariesForMetric(summaries, "missing")).toEqual([])
  })

  it("builds driver-growth median rows", () => {
    const growth = toDriverGrowthRows(summaries)
    expect(growth).toHaveLength(2)
    expect(growth[0]?.period).toBe("FY2024Q4")
    expect(growth[0]?.payments_volume_growth_constant).toBe(0.1)
    expect(growth[0]?.processed_transactions_growth).toBe(0.05)
    expect(growth[0]?.cross_border_ex_intra_europe_growth_constant).toBeNull()
  })
})
