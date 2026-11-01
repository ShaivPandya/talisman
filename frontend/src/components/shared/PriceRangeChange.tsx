import { cn } from "@/lib/utils"

/** Price change between the first and last valid closes actually shown in the chart. */
export function PriceRangeChange({ rows, lookback }: { rows: readonly Record<string, unknown>[]; lookback: string }) {
  let first: { time: number; price: number; date: string } | undefined
  let last: typeof first
  for (const row of rows) {
    if (row.Close == null || row.Close === "") continue
    const price = Number(row.Close)
    const date = String(row.date ?? "")
    const time = Date.parse(date)
    if (!Number.isFinite(price) || !Number.isFinite(time)) continue
    const point = { time, price, date: date.slice(0, 10) }
    if (!first || time < first.time) first = point
    if (!last || time > last.time) last = point
  }
  const raw = first && last && last.time > first.time && first.price > 0 ? (last.price / first.price - 1) * 100 : null
  const change = raw != null && Number.isFinite(raw) ? Math.round(raw * 100) / 100 : null
  return (
    <span
      className={cn("text-sm font-semibold tabular-nums", change == null || change === 0 ? "text-muted" : change > 0 ? "text-positive" : "text-negative")}
      title={first && last ? `Price change over available history: ${first.date} to ${last.date}` : "At least two valid closes are needed"}
      data-testid="price-range-change"
    >
      {lookback} change: {change == null ? "N/A" : `${change > 0 ? "+" : ""}${change.toFixed(2)}%`}
    </span>
  )
}
