import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import {
  getAttribution,
  getComparison,
  getRun,
  getRunResults,
  getScenario,
  isActiveRunStatus,
  type AttributionRead,
  type ComparisonRead,
  type RunRead,
  type RunResultSummary,
} from "@/lib/api"
import { fmtMetricValue, fmtNumber, fmtUtc, shortHash } from "@/lib/format"
import { metricLabel } from "@/lib/metrics"
import { comparisonRows, errorMessage } from "@/lib/scenarios"
import { toFanRows } from "@/lib/runs"
import { FanChart } from "@/components/charts/FanChart"
import { PairedDiffChart } from "@/components/charts/PairedDiffChart"
import { ChartTile } from "@/components/shared/ChartTile"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import {
  EvidencePanel,
  type EvidenceSelection,
} from "@/components/shared/EvidencePanel"

const METRICS = [
  "net_revenue",
  "operating_profit_ex_special_items",
  "payments_volume_nominal_us",
  "cross_border_ex_intra_europe_volume",
  "processed_transactions_count",
  "service_revenue",
]
interface SavedResults {
  baseline: RunResultSummary[]
  variant: RunResultSummary[]
  comparison: ComparisonRead
  parameterSetId: string
  variantName: string
}

export function SavedComparison({
  runId,
  baselineId,
}: {
  runId: string
  baselineId: string
}) {
  const section = useRef<HTMLElement>(null)
  const [pair, setPair] = useState<RunRead[] | null>(null)
  const [results, setResults] = useState<SavedResults | null>(null)
  const [attribution, setAttribution] = useState<AttributionRead | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attributionError, setAttributionError] = useState<string | null>(null)
  const [metric, setMetric] = useState("net_revenue")
  const [attempt, setAttempt] = useState(0)
  const [attributionAttempt, setAttributionAttempt] = useState(0)
  const [evidence, setEvidence] = useState<EvidenceSelection | null>(null)
  const succeeded = pair?.every((run) => run.status === "succeeded") ?? false
  useEffect(() => {
    section.current?.scrollIntoView({ behavior: "smooth", block: "start" })
  }, [])
  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const rows = await Promise.all([getRun(baselineId), getRun(runId)])
        if (cancelled) return
        setPair(rows)
        setError(null)
        if (rows.some((run) => isActiveRunStatus(run.status)))
          timer = window.setTimeout(() => void poll(), 2000)
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      }
    }
    void poll()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [baselineId, runId, attempt])
  const variantScenarioId = pair?.[1].scenario_id
  useEffect(() => {
    if (!succeeded || !variantScenarioId) return
    let cancelled = false
    Promise.all([
      getRunResults(baselineId),
      getRunResults(runId),
      getComparison(runId, baselineId),
      getScenario(variantScenarioId),
    ])
      .then(([baseline, variant, comparison, scenario]) => {
        if (!cancelled) {
          setResults({
            baseline,
            variant,
            comparison,
            parameterSetId: scenario.parameter_set_id,
            variantName: scenario.name,
          })
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [succeeded, baselineId, runId, variantScenarioId, attempt])
  useEffect(() => {
    if (!succeeded) return
    let cancelled = false
    getAttribution(runId, baselineId)
      .then((value) => {
        if (!cancelled) {
          setAttribution(value)
          setAttributionError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setAttributionError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [succeeded, baselineId, runId, attributionAttempt])
  const showEvidence = (parameter: string) => {
    if (results)
      setEvidence({
        title: parameter.replaceAll("_", " "),
        parameter,
        parameterSetId: results.parameterSetId,
      })
  }
  return (
    <section
      ref={section}
      className="scroll-mt-5"
      aria-label="Saved comparison"
    >
      <header className="theme-page-header">
        <div>
          <p className="theme-eyebrow">Saved comparison</p>
          <h2 className="text-xl font-semibold">
            {results?.variantName ?? "Paired scenario runs"}
          </h2>
          <p className="caption mt-1">
            Variant minus calibrated baseline · {pair?.[0].origin_label} ·{" "}
            {fmtUtc(pair?.[0].cutoff_ts)}
          </p>
        </div>
      </header>
      {error && (
        <div role="alert" className="theme-notice theme-notice-error mb-4">
          <p>{error}</p>
          <button
            className="text-link"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Retry saved results
          </button>
        </div>
      )}
      {!pair && !error && (
        <p role="status" className="mb-4">
          Loading run records…
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2 mb-5">
        {pair?.map((run, index) => (
          <SurfaceCard className="p-4" key={run.id}>
            <div className="flex justify-between gap-3">
              <h3 className="font-semibold">
                {index === 0 ? "Baseline" : "Variant"}
              </h3>
              <span
                role="status"
                className={`theme-badge ${run.status === "succeeded" ? "theme-badge-success" : run.status === "failed" ? "theme-badge-error" : "theme-badge-info"}`}
              >
                {run.status}
              </span>
            </div>
            <Link
              to={`/runs/${run.id}`}
              className="text-link mono-text text-xs break-all inline-block mt-2"
            >
              {run.id}
            </Link>
            <p className="caption mt-2">
              Seed {run.seed} · {run.n_paths.toLocaleString()} paths ·{" "}
              {run.n_quarters} quarters
            </p>
            <p className="caption">Outputs: {shortHash(run.outputs_hash)}</p>
            {run.error && (
              <p role="alert" className="text-negative mt-2 text-sm">
                {run.error}
              </p>
            )}
          </SurfaceCard>
        ))}
      </div>
      {pair?.some((run) => isActiveRunStatus(run.status)) && (
        <p role="status" className="theme-notice theme-notice-info mb-5">
          The worker is processing this pair. Status refreshes every two
          seconds.
        </p>
      )}
      {succeeded && !results && !error && (
        <p role="status">Loading saved distributions…</p>
      )}
      {results && (
        <>
          <label className="theme-field-label" htmlFor="comparison-metric">
            Compare metric
          </label>
          <select
            id="comparison-metric"
            className="theme-input max-w-md mb-4"
            value={metric}
            onChange={(event) => setMetric(event.target.value)}
          >
            {METRICS.map((key) => (
              <option key={key} value={key}>
                {metricLabel(key)}
              </option>
            ))}
          </select>
          <div className="grid gap-4 xl:grid-cols-2 mb-4">
            <ChartTile
              title="Calibrated baseline"
              subtitle={metricLabel(metric)}
            >
              <FanChart
                data={toFanRows(results.baseline, metric)}
                yFormatter={(v) => fmtMetricValue(v, metric)}
                tooltipFormatter={(v) => fmtMetricValue(v, metric)}
              />
            </ChartTile>
            <ChartTile
              title={results.variantName}
              subtitle={metricLabel(metric)}
            >
              <FanChart
                data={toFanRows(results.variant, metric)}
                yFormatter={(v) => fmtMetricValue(v, metric)}
                tooltipFormatter={(v) => fmtMetricValue(v, metric)}
              />
            </ChartTile>
          </div>
          <ChartTile
            title="Path-wise difference"
            subtitle={`${metricLabel(metric)} · variant minus baseline, using saved paths`}
          >
            <PairedDiffChart
              data={comparisonRows(results.comparison.items, metric)}
              yFormatter={(v) => fmtMetricValue(v, metric)}
              tooltipFormatter={(v) => fmtMetricValue(v, metric)}
            />
          </ChartTile>
          <details className="theme-surface p-4 mt-4 mb-6">
            <summary className="cursor-pointer font-semibold">
              Saved quarterly means & differences
            </summary>
            <div className="overflow-x-auto">
              <table className="workspace-table">
                <thead>
                  <tr>
                    <th>Quarter</th>
                    <th>Baseline</th>
                    <th>Variant</th>
                    <th>Difference</th>
                    <th>MC standard error</th>
                  </tr>
                </thead>
                <tbody>
                  {results.comparison.items
                    .filter((row) => row.metric === metric)
                    .map((row) => (
                      <tr key={row.quarter_index}>
                        <td>{row.period_label}</td>
                        <td>{fmtMetricValue(row.baseline_mean, metric)}</td>
                        <td>{fmtMetricValue(row.variant_mean, metric)}</td>
                        <td>{fmtMetricValue(row.difference_mean, metric)}</td>
                        <td>
                          {fmtMetricValue(row.difference_std_error, metric)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
      {succeeded && (
        <SurfaceCard className="p-5 mt-5">
          <h2 className="text-lg font-semibold">
            Attribution · conditional on the model
          </h2>
          {attributionError && (
            <div role="alert" className="theme-notice theme-notice-error mt-3">
              <p>{attributionError}</p>
              <button
                className="text-link"
                onClick={() => {
                  setAttributionError(null)
                  setAttributionAttempt((value) => value + 1)
                }}
              >
                Retry attribution
              </button>
            </div>
          )}
          {!attribution && !attributionError && (
            <p role="status" className="caption mt-3">
              Verifying saved outputs and calculating attribution…
            </p>
          )}
          {attribution && (
            <>
              <p className="body-copy mt-3">{attribution.order_note}</p>
              <p className="caption mt-2">
                Verification:{" "}
                {attribution.verification.join(" · ").replaceAll("_", " ")}
              </p>
              <p className="caption mt-1 break-words">
                Sequential order:{" "}
                {attribution.sequential_order.join(" → ") || "No changes"}
              </p>
              {attribution.metrics.map((item) => (
                <div key={item.metric} className="mt-6">
                  <h3 className="font-semibold">
                    {metricLabel(item.metric)} · horizon total
                  </h3>
                  <p className="caption mt-1">
                    Difference {fmtMetricValue(item.horizon_total, item.metric)}{" "}
                    · joint residual{" "}
                    {fmtMetricValue(item.joint_residual_horizon, item.metric)}
                  </p>
                  <div className="overflow-x-auto">
                    <table className="workspace-table">
                      <thead>
                        <tr>
                          <th>Change</th>
                          <th>Before → after / size</th>
                          <th>One at a time</th>
                          <th>Sequential</th>
                          <th>Rules & sources</th>
                        </tr>
                      </thead>
                      <tbody>
                        {attribution.contributions.map((contribution) => (
                          <tr key={contribution.key}>
                            <td>
                              {contribution.label}
                              <p className="caption">{contribution.kind}</p>
                            </td>
                            <td>
                              {contribution.kind === "parameter" ? (
                                <>
                                  <p>
                                    {fmtNumber(contribution.before, 4)} →{" "}
                                    {fmtNumber(contribution.after, 4)}
                                  </p>
                                  <p className="caption">
                                    Δ {fmtNumber(contribution.size, 4)} · model
                                    units
                                  </p>
                                </>
                              ) : (
                                <p className="text-xs">
                                  {contribution.intervention?.type ===
                                  "mix_shift_conserving_total"
                                    ? `${fmtNumber(contribution.intervention.cross_border_change * 100)}% cross-border mix`
                                    : contribution.intervention?.type ===
                                        "total_spend_reduction"
                                      ? `${fmtNumber(contribution.intervention.reduction * 100)}% spending reduction`
                                      : "Intervention"}{" "}
                                  · quarter{" "}
                                  {contribution.intervention?.start_quarter}
                                </p>
                              )}
                            </td>
                            <td>
                              {fmtMetricValue(
                                contribution.by_metric[item.metric]
                                  ?.one_at_a_time_horizon,
                                item.metric,
                              )}
                            </td>
                            <td>
                              {fmtMetricValue(
                                contribution.by_metric[item.metric]
                                  ?.sequential_horizon,
                                item.metric,
                              )}
                            </td>
                            <td>
                              <p className="caption break-all">
                                Rules:{" "}
                                {contribution.rule_ids.join(", ") ||
                                  "No mapping rule · analyst assumption"}
                              </p>
                              <p className="caption break-all mt-1">
                                Sources:{" "}
                                {contribution.source_ids.join(", ") || "None"}
                              </p>
                              {contribution.kind === "parameter" && (
                                <button
                                  className="text-link text-xs mt-2"
                                  onClick={() =>
                                    showEvidence(contribution.name)
                                  }
                                >
                                  View passages & rationale
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
              <h3 className="font-semibold mt-6">Sensitivity & support</h3>
              <p className="caption mt-1">
                Ranked by horizon net-revenue swing across each parameter range.
                Flags use the model’s sensitivity × weak-support heuristic.
              </p>
              <div className="overflow-x-auto">
                <table className="workspace-table">
                  <thead>
                    <tr>
                      <th>Parameter</th>
                      <th>Relative sensitivity</th>
                      <th>Support</th>
                      <th>Flag</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attribution.sensitivity.map((item) => (
                      <tr key={item.parameter}>
                        <td>{item.parameter.replaceAll("_", " ")}</td>
                        <td>
                          {fmtNumber(item.normalized_sensitivity * 100, 1)}%
                        </td>
                        <td>{fmtNumber(item.support_score, 2)}</td>
                        <td>
                          {item.flag ? (
                            <span className="theme-badge theme-badge-warning">
                              High sensitivity · weak support
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          <button
                            className="text-link"
                            onClick={() => showEvidence(item.parameter)}
                          >
                            View evidence
                          </button>
                          {item.rule_ids.length > 0 && (
                            <p className="caption break-all mt-1">
                              Rules: {item.rule_ids.join(", ")}
                            </p>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </SurfaceCard>
      )}
      {evidence && (
        <EvidencePanel selection={evidence} onClose={() => setEvidence(null)} />
      )}
    </section>
  )
}
