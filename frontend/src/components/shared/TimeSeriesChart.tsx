/* eslint-disable react-refresh/only-export-components */
import { memo, useCallback, useMemo, useState } from "react"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from "recharts"
import type { LegendPayload, YAxisOrientation, YAxisProps } from "recharts"

export interface DataPoint {
  date: string
  value: number | null
}

export interface SeriesDef {
  key: string
  name?: string
  color?: string
  strokeWidth?: number
  /** Maps to strokeOpacity on the Line element */
  opacity?: number
  strokeDasharray?: string
}

interface TimeSeriesChartProps {
  data?: DataPoint[]
  height?: number
  color?: string
  label?: string
  /** If true, draw a horizontal reference line at y=0 */
  zeroLine?: boolean
  /** Format y-axis ticks */
  yFormatter?: (v: number) => string
  /** Format tooltip values */
  tooltipFormatter?: (v: number) => string
  /** Sort tooltip rows from highest to lowest numeric value at the hovered point */
  tooltipSortByValueDesc?: boolean
  /** Timeframe string — drives x-axis tick deduplication and formatting */
  timeframe?: string
  /** For multi-series charts: rows with 'date' + one key per series */
  multiData?: Record<string, unknown>[]
  /** Series definitions for multi-series mode */
  series?: SeriesDef[]
  /** Which side should render the y-axis tick labels */
  yAxisOrientation?: YAxisOrientation
  /** Allow clicking legend items to hide/show multi-series lines */
  toggleableLegend?: boolean
  /** Y-axis scale. Log assumes callers pass only positive visible values. */
  yScale?: "linear" | "log"
}

const DEFAULT_SERIES_COLORS = {
  primary: "hsl(var(--accent))",
  positive: "hsl(var(--positive))",
  negative: "hsl(var(--negative))",
  neutral: "hsl(var(--neutral))",
}

const EMPTY_DATA: DataPoint[] = []
const AXIS_TICK = { fontSize: 10, fill: "hsl(var(--chart-axis))" }
const AXIS_LINE = { stroke: "hsl(var(--chart-grid))" }
const LEFT_MARGIN = { top: 4, right: 8, left: 0, bottom: 0 }
const RIGHT_MARGIN = { top: 4, right: 0, left: 8, bottom: 0 }
const AUTO_DOMAIN: YAxisProps["domain"] = ["auto", "auto"]
const LOG_DOMAIN: YAxisProps["domain"] = ["dataMin", "dataMax"]
const ZERO_DOMAIN: YAxisProps["domain"] = [(dataMin: number) => Math.min(0, dataMin), "auto"]
const TOOLTIP_STYLE = {
  backgroundColor: "hsl(var(--chart-tooltip-bg))",
  borderColor: "hsl(var(--chart-tooltip-border))",
  borderRadius: "0.75rem",
  color: "hsl(var(--foreground))",
}
const TOOLTIP_TEXT_STYLE = { color: "hsl(var(--foreground))" }
const LEGEND_STYLE = { fontSize: 11, color: "hsl(var(--muted-foreground))", cursor: "default" }
const TOGGLEABLE_LEGEND_STYLE = { ...LEGEND_STYLE, cursor: "pointer" }
// Recharts formats candidate ticks for each chart. Reuse the locale formatters
// rather than constructing one for every tick in every portfolio position.
const DATE_FORMATTER = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" })
const MONTH_FORMATTER = new Intl.DateTimeFormat("en-US", { month: "short" })
const DATE_LABELS = new Map<string, string>()
const MONTH_LABELS = new Map<string, string>()
const YEAR_LABELS = new Map<string, string>()
const MAX_CACHED_DATE_LABELS = 512

function cachedDateLabel(isoDate: string, cache: Map<string, string>, formatter?: Intl.DateTimeFormat): string {
  const cached = cache.get(isoDate)
  if (cached !== undefined) return cached
  const date = new Date(isoDate)
  const label = formatter
    ? Number.isNaN(date.getTime()) ? "Invalid Date" : formatter.format(date)
    : String(date.getFullYear())
  if (cache.size >= MAX_CACHED_DATE_LABELS) cache.delete(cache.keys().next().value!)
  cache.set(isoDate, label)
  return label
}

