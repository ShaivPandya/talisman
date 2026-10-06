import { intervalBand } from "@/lib/scenarios"

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

export interface DiffRow {
  period: string
  mean?: number
  p05: number
  p10: number
  p25: number
  p50: number
  p75: number
  p90: number
  p95: number
}

interface PairedDiffChartProps {
  data: DiffRow[]
  height?: number
  yFormatter?: (v: number) => string
  tooltipFormatter?: (v: number) => string
}

const TOOLTIP_STYLE = {
  backgroundColor: "hsl(var(--chart-tooltip-bg))",
  borderColor: "hsl(var(--chart-tooltip-border))",
  borderRadius: "0.75rem",
  color: "hsl(var(--foreground))",
}

function plotRows(data: DiffRow[]) {
  return data.map((row) => ({
    ...row,
    outer: intervalBand(row.p05, row.p95),
    mid: intervalBand(row.p10, row.p90),
    inner: intervalBand(row.p25, row.p75),
  }))
}

export function PairedDiffChart({
  data,
  height = 260,
  yFormatter,
  tooltipFormatter,
}: PairedDiffChartProps) {
  const plot = plotRows(data)
  if (!plot.length) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-sm text-subtle"
      >
        No data
      </div>
    )
  }

  const formatValue = (v: unknown) => {
    if (Array.isArray(v))
      return v
        .map((value) =>
          tooltipFormatter
            ? tooltipFormatter(Number(value))
            : Number(value).toFixed(2),
        )
        .join(" – ")
    const n = typeof v === "number" ? v : Number(v)
    if (!Number.isFinite(n)) return ""
    return tooltipFormatter ? tooltipFormatter(n) : n.toFixed(2)
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart
        data={plot}
        margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" />
        <XAxis
          dataKey="period"
          tick={{ fontSize: 10, fill: "hsl(var(--chart-axis))" }}
          tickLine={false}
          axisLine={{ stroke: "hsl(var(--chart-grid))" }}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "hsl(var(--chart-axis))" }}
          tickLine={false}
          axisLine={false}
          width={72}
          tickFormatter={yFormatter}
        />
        <ReferenceLine
          y={0}
          stroke="hsl(var(--chart-axis))"
          strokeDasharray="4 2"
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(label: unknown) => String(label)}
          formatter={(value: unknown, name: unknown) => [
            formatValue(value),
            String(name),
          ]}
        />
        <Area
          type="monotone"
          dataKey="outer"
          name="5–95%"
          stroke="none"
          fill="hsl(var(--neutral))"
          fillOpacity={0.16}
        />
        <Area
          type="monotone"
          dataKey="mid"
          name="10–90%"
          stroke="none"
          fill="hsl(var(--neutral))"
          fillOpacity={0.22}
        />
        <Area
          type="monotone"
          dataKey="inner"
          name="25–75%"
          stroke="none"
          fill="hsl(var(--neutral))"
          fillOpacity={0.32}
        />
        <Line
          type="monotone"
          dataKey="p50"
          name="Median difference"
          stroke="hsl(var(--foreground))"
          strokeWidth={2}
          dot={false}
        />
        <Legend
          wrapperStyle={{
            fontSize: 11,
            color: "hsl(var(--foreground-tertiary))",
          }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
