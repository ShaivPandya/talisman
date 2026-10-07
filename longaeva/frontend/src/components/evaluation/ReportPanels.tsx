import { Link } from "react-router-dom"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { fmtRatioPct } from "@/lib/format"
import {
  coverageLabel,
  fmtScore,
  horizonTarget,
  scoreAggregate,
} from "@/lib/reportDisplay"
import type {
  AblationReport,
  ForecastReport,
  PortfolioReport,
  SavedReport,
} from "@/lib/reportApi"

export function Provenance({ values }: { values: Record<string, unknown> }) {
  return (
    <details className="mt-4">
      <summary>Saved configuration and provenance</summary>
      <pre className="report-pre">{JSON.stringify(values, null, 2)}</pre>
    </details>
  )
}

export function ForecastPanel({
  reports,
  selected,
  target,
  horizon,
  window,
}: {
  reports: SavedReport[]
  selected: string
  target: string
  horizon: string
  window: string
}) {
  const chosen = reports.find((r) => r.key === selected)
  const report = chosen?.forecast
  if (!report)
    return (
      <p className="theme-notice">
        {chosen?.reason ?? "This saved report is unavailable."}
      </p>
    )
  const origins = report.origins.filter(
    (o) => window === "overall" || o.window === window,
  )
  const metric = horizonTarget(target, horizon)
  const scoreKey = `${horizon}.${metric}`
  return (
    <>
      <SurfaceCard className="p-5 mb-5">
        <h2 className="font-semibold">{chosen.title}</h2>
        <p className="body-copy mt-2">
          {report.n_scored} origins processed · {report.n_excluded} excluded.
          Each target has its own scored n.
        </p>
        {horizon === "4q" && (
          <p className="caption mt-2">
            Four-quarter aggregates cover all windows. Only origins with four
            released target quarters can contribute.
          </p>
        )}
        <Provenance
          values={{ config_hash: report.config_hash, ...report.config }}
        />
      </SurfaceCard>
      <SurfaceCard className="overflow-x-auto mb-5">
        <table className="report-table">
          <caption>
            Saved comparison ·{" "}
            {horizon === "q1" ? "Next quarter" : "Four quarters"} · {window}
          </caption>
          <thead>
            <tr>
              <th>Model / baseline</th>
              <th>n</th>
              <th>MAE</th>
              <th>Bias</th>
              <th>MAPE</th>
              <th>80% coverage</th>
              <th>CRPS</th>
              <th>WIS</th>
            </tr>
          </thead>
          <tbody>
            {reports
              .filter((r) => r.forecast)
              .map((r) => {
                const a = scoreAggregate(r.forecast!, horizon, window, target)
                return (
                  <tr key={r.key}>
                    <td>
                      {r.title}
                      {r.key === selected ? " · selected" : ""}
                    </td>
                    <td>{a?.n ?? "—"}</td>
                    <td>{fmtScore(a?.mae, target)}</td>
                    <td>{fmtScore(a?.bias, target)}</td>
                    <td>{fmtRatioPct(a?.mape)}</td>
                    <td>{coverageLabel(a)}</td>
                    <td>{fmtScore(a?.mean_crps, target)}</td>
                    <td>{fmtScore(a?.mean_wis, target)}</td>
                  </tr>
                )
              })}
          </tbody>
        </table>
      </SurfaceCard>
      <p className="body-copy mb-5">
        Growth errors and scores are percentage points (pp). Revenue and profit
        errors are USD millions. MAPE is a percentage. Company guidance is a
        separately labeled baseline; consensus unavailable (no licensed free
        historical source).
      </p>
      <SurfaceCard className="overflow-x-auto mb-5">
        <table className="report-table">
          <caption>
            Origin results · {origins.length} in the selected window
          </caption>
          <thead>
            <tr>
              <th>Origin</th>
              <th>Window</th>
              <th>Median forecast</th>
              <th>Absolute error</th>
              <th>Percentage error</th>
              <th>80% covered</th>
              <th>CRPS</th>
              <th>WIS</th>
              <th>Availability</th>
            </tr>
          </thead>
          <tbody>
            {origins.map((o) => (
              <tr key={o.origin_date}>
                <td>
                  {o.label}
                  <span className="caption block">{o.origin_date}</span>
                </td>
                <td>{o.window}</td>
                <td>
                  {target.includes("growth")
                    ? fmtRatioPct(o.scores[`${scoreKey}.median`])
                    : fmtScore(o.scores[`${scoreKey}.median`], target)}
                </td>
                <td>{fmtScore(o.scores[`${scoreKey}.abs_error`], target)}</td>
                <td>{fmtRatioPct(o.scores[`${scoreKey}.pct_error`])}</td>
                <td>
                  {o.scores[`${scoreKey}.covered_80`] == null
                    ? "—"
                    : o.scores[`${scoreKey}.covered_80`]
                      ? "Yes"
                      : "No"}
                </td>
                <td>{fmtScore(o.scores[`${scoreKey}.crps`], target)}</td>
                <td>{fmtScore(o.scores[`${scoreKey}.wis`], target)}</td>
                <td>
                  {o.error ??
                    (o.scores[`${scoreKey}.abs_error`] == null
                      ? (o.skipped_drivers[target] ??
                        "No saved score for this target/horizon")
                      : "Scored")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </SurfaceCard>
      <Exclusions report={report} />
      <p className="caption mt-4">
        These reports retain historical run IDs for provenance. Their run
        records may not exist in this local database.
      </p>
    </>
  )
}

function Exclusions({
  report,
}: {
  report: Pick<ForecastReport, "exclusions" | "n_excluded">
}) {
  return (
    <SurfaceCard className="p-5">
      <h2 className="font-semibold">Exclusions ({report.n_excluded})</h2>
      {report.exclusions.length ? (
        <ul className="mt-3 space-y-3">
          {report.exclusions.map((e) => (
            <li key={e.origin_date}>
              <span className="font-medium">{e.label ?? e.origin_date}</span> ·{" "}
              {e.origin_date}
              <p className="body-copy">{e.reason}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="caption mt-2">No exclusions recorded.</p>
      )}
    </SurfaceCard>
  )
}

export function AblationPanel({
  report,
  target,
  horizon,
  window,
  profile,
}: {
  report: AblationReport
  target: string
  horizon: string
  window: string
  profile: string
}) {
  const summary = report.summaries[profile] ?? {}
  const metric = horizonTarget(target, horizon)
  const suffix = `.${window}.${horizon}.${metric}.abs_error`
  const comparisons = Object.entries(summary).filter(([key]) =>
    key.endsWith(suffix),
  )
  return (
    <>
      <SurfaceCard className="p-5 mb-5">
        <h2 className="font-semibold">Ablation robustness</h2>
        <p className="body-copy mt-2">{report.profile_policy}</p>
        <p className="body-copy mt-2">{report.delta_convention}</p>
        <p className="caption mt-2">
          {Object.keys(report.summaries).length} saved profiles ·{" "}
          {profile.replaceAll("_", " ")}
        </p>
        <Provenance
          values={{
            suite_version: report.suite_version,
            content_hash: report.content_hash,
            settings: report.settings[profile],
            config_hashes: report.config_hashes[profile],
          }}
        />
      </SurfaceCard>
      <SurfaceCard className="overflow-x-auto mb-5">
        <table className="report-table">
          <caption>Paired absolute-error comparisons</caption>
          <thead>
            <tr>
              <th>Removed feature</th>
              <th>n</th>
              <th>Full wins</th>
              <th>Ablated wins</th>
              <th>Ties</th>
              <th>Mean ablated − full</th>
              <th>Full coverage</th>
              <th>Ablated coverage</th>
              <th>Profiles full / ablated / tied</th>
            </tr>
          </thead>
          <tbody>
            {comparisons.map(([key, a]) => {
              const r = report.robustness[key]
              return (
                <tr key={key}>
                  <td>{key.split(".")[0].replaceAll("_", " ")}</td>
                  <td>{a.n}</td>
                  <td>{a.full_wins}</td>
                  <td>{a.ablated_wins}</td>
                  <td>{a.ties}</td>
                  <td>{fmtScore(a.mean_ablated_minus_full, target)}</td>
                  <td>
                    {a.full_covered} of {a.n}
                  </td>
                  <td>
                    {a.ablated_covered} of {a.n}
                  </td>
                  <td>
                    {r
                      ? `${r.full_better} / ${r.ablated_better} / ${r.ties} (${r.profiles} profiles)`
                      : "—"}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </SurfaceCard>
      <details className="theme-surface p-5">
        <summary>CRPS and WIS paired differences</summary>
        <div className="overflow-x-auto mt-3">
          <table className="report-table">
            <thead>
              <tr>
                <th>Ablation</th>
                <th>Score</th>
                <th>n</th>
                <th>Mean ablated − full</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary)
                .filter(([k]) =>
                  ["crps", "wis"].some((s) =>
                    k.endsWith(`.${window}.${horizon}.${metric}.${s}`),
                  ),
                )
                .map(([k, a]) => (
                  <tr key={k}>
                    <td>{k.split(".")[0].replaceAll("_", " ")}</td>
                    <td>{k.split(".").at(-1)?.toUpperCase()}</td>
                    <td>{a.n}</td>
                    <td>{fmtScore(a.mean_ablated_minus_full, target)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  )
}

export function PortfolioPanel({ report }: { report: PortfolioReport }) {
  return (
    <>
      <SurfaceCard className="p-5 mb-5">
        <h2 className="font-semibold">Benchmark comparison</h2>
        <p className="body-copy mt-2">{report.label}</p>
        <p className="mt-2">
          {report.n_eligible} eligible origins · {report.n_excluded} exclusions
          · {report.overlap.overlapping_pairs} overlapping window pairs
          involving {report.overlap.windows_with_overlap} windows
        </p>
        <p className="body-copy mt-3">{report.labels.primary_footnote}</p>
        <Provenance
          values={{
            config_hash: report.config_hash,
            rule_frozen_at: report.rule_frozen_at,
            config: report.config,
            sources: report.sources,
            drift_diagnostic: report.drift_diagnostic,
          }}
        />
      </SurfaceCard>
      <SurfaceCard className="overflow-x-auto mb-5">
        <table className="report-table">
          <caption>Independent holding-window aggregates</caption>
          <thead>
            <tr>
              <th>Series</th>
              <th>Scored</th>
              <th>Unavailable</th>
              <th>Estimated</th>
              <th>Mean return</th>
              <th>Worst window drawdown</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(report.aggregates).map(([key, a]) => (
              <tr key={key}>
                <td>
                  {
                    report.labels[
                      key === "sp500_tr_approx" ? "primary" : "secondary"
                    ]
                  }
                </td>
                <td>{a.n_scored}</td>
                <td>{a.n_unavailable}</td>
                <td>{a.n_estimated}</td>
                <td>{fmtRatioPct(a.mean_return)}</td>
                <td>{fmtRatioPct(a.worst_window_drawdown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </SurfaceCard>
      <SurfaceCard className="p-5 mb-5">
        <h2 className="font-semibold">Visa comparisons</h2>
        <p className="mt-3">
          Visa strategy · {report.visa_strategy.status} · n=
          {report.visa_strategy.n_scored}
        </p>
        <p className="body-copy">{report.visa_strategy.reason}</p>
        <p className="mt-3">
          {report.visa_buy_and_hold.label} · {report.visa_buy_and_hold.status} ·
          n={report.visa_buy_and_hold.n_scored}
        </p>
        <p className="body-copy">{report.visa_buy_and_hold.reason}</p>
      </SurfaceCard>
      <SurfaceCard className="overflow-x-auto mb-5">
        <table className="report-table">
          <caption>Holding windows</caption>
          <thead>
            <tr>
              <th>Origin</th>
              <th>Entry / exit</th>
              <th>Benchmark</th>
              <th>Return</th>
              <th>Drawdown</th>
              <th>Exposure</th>
              <th>Availability</th>
            </tr>
          </thead>
          <tbody>
            {report.origins.flatMap((o) =>
              Object.entries(o.benchmarks).map(([key, b]) => (
                <tr key={`${o.origin_date}-${key}`}>
                  <td>
                    {o.label}
                    <span className="caption block">{o.origin_date}</span>
                  </td>
                  <td>
                    {o.entry_date ?? "—"}
                    <span className="block">{o.exit_date ?? "—"}</span>
                  </td>
                  <td>{b.label}</td>
                  <td>{fmtRatioPct(b.metrics?.total_return)}</td>
                  <td>{fmtRatioPct(b.metrics?.max_drawdown)}</td>
                  <td>{fmtRatioPct(b.metrics?.average_invested_exposure)}</td>
                  <td>
                    {b.status}
                    {b.estimated ? " · estimated" : ""}
                    {b.reason ? ` · ${b.reason}` : ""}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </SurfaceCard>
      <Exclusions report={report} />
      <p className="mt-4">
        <Link
          className="text-link"
          to="/evaluation?section=documents&document=portfolio-evaluation"
        >
          Read portfolio conventions
        </Link>
      </p>
    </>
  )
}
