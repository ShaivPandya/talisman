import { useEffect, useRef, useState } from "react"
import {
  getParameterSet,
  prepareOrigin,
  type ParameterSetRead,
} from "@/lib/api"
import {
  applyRules,
  getContext,
  getLineage,
  getMappingRule,
  getReview,
  getUpdates,
  listParameterSets,
  previewKey,
  previewRules,
  reviewVersion,
  sameCutoff,
  type ContextItem,
  type MappingRule,
  type ObservationReview,
  type RuleApplication,
  type RuleRequest,
  type RuleUpdate,
} from "@/lib/evidence"
import { errorMessage } from "@/lib/scenarios"
import { fmtNumber, fmtUtc, shortHash } from "@/lib/format"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { useTourDraftGuard } from "@/lib/tourContext"
import type { UpdateParams } from "@/components/evidence/PassageSearch"

export function RuleReview({
  review,
  origin,
  cutoff,
  params,
  update,
}: {
  review: ObservationReview
  origin: string
  cutoff: string
  params: URLSearchParams
  update: UpdateParams
}) {
  const selected = params.get("parameter_set_id") ?? ""
  return (
    <RuleWorkspace
      key={`${origin}:${selected}`}
      review={review}
      origin={origin}
      cutoff={cutoff}
      selected={selected}
      resultId={params.get("result_set_id")}
      update={update}
    />
  )
}
function RuleWorkspace({
  review,
  origin,
  cutoff,
  selected,
  resultId,
  update,
}: {
  review: ObservationReview
  origin: string
  cutoff: string
  selected: string
  resultId: string | null
  update: UpdateParams
}) {
  const [base, setBase] = useState<ParameterSetRead | null>(null)
  const [sets, setSets] = useState<ParameterSetRead[]>([])
  const [reviewer, setReviewer] = useState("")
  const [rationale, setRationale] = useState("")
  const [preview, setPreview] = useState<{
    key: string
    data: RuleApplication
    body: RuleRequest
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [savedRevision, setSavedRevision] = useState(0)
  const lock = useRef(false)
  const signature = JSON.stringify({ reviewer, rationale })
  const cleanForm = useRef(signature)
  useTourDraftGuard(busy || signature !== cleanForm.current, "mapping rule edits")
  const eligible =
    review.observation.review_status === "accepted" ||
    review.observation.review_status === "corrected"
  const key = previewKey(
    base?.id ?? "",
    review.observation.id,
    reviewVersion(review),
    reviewer,
    rationale,
  )
  const currentKey = useRef(key)
  useEffect(() => {
    currentKey.current = key
  }, [key])
  const validPreview = preview?.key === key && eligible ? preview : null
  useEffect(() => {
    let cancelled = false
    const resolve = selected ? getParameterSet(selected) : prepareOrigin(origin)
    resolve
      .then(async (parameterSet) => {
        if (
          parameterSet.company !== "visa" ||
          !sameCutoff(parameterSet.cutoff_ts, cutoff)
        )
          throw new Error(
            "This parameter set does not match the selected Visa origin and cutoff.",
          )
        const options = await listParameterSets()
        if (!cancelled) {
          setBase(parameterSet)
          setSets([
            parameterSet,
            ...options.filter(
              (item) =>
                item.id !== parameterSet.id &&
                sameCutoff(item.cutoff_ts, cutoff),
            ),
          ])
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [origin, cutoff, selected, attempt])
  async function previewOrApply(apply: boolean) {
    if (!base || !eligible || lock.current || (apply && !validPreview)) return
    lock.current = true
    setBusy(true)
    setError(null)
    setNotice(null)
    const requestedKey = key
    try {
      if (!reviewer.trim() || !rationale.trim())
        throw new Error("Rule reviewer and application rationale are required.")
      const latest = await getReview(review.observation.id)
      if (
        reviewVersion(latest) !== reviewVersion(review) ||
        latest.observation.review_status !== review.observation.review_status
      )
        throw new Error(
          "This observation was reviewed again. Reload the observation and preview the latest decision before applying.",
        )
      const body: RuleRequest = {
        observation_ids: [review.observation.id],
        decided_by: reviewer.trim(),
        rationale: rationale.trim(),
      }
      if (apply && validPreview) {
        const result = await applyRules(base.id, validPreview.body)
        cleanForm.current = signature
        setPreview(null)
        update({
          result_set_id: result.result_parameter_set_id ?? base.id,
        })
        setSavedRevision((value) => value + 1)
        setNotice(
          result.changed
            ? result.created
              ? "Applied to a new child parameter set. The base set is unchanged."
              : "Reused the existing child parameter set."
            : "No numeric change. Context was retained on the base set.",
        )
      } else {
        const data = await previewRules(base.id, body)
        if (currentKey.current === requestedKey)
          setPreview({ key: requestedKey, data, body })
      }
    } catch (err) {
      setPreview(null)
      setError(`${errorMessage(err)} No automatic retry was made.`)
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  return (
    <SurfaceCard className="p-5">
      <h2 className="section-title mb-3">Mapping rules & parameter changes</h2>
      <p className="body-copy mb-4">
        Preview the selected observation against a base set, then explicitly
        apply. Unsupported statements remain context. Stored runs and forecasts
        are unchanged.
      </p>
      {!base && !error && <p role="status">Preparing calibrated base…</p>}
      {error && (
        <p role="alert" className="theme-notice theme-notice-error mb-3">
          {error}
        </p>
      )}
      {!base && error && (
        <button
          className="text-link"
          onClick={() => {
            update({ parameter_set_id: null, result_set_id: null })
            setAttempt((value) => value + 1)
          }}
        >
          Load origin’s calibrated base
        </button>
      )}
      {base && (
        <>
          <label className="theme-field-label block mb-3">
            Base parameter set
            <select
              className="theme-input w-full mt-1"
              value={base.id}
              disabled={busy}
              onChange={(event) =>
                update({
                  parameter_set_id: event.target.value,
                  result_set_id: null,
                })
              }
            >
              {sets.map((item) => (
                <option key={item.id} value={item.id}>
                  {shortHash(item.content_hash)} ·{" "}
                  {item.parent_id ? "child" : "calibrated root"}
                </option>
              ))}
            </select>
          </label>
          <p className="caption mb-4 break-all">
            {base.id} · cutoff {fmtUtc(base.cutoff_ts)} · most recent 200 Visa
            sets, filtered to this cutoff; a linked older set remains
            selectable.
          </p>
          {!eligible && (
            <p className="theme-notice theme-notice-warning mb-4">
              Accept or adjust this observation before previewing a rule.
              Pending and rejected observations cannot change parameters.
            </p>
          )}
          <fieldset
            disabled={busy || !eligible}
            className="grid gap-3 sm:grid-cols-2"
          >
            <label className="theme-field-label">
              Rule reviewer
              <input
                className="theme-input w-full mt-1"
                value={reviewer}
                onChange={(event) => setReviewer(event.target.value)}
              />
            </label>
            <label className="theme-field-label">
              Application rationale
              <textarea
                className="theme-input w-full mt-1"
                rows={2}
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
              />
            </label>
            <div>
              <button
                className="theme-button-base theme-button-secondary"
                disabled={!reviewer.trim() || !rationale.trim()}
                onClick={() => previewOrApply(false)}
              >
                {busy ? "Working…" : "Preview rule changes"}
              </button>
            </div>
          </fieldset>
          {preview && !validPreview && (
            <p className="caption mt-3">
              Inputs changed. Preview again before applying.
            </p>
          )}
          {validPreview && (
            <section
              className="mt-5 border-t border-app pt-4"
              aria-label="Rule preview"
            >
              <h3 className="font-semibold mb-3">
                Proposed changes · not yet applied
              </h3>
              <UpdateList updates={validPreview.data.updates} />
              <ContextList items={validPreview.data.context} update={update} />
              <button
                className="theme-button-base theme-button-primary mt-4"
                disabled={busy}
                onClick={() => previewOrApply(true)}
              >
                {validPreview.data.changed
                  ? "Apply reviewed rule changes"
                  : "Save context without numeric change"}
              </button>
            </section>
          )}
          {notice && (
            <p role="status" className="theme-notice theme-notice-info mt-3">
              {notice}
            </p>
          )}
          <SavedApplication
            key={`${resultId ?? base.id}:${savedRevision}`}
            id={resultId ?? base.id}
            baseId={base.id}
            cutoff={cutoff}
            update={update}
          />
        </>
      )}
    </SurfaceCard>
  )
}
function SavedApplication({
  id,
  baseId,
  cutoff,
  update,
}: {
  id: string
  baseId: string
  cutoff: string
  update: UpdateParams
}) {
  const [data, setData] = useState<{
    updates: RuleUpdate[]
    context: ContextItem[]
    lineage: ParameterSetRead[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    Promise.all([getUpdates(id), getContext(id), getLineage(id)])
      .then(([updates, context, lineage]) => {
        if (
          !lineage.some((item) => item.id === baseId) ||
          !lineage.every((item) => sameCutoff(item.cutoff_ts, cutoff))
        )
          throw new Error(
            "The saved result does not belong to this base set and cutoff.",
          )
        if (!cancelled) setData({ updates, context, lineage })
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [id, baseId, cutoff])
  return (
    <section
      className="mt-6 border-t border-app pt-4"
      aria-label="Saved parameter changes"
    >
      <h3 className="font-semibold">Saved parameter changes</h3>
      <p className="caption break-all mt-1">Parameter set: {id}</p>
      {error && (
        <p role="alert" className="theme-notice theme-notice-error mt-3">
          {error}{" "}
          <button
            className="text-link"
            onClick={() => update({ result_set_id: null })}
          >
            Show base set
          </button>
        </p>
      )}
      {!data && !error && <p role="status">Loading saved provenance…</p>}
      {data && (
        <>
          <p className="caption mt-3 mb-4">
            Lineage, root first:{" "}
            {data.lineage
              .map((item) => shortHash(item.content_hash))
              .join(" → ")}
          </p>
          <UpdateList updates={data.updates} />
          {data.updates.length > 0 && (
            <section className="mt-4">
              <h4 className="font-semibold mb-2">Saved parameter ranges</h4>
              <p className="caption mb-2">
                The stored range retains the prior range as well as the
                rule-proposed range.
              </p>
              {[
                ...new Set(data.updates.map((item) => item.target_parameter)),
              ].map((name) => (
                <p key={name} className="text-sm">
                  {name.replaceAll("_", " ")}:{" "}
                  {data.lineage
                    .at(-1)
                    ?.ranges[name]?.map((value) => fmtNumber(value, 6))
                    .join(" – ") ?? "Unavailable"}
                </p>
              ))}
            </section>
          )}
          <ContextList items={data.context} update={update} />
        </>
      )}
    </section>
  )
}
function UpdateList({ updates }: { updates: RuleUpdate[] }) {
  return (
    <div className="space-y-3">
      {!updates.length && (
        <p className="caption">No numeric parameter updates.</p>
      )}
      {updates.map((item, index) => (
        <article
          key={`${item.target_parameter}:${index}`}
          className="rounded-xl border border-app p-4"
        >
          <h4 className="font-semibold">
            {item.target_parameter.replaceAll("_", " ")}
          </h4>
          <p className="caption mt-1">
            {item.rule_key ?? "Analyst override"}
            {item.rule_version ? ` · v${item.rule_version}` : ""} ·{" "}
            {item.assumption ||
            item.after_value?.kind === "analyst_range" ||
            item.after_value?.assumption ||
            item.after_value?.fallback
              ? "Assumption / analyst range"
              : "Recorded rule update"}
          </p>
          <div className="grid gap-3 mt-3 sm:grid-cols-2">
            <ParameterValue title="Before" value={item.before_value} />
            <ParameterValue title="After" value={item.after_value} />
          </div>
          <p className="text-sm mt-3">
            Change size (model units):{" "}
            {item.size === null ? "Not available" : fmtNumber(item.size, 6)}
          </p>
          <p className="body-copy mt-2">{item.rationale}</p>
          {item.rule_id && <RuleDefinition id={item.rule_id} />}
        </article>
      ))}
    </div>
  )
}
function ParameterValue({
  title,
  value,
}: {
  title: string
  value: Record<string, unknown> | null
}) {
  return (
    <div className="min-w-0">
      <p className="caption">{title} · native model units</p>
      <p className="mono-text mt-1">
        {typeof value?.value === "number"
          ? fmtNumber(value.value, 6)
          : "Not available"}
      </p>
      {typeof value?.range_low === "number" &&
        typeof value?.range_high === "number" && (
          <p className="caption mt-1">
            Rule range: {fmtNumber(value.range_low, 6)} –{" "}
            {fmtNumber(value.range_high, 6)}
          </p>
        )}
      {value && Object.keys(value).length > 1 && (
        <details className="mt-2">
          <summary className="text-link text-sm cursor-pointer">
            Calculation details
          </summary>
          <pre className="text-xs whitespace-pre-wrap break-words mt-1">
            {JSON.stringify(value, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}
function RuleDefinition({ id }: { id: string }) {
  const [rule, setRule] = useState<MappingRule | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  async function load() {
    if (rule || loading) return
    setLoading(true)
    try {
      setRule(await getMappingRule(id))
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }
  return (
    <details
      className="mt-3"
      onToggle={(event) => {
        if (event.currentTarget.open) void load()
      }}
    >
      <summary className="text-link cursor-pointer">Rule definition</summary>
      <p className="caption break-all mt-2">{id}</p>
      {loading && <p role="status">Loading rule…</p>}
      {error && <p role="alert">{error}</p>}
      {rule && (
        <>
          <p className="text-sm mt-2">
            {rule.kind} · {rule.rationale}
          </p>
          <pre className="text-xs whitespace-pre-wrap break-words mt-2">
            {JSON.stringify(rule.transform, null, 2)}
          </pre>
        </>
      )}
    </details>
  )
}
function ContextList({
  items,
  update,
}: {
  items: ContextItem[]
  update: UpdateParams
}) {
  return (
    <section className="mt-4">
      <h4 className="font-semibold mb-2">Context only · no numeric change</h4>
      {!items.length && (
        <p className="caption">No context-only observations in this result.</p>
      )}
      <ul className="space-y-2">
        {items.map((item) => (
          <li
            key={`${item.observation_id}:${item.reason}`}
            className="text-sm border-t border-app pt-2"
          >
            <button
              className="text-link break-all"
              onClick={() => update({ observation: item.observation_id })}
            >
              {item.observation_id}
            </button>
            <p>
              {item.reason.replaceAll("_", " ")}
              {item.rule_key
                ? ` · ${item.rule_key}`
                : " · no adopted transforming rule"}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
