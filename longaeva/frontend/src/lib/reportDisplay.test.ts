import { describe, expect, it } from "vitest"
import {
  coverageLabel,
  extractionRate,
  documentHref,
  fmtScore,
  horizonTarget,
  REPLAY_LABELS,
  scoreAggregate,
  valuationRanges,
} from "./reportDisplay"
import { fmtRatioPct } from "./format"
import type { ValuationBridge } from "./valuationApi"

describe("saved report display", () => {
  it("keeps unscored extraction rates distinct from zero errors", () => {
    expect(extractionRate(null)).toBe("Not scored")
    expect(extractionRate(0)).toBe("0.0%")
    expect(extractionRate(1 / 3)).toBe("33.3%")
  })
  it("distinguishes percentages, percentage points, and dollar scores", () => {
    expect(fmtRatioPct(0.042189)).toBe("4.2%")
    expect(fmtScore(0.042189, "payments_volume_growth_constant")).toBe(
      "4.22 pp",
    )
    expect(fmtScore(196.339, "net_revenue")).toBe("$196.34m")
    expect(fmtScore(null, "net_revenue")).toBe("—")
    expect(fmtScore(0, "processed_transactions_growth")).toBe("0.00 pp")
  })
  it("uses the target's coverage denominator and horizon-specific aggregate", () => {
    const q1 = {
      n: 12,
      covered_k: 5,
      covered_n: 12,
      bias: null,
      mae: null,
      mape: null,
      coverage: null,
      mean_crps: null,
      mean_wis: null,
    }
    const four = { ...q1, n: 13, covered_k: 9, covered_n: 13 }
    const report = {
      aggregates: { overall: { net_revenue: q1 } },
      four_quarter: { net_revenue_sum: four },
    }
    expect(
      coverageLabel(scoreAggregate(report, "q1", "overall", "net_revenue")),
    ).toBe("5 of 12")
    expect(
      coverageLabel(scoreAggregate(report, "4q", "overall", "net_revenue")),
    ).toBe("9 of 13")
    expect(horizonTarget("processed_transactions_growth", "4q")).toBe(
      "processed_transactions_growth",
    )
    expect(
      scoreAggregate(report, "q1", "primary", "net_revenue"),
    ).toBeUndefined()
  })
  it("keeps independent uncertainty ranges and suppresses unsupported values", () => {
    const bridge: Pick<
      ValuationBridge,
      "status" | "earnings_driven" | "multiple_driven"
    > = {
      status: "ok",
      earnings_driven: {
        multiple: 20,
        value_per_share: { p10: 100, p50: 120, p90: 140 },
        equity_usd_millions: {},
        spread_per_share: 40,
        spread_equity_usd_millions: 40,
      },
      multiple_driven: {
        forward_eps: 6,
        value_per_share: { low: 90, mid: 120, high: 180 },
        equity_usd_millions: {},
        spread_per_share: 90,
        spread_equity_usd_millions: 90,
      },
    }
    const ranges = valuationRanges(bridge)
    expect(ranges.map((r) => [r.low, r.mid, r.high])).toEqual([
      [100, 120, 140],
      [90, 120, 180],
    ])
    expect(valuationRanges({ ...bridge, status: "unsupported" })).toEqual([])
  })
  it("names all four replay outcomes distinctly", () => {
    expect(Object.keys(REPLAY_LABELS)).toEqual([
      "exact_match",
      "numerically_equivalent",
      "mismatch",
      "inputs_changed",
    ])
    expect(new Set(Object.values(REPLAY_LABELS)).size).toBe(4)
    expect(REPLAY_LABELS.numerically_equivalent).toContain("hashes differ")
  })
  it("only navigates registered documents, fragments or http links", () => {
    expect(
      documentHref("../docs/model-spec.md", { "model-spec.md": "model-spec" }),
    ).toBe("/evaluation?section=documents&document=model-spec")
    expect(documentHref("javascript:alert(1)", {})).toBeUndefined()
    expect(documentHref("//unknown.example", {})).toBeUndefined()
    expect(documentHref("../data/secret.json", {})).toBeUndefined()
    expect(documentHref("https://www.sec.gov/", {})).toBe(
      "https://www.sec.gov/",
    )
  })
})
