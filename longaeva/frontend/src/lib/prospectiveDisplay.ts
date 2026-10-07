import type { ProspectiveMetric } from "./reportApi"

export function prospectiveValue(row: Pick<ProspectiveMetric, "unit" | "quantiles">, quantile: string): string {
  const value = row.quantiles[quantile]
  if (value == null || !Number.isFinite(value)) return "Unavailable"
  return row.unit === "ratio"
    ? `${(value * 100).toFixed(2)}%`
    : value.toLocaleString("en-US", { maximumFractionDigits: 1 })
}
