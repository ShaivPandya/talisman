import { useState } from "react"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import type { ExtractionErrorRate, ExtractionReport } from "@/lib/reportApi"
import { extractionRate } from "@/lib/reportDisplay"

function ErrorTable({ rows }: { rows: Record<string, ExtractionErrorRate> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead><tr className="border-b border-white/10">
          <th className="p-2">Error type</th><th className="p-2">Errors</th>
          <th className="p-2">Denominator</th><th className="p-2">Rate</th>
        </tr></thead>
        <tbody>{Object.entries(rows).map(([name, row]) => (
          <tr key={name} className="border-b border-white/10">
            <td className="p-2">{name.replaceAll("_", " ")}</td>
            <td className="p-2">{row.errors}</td><td className="p-2">{row.denominator}</td>
            <td className="p-2">{extractionRate(row.rate)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

export function ExtractionPanel({ report }: { report: ExtractionReport }) {
  const [group, setGroup] = useState("overall")
  const coverage = report.coverage
  const groups: Record<string, Record<string, ExtractionErrorRate>> = {
    overall: report.errors,
    ...Object.fromEntries(Object.entries(report.by_family).map(([k, v]) => [`Family: ${k}`, v])),
    ...Object.fromEntries(Object.entries(report.by_category).map(([k, v]) => [`Category: ${k}`, v])),
  }
  const rows = groups[group] ?? report.errors
  return (
    <div className="space-y-5">
      <SurfaceCard className="p-5">
        <h2 className="font-semibold text-lg">Extraction error sample</h2>
        <p className="body-copy mt-2">{report.provider} / {report.model} · Prompt {report.prompt_version}</p>
        <p className="body-copy mt-2">
          {coverage.total_labels} labels across {coverage.total_passages} passages.
          {" "}{coverage.succeeded_passages} succeeded, {coverage.failed_passages} failed,
          {" "}{coverage.missing_passages} missing.
        </p>
        <p className="body-copy mt-2">
          {coverage.correct_labels} exact matches · {coverage.matched_labels} matched labels
          {" "}· {coverage.scored_labels} scorable labels · {coverage.unavailable_labels} unavailable
          {" "}· {coverage.disputed_labels} disputed.
        </p>
        <p className={`theme-notice mt-3 ${report.review.status === "pending" ? "theme-notice-warning" : ""}`}>
          Prepared by {report.review.author}. Human review {report.review.status === "reviewed" ? "complete" : "pending"}:
          {" "}{report.review.reviewed_labels} of {coverage.total_labels} labels.
        </p>
        <p className="caption mt-3">Semantic rates use matched labels. Omissions use labels in successful passages.
          Unavailable and disputed labels remain visible in coverage. Category groups overlap.</p>
      </SurfaceCard>
      <SurfaceCard className="p-5">
        <label className="text-sm">Error breakdown
          <select className="theme-input block mt-2 mb-4" value={group} onChange={(e) => setGroup(e.target.value)}>
            {Object.keys(groups).map((key) => <option key={key} value={key}>{key === "overall" ? "Overall" : key}</option>)}
          </select>
        </label>
        <ErrorTable rows={rows} />
      </SurfaceCard>
      {report.failures.length > 0 && <SurfaceCard className="p-5">
        <h3 className="font-semibold">Failed calls and missing outputs</h3>
        <ul className="body-copy mt-2 space-y-1">{report.failures.map((f) => <li key={f.passage_id}>
          {f.passage_id}: {f.status}{f.error ? ` — ${f.error}` : ""}
        </li>)}</ul>
      </SurfaceCard>}
      <SurfaceCard className="p-5">
        <h3 className="font-semibold">Original output disagreements ({report.disagreements.length})</h3>
        {!report.disagreements.length && <p className="body-copy mt-2">No disagreements in the available scored outputs.</p>}
        {report.disagreements.map((d, i) => <details key={`${d.passage_id}-${i}`} className="mt-3 border-b border-white/10 pb-3">
          <summary className="cursor-pointer text-sm">{d.label_id ?? d.passage_id} · {d.errors.join(", ").replaceAll("_", " ")}</summary>
          <p className="body-copy mt-3">{d.rationale}</p>
          <a className="text-sm underline" href={d.source_url} target="_blank" rel="noreferrer">Source · page {d.page}</a>
          <div className="grid gap-4 md:grid-cols-2 mt-3">
            <div><h4 className="text-sm font-semibold">Expected</h4><pre className="text-xs whitespace-pre-wrap break-words mt-2">{JSON.stringify(d.expected, null, 2)}</pre></div>
            <div><h4 className="text-sm font-semibold">Original prediction</h4><pre className="text-xs whitespace-pre-wrap break-words mt-2">{JSON.stringify(d.actual, null, 2)}</pre></div>
          </div>
        </details>)}
      </SurfaceCard>
      <SurfaceCard className="p-5">
        <h3 className="font-semibold">Provenance and limitations</h3>
        <p className="caption break-all mt-2">Corpus: {report.corpus_hash}<br />Report: {report.content_hash}</p>
        <details className="mt-3"><summary className="cursor-pointer text-sm">Saved calls ({report.calls.length})</summary>
          <ul className="caption mt-2 space-y-2">{report.calls.map((c) => <li key={c.passage_id}>
            {c.passage_id}: {c.status}; {c.attempts} attempt(s), cache hit {c.cache_hit ? "yes" : "no"}.
            <span className="block break-all">Prompt {c.prompt_hash}</span>
          </li>)}</ul>
        </details>
        <ul className="body-copy mt-3 space-y-2">{report.limitations.map((s) => <li key={s}>{s}</li>)}</ul>
      </SurfaceCard>
    </div>
  )
}
