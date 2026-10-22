import { memo, startTransition, useEffect, useMemo, useState } from "react"
import { keepPreviousData, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { useRegisterScreenContext } from "@/contexts/ScreenContext"
import { useApiQuery } from "@/hooks/useApiQuery"
import { useDisplayedQueryParameter } from "@/hooks/useDisplayedQueryParameter"
import { fetchPortfolio } from "@/lib/api"
import { TimeSeriesChart, calcReturn, type DataPoint, type SeriesDef } from "@/components/shared/TimeSeriesChart"
import { LoadingSpinner, ErrorMessage } from "@/components/shared/LoadingSpinner"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { SegmentedControl } from "@/components/shared/FormControls"
import { Notice } from "@/components/shared/Notice"
import { PageHeader } from "@/components/shared/PageHeader"
import { ChartTile } from "@/components/shared/ChartTile"

const TIMEFRAMES = ["This Week", "Daily", "Weekly", "Monthly"] as const
const TIMEFRAME_OPTIONS = TIMEFRAMES.map(tf => ({
  value: tf,
  label: tf === "This Week" ? "Past Week" : tf,
}))
const VIEW_MODES = ["Grid", "Unified"] as const
const POSITION_COLORS = [
  "#2563eb",
  "#16a34a",
  "#dc2626",
  "#9333ea",
  "#f97316",
  "#0891b2",
  "#db2777",
  "#65a30d",
  "#7c3aed",
  "#0f766e",
  "#b45309",
  "#475569",
]
type Timeframe = typeof TIMEFRAMES[number]
type ViewMode = typeof VIEW_MODES[number]
type TimeframePayload = {
  positions?: Record<string, DataPoint[]>
  position_order?: string[]
  warning?: string
  group_exposures?: Array<{
    group_name?: string | null
    group_conviction?: number | null
    direction?: string | null
    tickers?: string[]
    current_notional?: number
    cost_notional?: number
  }>
}
type PortfolioTimeframeResponse = TimeframePayload & {
  holdings?: Array<{ ticker?: string | null; role?: string | null }>
}

interface UnifiedPositionSummary {
  ticker: string
  seriesKey: string
  color: string
  baseValue: number
  returnPct: number
}

interface UnifiedPerformance {
  chartData: Record<string, unknown>[]
  sortedPositions: UnifiedPositionSummary[]
  series: SeriesDef[]
}

const EMPTY_UNIFIED_PERFORMANCE: UnifiedPerformance = { chartData: [], sortedPositions: [], series: [] }

const PortfolioPositionChart = memo(function PortfolioPositionChart({ ticker, data, timeframe }: {
  ticker: string
  data: DataPoint[]
  timeframe: Timeframe
}) {
  const ret = calcReturn(data)
  return (
    <ChartTile
      title={ticker}
      href={`/dossier/${encodeURIComponent(ticker)}`}
      meta={ret != null ? (
        <span className={`text-xs font-semibold ${ret >= 0 ? "text-positive" : "text-negative"}`}>
          {ret >= 0 ? "+" : ""}{ret.toFixed(2)}%
        </span>
      ) : undefined}
    >
      <TimeSeriesChart data={data} height={160} timeframe={timeframe} />
    </ChartTile>
  )
})

type PositionChartSnapshot = { data: DataPoint[]; timeframe: Timeframe }

const PortfolioChartGrid = memo(function PortfolioChartGrid({ order, positions, timeframe }: {
  order: string[]
  positions: Record<string, DataPoint[]>
  timeframe: Timeframe
}) {
  const [rendered, setRendered] = useState(() => new Map<string, PositionChartSnapshot>(
    order.map(ticker => [ticker, { data: positions[ticker], timeframe }]),
  ))
  const needsUpdate = (ticker: string) => Boolean(positions[ticker]?.length) && (
    rendered.get(ticker)?.data !== positions[ticker] || rendered.get(ticker)?.timeframe !== timeframe
  )
  const pending = order.some(needsUpdate)

  useEffect(() => {
    const updates = order.filter(ticker => Boolean(positions[ticker]?.length) && (
      rendered.get(ticker)?.data !== positions[ticker] || rendered.get(ticker)?.timeframe !== timeframe
    ))
    if (!updates.length) return
    // Recharts synchronously commits its internal store updates. Bound each
    // commit to four tiles rather than updating the whole portfolio at once.
    const frame = requestAnimationFrame(() => setRendered(previous => {
      const next = new Map<string, PositionChartSnapshot>()
      for (const ticker of order) {
        const snapshot = previous.get(ticker)
        if (snapshot) next.set(ticker, snapshot)
      }
      for (const ticker of updates.slice(0, 4)) next.set(ticker, { data: positions[ticker], timeframe })
      return next
    }))
    return () => cancelAnimationFrame(frame)
  }, [order, positions, timeframe, rendered])

  return (
    <>
      {pending && <p role="status" className="sr-only">Updating portfolio charts…</p>}
      <div role="group" aria-label="Portfolio position charts" aria-busy={pending} className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {order.map(ticker => {
          const series = positions[ticker]
          if (!series?.length) return null
          const snapshot = rendered.get(ticker)
          return <PortfolioPositionChart key={ticker} ticker={ticker} data={snapshot?.data ?? series} timeframe={snapshot?.timeframe ?? timeframe} />
        })}
      </div>
    </>
  )
})

function timeframeLabel(timeframe: Timeframe): string {
  return timeframe === "This Week" ? "Past Week" : timeframe
}

function portfolioStaleTime(timeframe: Timeframe): number {
  return timeframe === "This Week" ? 5 * 60 * 1000 : 60 * 60 * 1000
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function formatPercent(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value)
}

function colorForPosition(index: number): string {
  return POSITION_COLORS[index % POSITION_COLORS.length]
}

function buildUnifiedPerformance(
  order: string[],
  positions: Record<string, DataPoint[]>,
): UnifiedPerformance {
  const comparablePositions = order.flatMap((ticker, index) => {
    const series = positions[ticker]
    if (!Array.isArray(series) || series.length === 0) return []

    const values = series
      .map(point => point.value)
      .filter(isFiniteNumber)
    if (values.length < 2 || values[0] === 0) return []

    return [{
      ticker,
      seriesKey: `position_${index}`,
      color: colorForPosition(index),
      baseValue: values[0],
      returnPct: (values[values.length - 1] / values[0] - 1) * 100,
    }]
  })

  const rowsByDate = new Map<string, Record<string, unknown>>()
  for (const position of comparablePositions) {
    const series = positions[position.ticker] ?? []
    for (const point of series) {
      const row = rowsByDate.get(point.date) ?? { date: point.date }
      row[position.seriesKey] = isFiniteNumber(point.value)
        ? (point.value / position.baseValue - 1) * 100
        : null
      rowsByDate.set(point.date, row)
    }
  }

  const chartData = Array.from(rowsByDate.values())
    .sort((a, b) => String(a.date).localeCompare(String(b.date)))
    .map(row => {
      for (const position of comparablePositions) {
        if (!(position.seriesKey in row)) row[position.seriesKey] = null
      }
      return row
    })

  const sortedPositions = [...comparablePositions]
    .sort((a, b) => b.returnPct - a.returnPct)

  return {
    chartData,
    sortedPositions,
    series: comparablePositions.map(position => ({
      key: position.seriesKey,
      name: position.ticker,
      color: position.color,
      strokeWidth: 1.8,
    })),
  }
}

export function PortfolioDashboard() {
  const queryClient = useQueryClient()
  const [timeframe, setTimeframe] = useState<Timeframe>("This Week")
  const [viewMode, setViewMode] = useState<ViewMode>("Grid")
  const {
    data: timeframeData,
    isLoading,
    error,
    isSuccess,
    isPlaceholderData,
  } = useApiQuery<PortfolioTimeframeResponse>(
    ["portfolio", timeframe],
    () => fetchPortfolio(timeframe),
    portfolioStaleTime(timeframe),
    { placeholderData: keepPreviousData },
  )
  const displayedTimeframe = useDisplayedQueryParameter(timeframe, isPlaceholderData)

  useEffect(() => {
    if (!isSuccess || isPlaceholderData) return

    let cancelled = false
    let timeoutId: number | null = null
    let idleId: number | null = null

    const prefetchRemainingTimeframes = async () => {
      for (const nextTimeframe of TIMEFRAMES) {
        if (cancelled || nextTimeframe === timeframe) continue
        try {
          await queryClient.prefetchQuery({
            queryKey: ["portfolio", nextTimeframe],
            queryFn: () => fetchPortfolio(nextTimeframe),
            staleTime: portfolioStaleTime(nextTimeframe),
          })
        } catch {
          // Background prefetch is opportunistic; the active query will surface errors when selected.
        }
      }
    }

    const startPrefetch = () => {
      void prefetchRemainingTimeframes()
    }

    if (typeof window.requestIdleCallback === "function") {
      idleId = window.requestIdleCallback(startPrefetch)
    } else {
      timeoutId = window.setTimeout(startPrefetch, 1000)
    }

    return () => {
      cancelled = true
      if (idleId !== null && typeof window.cancelIdleCallback === "function") {
        window.cancelIdleCallback(idleId)
      }
      if (timeoutId !== null) window.clearTimeout(timeoutId)
    }
  }, [isSuccess, isPlaceholderData, queryClient, timeframe])

  const refreshPortfolio = async () => {
    await queryClient.invalidateQueries({ queryKey: ["portfolio"], refetchType: "none" })
    await queryClient.cancelQueries({ queryKey: ["portfolio", timeframe], exact: true })
    // Longer timeframes sit in an hour-long backend cache, so force the open one past it.
    queryClient.setQueryData(["portfolio", timeframe], await fetchPortfolio(timeframe, { force_refresh: true }))
  }

  const loadError = error
    ? String(error)
    : !timeframeData
    ? "Failed to load portfolio data."
    : null
  const holdings = timeframeData?.holdings
  const activePortfolioTickers = useMemo(() => {
    if (!Array.isArray(holdings)) return null

    const tickers = new Set(
      holdings
        .filter(holding => String(holding.role ?? "position").toLowerCase() !== "hedge")
        .map(holding => String(holding.ticker ?? "").trim().toUpperCase())
        .filter(Boolean),
    )

    return tickers.size > 0 ? tickers : null
  }, [holdings])
  const positions: Record<string, DataPoint[]> = useMemo(
    () => {
      const rawPositions = timeframeData?.positions ?? {}
      if (!activePortfolioTickers) return rawPositions

      return Object.fromEntries(
        Object.entries(rawPositions).filter(([ticker]) => activePortfolioTickers.has(ticker.toUpperCase())),
      )
    },
    [activePortfolioTickers, timeframeData?.positions],
  )
  const order: string[] = useMemo(
    () => {
      const rawOrder = timeframeData?.position_order ?? Object.keys(positions)
      if (!activePortfolioTickers) return rawOrder
      return rawOrder.filter(ticker => activePortfolioTickers.has(ticker.toUpperCase()))
    },
    [activePortfolioTickers, positions, timeframeData?.position_order],
  )
  const warning = timeframeData?.warning
  const hasSeries = order.some(ticker => {
    const series = positions[ticker]
    return Array.isArray(series) && series.length > 0
  })

  // Register screen context for agent chat
  const screenCtx = useMemo(() => {
    if (!timeframeData || order.length === 0) return null
    const metrics: Record<string, string> = {
      "Positions": `${order.length} tickers`,
      "Timeframe": timeframeLabel(displayedTimeframe),
      "View": viewMode,
    }
    const returns = order.slice(0, 10).map(ticker => {
      const series = positions[ticker]
      if (!series || series.length === 0) return null
      const ret = calcReturn(series)
      return ret != null ? `${ticker}: ${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%` : null
    }).filter(Boolean)
    if (returns.length > 0) metrics["Returns"] = returns.join(", ")
    return {
      pageName: "Portfolio Dashboard",
      metrics,
      filters: { timeframe: timeframeLabel(displayedTimeframe), view: viewMode },
      summary: `Portfolio with ${order.length} positions, viewing ${timeframeLabel(displayedTimeframe)} in ${viewMode} mode`,
      correspondingTools: ["get_portfolio"],
    }
  }, [timeframeData, order, positions, displayedTimeframe, viewMode])
  useRegisterScreenContext(screenCtx)

  const unifiedPerformance = useMemo(
    () => viewMode === "Unified" ? buildUnifiedPerformance(order, positions) : EMPTY_UNIFIED_PERFORMANCE,
    [order, positions, viewMode],
  )
  const groupExposures = timeframeData?.group_exposures ?? []
  const hasUnifiedSeries = unifiedPerformance.sortedPositions.length > 0 && unifiedPerformance.chartData.length > 0

  return (
    <div>
      <PageHeader
        title="Portfolio Dashboard"
        subtitle="Portfolio positions organized as an adaptive chart grid and comparable performance view."
        actions={(
          <>
            <Link
              to="/portfolio/edit"
              className="theme-button-base theme-button-secondary px-4"
            >
              Edit Portfolio
            </Link>
            <RefreshButton
              queryKeys={[["thesis", "status"]]}
              beforeRefetch={refreshPortfolio}
            />
          </>
        )}
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <SegmentedControl
          options={TIMEFRAME_OPTIONS}
          value={timeframe}
          onChange={next => startTransition(() => setTimeframe(next))}
        />
        <SegmentedControl
          options={VIEW_MODES.map(mode => ({ value: mode, label: mode }))}
          value={viewMode}
          onChange={setViewMode}
        />
      </div>

      {isPlaceholderData && (
        <p role="status" className="mb-4 text-sm text-muted">
          Updating to {timeframeLabel(timeframe)}… Showing {timeframeLabel(displayedTimeframe)} until the new data arrives.
        </p>
      )}
      {isLoading && <LoadingSpinner message="Fetching portfolio data..." />}
      {!isLoading && loadError && (
        <ErrorMessage message={loadError} />
      )}
      {!isLoading && !error && warning && (
        <Notice tone="warning" className="mb-4">{warning}</Notice>
      )}
      {!isLoading && !error && timeframeData && !hasSeries && (
        <Notice tone="info">No price series available.</Notice>
      )}

      {groupExposures.length > 0 && !isLoading && (
        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {groupExposures.map(group => (
            <div key={String(group.group_name)} className="rounded-lg border border-app bg-card-muted px-3 py-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-app">{group.group_name}</p>
                  <p className="mt-0.5 truncate text-xs text-muted">{(group.tickers ?? []).join(", ")}</p>
                </div>
                <span className="shrink-0 text-xs font-medium text-subtle">
                  Conv {group.group_conviction ?? "-"}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                <span>{group.direction ?? "mixed"}</span>
                {isFiniteNumber(group.current_notional) && <span>{formatMoney(group.current_notional)}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {timeframeData && !isLoading && hasSeries && viewMode === "Grid" && (
        <PortfolioChartGrid order={order} positions={positions} timeframe={displayedTimeframe} />
      )}

      {timeframeData && !isLoading && hasSeries && viewMode === "Unified" && !hasUnifiedSeries && (
        <Notice tone="info">No comparable price series available.</Notice>
      )}

      {timeframeData && !isLoading && hasSeries && viewMode === "Unified" && hasUnifiedSeries && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {unifiedPerformance.sortedPositions.map(position => (
              <Link
                key={position.ticker}
                to={`/dossier/${encodeURIComponent(position.ticker)}`}
                className="rounded-xl border border-app bg-card px-4 py-3 shadow-sm transition-colors hover:border-strong hover:bg-card-muted"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: position.color }}
                      />
                      <span className="truncate text-sm font-semibold text-app">{position.ticker}</span>
                    </div>
                  </div>
                  <span className={`shrink-0 text-sm font-semibold tabular-nums ${position.returnPct >= 0 ? "text-positive" : "text-negative"}`}>
                    {formatPercent(position.returnPct)}
                  </span>
                </div>
              </Link>
            ))}
          </div>

          <div className="theme-surface p-4 sm:p-5">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="section-title">Unified Performance</h2>
                <p className="mt-1 text-sm text-muted">{timeframeLabel(displayedTimeframe)} raw price return, normalized to 0%.</p>
              </div>
              <span className="text-xs font-medium text-subtle">{unifiedPerformance.sortedPositions.length} positions</span>
            </div>
            <TimeSeriesChart
              multiData={unifiedPerformance.chartData}
              series={unifiedPerformance.series}
              height={360}
              timeframe={displayedTimeframe}
              zeroLine
              yFormatter={formatPercent}
              tooltipFormatter={formatPercent}
              tooltipSortByValueDesc
              yAxisOrientation="right"
              toggleableLegend
            />
          </div>
        </div>
      )}

    </div>
  )
}
