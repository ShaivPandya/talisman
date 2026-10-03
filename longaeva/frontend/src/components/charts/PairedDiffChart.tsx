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
    band05: row.p05,
    band10: row.p10,
    band25: row.p25,
    span05_95: row.p95 - row.p05,
    span10_90: row.p90 - row.p10,
    span25_75: row.p75 - row.p25,
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
      <ComposedChart data={plot} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
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
        <ReferenceLine y={0} stroke="hsl(var(--chart-axis))" strokeDasharray="4 2" />
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
          fill="hsl(var(--neutral))"
          fillOpacity={0.16}
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
          fill="hsl(var(--neutral))"
          fillOpacity={0.22}
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
        <Legend wrapperStyle={{ fontSize: 11, color: "hsl(var(--foreground-tertiary))" }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
