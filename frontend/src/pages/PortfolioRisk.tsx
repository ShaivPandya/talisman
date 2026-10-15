import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { ArrowDownUp, RefreshCw } from "lucide-react"
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { MetricCard } from "@/components/shared/MetricCard"
import { Notice } from "@/components/shared/Notice"
import { PageHeader } from "@/components/shared/PageHeader"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { fetchPortfolioRiskDashboard, fetchPortfolioRiskDashboardJob, refreshPortfolioRiskDashboard } from "@/lib/api"
import {
  riskBeta, riskDate, riskMoney, riskPercent,
  type PortfolioRiskDashboard, type RiskDashboardPosition, type RiskDashboardView, type RiskExposureBucket,
} from "@/lib/portfolioRisk"

const QUERY_KEY = ["portfolio-risk-dashboard"]
const ACTIVE_JOB_KEY = "portfolio-risk-dashboard:active-job:v1"
const CHART_COLOR = "#3b82f6"
const HEDGE_COLOR = "#a78bfa"
const COMBINED_COLOR = "#06b6d4"
const AXIS_COLOR = "var(--color-text-muted)"

function readActiveJob(): string | null {
  try { return sessionStorage.getItem(ACTIVE_JOB_KEY) } catch { return null }
}

function saveActiveJob(jobId: string | null) {
  try {
    if (jobId) sessionStorage.setItem(ACTIVE_JOB_KEY, jobId)
    else sessionStorage.removeItem(ACTIVE_JOB_KEY)
  } catch { /* Refresh polling also works when browser storage is unavailable. */ }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Risk refresh failed. Please retry."
}

function ConcentrationChart({ title, rows }: { title: string; rows: RiskExposureBucket[] }) {
  const visible = rows.slice(0, 8)
  const hasShares = rows.some(row => row.gross_share_pct != null)
  return (
    <SurfaceCard className="min-w-0 p-4 sm:p-5">
      <h2 className="text-base font-semibold text-app">{title}</h2>
      <p className="mt-1 text-xs text-subtle">Share of measured gross linear exposure{rows.length > 8 ? ` · top 8 of ${rows.length}` : ""}</p>
      {hasShares ? (
        <div className="mt-4 h-64" role="img" aria-label={`${title} as shares of measured gross exposure`}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={visible} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 0 }} accessibilityLayer>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--color-border)" />
              <XAxis type="number" domain={[0, 100]} tickFormatter={value => `${value}%`} tick={{ fill: AXIS_COLOR, fontSize: 11 }} />
              <YAxis type="category" dataKey="name" width={105} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickFormatter={value => String(value).length > 16 ? `${String(value).slice(0, 15)}…` : String(value)} />
              <Tooltip contentStyle={{ background: "var(--color-bg-card)", borderColor: "var(--color-border)", color: "var(--color-text)" }} formatter={value => [riskPercent(Number(value)), "Gross share"]} />
              <Bar dataKey="gross_share_pct" fill={CHART_COLOR} radius={[0, 3, 3, 0]} maxBarSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : <p className="py-8 text-sm text-muted">No measured gross exposure to compare.</p>}
      {rows.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted">All {title.toLowerCase()} values</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-xs" aria-label={`${title} values`}>
              <thead><tr><th className="py-2">Name</th><th className="py-2 text-right">Gross</th><th className="py-2 text-right">Net</th><th className="py-2 text-right">Share</th></tr></thead>
              <tbody>{rows.map(row => <tr key={row.name} className="border-t border-app">
                <td className="py-2 pr-2 text-app">{row.name}</td><td className="py-2 text-right tabular-nums">{riskMoney(row.gross_usd)}</td><td className="py-2 text-right tabular-nums">{riskMoney(row.net_usd)}</td><td className="py-2 text-right tabular-nums">{riskPercent(row.gross_share_pct)}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </details>
      )}
    </SurfaceCard>
  )
}

