import { memo, useMemo } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { TimeSeriesChart, type SeriesDef } from "@/components/shared/TimeSeriesChart"
import type { AgentChartPart, ChartYFormat } from "@/hooks/agentChatShared"

const CHART_HEIGHT = 220
// The same hues as the Chart page, so a price and its moving averages read alike in both places.
const SERIES_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
const AXIS_TICK = { fontSize: 10, fill: "hsl(var(--chart-axis))" }
const AXIS_LINE = { stroke: "hsl(var(--chart-grid))" }
const MARGIN = { top: 4, right: 8, left: 0, bottom: 0 }
const TOOLTIP_STYLE = {
  backgroundColor: "hsl(var(--chart-tooltip-bg))",
  borderColor: "hsl(var(--chart-tooltip-border))",
  borderRadius: "0.75rem",
  color: "hsl(var(--foreground))",
}
const TOOLTIP_TEXT_STYLE = { color: "hsl(var(--foreground))" }
const LEGEND_STYLE = { fontSize: 11, color: "hsl(var(--muted-foreground))" }

interface ValueFormat {
  axis: (value: number) => string
  tooltip: (value: number) => string
}

const signed = (value: number, digits: number) => `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`

const VALUE_FORMATS: Record<ChartYFormat, ValueFormat> = {
  price: {
    axis: value => value.toLocaleString("en-US", { maximumFractionDigits: 2 }),
    tooltip: value => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  },
  percent: { axis: value => `${value.toFixed(1)}%`, tooltip: value => `${signed(value, 2)}%` },
  yield: { axis: value => `${value.toFixed(2)}%`, tooltip: value => `${value.toFixed(3)}%` },
  ratio: { axis: value => value.toFixed(2), tooltip: value => value.toFixed(4) },
  number: { axis: value => String(Math.round(value * 100) / 100), tooltip: value => value.toFixed(2) },
}

function tooltipValue(format: ValueFormat) {
  return (value: unknown) => (typeof value === "number" ? format.tooltip(value) : "")
}

function LineBody({ chart, format }: { chart: AgentChartPart; format: ValueFormat }) {
  const series = useMemo<SeriesDef[]>(
    () =>
      chart.series.map((s, index) => ({
        key: s.key,
        name: s.name,
        color: SERIES_COLORS[index % SERIES_COLORS.length],
        // The first series is the thing itself, the rest are references to it.
        strokeWidth: index === 0 ? 2 : 1,
        opacity: index === 0 ? 1 : 0.8,
      })),
    [chart.series],
  )
  const first = String(chart.rows[0]?.[chart.xKey] ?? "").slice(0, 4)
  const last = String(chart.rows[chart.rows.length - 1]?.[chart.xKey] ?? "").slice(0, 4)
  // Month ticks suit a year or two; a longer window gets one tick a year.
  const timeframe = Number(last) - Number(first) > 3 ? "Monthly" : "Daily"
  return (
    <TimeSeriesChart
      multiData={chart.rows}
      series={series}
      height={CHART_HEIGHT}
      timeframe={timeframe}
      yFormatter={format.axis}
      tooltipFormatter={format.tooltip}
    />
  )
}

function CurveBody({ chart, format }: { chart: AgentChartPart; format: ValueFormat }) {
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <LineChart data={chart.rows} margin={MARGIN}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" />
        <XAxis dataKey={chart.xKey} tick={AXIS_TICK} tickLine={false} axisLine={AXIS_LINE} interval="preserveStartEnd" />
        <YAxis
          domain={["auto", "auto"]}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={50}
          tickFormatter={format.axis}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_TEXT_STYLE}
          itemStyle={TOOLTIP_TEXT_STYLE}
          formatter={tooltipValue(format)}
        />
        <Legend wrapperStyle={LEGEND_STYLE} />
        {chart.series.map((s, index) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name}
            stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
            strokeWidth={index === 0 ? 2 : 1.25}
            strokeDasharray={index === 0 ? undefined : "4 3"}
            dot={{ r: 2 }}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function BarsBody({ chart, format }: { chart: AgentChartPart; format: ValueFormat }) {
  const key = chart.series[0].key
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <BarChart data={chart.rows} margin={MARGIN}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" vertical={false} />
        <XAxis dataKey={chart.xKey} tick={AXIS_TICK} tickLine={false} axisLine={AXIS_LINE} />
        <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={50} tickFormatter={format.axis} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_TEXT_STYLE}
          itemStyle={TOOLTIP_TEXT_STYLE}
          formatter={tooltipValue(format)}
          cursor={false}
        />
        <Bar dataKey={key} name={chart.series[0].name} isAnimationActive={false}>
          {chart.rows.map((row, index) => (
            <Cell
              key={index}
              fill={Number(row[key]) < 0 ? "hsl(var(--negative))" : "hsl(var(--positive))"}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** A chart the assistant's tools produced, drawn inside the answer. */
export const AgentChart = memo(function AgentChart({ chart }: { chart: AgentChartPart }) {
  const format = VALUE_FORMATS[chart.yFormat]
  const notes = [
    chart.asOf ? `As of ${chart.asOf}` : null,
    chart.sampledFrom ? `Showing ${chart.rows.length} of ${chart.sampledFrom} points` : null,
  ].filter(Boolean)
  return (
    <figure
      className="my-3 rounded-lg border border-app bg-card-muted p-3"
      data-testid="agent-chart"
      aria-label={[chart.title, chart.subtitle].filter(Boolean).join(". ")}
    >
      <figcaption className="mb-2">
        <p className="text-sm font-semibold text-app">{chart.title}</p>
        {chart.subtitle && <p className="text-xs text-muted">{chart.subtitle}</p>}
      </figcaption>
      {chart.kind === "line" && <LineBody chart={chart} format={format} />}
      {chart.kind === "curve" && <CurveBody chart={chart} format={format} />}
      {chart.kind === "bars" && <BarsBody chart={chart} format={format} />}
      {notes.length > 0 && <p className="mt-1 text-[11px] text-subtle">{notes.join(" · ")}</p>}
    </figure>
  )
})
