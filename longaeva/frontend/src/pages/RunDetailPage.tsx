import { useEffect, useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"

import { FanChart } from "@/components/charts/FanChart"
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart"
import { ChartTile } from "@/components/shared/ChartTile"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import {
  ApiError,
  getRun,
  getRunResults,
  isActiveRunStatus,
  listScenarios,
  type RunRead,
  type RunResultSummary,
} from "@/lib/api"
import { fmtMetricValue, fmtUtc, shortHash } from "@/lib/format"
import { DEFAULT_FAN_METRIC, metricLabel } from "@/lib/metrics"
import {
  summariesForMetric,
  toDriverGrowthRows,
  toFanRows,
  uniqueMetrics,
} from "@/lib/runs"

function statusClass(status: string): string {
  if (status === "succeeded") return "theme-badge theme-badge-success"
  if (status === "failed") return "theme-badge theme-badge-error"
  if (status === "running") return "theme-badge theme-badge-info"
  return "theme-badge theme-badge-neutral"
}

export function RunDetailPage() {
  const { runId } = useParams()
  const [run, setRun] = useState<RunRead | null>(null)
  const [results, setResults] = useState<RunResultSummary[] | null>(null)
  const [scenarioName, setScenarioName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [metric, setMetric] = useState(DEFAULT_FAN_METRIC)

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    const load = async () => {
      try {
        const row = await getRun(runId)
        if (cancelled) return
        setRun(row)
        setError(null)
        if (row.status === "succeeded") {
          try {
            const summaries = await getRunResults(runId)
            if (!cancelled) setResults(summaries)
          } catch (err) {
            if (cancelled) return
            if (err instanceof ApiError && err.status === 409) {
              setResults(null)
            } else {
              setError(
                err instanceof ApiError ? err.detail : "Failed to load results",
              )
            }
          }
        } else {
          setResults(null)
        }
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof ApiError
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Failed to load run",
        )
      }
    }
    void load()
    const id = window.setInterval(() => {
      void load()
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [runId])

  useEffect(() => {
    if (!run) return
    let cancelled = false
    listScenarios()
      .then((rows) => {
        if (cancelled) return
        setScenarioName(
          rows.find((row) => row.id === run.scenario_id)?.name ?? null,
        )
      })
      .catch(() => {
        if (!cancelled) setScenarioName(null)
      })
    return () => {
      cancelled = true
    }
  }, [run])

  const metrics = useMemo(
    () => (results ? uniqueMetrics(results) : []),
    [results],
  )
  const selectedMetric = metrics.includes(metric)
    ? metric
    : metrics.includes(DEFAULT_FAN_METRIC)
      ? DEFAULT_FAN_METRIC
      : (metrics[0] ?? DEFAULT_FAN_METRIC)

  const fanRows = useMemo(
    () => (results ? toFanRows(results, selectedMetric) : []),
    [results, selectedMetric],
  )
  const driverRows = useMemo(
    () => (results ? toDriverGrowthRows(results) : []),
    [results],
  )
  const tableRows = useMemo(
    () => (results ? summariesForMetric(results, selectedMetric) : []),
    [results, selectedMetric],
  )

  if (!runId) {
    return <p className="theme-notice theme-notice-error">Missing run id.</p>
  }

  return (
    <div>
      <header className="theme-page-header">
        <div>
          <div className="flex items-center flex-wrap gap-x-4 gap-y-2">
            <h1 className="theme-page-title">{run?.origin_label ?? "Run"}</h1>
            <Link to="/runs" className="text-link text-sm">← All runs</Link>
          </div>
          <p className="theme-page-subtitle mono-text text-xs">{runId}</p>
        </div>
        {run ? (
          <div className="flex flex-wrap items-center gap-3">
            <Link
              className="text-link text-sm"
              to={`/valuation?run_id=${run.id}`}
            >
              Valuation & Actions
            </Link>
            <Link className="text-link text-sm" to={`/replay?run_id=${run.id}`}>
              Replay
            </Link>
            <span className={statusClass(run.status)}>{run.status}</span>
            {run.baseline_run_id && (
              <Link
                className="text-link text-sm"
                to={`/scenarios?origin=${run.cutoff_ts.slice(0, 10)}&run_id=${run.id}&baseline_run_id=${run.baseline_run_id}`}
              >
                Compare with baseline →
              </Link>
            )}
          </div>
        ) : null}
      </header>

      {error ? (
        <div className="theme-notice theme-notice-error mb-4">{error}</div>
      ) : null}

      {run?.status === "failed" && run.error ? (
        <div className="theme-notice theme-notice-error mb-4">
          <div>
            <p className="font-semibold">Run failed</p>
            <p className="mt-1">{run.error}</p>
          </div>
        </div>
      ) : null}

      {run && isActiveRunStatus(run.status) ? (
        <div className="theme-notice theme-notice-info mb-4">
          Waiting for the worker. This page refreshes every two seconds.
        </div>
      ) : null}

      {run ? (
        <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Meta
            label="Scenario"
            value={scenarioName ?? shortHash(run.scenario_id, 8)}
          />
          <Meta label="Cutoff" value={fmtUtc(run.cutoff_ts)} />
          <Meta
            label="Seed / paths"
            value={`${run.seed} · ${run.n_paths.toLocaleString()}`}
          />
          <Meta
            label="Parameter set"
            value={shortHash(run.parameter_set_hash)}
            mono
          />
          <Meta
            label="Starting state"
            value={shortHash(run.starting_state_hash)}
            mono
          />
          <Meta
            label="Manifest"
            value={shortHash(run.source_manifest_hash)}
            mono
          />
          <Meta label="Outputs" value={shortHash(run.outputs_hash)} mono />
          <Meta label="Code version" value={run.code_version} mono />
          <Meta
            label="Libraries"
            value={
              typeof run.lib_versions.numpy === "string"
                ? `numpy ${run.lib_versions.numpy}`
                : JSON.stringify(run.lib_versions)
            }
            mono
          />
        </div>
      ) : (
        <p className="caption mb-5">Loading run…</p>
      )}

      {results ? (
        <>
          <div className="mb-4">
            <label className="theme-field-label" htmlFor="metric">
              Metric
            </label>
            <select
              id="metric"
              className="theme-input max-w-md"
              value={selectedMetric}
              onChange={(event) => setMetric(event.target.value)}
            >
              {metrics.map((key) => (
                <option key={key} value={key}>
                  {metricLabel(key)}
                </option>
              ))}
            </select>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartTile
              title={`${metricLabel(selectedMetric)} fan`}
              subtitle="Quantile bands from the saved run summary (not live paths)"
            >
              <FanChart
                data={fanRows}
                yFormatter={(v) => fmtMetricValue(v, selectedMetric)}
                tooltipFormatter={(v) => fmtMetricValue(v, selectedMetric)}
              />
            </ChartTile>
            <ChartTile
              title="Driver growth medians"
              subtitle="Constant-dollar / count growth (median)"
            >
              <TimeSeriesChart
                data={driverRows}
                xKey="period"
                category
                height={280}
                toggleableLegend
                yFormatter={(v) => `${(v * 100).toFixed(1)}%`}
                tooltipFormatter={(v) => `${(v * 100).toFixed(1)}%`}
                series={[
                  {
                    key: "payments_volume_growth_constant",
                    name: "Payments volume",
                    color: "hsl(var(--accent))",
                  },
                  {
                    key: "cross_border_ex_intra_europe_growth_constant",
                    name: "Cross-border",
                    color: "hsl(var(--positive))",
                  },
                  {
                    key: "processed_transactions_growth",
                    name: "Transactions",
                    color: "hsl(var(--warning))",
                  },
                ]}
              />
            </ChartTile>
          </div>

          <SurfaceCard className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="caption border-b border-app">
                <tr>
                  <th className="px-4 py-3">Period</th>
                  <th className="px-4 py-3">Mean</th>
                  <th className="px-4 py-3">Std</th>
                  <th className="px-4 py-3">MC SE</th>
                  <th className="px-4 py-3">p05</th>
                  <th className="px-4 py-3">p50</th>
                  <th className="px-4 py-3">p95</th>
                </tr>
              </thead>
              <tbody>
                {tableRows.map((row) => (
                  <tr
                    key={`${row.metric}-${row.quarter_index}`}
                    className="border-b border-app last:border-0"
                  >
                    <td className="px-4 py-3">{row.period_label}</td>
                    <td className="px-4 py-3 mono-text">
                      {fmtMetricValue(row.mean, selectedMetric)}
                    </td>
                    <td className="px-4 py-3 mono-text">
                      {fmtMetricValue(row.std, selectedMetric)}
                    </td>
                    <td className="px-4 py-3 mono-text">
                      {fmtMetricValue(row.std_error, selectedMetric)}
                    </td>
                    <td className="px-4 py-3 mono-text">
                      {fmtMetricValue(row.quantiles["0.05"], selectedMetric)}
                    </td>
                    <td className="px-4 py-3 mono-text">
                      {fmtMetricValue(row.quantiles["0.5"], selectedMetric)}
                    </td>
                    <td className="px-4 py-3 mono-text">
                      {fmtMetricValue(row.quantiles["0.95"], selectedMetric)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="caption px-4 py-2">
              Quantile SE is stored on the run record; mean Monte Carlo SE is
              std / sqrt(n_paths).
              {run ? ` n=${run.n_paths.toLocaleString()}.` : ""}
            </p>
          </SurfaceCard>
        </>
      ) : null}
    </div>
  )
}

function Meta({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <SurfaceCard muted className="p-3">
      <p className="caption">{label}</p>
      <p
        className={
          mono ? "mt-1 truncate mono-text text-sm" : "mt-1 truncate text-sm"
        }
      >
        {value}
      </p>
    </SurfaceCard>
  )
}