function MarketBetas({ view, includeHedges }: { view: RiskDashboardView; includeHedges: boolean }) {
  const chartRows = (["SPY", "IWM"] as const).map(benchmark => ({ benchmark, ...view.betas[benchmark] }))
  const hasBeta = chartRows.some(row => row.combined != null && row.covered_count > 0)
  return (
    <SurfaceCard className="min-w-0 p-4 sm:p-5">
      <h2 className="text-base font-semibold text-app">Equity market beta</h2>
      <p className="mt-1 text-xs leading-5 text-subtle">Sensitivity per dollar of book to each benchmark independently. Equities and equity-index futures only; option deltas are unavailable.</p>
      {hasBeta ? <div className="mt-3 h-52" role="img" aria-label="SPY and IWM beta contributions from primary holdings and held hedges">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartRows} margin={{ top: 10, right: 10, bottom: 0, left: 0 }} accessibilityLayer>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
            <XAxis dataKey="benchmark" tick={{ fill: AXIS_COLOR, fontSize: 12 }} />
            <YAxis tickFormatter={value => `${Number(value).toFixed(1)}×`} tick={{ fill: AXIS_COLOR, fontSize: 11 }} width={48} />
            <ReferenceLine y={0} stroke="var(--color-text-muted)" />
            <Tooltip contentStyle={{ background: "var(--color-bg-card)", borderColor: "var(--color-border)", color: "var(--color-text)" }} formatter={value => riskBeta(Number(value))} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="primary" name="Primary holdings" fill={CHART_COLOR} maxBarSize={44} />
            {includeHedges && <Bar dataKey="hedges" name="Held hedges" fill={HEDGE_COLOR} maxBarSize={44} />}
            {includeHedges && <Bar dataKey="combined" name="Combined" fill={COMBINED_COLOR} maxBarSize={44} />}
          </BarChart>
        </ResponsiveContainer>
      </div> : <p className="py-8 text-sm text-muted">Market beta unavailable for the selected holdings.</p>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {chartRows.map(row => <div key={row.benchmark} className="rounded-lg border border-app p-3">
          <p className="text-sm font-medium text-app">{row.benchmark} · {riskBeta(row.covered_count ? row.combined : null)}</p>
          <p className="mt-1 text-xs text-subtle">{row.covered_count}/{row.eligible_count} eligible positions measured · {riskPercent(row.covered_gross_pct)} of gross exposure</p>
          {includeHedges && <p className="mt-1 text-xs text-muted">Primary {riskBeta(row.primary)} · hedges {riskBeta(row.hedges)}</p>}
        </div>)}
      </div>
    </SurfaceCard>
  )
}

function StressSummary({ data }: { data: PortfolioRiskDashboard }) {
  const stress = data.stress
  const hasStress = Boolean(stress && (stress.position_count ?? 0) > 0)
  const score = (value: number | null | undefined) => value == null ? "Unavailable" : `${(value * 100).toFixed(0)} / 100`
  return (
    <SurfaceCard className="min-w-0 p-4 sm:p-5">
      <h2 className="text-base font-semibold text-app">Primary-position stress</h2>
      <p className="mt-1 text-xs leading-5 text-subtle">Unweighted market-stress scores across primary positions. Measures volatility, breadth, sector and macro stress; scores are not loss probabilities.</p>
      {hasStress ? <>
        <div className="mt-5 grid grid-cols-2 gap-4">
          <div><p className="text-xs text-subtle">Average stress</p><p className="mt-1 text-xl font-semibold text-app">{score(stress?.average_risk_score)}</p></div>
          <div><p className="text-xs text-subtle">Maximum stress</p><p className="mt-1 text-xl font-semibold text-app">{score(stress?.max_risk_score)}</p></div>
        </div>
        <dl className="mt-5 flex flex-wrap gap-4 text-sm">
          {(["high", "medium", "low"] as const).map(level => <div key={level}><dt className="capitalize text-subtle">{level}</dt><dd className="mt-1 font-semibold text-app">{stress?.risk_buckets?.[level] ?? "Unavailable"}</dd></div>)}
        </dl>
        <p className="mt-4 text-xs text-subtle">{stress?.position_count} primary positions · as of {riskDate(stress?.as_of || stress?.computed_at)}</p>
        <div className="mt-3"><StatusBadge tone={stress?.quality === "ok" ? "success" : "warning"}>{stress?.quality === "ok" ? "Sources available" : "Sources degraded"}</StatusBadge></div>
      </> : <p className="py-8 text-sm text-muted">No primary-position stress snapshot available.</p>}
      {data.source_status.stress?.error && <p className="mt-3 text-xs text-muted">Stress refresh failed; the prior stress snapshot is shown.</p>}
    </SurfaceCard>
  )
}

