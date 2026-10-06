import { useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import {
  getWorkspace,
  listOrigins,
  prepareOrigin,
  type ParameterSetRead,
  type ParameterSpec,
  type WorkspaceOrigin,
  type WorkspaceState,
} from "@/lib/api"
import {
  defaultDraft,
  errorMessage,
  inputValue,
  isPercentParameter,
  submitWorkspacePair,
  type ScenarioDraft,
} from "@/lib/scenarios"
import { fmtUtc, shortHash } from "@/lib/format"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import {
  EvidencePanel,
  type EvidenceSelection,
} from "@/components/shared/EvidencePanel"
import { SavedComparison } from "@/components/scenario/SavedComparison"

export function ScenariosPage() {
  const [params] = useSearchParams()
  return <ScenarioWorkspace key={params.get("origin") ?? "2024-07-23"} />
}

function ScenarioWorkspace() {
  const [params, setParams] = useSearchParams()
  const origin = params.get("origin") ?? "2024-07-23"
  const runId = params.get("run_id")
  const baselineId = params.get("baseline_run_id")
  const [origins, setOrigins] = useState<WorkspaceOrigin[]>([])
  const [workspace, setWorkspace] = useState<WorkspaceState | null>(null)
  const [base, setBase] = useState<ParameterSetRead | null>(null)
  const [draft, setDraft] = useState<ScenarioDraft>(defaultDraft)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const submitLock = useRef(false)
  const [evidence, setEvidence] = useState<EvidenceSelection | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let cancelled = false
    Promise.all([listOrigins(), getWorkspace(origin), prepareOrigin(origin)])
      .then(([options, state, parameterSet]) => {
        if (!cancelled) {
          setOrigins(options)
          setWorkspace(state)
          setBase(parameterSet)
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
  const ready =
    workspace?.origin_date === origin && base?.cutoff_ts.slice(0, 10) === origin
  const patch = (update: Partial<ScenarioDraft>) =>
    setDraft((current) => ({ ...current, ...update }))
  const showEvidence = (parameter: string) => {
    if (base)
      setEvidence({
        title: parameter.replaceAll("_", " "),
        parameter,
        parameterSetId: base.id,
      })
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!ready || !base || !workspace || submitLock.current) return
    submitLock.current = true
    setSubmitting(true)
    setError(null)
    try {
      const runs = await submitWorkspacePair(
        draft,
        base,
        workspace.parameter_specs,
      )
      const baseline = runs.find((run) => !run.baseline_run_id)
      const variant = runs.find((run) => run.baseline_run_id)
      if (!baseline || !variant)
        throw new Error(
          "Paired submission did not return both run IDs. Check Runs before retrying.",
        )
      setParams({ origin, baseline_run_id: baseline.id, run_id: variant.id })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      submitLock.current = false
      setSubmitting(false)
    }
  }
  return (
    <div>
      <header className="theme-page-header">
        <div>
          <p className="theme-eyebrow">Visa · four-quarter simulation</p>
          <h1 className="theme-page-title">Scenarios</h1>
          <p className="theme-page-subtitle">
            Change an assumption. Compare it with the calibrated baseline using
            shared random draws.
          </p>
        </div>
        <Link className="text-link text-sm" to={`/state?origin=${origin}`}>
          Inspect starting state →
        </Link>
      </header>
      <SurfaceCard className="p-4 mb-5 flex flex-wrap items-end gap-6">
        <div>
          <label className="theme-field-label" htmlFor="scenario-origin">
            Origin
          </label>
          <select
            id="scenario-origin"
            className="theme-input"
            disabled={submitting}
            value={origin}
            onChange={(event) => {
              setParams({ origin: event.target.value })
              setDraft(defaultDraft())
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
          <p className="caption">Cutoff</p>
          <p className="mono-text text-sm">
            {fmtUtc(ready ? workspace?.cutoff_ts : null)}
          </p>
        </div>
        <div>
          <p className="caption">Calibrated parameter set</p>
          <p className="mono-text text-sm">
            {ready
              ? shortHash(base?.content_hash)
              : "Preparing bundled inputs…"}
          </p>
        </div>
      </SurfaceCard>
      {!ready && !error && (
        <p role="status" className="mb-4">
          Loading bundled calibration…
        </p>
      )}
      {error && !ready && (
        <div role="alert" className="theme-notice theme-notice-error mb-4">
          <p>{error}</p>
          {!ready && (
            <button
              className="text-link"
              onClick={() => {
                setError(null)
                setAttempt((value) => value + 1)
              }}
            >
              Retry loading inputs
            </button>
          )}
        </div>
      )}
      {ready && workspace && base && (
        <details open={!runId} className="mb-5">
          <summary className="font-semibold cursor-pointer mb-4">
            {runId ? "Define another comparison" : "Scenario definition"}
          </summary>
          <form onSubmit={submit} noValidate>
            <fieldset disabled={submitting} className="min-w-0">
              <div className="grid gap-4 lg:grid-cols-2 mb-5">
                <SurfaceCard className="p-5">
                  <p className="theme-eyebrow">Baseline</p>
                  <h2 className="text-lg font-semibold mb-2">
                    Calibrated Visa
                  </h2>
                  <p className="body-copy">
                    Saved parameter values and ranges at {workspace.label}. No
                    interventions.
                  </p>
                  <p className="caption mt-3">
                    Both runs use the same seed, path count, starting state and
                    four-quarter horizon. Manual changes are recorded as
                    assumptions.
                  </p>
                </SurfaceCard>
                <SurfaceCard className="p-5">
                  <label className="theme-field-label" htmlFor="scenario-name">
                    Variant name
                  </label>
                  <input
                    id="scenario-name"
                    className="theme-input"
                    value={draft.name}
                    onChange={(event) => patch({ name: event.target.value })}
                  />
                  <p className="caption mt-3">
                    Edit the variant below. The calibrated baseline remains
                    available for comparison.
                  </p>
                </SurfaceCard>
              </div>
              <SurfaceCard className="p-5 mb-5">
                <h2 className="font-semibold mb-1">Interventions</h2>
                <p className="caption mb-4">
                  Persistent level changes, applied once at the selected
                  quarter.
                </p>
                <div className="grid gap-5 lg:grid-cols-2">
                  <InterventionControl
                    title="Mix shift · conserve total spending"
                    checked={draft.mix}
                    onCheck={(mix) => patch({ mix })}
                    value={draft.mixChange}
                    onValue={(mixChange) => patch({ mixChange })}
                    quarter={draft.mixQuarter}
                    onQuarter={(mixQuarter) => patch({ mixQuarter })}
                    id="mix"
                    label="Cross-border mix change (%)"
                    description="Domestic volume absorbs the cross-border change. Total payments volume is conserved."
                  />
                  <InterventionControl
                    title="Total-spend reduction"
                    checked={draft.spend}
                    onCheck={(spend) => patch({ spend })}
                    value={draft.reduction}
                    onValue={(reduction) => patch({ reduction })}
                    quarter={draft.spendQuarter}
                    onQuarter={(spendQuarter) => patch({ spendQuarter })}
                    id="spend"
                    label="Spending reduction (%)"
                    description="Payments volume falls. Processed transactions stay unchanged; service revenue responds with its one-quarter lag."
                  />
                </div>
              </SurfaceCard>
              <SurfaceCard className="p-5 mb-5">
                <h2 className="font-semibold mb-1">Business drivers</h2>
                <p className="caption mb-4">
                  Calibrated ranges describe support; model bounds limit
                  editable values. Every changed value needs a rationale.
                </p>
                <div className="grid gap-4 lg:grid-cols-2">
                  {workspace.parameter_specs
                    .filter((spec) => spec.role === "free")
                    .map((spec) => (
                      <ParameterControl
                        key={spec.name}
                        spec={spec}
                        base={base}
                        draft={draft}
                        patch={patch}
                        onEvidence={() => showEvidence(spec.name)}
                      />
                    ))}
                </div>
              </SurfaceCard>
              <details className="theme-surface p-5 mb-5">
                <summary className="font-semibold cursor-pointer">
                  Advanced parameters & run settings
                </summary>
                <div className="grid gap-4 lg:grid-cols-2 mt-4">
                  {workspace.parameter_specs
                    .filter((spec) => spec.role !== "free")
                    .map((spec) => (
                      <ParameterControl
                        key={spec.name}
                        spec={spec}
                        base={base}
                        draft={draft}
                        patch={patch}
                        onEvidence={() => showEvidence(spec.name)}
                      />
                    ))}
                </div>
                <div className="grid grid-cols-2 gap-4 mt-6">
                  <div>
                    <label className="theme-field-label" htmlFor="seed">
                      Shared seed
                    </label>
                    <input
                      id="seed"
                      type="number"
                      className="theme-input"
                      value={draft.seed}
                      onChange={(event) => patch({ seed: event.target.value })}
                    />
                  </div>
                  <div>
                    <label className="theme-field-label" htmlFor="paths">
                      Paths per scenario
                    </label>
                    <input
                      id="paths"
                      type="number"
                      className="theme-input"
                      value={draft.paths}
                      onChange={(event) => patch({ paths: event.target.value })}
                    />
                  </div>
                </div>
              </details>
              {error && (
                <p
                  role="alert"
                  className="theme-notice theme-notice-error mb-4"
                >
                  {error}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-4 mb-7">
                <button
                  type="submit"
                  className="theme-button-base theme-button-primary"
                >
                  {submitting ? "Submitting pair…" : "Run paired scenarios"}
                </button>
                <p className="caption">
                  4 quarters · {draft.paths} paths · seed {draft.seed} · no LLM
                  required
                </p>
              </div>
            </fieldset>
          </form>
        </details>
      )}
      {runId && baselineId && (
        <SavedComparison
          key={`${baselineId}/${runId}`}
          runId={runId}
          baselineId={baselineId}
        />
      )}
      {evidence && (
        <EvidencePanel selection={evidence} onClose={() => setEvidence(null)} />
      )}
    </div>
  )
}

function InterventionControl({
  title,
  checked,
  onCheck,
  value,
  onValue,
  quarter,
  onQuarter,
  id,
  label,
  description,
}: {
  title: string
  checked: boolean
  onCheck: (value: boolean) => void
  value: string
  onValue: (value: string) => void
  quarter: string
  onQuarter: (value: string) => void
  id: string
  label: string
  description: string
}) {
  return (
    <div className="rounded-xl border border-app p-4">
      <label className="flex items-start gap-2 font-medium">
        <input
          type="checkbox"
          className="mt-1"
          checked={checked}
          onChange={(event) => onCheck(event.target.checked)}
        />
        {title}
      </label>
      <p className="caption mt-2 mb-4">{description}</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="theme-field-label" htmlFor={`${id}-magnitude`}>
            {label}
          </label>
          <input
            id={`${id}-magnitude`}
            type="number"
            step="any"
            className="theme-input"
            disabled={!checked}
            value={value}
            onChange={(event) => onValue(event.target.value)}
          />
        </div>
        <div>
          <label className="theme-field-label" htmlFor={`${id}-quarter`}>
            Start quarter
          </label>
          <select
            id={`${id}-quarter`}
            className="theme-input"
            disabled={!checked}
            value={quarter}
            onChange={(event) => onQuarter(event.target.value)}
          >
            {[1, 2, 3, 4].map((q) => (
              <option key={q} value={q}>
                Quarter {q}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  )
}

function ParameterControl({
  spec,
  base,
  draft,
  patch,
  onEvidence,
}: {
  spec: ParameterSpec
  base: ParameterSetRead
  draft: ScenarioDraft
  patch: (update: Partial<ScenarioDraft>) => void
  onEvidence: () => void
}) {
  const original = inputValue(spec.name, base.values[spec.name])
  const value = draft.values[spec.name] ?? original
  const changed = value !== original
  const link = base.evidence_links[spec.name]
  const range = base.ranges[spec.name]
  const suffix = isPercentParameter(spec.name) ? "%" : "ratio"
  return (
    <div className="rounded-xl border border-app p-4">
      <div className="flex flex-wrap justify-between gap-2 mb-2">
        <label className="text-sm font-medium" htmlFor={`param-${spec.name}`}>
          {spec.name.replaceAll("_", " ")}
        </label>
        <span
          className={`theme-badge ${changed || link?.assumption ? "theme-badge-warning" : "theme-badge-info"}`}
        >
          {changed
            ? "Override assumption"
            : link?.assumption
              ? "Assumption"
              : "Observation backed"}
        </span>
      </div>
      <p className="caption mb-3">{spec.description}</p>
      <div className="flex gap-2 items-center">
        <input
          id={`param-${spec.name}`}
          className="theme-input"
          type="number"
          step="any"
          value={value}
          onChange={(event) =>
            patch({
              values: { ...draft.values, [spec.name]: event.target.value },
            })
          }
        />
        <span className="caption">{suffix}</span>
      </div>
      <p className="caption mt-2">
        Baseline {original} {suffix} · range{" "}
        {range
          ? range.map((v) => inputValue(spec.name, v)).join(" to ")
          : "unavailable"}
      </p>
      <p className="caption mt-1">
        Model bounds {inputValue(spec.name, spec.lower)} to{" "}
        {inputValue(spec.name, spec.upper)} {suffix}
      </p>
      <button
        type="button"
        className="text-link text-xs mt-2"
        onClick={onEvidence}
      >
        Evidence & rationale
        {link?.observation_ids.length
          ? ` (${link.observation_ids.length})`
          : ""}
      </button>
      {changed && (
        <div className="mt-3">
          <label className="theme-field-label" htmlFor={`reason-${spec.name}`}>
            Override rationale (required)
          </label>
          <textarea
            id={`reason-${spec.name}`}
            className="theme-input"
            rows={2}
            value={draft.rationales[spec.name] ?? ""}
            onChange={(event) =>
              patch({
                rationales: {
                  ...draft.rationales,
                  [spec.name]: event.target.value,
                },
              })
            }
          />
          <button
            type="button"
            className="text-link text-xs mt-1"
            onClick={() =>
              patch({ values: { ...draft.values, [spec.name]: original } })
            }
          >
            Reset to baseline
          </button>
        </div>
      )}
    </div>
  )
}
