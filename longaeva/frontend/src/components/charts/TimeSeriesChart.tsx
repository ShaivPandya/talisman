import { useMemo, useState } from "react"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { LegendPayload, YAxisOrientation } from "recharts"

export interface SeriesDef {
  key: string
  name?: string
  color?: string
  strokeWidth?: number
  opacity?: number
  strokeDasharray?: string
}

interface TimeSeriesChartProps {
  data?: Record<string, unknown>[]
  height?: number
  color?: string
  label?: string
  xKey?: string
  category?: boolean
  yFormatter?: (v: number) => string
  tooltipFormatter?: (v: number) => string
  series?: SeriesDef[]
  yAxisOrientation?: YAxisOrientation
  toggleableLegend?: boolean
}

const DEFAULT_SERIES_COLORS = {
  primary: "hsl(var(--accent))",
  positive: "hsl(var(--positive))",
  negative: "hsl(var(--negative))",
  neutral: "hsl(var(--neutral))",
}

interface LegendVisibilityState {
  seriesSignature: string
  hiddenKeys: Set<string>
}

const EMPTY_HIDDEN_KEYS = new Set<string>()

const CHART_TOOLTIP_STYLE = {
  backgroundColor: "hsl(var(--chart-tooltip-bg))",
  borderColor: "hsl(var(--chart-tooltip-border))",
  borderRadius: "0.75rem",
  color: "hsl(var(--foreground))",
}

export function TimeSeriesChart({
  data = [],
  height = 200,
  color = DEFAULT_SERIES_COLORS.primary,
  label,
  xKey = "date",
  category = false,
  yFormatter,
  tooltipFormatter,
  series,
  yAxisOrientation = "left",
  toggleableLegend = false,
}: TimeSeriesChartProps) {
  const chartSeries = useMemo(
    () => series ?? [{ key: "value" }],
    [series],
  )
  const seriesSignature = useMemo(
    () => chartSeries.map((s) => `${s.key}:${s.name ?? s.key}`).join("|"),
    [chartSeries],
  )
  const [legendVisibility, setLegendVisibility] = useState<LegendVisibilityState>(() => ({
    seriesSignature: "",
    hiddenKeys: new Set(),
  }))
  const hiddenSeries =
    legendVisibility.seriesSignature === seriesSignature
      ? legendVisibility.hiddenKeys
      : EMPTY_HIDDEN_KEYS

  const toggleLegendSeries = (payload: LegendPayload) => {
    if (!toggleableLegend) return
    const dataKey = payload.dataKey != null ? String(payload.dataKey) : null
    if (!dataKey) return
    setLegendVisibility((prev) => {
      const prevHidden = prev.seriesSignature === seriesSignature ? prev.hiddenKeys : EMPTY_HIDDEN_KEYS
      const next = new Set(prevHidden)
      if (next.has(dataKey)) next.delete(dataKey)
      else next.add(dataKey)
      return { seriesSignature, hiddenKeys: next }
    })
  }

  const formatLegendLabel = (value: unknown, entry: LegendPayload) => {
    const dataKey = entry.dataKey != null ? String(entry.dataKey) : null
    const isHidden = dataKey != null && hiddenSeries.has(dataKey)
    return (
      <span
        style={{
          color: isHidden ? "hsl(var(--muted-foreground, var(--foreground-tertiary)))" : entry.color,
          opacity: isHidden ? 0.45 : 1,
          textDecoration: isHidden ? "line-through" : "none",
        }}
      >
        {String(value ?? "")}
      </span>
    )
  }

  if (!data.length) {
    return (
      <div style={{ height }} className="flex items-center justify-center text-sm text-subtle">
        No data
      </div>
    )
  }

  return (
    <div>
      {label ? <p className="mb-1 text-xs font-medium text-muted">{label}</p> : null}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" />
          <XAxis
            dataKey={xKey}
            tick={{ fontSize: 10, fill: "hsl(var(--chart-axis))" }}
            tickLine={false}
            axisLine={{ stroke: "hsl(var(--chart-grid))" }}
            minTickGap={24}
          />
          <YAxis
            orientation={yAxisOrientation}
            tick={{ fontSize: 10, fill: "hsl(var(--chart-axis))" }}
            tickLine={false}
            axisLine={false}
            width={64}
            tickFormatter={yFormatter}
          />
          <Tooltip
            contentStyle={CHART_TOOLTIP_STYLE}
            labelStyle={{ color: "hsl(var(--foreground))" }}
            itemStyle={{ color: "hsl(var(--foreground))" }}
            labelFormatter={(l: unknown) => {
              const text = String(l)
              if (category) return text
              const parsed = new Date(text)
              return Number.isNaN(parsed.getTime()) ? text : parsed.toLocaleDateString()
            }}
            formatter={(v: unknown) => {
              const n = v as number | undefined
              return tooltipFormatter && n != null ? tooltipFormatter(n) : n?.toFixed(2) ?? ""
            }}
          />
          {chartSeries.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.name ?? s.key}
              stroke={s.color ?? color}
              dot={false}
              strokeWidth={s.strokeWidth ?? 1.8}
              strokeOpacity={s.opacity ?? 1}
              strokeDasharray={s.strokeDasharray}
              hide={hiddenSeries.has(s.key)}
              connectNulls={false}
            />
          ))}
          {chartSeries.length > 1 ? (
            <Legend
              wrapperStyle={{
                fontSize: 11,
                color: "hsl(var(--foreground-tertiary))",
                cursor: toggleableLegend ? "pointer" : "default",
              }}
              onClick={toggleableLegend ? toggleLegendSeries : undefined}
              formatter={toggleableLegend ? formatLegendLabel : undefined}
            />
          ) : null}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