type PositionSort = "ticker" | "gross_notional" | "weight_pct" | "beta_contribution_spy"

function PositionDetails({ rows }: { rows: RiskDashboardPosition[] }) {
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState<PositionSort>("gross_notional")
  const [ascending, setAscending] = useState(false)
  const visible = useMemo(() => {
    const query = search.trim().toLowerCase()
    return rows.filter(row => [row.ticker, row.underlying_ticker, row.asset, row.sector, row.group_name, row.role].some(value => value?.toLowerCase().includes(query))).sort((a, b) => {
      if (sort === "ticker") return a.ticker.localeCompare(b.ticker) * (ascending ? 1 : -1)
      const left = a[sort], right = b[sort]
      if (left == null) return right == null ? 0 : 1
      if (right == null) return -1
      return (left - right) * (ascending ? 1 : -1)
    })
  }, [rows, search, sort, ascending])
  function sortBy(next: PositionSort) {
    setAscending(next === sort ? !ascending : next === "ticker")
    setSort(next)
  }
  function sortHeader(label: string, key: PositionSort) {
    return <th scope="col" className="px-3 py-3 text-left" aria-sort={sort === key ? ascending ? "ascending" : "descending" : "none"}>
      <button type="button" onClick={() => sortBy(key)} className="inline-flex items-center gap-1 whitespace-nowrap font-semibold">{label}<ArrowDownUp size={12} aria-hidden="true" /></button>
    </th>
  }
  return <SurfaceCard className="min-w-0 p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base font-semibold text-app">Linear position details</h2>
      <input type="search" aria-label="Search positions" placeholder="Search positions" value={search} onChange={event => setSearch(event.target.value)} className="theme-input w-full sm:w-64" />
    </div>
    <p className="mt-2 text-xs text-subtle">{visible.length} of {rows.length} positions · search and sort apply to this table</p>
    <div className="mt-4 overflow-x-auto rounded-lg border border-app">
      <table className="w-full text-sm" aria-label="Linear position details">
        <thead className="bg-card-muted text-xs text-muted"><tr>
          {sortHeader("Ticker", "ticker")}<th scope="col" className="px-3 py-3 text-left">Role / asset</th><th scope="col" className="px-3 py-3 text-left">Sector / group</th>
          {sortHeader("Gross USD", "gross_notional")}{sortHeader("Book exposure", "weight_pct")}{sortHeader("SPY contribution", "beta_contribution_spy")}<th scope="col" className="px-3 py-3 text-left">IWM contribution</th><th scope="col" className="px-3 py-3 text-left">Evidence</th>
        </tr></thead>
        <tbody>{visible.map(row => <tr key={row.position_id} className="border-t border-app align-top">
          <td className="px-3 py-3"><Link className="font-medium text-blue-600 underline-offset-2 hover:underline dark:text-blue-400" to={`/dossier/${encodeURIComponent(row.underlying_ticker || row.ticker)}`}>{row.ticker}</Link>
            <p className="mt-1 whitespace-nowrap text-xs text-subtle">{row.direction}{row.exposure_multiplier !== 1 ? ` · ${row.exposure_multiplier}× ${row.underlying_ticker}` : ""}</p></td>
          <td className="px-3 py-3"><p className="capitalize">{row.role === "hedge" ? "Hedge" : "Primary"}</p><p className="mt-1 text-xs text-subtle">{row.asset || "Unclassified"}</p></td>
          <td className="px-3 py-3"><p>{row.sector || "Unclassified"}</p><p className="mt-1 text-xs text-subtle">{row.group_name || "Ungrouped"}</p></td>
          <td className="whitespace-nowrap px-3 py-3 tabular-nums">{riskMoney(row.gross_notional, 2)}</td><td className="whitespace-nowrap px-3 py-3 tabular-nums">{riskPercent(row.weight_pct)}</td>
          <td className="whitespace-nowrap px-3 py-3 tabular-nums">{riskBeta(row.beta_contribution_spy)}</td><td className="whitespace-nowrap px-3 py-3 tabular-nums">{riskBeta(row.beta_contribution_iwm)}</td>
          <td className="min-w-48 px-3 py-3"><details><summary className="cursor-pointer text-xs text-muted">{row.issues.length ? `${row.issues.length} coverage gaps` : "Prices and drivers"}</summary>
            <div className="mt-2 space-y-1 text-xs text-subtle">
              <p>Close: {row.price ?? "Unavailable"} {row.currency} · {riskDate(row.price_as_of)}</p><p>USD FX: {row.fx_rate_to_usd ?? "Unavailable"} · {riskDate(row.fx_as_of)}</p>
              <p>SPY beta: {riskBeta(row.beta_spy)} · {row.beta_spy_observations} observations</p><p>IWM beta: {riskBeta(row.beta_iwm)} · {row.beta_iwm_observations} observations</p>
              <p>Beta eligibility: {row.beta_status.replaceAll("_", " ")}</p>
              <p>Stress: {row.risk_score == null ? "Unavailable" : `${(row.risk_score * 100).toFixed(0)} / 100`}</p>
              {row.issues.map(issue => <p key={issue}>{issue.replaceAll("_", " ")}</p>)}
              {row.drivers.map((driver, index) => <p key={index}>{String(driver.detail || driver.reason || driver.label || driver.component || "")}</p>)}
            </div>
          </details></td>
        </tr>)}</tbody>
      </table>
    </div>
    {visible.length === 0 && <p className="mt-4 text-sm text-muted">{rows.length ? "No positions match this search." : "No linear positions in this view."}</p>}
  </SurfaceCard>
}