function tooltipLabel(l: unknown): string {
  return new Date(String(l)).toLocaleDateString()
}

function shortDate(isoDate: string): string {
  try {
    return cachedDateLabel(isoDate, DATE_LABELS, DATE_FORMATTER)
  } catch {
    return isoDate
  }
}

function shortMonth(isoDate: string): string {
  try {
    return cachedDateLabel(isoDate, MONTH_LABELS, MONTH_FORMATTER)
  } catch {
    return isoDate
  }
}

function shortYear(isoDate: string): string {
  try {
    return cachedDateLabel(isoDate, YEAR_LABELS)
  } catch {
    return isoDate
  }
}

type ChartRow = DataPoint | Record<string, unknown>
type TooltipValuePayload = {
  value?: number | string | ReadonlyArray<number | string>
}
interface LegendVisibilityState {
  seriesSignature: string
  hiddenKeys: Set<string>
}

const EMPTY_HIDDEN_KEYS = new Set<string>()

function getRowDate(row: ChartRow): string | null {
  return typeof row.date === "string" ? row.date : null
}

function getThisWeekTicks(data: ChartRow[]): string[] {
  const seen = new Set<string>()
  const ticks: string[] = []
  for (const pt of data) {
    const date = getRowDate(pt)
    if (!date) continue
    const day = date.substring(0, 10)
    if (!seen.has(day)) {
      seen.add(day)
      ticks.push(date)
    }
  }
  return ticks
}

function tooltipValueDescSorter(item: TooltipValuePayload): number {
  const value = Array.isArray(item.value) ? Number(item.value[0]) : Number(item.value)
  return Number.isFinite(value) ? -value : Number.POSITIVE_INFINITY
}

export function calcReturn(data: DataPoint[]): number | null {
  const vals = data.filter(p => p.value != null).map(p => p.value as number)
  if (vals.length < 2) return null
  return (vals[vals.length - 1] - vals[0]) / vals[0] * 100
}

function getMonthTicks(data: ChartRow[]): string[] {
  const seen = new Set<string>()
  const ticks: string[] = []
  for (const pt of data) {
    const date = getRowDate(pt)
    if (!date) continue
    const month = date.substring(0, 7)
    if (!seen.has(month)) {
      seen.add(month)
      ticks.push(date)
    }
  }
  return ticks
}

function getYearTicks(data: ChartRow[]): string[] {
  const seen = new Set<string>()
  const ticks: string[] = []
  for (const pt of data) {
    const date = getRowDate(pt)
    if (!date) continue
    const year = date.substring(0, 4)
    if (!seen.has(year)) {
      seen.add(year)
      ticks.push(date)
    }
  }
  return ticks
}

