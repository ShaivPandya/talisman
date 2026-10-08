import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { TourTarget } from "@/components/tour/TourTarget"
import { SavedRunPicker } from "@/components/shared/SavedRunPicker"
import { useSelectedRun } from "@/lib/useSelectedRun"
import { fmtNumber, fmtRatioPct, fmtUtc } from "@/lib/format"
import { valuationRanges } from "@/lib/reportDisplay"
import {
  getValuationActions,
  getValuationMultiples,
  type ValuationActions,
  type ValuationMultiples,
} from "@/lib/valuationApi"

function RangeBar({
  label,
  low,
  mid,
  high,
  held,
  domain,
}: {
  label: string
  low: number
  mid: number
  high: number
  held: string
  domain: [number, number]
}) {
  const width = domain[1] - domain[0] || 1
  const left = ((low - domain[0]) / width) * 100,
    span = ((high - low) / width) * 100
  return (
    <SurfaceCard className="p-5">
      <h2 className="font-semibold">{label}</h2>
      <p className="caption mt-1">{held}</p>
      <div
        aria-hidden="true"
        className="relative my-6 h-5 rounded bg-card-muted"
      >
        <div
          className="absolute h-5 rounded"
          style={{
            left: `${left}%`,
            width: `${Math.max(span, 0.5)}%`,
            background: "#527a85",
          }}
        />
        <div
          className="absolute -top-1 h-7 border-l-2 border-app"
          style={{ left: `${((mid - domain[0]) / width) * 100}%` }}
        />
      </div>
      <p className="text-sm">
        Low ${fmtNumber(low)} · Center ${fmtNumber(mid)} · High $
        {fmtNumber(high)}
      </p>
      <p className="caption mt-2">Spread ${fmtNumber(high - low)} per share</p>
    </SurfaceCard>
  )
}

