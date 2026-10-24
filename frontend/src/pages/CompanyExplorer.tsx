import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { NameDocumentsPanel } from "@/components/NameDocumentsPanel"

import { EquityOverviewReadView, FinancialsSnapshot } from "@/components/overview/EquityOverviewReadView"
import { ActionButton, TextInput } from "@/components/shared/FormControls"
import { LoadingSpinner } from "@/components/shared/LoadingSpinner"
import { PageHeader } from "@/components/shared/PageHeader"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { TimeSeriesChart, type SeriesDef } from "@/components/shared/TimeSeriesChart"
import { fetchDossier, runChart } from "@/lib/api"
import type { ParsedOverview } from "@/lib/overviewTypes"

const formatPrice = (value: number) => PRICE_FORMATTER.format(value)

const CLOSE_SERIES: SeriesDef[] = [
  { key: "Close", name: "Close", color: "hsl(var(--accent))", strokeWidth: 2 },
]

const PRICE_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

type ExplorerDossier = {
  position?: Record<string, unknown> | null
  related_portfolio_legs?: unknown[] | null
  overview_content?: string | null
  overview_parsed?: ParsedOverview | null
  management_quality?: { content?: string | null } | null
  thesis?: { meta?: unknown; content?: string | null } | null
  thesis_claims?: unknown[] | null
  catalysts?: unknown[] | null
  kill_conditions?: unknown[] | null
  evaluations?: unknown[] | null
}

type ChartPayload = {
  name?: string
  ticker?: string
  price_data?: Record<string, unknown>[]
}

function hasItems(value: unknown[] | null | undefined) {
  return Array.isArray(value) && value.length > 0
}

function hasDossierMaterial(data: ExplorerDossier | undefined) {
  if (!data) return false
  return Boolean(
    data.position ||
    hasItems(data.related_portfolio_legs) ||
    data.overview_content ||
    data.management_quality?.content ||
    data.thesis?.meta ||
    data.thesis?.content ||
    hasItems(data.thesis_claims) ||
    hasItems(data.catalysts) ||
    hasItems(data.kill_conditions) ||
    hasItems(data.evaluations),
  )
}

function errorMessage(error: unknown) {
  return error instanceof Error && error.message ? error.message : "Request failed"
}

function chartDate(row: Record<string, unknown>) {
  const raw = row.Date ?? row.date ?? row.index
  return raw == null ? "" : String(raw)
}

function chartClose(row: Record<string, unknown>) {
  const value = row.Close
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function TickerForm({
  value,
  onChange,
  onSubmit,
}: {
  value: string
  onChange: (value: string) => void
  onSubmit: (event: FormEvent) => void
}) {
  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <TextInput
        id="company-explorer-ticker"
        label="Ticker"
        value={value}
        onChange={onChange}
        placeholder="AAPL"
        className="w-40"
        uppercase
      />
      <ActionButton type="submit" disabled={!value.trim()} className="w-auto px-6">
        Open
      </ActionButton>
    </form>
  )
}

function PriceChart({ ticker }: { ticker: string }) {
  const chartQuery = useQuery({
    queryKey: ["explore", "chart", ticker],
    queryFn: () => runChart({ ticker, lookback: "1Y" }) as Promise<ChartPayload>,
    staleTime: 300_000,
  })
  const points = useMemo(() => {
    const rows = Array.isArray(chartQuery.data?.price_data) ? chartQuery.data.price_data : []
    return rows
      .map(row => ({
        date: chartDate(row),
        Close: chartClose(row),
      }))
      .filter(point => point.date)
  }, [chartQuery.data])

  return (
    <SurfaceCard className="min-w-0 p-4 sm:p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-app">Price</h2>
      {chartQuery.isLoading && <LoadingSpinner message="Loading price chart..." />}
      {chartQuery.error && (
        <p className="mt-3 text-sm text-red-500">Price chart unavailable: {errorMessage(chartQuery.error)}</p>
      )}
      {!chartQuery.isLoading && !chartQuery.error && points.length === 0 && (
        <p className="mt-3 text-sm text-muted">No price history for this ticker.</p>
      )}
      {points.length > 0 && (
        <div className="mt-3">
          <TimeSeriesChart
            multiData={points}
            series={CLOSE_SERIES}
            height={200}
            yFormatter={formatPrice}
            tooltipFormatter={formatPrice}
          />
        </div>
      )}
    </SurfaceCard>
  )
}

