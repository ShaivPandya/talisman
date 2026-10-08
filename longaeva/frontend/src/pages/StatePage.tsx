import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import {
  getWorkspace,
  listOrigins,
  type StateValue,
  type WorkspaceOrigin,
  type WorkspaceState,
} from "@/lib/api"
import { fmtNumber, fmtUtc } from "@/lib/format"
import { errorMessage } from "@/lib/scenarios"
import { EvidenceWorkspace } from "@/components/evidence/EvidenceWorkspace"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { TourTarget } from "@/components/tour/TourTarget"
import {
  EvidencePanel,
  type EvidenceSelection,
} from "@/components/shared/EvidencePanel"

function groupFor(name: string): string {
  if (/revenue|incentives|expenses|profit|special_items/.test(name))
    return "Revenue & operating profit"
  if (/shares|tax|interest/.test(name)) return "Valuation inputs"
  return "Activity & effective yields"
}

export function StatePage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get("tab") === "evidence" ? "evidence" : "state"
  const origin = params.get("origin") ?? "2024-07-23"
  const [origins, setOrigins] = useState<WorkspaceOrigin[]>([])
  const [state, setState] = useState<WorkspaceState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<EvidenceSelection | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let cancelled = false
    Promise.all([listOrigins(), getWorkspace(origin)])
      .then(([options, result]) => {
        if (!cancelled) {
          setOrigins(options)
          setState(result)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [origin, attempt])
  const current = state?.origin_date === origin ? state : null
  return (
    <TourTarget id={tab === "state" ? "starting-state" : !current ? "evidence-review" : undefined} status={error ? "error" : current ? "ready" : "loading"} message={error} onRetry={() => { setError(null); setAttempt((value) => value + 1) }}>
      <header className="theme-page-header">
        <div>
          <h1 className="theme-page-title">State & Evidence</h1>
          <p className="theme-page-subtitle">
            Inspect what was known at the cutoff, then build a scenario.
          </p>
        </div>
        <Link
          className="theme-button-base theme-button-primary"
          to={`/scenarios?origin=${origin}`}
        >
          Build a scenario →
        </Link>
      </header>
      <SurfaceCard className="p-4 mb-5 flex flex-wrap items-end gap-6">
        <div>
          <label className="theme-field-label" htmlFor="state-origin">
            Origin
          </label>
          <select
            id="state-origin"
            className="theme-input"
            value={origin}
            onChange={(event) => {
              setParams({ origin: event.target.value, tab })
              setEvidence(null)
              setError(null)
            }}
          >
            {origins.length ? (
              origins.map((item) => (
                <option key={item.origin_date} value={item.origin_date}>
                  {item.label} · {item.origin_date}
                </option>
              ))
            ) : (
              <option>{origin}</option>
            )}
          </select>
        </div>
        <div>
          <p className="caption">Information cutoff</p>
          <p className="mono-text text-sm">{fmtUtc(current?.cutoff_ts)}</p>
        </div>
        <div>
          <p className="caption">Input documents</p>
          <p className="text-sm">
            {current ? Object.keys(current.sources).length : "—"} retained
            originals
          </p>
        </div>
      </SurfaceCard>
      <nav
        aria-label="State and evidence views"
        className="flex flex-wrap gap-3 mb-5"
      >
        {[
          ["state", "Starting state"],
          ["evidence", "Evidence & Review"],
        ].map(([value, label]) => (
          <Link
            key={value}
            aria-current={tab === value ? "page" : undefined}
            className={`theme-button-base ${tab === value ? "theme-button-primary" : "theme-button-secondary"}`}
            to={`?${new URLSearchParams({ ...Object.fromEntries(params), tab: value })}`}
          >
            {label}
          </Link>
        ))}
      </nav>
      {error && (
        <p role="alert" className="theme-notice theme-notice-error mb-4">
          {error}
        </p>
      )}
      {!current && !error && <p role="status">Loading starting state…</p>}
      {current && tab === "evidence" && (
        <EvidenceWorkspace key={origin} state={current} />
      )}
      {current && tab === "state" && (
        <>
          {[
            "Activity & effective yields",
            "Revenue & operating profit",
            "Valuation inputs",
          ].map((group) => (
            <SurfaceCard key={group} className="mb-5 overflow-hidden">
              <h2 className="p-4 font-semibold border-b border-app">{group}</h2>
              <div className="overflow-x-auto">
                <table className="workspace-table">
                  <thead>
                    <tr>
                      <th>Starting value</th>
                      <th>Value / unit</th>
                      <th>Period / basis</th>
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(current.values)
                      .filter(([name]) => groupFor(name) === group)
                      .map(([name, value]) => (
                        <StateRow
                          key={name}
                          name={name}
                          value={value}
                          onEvidence={
                            current.evidence[name]
                              ? () =>
                                  setEvidence({
                                    title: name.replaceAll("_", " "),
                                    excerpt: current.evidence[name],
                                  })
                              : undefined
                          }
                        />
                      ))}
                  </tbody>
                </table>
              </div>
            </SurfaceCard>
          ))}
          <details className="theme-surface p-4 mb-5">
            <summary className="font-semibold cursor-pointer">
              Supporting levels used in derivations
            </summary>
            <div className="overflow-x-auto mt-3">
              <table className="workspace-table">
                <tbody>
                  {Object.entries(current.supporting_levels).map(
                    ([key, value]) => (
                      <tr key={key}>
                        <td>{key.replaceAll("_", " ")}</td>
                        <td>
                          {fmtNumber(value.value)}{" "}
                          {value.unit.replaceAll("_", " ")}
                        </td>
                        <td>
                          {value.period_label} · {value.basis}
                        </td>
                        <td>
                          <button
                            className="text-link"
                            onClick={() =>
                              setEvidence({
                                title: key,
                                excerpt: current.evidence[key],
                              })
                            }
                          >
                            View source
                          </button>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          </details>
          <details className="theme-surface p-4 mb-5">
            <summary className="font-semibold cursor-pointer">
              Later documents · excluded from this starting state
            </summary>
            <p className="caption my-3">
              These documents were published after the cutoff and are retained
              only for later reconciliation.
            </p>
            {Object.values(current.post_cutoff_sources).map((source) => (
              <p className="text-sm mb-2 break-all" key={source.source_id}>
                {source.form} · {fmtUtc(source.acceptance_utc)} ·{" "}
                <a
                  className="text-link"
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {source.document}
                </a>
              </p>
            ))}
          </details>
          <details className="theme-surface p-4">
            <summary className="font-semibold cursor-pointer">
              Method notes
            </summary>
            <ul className="list-disc pl-5 mt-3 space-y-2 body-copy">
              {current.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </details>
        </>
      )}
      {evidence && (
        <EvidencePanel selection={evidence} onClose={() => setEvidence(null)} />
      )}
    </TourTarget>
  )
}

function StateRow({
  name,
  value,
  onEvidence,
}: {
  name: string
  value: StateValue
  onEvidence?: () => void
}) {
  return (
    <tr>
      <td>
        <p className="font-medium">{name.replaceAll("_", " ")}</p>
        <span className="theme-badge theme-badge-neutral mt-1">
          {value.status.replaceAll("_", " ")}
        </span>
        {value.note && <p className="caption mt-2 max-w-sm">{value.note}</p>}
        {value.derivation && (
          <details className="caption mt-2">
            <summary className="cursor-pointer">Derivation</summary>
            <p className="mono-text mt-1">{value.derivation.formula}</p>
            {Object.entries(value.derivation.inputs).map(([key, v]) => (
              <p key={key}>
                {key}: {fmtNumber(v, 4)}
              </p>
            ))}
          </details>
        )}
      </td>
      <td>
        <p className="mono-text">
          {value.value === null ? "Unavailable" : fmtNumber(value.value, 3)}
        </p>
        <p className="caption">{value.unit.replaceAll("_", " ")}</p>
        {value.unavailable_reason && (
          <p className="caption max-w-xs mt-2">{value.unavailable_reason}</p>
        )}
      </td>
      <td>
        <p>{value.period_label ?? "At cutoff"}</p>
        <p className="caption">{value.basis.replaceAll("_", " ")}</p>
      </td>
      <td>
        {onEvidence ? (
          <button className="text-link whitespace-nowrap" onClick={onEvidence}>
            View source
          </button>
        ) : (
          <span className="caption">Unavailable at cutoff</span>
        )}
      </td>
    </tr>
  )
}
