import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"

import {
  ApiError,
  isActiveRunStatus,
  listRuns,
  listScenarios,
  type RunRead,
  type ScenarioRead,
} from "@/lib/api"
import { fmtUtc, shortHash } from "@/lib/format"
import { SurfaceCard } from "@/components/shared/SurfaceCard"

function statusClass(status: string): string {
  if (status === "succeeded") return "theme-badge theme-badge-success"
  if (status === "failed") return "theme-badge theme-badge-error"
  if (status === "running") return "theme-badge theme-badge-info"
  return "theme-badge theme-badge-neutral"
}

export function RunsPage() {
  const [runs, setRuns] = useState<RunRead[]>([])
  const [scenarios, setScenarios] = useState<ScenarioRead[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [runRows, scenarioRows] = await Promise.all([
          listRuns(),
          listScenarios(),
        ])
        if (cancelled) return
        setRuns(runRows)
        setScenarios(scenarioRows)
        setError(null)
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof ApiError
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Failed to load runs",
        )
      } finally {
        if (!cancelled) setLoading(false)
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
  }, [])

  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const scenario of scenarios) map.set(scenario.id, scenario.name)
    return map
  }, [scenarios])

  const polling = runs.some((run) => isActiveRunStatus(run.status))

  return (
    <div>
      <header className="theme-page-header">
        <div>
          <p className="theme-eyebrow">Saved runs</p>
          <h1 className="theme-page-title">Runs</h1>
          <p className="theme-page-subtitle">
            Saved Monte Carlo runs. Open a run for its quantiles or a paired
            comparison for its differences and attribution.
          </p>
        </div>
      </header>

      {error ? (
        <div className="theme-notice theme-notice-error mb-4">{error}</div>
      ) : null}

      {!loading && runs.length === 0 && !error ? (
        <SurfaceCard className="p-5">
          <p className="body-copy mb-3">
            No saved runs yet. Build your first paired scenario from bundled
            inputs.
          </p>
          <Link
            to="/scenarios"
            className="theme-button-base theme-button-primary"
          >
            Build a scenario →
          </Link>
        </SurfaceCard>
      ) : (
        <SurfaceCard className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="caption border-b border-app">
              <tr>
                <th className="px-4 py-3 font-semibold">Origin</th>
                <th className="px-4 py-3 font-semibold">Cutoff</th>
                <th className="px-4 py-3 font-semibold">Scenario</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Seed</th>
                <th className="px-4 py-3 font-semibold">Paths</th>
                <th className="px-4 py-3 font-semibold">Created</th>
                <th className="px-4 py-3 font-semibold">Outputs</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-app last:border-0">
                  <td className="px-4 py-3">
                    <Link
                      to={`/runs/${run.id}`}
                      className="text-link font-medium"
                    >
                      {run.origin_label}
                    </Link>
                    {run.baseline_run_id && (
                      <Link
                        className="text-link block text-xs mt-1"
                        to={`/scenarios?origin=${run.cutoff_ts.slice(0, 10)}&run_id=${run.id}&baseline_run_id=${run.baseline_run_id}`}
                      >
                        Compare pair →
                      </Link>
                    )}
                  </td>
                  <td className="px-4 py-3 mono-text text-xs">
                    {fmtUtc(run.cutoff_ts)}
                  </td>
                  <td className="px-4 py-3">
                    {names.get(run.scenario_id) ??
                      shortHash(run.scenario_id, 8)}
                  </td>
                  <td className="px-4 py-3">
                    <span className={statusClass(run.status)}>
                      {run.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 mono-text">{run.seed}</td>
                  <td className="px-4 py-3">{run.n_paths.toLocaleString()}</td>
                  <td className="px-4 py-3 caption">
                    {fmtUtc(run.created_at)}
                  </td>
                  <td className="px-4 py-3 mono-text text-xs">
                    {shortHash(run.outputs_hash)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {polling ? (
            <p className="caption px-4 py-2">
              Refreshing while a run is queued or running…
            </p>
          ) : null}
        </SurfaceCard>
      )}
    </div>
  )
}