function OptionPremiums({ rows }: { rows: RiskDashboardPosition[] }) {
  return <SurfaceCard className="min-w-0 p-4 sm:p-5">
    <h2 className="text-base font-semibold text-app">Option premiums</h2>
    <p className="mt-1 text-xs leading-5 text-subtle">Premium values are separate from linear exposure and market beta. Underlying delta exposure is unavailable.</p>
    {rows.length ? <div className="mt-4 overflow-x-auto rounded-lg border border-app">
      <table className="w-full text-left text-sm" aria-label="Option premiums">
        <thead className="bg-card-muted text-xs text-muted"><tr>{["Contract", "Role", "Direction", "Quantity", "Premium USD", "Close date", "Delta exposure"].map(label => <th key={label} scope="col" className="whitespace-nowrap px-3 py-3">{label}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.position_id} className="border-t border-app">
          <td className="px-3 py-3"><Link className="text-blue-600 hover:underline dark:text-blue-400" to={`/dossier/${encodeURIComponent(row.underlying_ticker || row.ticker)}`}>{row.ticker} {row.option_type} {row.option_strike}</Link><p className="mt-1 whitespace-nowrap text-xs text-subtle">{row.price_symbol || "Contract unavailable"} · {riskDate(row.option_expiration)}</p></td>
          <td className="px-3 py-3">{row.role === "hedge" ? "Hedge" : "Primary"}</td><td className="px-3 py-3 capitalize">{row.direction}</td><td className="px-3 py-3">{row.quantity ?? "Unavailable"}</td>
          <td className="whitespace-nowrap px-3 py-3 tabular-nums">{riskMoney(row.premium_usd, 2)}{row.issues.length > 0 && <p className="mt-1 text-xs text-subtle">{row.issues.map(issue => issue.replaceAll("_", " ")).join(", ")}</p>}</td>
          <td className="whitespace-nowrap px-3 py-3">{riskDate(row.price_as_of)}</td><td className="px-3 py-3 text-muted">Unavailable</td>
        </tr>)}</tbody>
      </table>
    </div> : <p className="mt-4 text-sm text-muted">No option positions in this view.</p>}
  </SurfaceCard>
}

