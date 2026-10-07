import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { listRuns, type RunRead } from "@/lib/api"
import { fmtUtc, shortHash } from "@/lib/format"

export function SavedRunPicker({
  runId,
  run,
  onSelect,
}: {
  runId: string
  run: RunRead | null
  onSelect: (id: string) => void
}) {
  const [runs, setRuns] = useState<RunRead[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let cancelled = false
    listRuns(200)
      .then((rows) => {
        if (!cancelled) {
          setRuns(rows.filter((r) => r.status === "succeeded"))
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Unable to list saved runs")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [revision])
  const options =
    run && !runs.some((r) => r.id === run.id) ? [run, ...runs] : runs
  return (
    <div className="mb-5 theme-surface p-4">
      <label className="block text-sm font-semibold mb-2" htmlFor="saved-run">
        Saved run
      </label>
      <select
        id="saved-run"
        className="theme-input w-full"
        value={runId}
        onChange={(e) => onSelect(e.target.value)}
      >
        <option value="">
          {loading ? "Loading runs…" : "Choose a successful run"}
        </option>
        {runId && !options.some((r) => r.id === runId) && (
          <option value={runId}>{runId}</option>
        )}
        {options.map((r) => (
          <option key={r.id} value={r.id}>
            {r.origin_label} · {fmtUtc(r.created_at)} · {shortHash(r.id)} ·{" "}
            {r.n_paths.toLocaleString()} paths
          </option>
        ))}
      </select>
      {error && <p className="theme-notice theme-notice-error mt-3">{error}</p>}
      {!loading && !runs.length && !error && (
        <p className="body-copy mt-3">
          No recent successful runs.{" "}
          <Link className="text-link" to="/scenarios">
            Build a scenario
          </Link>{" "}
          or open a saved run link.
        </p>
      )}
      <button
        type="button"
        className="theme-button-base theme-button-secondary mt-3"
        onClick={() => setRevision((n) => n + 1)}
      >
        Refresh run list
      </button>
    </div>
  )
}
