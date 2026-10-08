import { useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { SavedRunPicker } from "@/components/shared/SavedRunPicker"
import { useSelectedRun } from "@/lib/useSelectedRun"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { TourTarget } from "@/components/tour/TourTarget"
import { fmtUtc } from "@/lib/format"
import { REPLAY_LABELS } from "@/lib/reportDisplay"
import { replayRun, type ReplayReport } from "@/lib/reportApi"

export function ReplayPage() {
  const [params, setParams] = useSearchParams()
  const runId = params.get("run_id") ?? ""
  const [revision, setRevision] = useState(0)
  const { run, error: runError } = useSelectedRun(runId, revision)
  const [result, setResult] = useState<{
    id: string
    report: ReplayReport | null
    error: string | null
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)
  const selectedId = useRef(runId)
  selectedId.current = runId
  async function replay() {
    if (!run || run.status !== "succeeded" || inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setResult(null)
    const id = run.id
    try {
      const report = await replayRun(id)
      if (selectedId.current === id) setResult({ id, report, error: null })
    } catch (e) {
      if (selectedId.current === id)
        setResult({
          id,
          report: null,
          error: e instanceof Error ? e.message : "Replay failed",
        })
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const report = result?.id === runId ? result.report : null
  const error = runError ?? (result?.id === runId ? result.error : null)
  return (
    <TourTarget id="replay-run" status={error ? "error" : run?.status === "succeeded" ? "ready" : run ? "empty" : "loading"} message={error} onRetry={() => { setResult(null); setRevision((n) => n + 1) }}>
      <header className="theme-page-header">
        <div>
          <h1 className="theme-page-title">Replay</h1>
          <p className="theme-page-subtitle">
            Recompute a saved run from pinned inputs and compare its output
            hash. Replay uses no LLM.
          </p>
        </div>
      </header>
      <SavedRunPicker
        runId={runId}
        run={run}
        onSelect={(id) => {
          setResult(null)
          setParams({ run_id: id })
        }}
      />
      {error && (
        <div className="theme-notice theme-notice-error mb-5">
          {error}{" "}
          <button
            className="theme-button-base theme-button-secondary"
            onClick={() => {
              setResult(null)
              setRevision((n) => n + 1)
            }}
          >
            Reload saved run
          </button>
        </div>
      )}
      {runId && !run && !error && <p role="status">Loading saved run…</p>}
      {run && (
        <SurfaceCard className="p-5 mb-5">
          <h2 className="font-semibold">{run.origin_label}</h2>
          <p className="caption mt-2">
            Cutoff {fmtUtc(run.cutoff_ts)} · Seed {run.seed} ·{" "}
            {run.n_paths.toLocaleString()} paths · {run.n_quarters} quarters
          </p>
          <p className="mt-2">
            <Link className="text-link" to={`/runs/${runId}`}>
              Run details
            </Link>
          </p>
          <p className="mono-text break-all text-xs mt-3">
            Recorded output hash: {run.outputs_hash ?? "unavailable"}
          </p>
          <button
            className="theme-button-base theme-button-primary mt-4"
            disabled={busy || run.status !== "succeeded"}
            onClick={() => void replay()}
          >
            {busy ? "Replaying…" : "Replay saved run"}
          </button>
          {run.status !== "succeeded" && (
            <p className="theme-notice mt-3">
              Run is {run.status}. Replay requires a successful run.
            </p>
          )}
          {busy && (
            <p role="status" className="caption mt-3">
              Computing from saved inputs…
            </p>
          )}
        </SurfaceCard>
      )}
      {report && (
        <SurfaceCard className="p-5">
          <h2
            className={`font-semibold ${["mismatch", "inputs_changed"].includes(report.status) ? "text-negative" : "text-positive"}`}
          >
            {REPLAY_LABELS[report.status]}
          </h2>
          <dl className="mt-4 space-y-3">
            <div>
              <dt className="caption">Recorded output hash</dt>
              <dd className="mono-text text-xs break-all">
                {report.recorded_outputs_hash}
              </dd>
            </div>
            <div>
              <dt className="caption">Recomputed output hash</dt>
              <dd className="mono-text text-xs break-all">
                {report.recomputed_outputs_hash ??
                  "Not recomputed; pinned inputs did not verify."}
              </dd>
            </div>
            <div>
              <dt className="caption">Maximum relative difference</dt>
              <dd>
                {report.max_relative_difference == null
                  ? "—"
                  : report.max_relative_difference.toExponential(6)}
              </dd>
            </div>
          </dl>
          {report.status === "numerically_equivalent" && (
            <p className="body-copy mt-4">
              Hashes differ, but numerical differences are within the backend
              tolerance of 1e-9. Inspect the recorded environments below.
            </p>
          )}
          <h3 className="font-semibold mt-5">Differences</h3>
          {report.differences.length ? (
            <ul className="list-disc pl-5 mt-2">
              {report.differences.map((d) => (
                <li className="break-all" key={d}>
                  {d}
                </li>
              ))}
            </ul>
          ) : (
            <p className="body-copy mt-2">No differences reported.</p>
          )}
          <div className="grid gap-4 lg:grid-cols-2 mt-5">
            {[
              [
                "Recorded environment",
                report.recorded_code_version,
                report.recorded_lib_versions,
              ],
              [
                "Recomputed environment",
                report.recomputed_code_version,
                report.recomputed_lib_versions,
              ],
            ].map(([label, version, libs]) => (
              <div className="min-w-0" key={String(label)}>
                <h3 className="font-semibold">{String(label)}</h3>
                <p className="mono-text text-xs break-all mt-2">
                  Code: {String(version ?? "unavailable")}
                </p>
                <pre className="report-pre">
                  {libs == null
                    ? "Environment unavailable"
                    : JSON.stringify(libs, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </SurfaceCard>
      )}
    </TourTarget>
  )
}