export function PortfolioRisk() {
  const queryClient = useQueryClient()
  const [includeHedges, setIncludeHedges] = useState(true)
  const [jobId, setJobId] = useState<string | null>(readActiveJob)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const snapshot = useQuery({ queryKey: QUERY_KEY, queryFn: fetchPortfolioRiskDashboard, retry: false, staleTime: 60_000 })
  const job = useQuery({
    queryKey: ["portfolio-risk-dashboard-job", jobId],
    queryFn: async () => {
      const result = await fetchPortfolioRiskDashboardJob(jobId!)
      if (["done", "error", "cancelled"].includes(result.status)) {
        saveActiveJob(null)
        setJobId(null)
        setRefreshError(result.status === "done" ? null : result.error || "Refresh failed. The prior snapshot is still available.")
        void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
      }
      return result
    },
    enabled: Boolean(jobId), retry: false,
    refetchInterval: query => query.state.data?.status === "queued" || query.state.data?.status === "running" ? 1500 : false,
  })
  const refresh = useMutation({
    mutationFn: refreshPortfolioRiskDashboard,
    onMutate: () => setRefreshError(null),
    onSuccess: result => {
      if (result.status === "done") {
        saveActiveJob(null)
        setJobId(null)
        void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
      } else if (result.status === "error" || result.status === "cancelled") {
        setRefreshError(result.error || "Refresh failed. Please retry.")
      } else {
        saveActiveJob(result.job_id)
        setJobId(result.job_id)
      }
    },
    onError: error => setRefreshError(errorText(error)),
  })
  const refreshing = refresh.isPending || Boolean(jobId && !job.error && (!job.data || job.data.status === "queued" || job.data.status === "running"))
  const data = snapshot.data
  const view = data?.views[includeHedges ? "all_holdings" : "primary_positions"]
  const selected = data?.positions.filter(row => includeHedges || row.role !== "hedge") ?? []
  const linear = selected.filter(row => row.instrument_type !== "option")
  const options = selected.filter(row => row.instrument_type === "option")
  return <div className="space-y-5">
    <PageHeader title="Portfolio Risk" subtitle="Daily exposure, concentration and market sensitivity" actions={
      <button type="button" onClick={() => refresh.mutate()} disabled={refreshing} className="theme-button-base theme-button-primary min-h-11 px-4">
        <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} aria-hidden="true" />{refreshing ? "Refreshing risk…" : "Refresh risk"}
      </button>
    } />
    {refreshing && <div role="status"><Notice>Risk refresh is {job.data?.status || "queued"}. The saved snapshot remains available while daily closes and betas are calculated.</Notice></div>}
    {(refreshError || job.error) && <div role="alert"><Notice tone="error">{refreshError || errorText(job.error)} Use Refresh risk to retry.</Notice></div>}
    {snapshot.isLoading && <p role="status" className="text-sm text-muted">Loading risk snapshot…</p>}
    {snapshot.error && <div role="alert"><Notice tone="error">Could not load the risk snapshot. {errorText(snapshot.error)} <button type="button" className="underline" onClick={() => void snapshot.refetch()}>Retry loading</button></Notice></div>}
    {!snapshot.isLoading && !snapshot.error && !data && <SurfaceCard className="p-6"><h2 className="text-lg font-semibold text-app">No risk dashboard snapshot yet</h2><p className="mt-2 text-sm text-muted">Use Refresh risk to calculate exposures and market betas from your current holdings.</p></SurfaceCard>}
    {data && view && <>
      <SurfaceCard className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="space-y-1 text-sm text-muted"><p>Book: <strong className="text-app">{riskMoney(data.book_size)}</strong> USD{data.book_is_default && <span className="ml-2"><StatusBadge tone="warning">Default book size</StatusBadge></span>}</p><p className="text-xs text-subtle">Closes as of {riskDate(data.as_of)} · calculated {riskDate(data.computed_at)}</p></div>
        <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-app"><input type="checkbox" checked={includeHedges} onChange={event => setIncludeHedges(event.target.checked)} className="h-4 w-4 accent-blue-600" />Include held hedges</label>
      </SurfaceCard>
      {data.freshness.stale && <Notice tone="warning"><strong>Snapshot needs refresh.</strong> {data.freshness.holdings_changed && "Holdings have changed. "}{data.freshness.book_changed && "Book settings have changed. "}{data.freshness.market?.fresh === false && `The latest expected close is ${riskDate(data.freshness.market.expected_as_of_date)}. `}{data.freshness.refresh_error && "The last refresh failed; prior successful values are shown. "}Use Refresh risk to update.</Notice>}
      {view.coverage.position_count === 0 && <Notice>No holdings in this view.</Notice>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(["long", "short", "gross", "net"] as const).map(key => <MetricCard key={key} title={`${key[0].toUpperCase()}${key.slice(1)} linear exposure`} value={riskPercent(view.summary[`${key}_pct`])} subtitle={`${riskMoney(view.summary[`${key}_usd`])} · % of book`} />)}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted" aria-label="Data coverage">
        <span>{view.coverage.valued_linear_count}/{view.coverage.linear_count} linear positions valued</span><span>{view.coverage.priced_option_count}/{view.coverage.option_count} option premiums valued separately</span><span>{view.coverage.classification_gap_count} positions with classification gaps</span>
      </div>
      {view.coverage.valued_linear_count < view.coverage.linear_count && <Notice tone="warning">Exposure totals cover measured positions only. Positions with missing quantities, closing prices or FX rates remain in the details below.</Notice>}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]"><MarketBetas view={view} includeHedges={includeHedges} /><StressSummary data={data} /></div>
      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        <ConcentrationChart title="Underlying concentration" rows={view.breakdowns.underlying} /><ConcentrationChart title="Sector concentration" rows={view.breakdowns.sector} />
        <ConcentrationChart title="Asset concentration" rows={view.breakdowns.asset} /><ConcentrationChart title="Group concentration" rows={view.breakdowns.group} />
      </div>
      <PositionDetails rows={linear} /><OptionPremiums rows={options} />
      <SurfaceCard className="p-4 sm:p-5"><details><summary className="cursor-pointer text-sm font-medium text-app">Sources and calculation details</summary><div className="mt-4 space-y-2 text-xs leading-5 text-muted">
        <p>Linear exposure = quantity × daily closing price × contract multiplier × USD FX rate × direction × economic leverage. Concentration sums absolute leg exposures before netting. Option premiums are excluded.</p>
        <p>SPY and IWM are separate market regressions, using {data.beta_method.lookback_days} calendar days of adjusted daily history, {data.beta_method.halflife_observations}-observation half-life, {data.beta_method.minimum_observations} minimum paired returns and {data.beta_method.shrink_to_one * 100}% shrinkage toward one. No assumed beta is counted as measured.</p>
        {Object.entries(data.source_status).map(([name, source]) => <p key={name}><strong className="capitalize text-app">{name}:</strong> {source.provider || source.quality || "Unavailable"} · as of {riskDate(source.as_of)}{source.error && ` · ${source.error}`}</p>)}
        {Object.entries(data.stress?.source_status || {}).map(([name, source]) => <p key={name}>{name.replaceAll("_", " ")}: {source.status || "Unavailable"} · {riskDate(source.as_of)}{source.reason && ` · ${source.reason}`}</p>)}
      </div></details></SurfaceCard>
    </>}
  </div>
}