export function ValuationPage() {
  const [params, setParams] = useSearchParams()
  const runId = params.get("run_id") ?? ""
  const [revision, setRevision] = useState(0)
  const { run, error: runError } = useSelectedRun(runId, revision)
  const [state, setState] = useState<{
    id: string
    actions: ValuationActions | null
    multiples: ValuationMultiples | null
    error: string | null
  }>({ id: "", actions: null, multiples: null, error: null })
  useEffect(() => {
    if (!run || run.status !== "succeeded") return
    let cancelled = false
    Promise.all([
      getValuationActions(run.id),
      getValuationMultiples(run.cutoff_ts),
    ])
      .then(([actions, multiples]) => {
        if (!cancelled)
          setState({ id: run.id, actions, multiples, error: null })
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setState({
            id: run.id,
            actions: null,
            multiples: null,
            error: e instanceof Error ? e.message : "Unable to load valuation",
          })
      })
    return () => {
      cancelled = true
    }
  }, [run, revision])
  const current = state.id === runId ? state : null
  const actions = current?.actions,
    bridge = actions?.bridge
  const ranges = bridge ? valuationRanges(bridge) : []
  const domain: [number, number] = [
    Math.min(...ranges.map((r) => r.low)),
    Math.max(...ranges.map((r) => r.high)),
  ]
  const error = runError ?? current?.error
  return (
    <TourTarget id="valuation-results" status={error ? "error" : run && run.status !== "succeeded" ? "empty" : actions ? "ready" : "loading"} message={error} onRetry={() => { setState({ id: "", actions: null, multiples: null, error: null }); setRevision((n) => n + 1) }}>
      <header className="theme-page-header">
        <div>
          <h1 className="theme-page-title">Valuation & Actions</h1>
          <p className="theme-page-subtitle">
            Forward earnings, multiple assumptions and illustrative action
            costs.
          </p>
        </div>
      </header>
      <SavedRunPicker
        runId={runId}
        run={run}
        onSelect={(id) => setParams({ run_id: id })}
      />
      {error && (
        <div className="theme-notice theme-notice-error mb-4">
          {error}{" "}
          <button
            className="theme-button-base theme-button-secondary"
            onClick={() => {
              setState({ id: "", actions: null, multiples: null, error: null })
              setRevision((n) => n + 1)
            }}
          >
            Retry valuation
          </button>
        </div>
      )}
      {runId && !run && !error && <p role="status">Loading saved run…</p>}
      {run && run.status !== "succeeded" && (
        <p className="theme-notice">
          Run is {run.status}. Valuation requires a successful run.
        </p>
      )}
      {run?.status === "succeeded" && !current && !error && (
        <p role="status">Loading valuation…</p>
      )}
      {actions && bridge && (
        <>
          <SurfaceCard className="p-5 mb-5">
            <p className="theme-badge theme-badge-neutral report-illustrative">{actions.label}</p>
            <p className="body-copy mt-3">
              {run?.origin_label} · {fmtUtc(bridge.cutoff_ts)} ·{" "}
              {bridge.n_paths.toLocaleString()} paths · {bridge.n_quarters}{" "}
              quarters
            </p>
            <p className="mt-2 text-sm">
              <Link className="text-link" to={`/runs/${runId}`}>
                Run details
              </Link>{" "}
              ·{" "}
              <Link className="text-link" to={`/replay?run_id=${runId}`}>
                Replay this run
              </Link>
            </p>
            <h2 className="font-semibold mt-5">
              Assumptions held at the origin
            </h2>
            <dl className="grid gap-3 sm:grid-cols-3 mt-3">
              {bridge.assumptions.map((a) => (
                <div key={a.name}>
                  <dt className="caption">{a.name.replaceAll("_", " ")}</dt>
                  <dd>
                    {a.unit === "ratio"
                      ? fmtRatioPct(a.value)
                      : fmtNumber(a.value)}{" "}
                    <span className="caption">
                      {a.unit === "ratio" ? "" : a.unit}
                    </span>
                  </dd>
                  <dd className="caption">{a.source.replaceAll("_", " ")}</dd>
                </div>
              ))}
            </dl>
          </SurfaceCard>
          {bridge.status === "unsupported" ? (
            <div className="theme-notice mb-5">
              <h2 className="font-semibold">Valuation unsupported</h2>
              <p>{bridge.reason}</p>
            </div>
          ) : (
            <>
              <SurfaceCard className="p-5 mb-5">
                <h2 className="font-semibold">Forward EPS (USD per share)</h2>
                <p className="mt-2">
                  Mean ${fmtNumber(bridge.forward_eps?.mean)} · p10 $
                  {fmtNumber(bridge.forward_eps?.p10)} · p50 $
                  {fmtNumber(bridge.forward_eps?.p50)} · p90 $
                  {fmtNumber(bridge.forward_eps?.p90)}
                </p>
              </SurfaceCard>
              <div className="grid gap-4 lg:grid-cols-2 mb-5">
                {ranges.map((r) => (
                  <RangeBar key={r.label} {...r} domain={domain} />
                ))}
              </div>
              {bridge.outer_envelope && (
                <p className="theme-notice mb-5">
                  Outer envelope: $
                  {fmtNumber(bridge.outer_envelope.low_per_share)}–$
                  {fmtNumber(bridge.outer_envelope.high_per_share)} per share ·{" "}
                  {bridge.outer_envelope.label}
                </p>
              )}
              <SurfaceCard className="overflow-x-auto mb-5">
                <table className="report-table">
                  <caption>Forward EPS × multiple grid</caption>
                  <thead>
                    <tr>
                      <th>EPS quantile</th>
                      <th>Multiple</th>
                      <th>P/E</th>
                      <th>USD / share</th>
                      <th>Equity (USD m)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bridge.grid?.map((c) => (
                      <tr key={`${c.eps_quantile}-${c.multiple_role}`}>
                        <td>{c.eps_quantile}</td>
                        <td>{c.multiple_role}</td>
                        <td>{fmtNumber(c.multiple)}</td>
                        <td>${fmtNumber(c.value_per_share)}</td>
                        <td>{fmtNumber(c.equity_usd_millions, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </SurfaceCard>
            </>
          )}
          <SurfaceCard className="p-5 mb-5">
            <h2 className="font-semibold">Multiple provenance</h2>
            <p className="body-copy mt-2">
              {bridge.multiple_band?.source_label ?? current?.multiples?.reason}
            </p>
            <p className="caption mt-2">{current?.multiples?.method_label}</p>
            {bridge.multiple_band && (
              <p className="mt-2">
                {bridge.multiple_band.window_start}–
                {bridge.multiple_band.window_end} ·{" "}
                {bridge.multiple_band.n_quarters} quarters ·{" "}
                {fmtNumber(bridge.multiple_band.low)} /{" "}
                {fmtNumber(bridge.multiple_band.mid)} /{" "}
                {fmtNumber(bridge.multiple_band.high)}×
              </p>
            )}
            <details className="mt-3">
              <summary>Eligible historical multiples at this cutoff</summary>
              <div className="overflow-x-auto mt-3">
                <table className="report-table">
                  <thead>
                    <tr>
                      <th>Period</th>
                      <th>Buyback average</th>
                      <th>Trailing EPS</th>
                      <th>P/E</th>
                      <th>Accepted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {current?.multiples?.rows.map((r) => (
                      <tr key={r.period_label}>
                        <td>
                          <a
                            className="text-link"
                            href={r.price_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {r.period_label}
                          </a>
                        </td>
                        <td>${fmtNumber(r.avg_purchase_price)}</td>
                        <td>${fmtNumber(r.ttm_eps)}</td>
                        <td>{fmtNumber(r.trailing_pe)}</td>
                        <td className="text-xs">
                          {fmtUtc(r.price_acceptance_utc)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </SurfaceCard>
          <SurfaceCard className="p-5 mb-5">
            <h2 className="font-semibold">Illustrative action rule</h2>
            <p className="body-copy mt-2">{actions.rule.label}</p>
            <p className="mt-2">
              Version {actions.rule.version} ·{" "}
              {actions.rule.holding_period_trading_days} trading days ·{" "}
              {fmtNumber(actions.position.shares, 0)}{" "}
              {actions.position.direction} shares ({actions.position.source})
            </p>
            <p className="mono-text text-xs break-all mt-2">
              Rule hash: {actions.rule.rule_hash}
            </p>
            <p className="mt-3">
              Reference: ${fmtNumber(actions.reference_price?.price)} ·{" "}
              {actions.reference_price?.period_label ?? "unavailable"}
            </p>
            <p className="body-copy mt-2">
              {actions.reference_price?.source_label}
            </p>
            <p className="caption">
              Accepted {fmtUtc(actions.reference_price?.acceptance_utc)} ·{" "}
              {actions.reference_price?.price_source_id ?? "—"}
            </p>
            <details className="mt-3">
              <summary>Frozen costs, thresholds and sizing</summary>
              <pre className="report-pre">
                {JSON.stringify(
                  {
                    costs: actions.rule.costs,
                    thresholds: actions.rule.thresholds,
                    sizing: actions.rule.sizing,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
            {actions.status === "unsupported" ? (
              <p className="theme-notice mt-4">
                Actions unsupported: {actions.reason}
              </p>
            ) : (
              <p className="mt-4 font-semibold">
                Illustrative decision: {actions.decision} · Margin{" "}
                {fmtRatioPct(actions.margin)}
              </p>
            )}
          </SurfaceCard>
          <SurfaceCard className="overflow-x-auto">
            <table className="report-table">
              <caption>Illustrative actions · costs in USD</caption>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Target shares</th>
                  <th>Traded notional</th>
                  <th>Transaction</th>
                  <th>Slippage</th>
                  <th>Impact</th>
                  <th>Funding</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {actions.actions.map((a) => (
                  <tr key={a.action}>
                    <td>
                      {a.action}
                      {a.is_no_action ? " (no action)" : ""}
                      {a.selected ? " · selected" : ""}
                    </td>
                    <td>{fmtNumber(a.target_shares, 0)}</td>
                    {[
                      a.costs?.traded_notional,
                      a.costs?.transaction_cost,
                      a.costs?.slippage_cost,
                      a.costs?.market_impact_cost,
                      a.costs?.funding_cost,
                      a.costs?.total_cost,
                    ].map((n, i) => (
                      <td key={i}>{n == null ? "—" : `$${fmtNumber(n)}`}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </SurfaceCard>
          {actions.status === "ok" && (
            <SurfaceCard className="p-5 mt-5">
              <h2 className="font-semibold">Illustrative net value gaps</h2>
              <p className="caption mt-2">
                {actions.actions.find((a) => a.gaps?.length)?.gaps?.[0]?.label}
              </p>
              <div className="overflow-x-auto mt-3">
                <table className="report-table">
                  <thead>
                    <tr>
                      <th>Action</th>
                      <th>Value point</th>
                      <th>USD / share</th>
                      <th>Net gap (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {actions.actions.flatMap((a) =>
                      (a.gaps ?? []).map((g) => (
                        <tr key={`${a.action}-${g.name}`}>
                          <td>{a.action}</td>
                          <td>{g.name.replaceAll("_", " ")}</td>
                          <td>${fmtNumber(g.value_per_share)}</td>
                          <td>${fmtNumber(g.net_gap)}</td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
            </SurfaceCard>
          )}
        </>
      )}
    </TourTarget>
  )
}
