import type { ScoreAggregate, ForecastReport, ReplayReport } from "./reportApi"
import type { ValuationBridge } from "./valuationApi"
import { fmtNumber, fmtRatioPct } from "./format"

export const EVALUATION_TARGETS = [
  "net_revenue",
  "operating_profit_ex_special_items",
  "payments_volume_growth_constant",
  "cross_border_ex_intra_europe_growth_constant",
  "processed_transactions_growth",
] as const
export const TARGET_LABELS: Record<string, string> = {
  net_revenue: "Net revenue (GAAP)",
  operating_profit_ex_special_items: "Operating profit excluding special items",
  payments_volume_growth_constant: "Payments volume growth (constant dollar)",
  cross_border_ex_intra_europe_growth_constant:
    "Cross-border growth (constant dollar, approximate)",
  processed_transactions_growth: "Processed transactions growth",
}
export function horizonTarget(target: string, horizon: string): string {
  return horizon === "4q" &&
    ["net_revenue", "operating_profit_ex_special_items"].includes(target)
    ? `${target}_sum`
    : target
}
export function fmtScore(
  value: number | null | undefined,
  target: string,
): string {
  if (value == null || !Number.isFinite(value)) return "—"
  return target.includes("growth")
    ? `${fmtNumber(value * 100, 2)} pp`
    : `$${fmtNumber(value, 2)}m`
}
export function scoreAggregate(
  report: Pick<ForecastReport, "aggregates" | "four_quarter">,
  horizon: string,
  window: string,
  target: string,
): ScoreAggregate | undefined {
  const key = horizonTarget(target, horizon)
  return horizon === "4q"
    ? report.four_quarter[key]
    : report.aggregates[window]?.[key]
}
export function coverageLabel(row: ScoreAggregate | undefined): string {
  return row ? `${row.covered_k} of ${row.covered_n}` : "—"
}
export function valuationRanges(
  bridge: Pick<
    ValuationBridge,
    "status" | "earnings_driven" | "multiple_driven"
  >,
): { label: string; low: number; mid: number; high: number; held: string }[] {
  if (
    bridge.status !== "ok" ||
    !bridge.earnings_driven ||
    !bridge.multiple_driven
  )
    return []
  const e = bridge.earnings_driven,
    m = bridge.multiple_driven
  return [
    {
      label: "Earnings-driven uncertainty",
      low: e.value_per_share.p10,
      mid: e.value_per_share.p50,
      high: e.value_per_share.p90,
      held: `P/E held at ${fmtNumber(e.multiple)}`,
    },
    {
      label: "Multiple-driven uncertainty",
      low: m.value_per_share.low,
      mid: m.value_per_share.mid,
      high: m.value_per_share.high,
      held: `Forward EPS held at $${fmtNumber(m.forward_eps)}`,
    },
  ]
}
export const REPLAY_LABELS: Record<ReplayReport["status"], string> = {
  exact_match: "Exact hash match",
  numerically_equivalent: "Numerically equivalent — hashes differ",
  mismatch: "Output mismatch",
  inputs_changed: "Pinned inputs have changed",
}
export const fmtReturn = fmtRatioPct
export function documentHref(
  href: string | undefined,
  links: Record<string, string>,
): string | undefined {
  if (!href) return undefined
  if (/^https?:\/\//i.test(href) || href.startsWith("#")) return href
  if (/^[a-z][a-z\d+.-]*:/i.test(href) || href.startsWith("//"))
    return undefined
  const [path, fragment] = href.split("#")
  const key = links[path.split("/").pop() ?? ""]
  return key
    ? `/evaluation?section=documents&document=${encodeURIComponent(key)}${fragment ? `#${fragment}` : ""}`
    : undefined
}
