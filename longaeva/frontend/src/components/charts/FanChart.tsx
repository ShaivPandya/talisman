import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { FanRow } from "@/lib/runs"

interface FanChartProps {
  data: FanRow[]
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

export function FanChart({
  data,
  height = 280,
  yFormatter,
  tooltipFormatter,
}: FanChartProps) {
  if (!data.length) {
    return (
      <div style={{ height }} className="flex items-center justify-center text-sm text-subtle">
        No data
      </div>
    )
  }

  const formatValue = (v: unknown) => {
    const n = typeof v === "number" ? v : Number(v)
    if (!Number.isFinite(n)) return ""
    return tooltipFormatter ? tooltipFormatter(n) : n.toFixed(2)
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
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
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(label: unknown) => String(label)}
          formatter={(value: unknown, name: unknown) => [formatValue(value), String(name)]}
        />
        <Area
          type="monotone"
          dataKey="band05"
          stackId="outer"
          stroke="none"
          fill="transparent"
          legendType="none"
          tooltipType="none"
        />
        <Area
          type="monotone"
          dataKey="span05_95"
          stackId="outer"
          name="5–95%"
          stroke="none"
          fill="hsl(var(--accent))"
          fillOpacity={0.12}
        />
        <Area
          type="monotone"
          dataKey="band10"
          stackId="mid"
          stroke="none"
          fill="transparent"
          legendType="none"
          tooltipType="none"
        />
        <Area
          type="monotone"
          dataKey="span10_90"
          stackId="mid"
          name="10–90%"
          stroke="none"
          fill="hsl(var(--accent))"
          fillOpacity={0.18}
        />
        <Area
          type="monotone"
          dataKey="band25"
          stackId="inner"
          stroke="none"
          fill="transparent"
          legendType="none"
          tooltipType="none"
        />
        <Area
          type="monotone"
          dataKey="span25_75"
          stackId="inner"
          name="25–75%"
          stroke="none"
          fill="hsl(var(--accent))"
          fillOpacity={0.28}
        />
        <Line
          type="monotone"
          dataKey="p50"
          name="Median"
          stroke="hsl(var(--accent))"
          strokeWidth={2}
          dot={false}
        />
        <Line
          type="monotone"
          dataKey="mean"
          name="Mean"
          stroke="hsl(var(--foreground-secondary))"
          strokeWidth={1.4}
          strokeDasharray="5 4"
          dot={false}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: "hsl(var(--foreground-tertiary))" }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
