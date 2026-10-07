import { useState } from "react"
import { Link } from "react-router-dom"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import type { ProspectiveReport } from "@/lib/reportApi"
import { TARGET_LABELS } from "@/lib/reportDisplay"
import { prospectiveValue } from "@/lib/prospectiveDisplay"

export function ProspectivePanel({ report }: { report: ProspectiveReport }) {
  const [period, setPeriod] = useState(report.target as string)
  const periods = [...new Set(report.forecasts.map((row) => row.period_label))]
  return (
    <div className="space-y-5">
      <SurfaceCard className="p-5">
        <h2 className="font-semibold text-lg">Registered forecast · {report.target}</h2>
        <p className="theme-notice mt-3">{report.scoring_status}</p>
        <p className="body-copy mt-3">Evidence cutoff: {report.cutoff_ts}<br />Registered: {report.registered_at}</p>
        <p className="body-copy mt-2">{report.n_paths.toLocaleString("en-US")} paths across {report.n_quarters} quarters.
          The registration was created after the quarter ended, before its results were published.</p>
        <p className="caption mt-2">This forecast is excluded from retrospective scores and sample counts.</p>
      </SurfaceCard>
      <SurfaceCard className="p-5">
        <label className="text-sm">Forecast quarter
          <select className="theme-input block mt-2 mb-4" value={period} onChange={(e) => setPeriod(e.target.value)}>
            {periods.map((p) => <option key={p} value={p}>{p}{p === report.target ? " · registered target" : " · supporting horizon"}</option>)}
          </select>
        </label>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead><tr className="border-b border-white/10">
              <th className="p-2">Metric</th><th className="p-2">Median</th><th className="p-2">80% interval</th><th className="p-2">Units / basis</th>
            </tr></thead>
            <tbody>{report.forecasts.filter((r) => r.period_label === period).map((r) => <tr key={r.metric} className="border-b border-white/10">
              <td className="p-2">{TARGET_LABELS[r.metric] ?? r.metric.replaceAll("_", " ")}</td>
              <td className="p-2">{prospectiveValue(r, "0.5")}</td>
              <td className="p-2">{prospectiveValue(r, "0.1")} – {prospectiveValue(r, "0.9")}</td>
              <td className="p-2">{r.unit === "ratio" ? "Annualized quarter-over-quarter %" : "USD millions"} · {r.basis.replaceAll("_", " ")}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <p className="caption mt-3">Driver growth is annualized quarter-over-quarter, using (1 + quarterly growth)⁴ − 1.
          Later scoring must apply the frozen history transformations to compare with published year-over-year growth.</p>
      </SurfaceCard>
      <SurfaceCard className="p-5">
        <h3 className="font-semibold">Replay and provenance</h3>
        <p className="body-copy mt-2">Registration replay: exact match · LLM disabled · Seed {report.seed}.</p>
        <p className="caption break-all mt-3">Run: {report.run_id}<br />Outputs: {report.outputs_hash}<br />Registration: {report.content_hash}</p>
        <details className="mt-3"><summary className="cursor-pointer text-sm">Frozen inputs and runtime</summary>
          <p className="caption break-all mt-2">Parameters: {report.parameter_set_hash}<br />Sources: {report.source_manifest_hash}<br />Code: {report.code_version}</p>
          <pre className="text-xs whitespace-pre-wrap break-words mt-2">{JSON.stringify(report.lib_versions, null, 2)}</pre>
        </details>
        <p className="caption mt-3">Publication listing checked: {report.publication_checked_at} · <a className="underline" href={report.publication_check_url} target="_blank" rel="noreferrer">Visa quarterly results</a></p>
        <Link className="theme-button-base theme-button-secondary inline-block mt-3" to="/evaluation?section=documents&document=evaluation-report">Read registration and later-scoring procedure</Link>
      </SurfaceCard>
    </div>
  )
}
