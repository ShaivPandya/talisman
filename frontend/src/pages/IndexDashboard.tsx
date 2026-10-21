import { useState } from "react"
import { keepPreviousData } from "@tanstack/react-query"
import {
  dashboardTimeframeStaleTime,
  useDashboardTimeframePrefetch,
} from "@/hooks/useDashboardTimeframePrefetch"
import { useApiQuery } from "@/hooks/useApiQuery"
import { useDisplayedQueryParameter } from "@/hooks/useDisplayedQueryParameter"
import { fetchIndexDashboard } from "@/lib/api"
import { TimeSeriesChart, calcReturn, type DataPoint } from "@/components/shared/TimeSeriesChart"
import { LoadingSpinner, ErrorMessage } from "@/components/shared/LoadingSpinner"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { SegmentedControl } from "@/components/shared/FormControls"
import { PageHeader } from "@/components/shared/PageHeader"
import { ChartTile } from "@/components/shared/ChartTile"
import { Notice } from "@/components/shared/Notice"
import { UnifiedPerformanceView } from "@/components/shared/UnifiedPerformanceView"
import { UNIFIED_VIEW_MODES, type UnifiedViewMode } from "@/lib/unifiedViewMode"

const TIMEFRAMES = ["This Week", "Daily", "Weekly", "Monthly"] as const
const TIMEFRAME_OPTIONS = TIMEFRAMES.map(tf => ({
  value: tf,
  label: tf === "This Week" ? "Past Week" : tf,
}))
type Timeframe = typeof TIMEFRAMES[number]
const DEFAULT_INDEX_ORDER = [
  "S&P 500",
  "NASDAQ",
  "Russell 2000",
  "STOXX 600",
  "FTSE London",
  "DAX",
  "CAC 40",
  "Nikkei 225",
  "KOSPI",
]

function timeframeLabel(timeframe: Timeframe): string {
  return timeframe === "This Week" ? "Past Week" : timeframe
}

export function IndexDashboard() {
  const [timeframe, setTimeframe] = useState<Timeframe>("This Week")
  const [viewMode, setViewMode] = useState<UnifiedViewMode>("Grid")
  const { data, isLoading, error, isSuccess, isPlaceholderData } = useApiQuery(
    ["index-dashboard", timeframe],
    () => fetchIndexDashboard(timeframe),
    dashboardTimeframeStaleTime(timeframe),
    { placeholderData: keepPreviousData },
  )
  const displayedTimeframe = useDisplayedQueryParameter(timeframe, isPlaceholderData)
  useDashboardTimeframePrefetch({
    queryKeyRoot: "index-dashboard",
    timeframes: TIMEFRAMES,
    activeTimeframe: timeframe,
    isReady: isSuccess && !isPlaceholderData,
    fetchTimeframe: fetchIndexDashboard,
  })

  const indices: Record<string, DataPoint[]> = data?.indices ?? {}
  const order: string[] = data?.index_order ?? [
    ...DEFAULT_INDEX_ORDER.filter(name => indices[name]?.length),
    ...Object.keys(indices).filter(name => !DEFAULT_INDEX_ORDER.includes(name)),
  ]
  const hasSeries = order.some(name => {
    const series = indices[name]
    return Array.isArray(series) && series.length > 0
  })

  return (
    <div>
      <PageHeader
        title="Index Dashboard"
        subtitle="Primary equity benchmarks in a compact chart grid and comparable performance view."
        actions={<RefreshButton queryKeys={[["index-dashboard", timeframe]]} />}
      />
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <SegmentedControl
          options={TIMEFRAME_OPTIONS}
          value={timeframe}
          onChange={setTimeframe}
        />
        <SegmentedControl
          options={UNIFIED_VIEW_MODES.map(mode => ({ value: mode, label: mode }))}
          value={viewMode}
          onChange={setViewMode}
        />
      </div>
      {isPlaceholderData && (
        <p role="status" className="mb-4 text-sm text-muted">
          Updating to {timeframeLabel(timeframe)}… Showing {timeframeLabel(displayedTimeframe)} until the new data arrives.
        </p>
      )}
      {isLoading && <LoadingSpinner />}
      {!isLoading && error && <ErrorMessage message={String(error)} />}
      {data && !isLoading && !error && !hasSeries && (
        <Notice tone="info">No price series available.</Notice>
      )}
      {data && !isLoading && hasSeries && viewMode === "Grid" && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {order.map(name => {
            const series = indices[name]
            if (!series || series.length === 0) return null
            const ret = calcReturn(series)
            return (
              <ChartTile
                key={name}
                title={name}
                meta={ret != null ? (
                  <span className={`text-xs font-semibold ${ret >= 0 ? "text-positive" : "text-negative"}`}>
                    {ret >= 0 ? "+" : ""}{ret.toFixed(2)}%
                  </span>
                ) : undefined}
              >
                <TimeSeriesChart data={series} height={160} timeframe={displayedTimeframe} />
              </ChartTile>
            )
          })}
        </div>
      )}
      {data && !isLoading && hasSeries && viewMode === "Unified" && (
        <UnifiedPerformanceView
          order={order}
          seriesByName={indices}
          timeframe={displayedTimeframe}
          timeframeLabel={timeframeLabel(displayedTimeframe)}
          itemLabel="indices"
        />
      )}
    </div>
  )
}