export const TimeSeriesChart = memo(function TimeSeriesChart({
  data = EMPTY_DATA,
  height = 200,
  color = DEFAULT_SERIES_COLORS.primary,
  label,
  zeroLine = false,
  yFormatter,
  tooltipFormatter,
  tooltipSortByValueDesc = false,
  timeframe,
  multiData,
  series,
  yAxisOrientation = "left",
  toggleableLegend = false,
  yScale = "linear",
}: TimeSeriesChartProps) {
  const isMulti = multiData != null && series != null
  const chartData: ChartRow[] = isMulti ? multiData : data
  const ticks = useMemo(() => {
    if (timeframe === "This Week") return getThisWeekTicks(chartData)
    if (timeframe === "Monthly") return getYearTicks(chartData)
    // Weekly labels show months too; avoid measuring every weekly point as
    // a candidate tick in each position's chart.
    if (timeframe === "Daily" || timeframe === "Weekly") return getMonthTicks(chartData)
    return undefined
  }, [chartData, timeframe])
  const formatTooltip = useCallback((v: unknown) => {
    const n = v as number | undefined
    return tooltipFormatter && n != null ? tooltipFormatter(n) : n?.toFixed(2) ?? ""
  }, [tooltipFormatter])
  const seriesSignature = useMemo(
    () => (series ?? []).map(s => `${s.key}:${s.name ?? s.key}`).join("|"),
    [series],
  )
  const [legendVisibility, setLegendVisibility] = useState<LegendVisibilityState>(() => ({
    seriesSignature: "",
    hiddenKeys: new Set(),
  }))
  const hiddenSeries = legendVisibility.seriesSignature === seriesSignature
    ? legendVisibility.hiddenKeys
    : EMPTY_HIDDEN_KEYS

  const toggleLegendSeries = useCallback((payload: LegendPayload) => {
    if (!toggleableLegend) return
    const dataKey = payload.dataKey != null ? String(payload.dataKey) : null
    if (!dataKey) return

    setLegendVisibility(prev => {
      const prevHidden = prev.seriesSignature === seriesSignature ? prev.hiddenKeys : EMPTY_HIDDEN_KEYS
      const next = new Set(prevHidden)
      if (next.has(dataKey)) {
        next.delete(dataKey)
      } else {
        next.add(dataKey)
      }
      return { seriesSignature, hiddenKeys: next }
    })
  }, [toggleableLegend, seriesSignature])

  const formatLegendLabel = useCallback((value: unknown, entry: LegendPayload) => {
    const dataKey = entry.dataKey != null ? String(entry.dataKey) : null
    const isHidden = dataKey != null && hiddenSeries.has(dataKey)
    return (
      <span
        style={{
          color: isHidden ? "hsl(var(--muted-foreground))" : entry.color,
          opacity: isHidden ? 0.45 : 1,
          textDecoration: isHidden ? "line-through" : "none",
        }}
      >
        {String(value ?? "")}
      </span>
    )
  }, [hiddenSeries])

  if (!chartData || chartData.length === 0) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-sm text-subtle"
      >
        No data
      </div>
    )
  }

  return (
    <div>
      {label && <p className="mb-1 text-xs font-medium text-muted">{label}</p>}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart
          data={chartData}
          margin={yAxisOrientation === "right" ? RIGHT_MARGIN : LEFT_MARGIN}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" />
          <XAxis
            dataKey="date"
            tickFormatter={timeframe === "Monthly" ? shortYear : timeframe === "Weekly" ? shortMonth : shortDate}
            ticks={ticks}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={AXIS_LINE}
            minTickGap={30}
          />
          <YAxis
            orientation={yAxisOrientation}
            scale={yScale === "log" ? "log" : undefined}
            domain={yScale === "log" ? LOG_DOMAIN : zeroLine ? ZERO_DOMAIN : AUTO_DOMAIN}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={50}
            tickFormatter={yFormatter}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelStyle={TOOLTIP_TEXT_STYLE}
            itemStyle={TOOLTIP_TEXT_STYLE}
            labelFormatter={tooltipLabel}
            itemSorter={tooltipSortByValueDesc ? tooltipValueDescSorter : undefined}
            formatter={formatTooltip}
          />
          {zeroLine && <ReferenceLine y={0} stroke="hsl(var(--chart-axis))" strokeDasharray="4 2" />}
          {isMulti
            ? series!.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.name ?? s.key}
                  stroke={s.color ?? color}
                  dot={false}
                  strokeWidth={s.strokeWidth ?? 1.5}
                  strokeOpacity={s.opacity ?? 1}
                  strokeDasharray={s.strokeDasharray}
                  hide={hiddenSeries.has(s.key)}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))
            : (
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={color}
                  dot={false}
                  strokeWidth={1.8}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              )
          }
          {isMulti && (
            <Legend
              wrapperStyle={toggleableLegend ? TOGGLEABLE_LEGEND_STYLE : LEGEND_STYLE}
              onClick={toggleableLegend ? toggleLegendSeries : undefined}
              formatter={toggleableLegend ? formatLegendLabel : undefined}
              inactiveColor="hsl(var(--muted-foreground))"
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
})