function ExplorerDashboard({ ticker }: { ticker: string }) {
  const chartQuery = useQuery({
    queryKey: ["explore", "chart", ticker],
    queryFn: () => runChart({ ticker, lookback: "1Y" }) as Promise<ChartPayload>,
    staleTime: 300_000,
  })
  const dossierQuery = useQuery({
    queryKey: ["dossier", ticker],
    queryFn: () => fetchDossier(ticker) as Promise<ExplorerDossier>,
    staleTime: 60_000,
    retry: 1,
  })
  const companyName = typeof chartQuery.data?.name === "string" ? chartQuery.data.name.trim() : ""
  const dossier = dossierQuery.data
  const showDossierLinks = hasDossierMaterial(dossier)
  const overviewContent = dossier?.overview_content ?? null
  const overviewParsed = dossier?.overview_parsed ?? null
  const hasOverview = Boolean(overviewContent || overviewParsed)
  const dossierPath = `/dossier/${encodeURIComponent(ticker)}`

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-2xl font-semibold tracking-tight text-app">{ticker}</p>
          {companyName && companyName.toUpperCase() !== ticker && (
            <p className="mt-1 text-sm text-muted">{companyName}</p>
          )}
        </div>
        {showDossierLinks && (
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <Link className="text-sm font-medium text-link hover:underline" to={dossierPath}>Dossier</Link>
            <Link className="text-sm font-medium text-link hover:underline" to={`${dossierPath}?tab=thesis`}>Thesis</Link>
            <Link className="text-sm font-medium text-link hover:underline" to={`${dossierPath}?tab=risk`}>Risk</Link>
          </div>
        )}
      </div>

      <PriceChart ticker={ticker} />
      <NameDocumentsPanel key={ticker} ticker={ticker} />

      <SurfaceCard className="min-w-0 p-4 sm:p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-app">Financials</h2>
        <FinancialsSnapshot ticker={ticker} />
      </SurfaceCard>

      <SurfaceCard className="min-w-0 p-4 sm:p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-app">Overview</h2>
        {dossierQuery.isLoading && <LoadingSpinner message="Loading overview..." />}
        {dossierQuery.error && (
          <p className="text-sm text-red-500">Overview unavailable: {errorMessage(dossierQuery.error)}</p>
        )}
        {!dossierQuery.isLoading && !dossierQuery.error && hasOverview && (
          <EquityOverviewReadView
            content={overviewContent}
            parsed={overviewParsed}
            ticker={ticker}
            includeFinancials={false}
          />
        )}
        {!dossierQuery.isLoading && !dossierQuery.error && !hasOverview && (
          <p className="text-sm text-muted">No overview on file.</p>
        )}
      </SurfaceCard>
    </div>
  )
}

export function CompanyExplorer() {
  const { ticker: tickerParam } = useParams<{ ticker?: string }>()
  const navigate = useNavigate()
  const routeTicker = (tickerParam ?? "").trim().toUpperCase()
  const [draft, setDraft] = useState(routeTicker)

  useEffect(() => {
    setDraft(routeTicker)
  }, [routeTicker])

  function openTicker(event: FormEvent) {
    event.preventDefault()
    const next = draft.trim().toUpperCase()
    if (!next) return
    navigate(`/explore/${encodeURIComponent(next)}`)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Labs"
        title="Company Explorer"
        subtitle={routeTicker ? undefined : "Open any ticker, including names that are not in the book."}
      />
      <TickerForm value={draft} onChange={setDraft} onSubmit={openTicker} />
      {routeTicker ? (
        <ExplorerDashboard ticker={routeTicker} />
      ) : (
        <p className="text-sm text-muted">Enter a ticker to open the company summary.</p>
      )}
    </div>
  )
}
