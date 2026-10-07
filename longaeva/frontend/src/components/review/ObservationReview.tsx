import { useEffect, useRef, useState, type FormEvent } from "react"
import {
  correctionDraft,
  correctionPayload,
  getObservationEvidence,
  getReview,
  saveReview,
  semanticFields,
  type Decision,
  type ObservationReview as Review,
  type SemanticField,
  type SemanticValues,
} from "@/lib/evidence"
import type { EvidenceExcerpt } from "@/lib/api"
import { errorMessage } from "@/lib/scenarios"
import { fmtUtc } from "@/lib/format"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { EvidenceExcerptView } from "@/components/shared/EvidencePanel"
import { RuleReview } from "./RuleReview"
import type { UpdateParams } from "@/components/evidence/PassageSearch"

export function ObservationReview({
  id,
  origin,
  cutoff,
  params,
  update,
  onSaved,
}: {
  id: string
  origin: string
  cutoff: string
  params: URLSearchParams
  update: UpdateParams
  onSaved: () => void
}) {
  const [review, setReview] = useState<Review | null>(null)
  const [excerpt, setExcerpt] = useState<EvidenceExcerpt | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [id])
  useEffect(() => {
    let cancelled = false
    Promise.all([getReview(id), getObservationEvidence(id, cutoff)])
      .then(([data, evidence]) => {
        if (!cancelled) {
          setReview(data)
          setExcerpt(evidence)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [id, cutoff, attempt])
  return (
    <section aria-label="Selected observation" className="space-y-5">
      <SurfaceCard className="p-5">
        <div className="flex justify-between items-start gap-3 mb-4">
          <div>
            <p className="theme-eyebrow">Evidence → review → rule</p>
            <h2 ref={heading} tabIndex={-1} className="section-title">
              Review observation
            </h2>
            <p className="caption break-all mt-1">{id}</p>
          </div>
          <button
            className="text-link"
            onClick={() => update({ observation: null })}
          >
            Close review
          </button>
        </div>
        {error && (
          <p role="alert" className="theme-notice theme-notice-error">
            {error}{" "}
            <button
              className="text-link"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Reload observation
            </button>
          </p>
        )}
        {!review && !error && (
          <p role="status">Loading observation and evidence…</p>
        )}
        {excerpt && <EvidenceExcerptView excerpt={excerpt} />}
        {review && (
          <ReviewForm
            key={id}
            review={review}
            onSaved={(data) => {
              setReview(data)
              onSaved()
            }}
          />
        )}
      </SurfaceCard>
      {review && (
        <RuleReview
          review={review}
          origin={origin}
          cutoff={cutoff}
          params={params}
          update={update}
        />
      )}
    </section>
  )
}

function ReviewForm({
  review,
  onSaved,
}: {
  review: Review
  onSaved: (review: Review) => void
}) {
  const [decision, setDecision] = useState<Decision>("accept")
  const [draft, setDraft] = useState(() => correctionDraft(review))
  const [reviewer, setReviewer] = useState("")
  const [rationale, setRationale] = useState("")
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [needsReload, setNeedsReload] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (lock.current || needsReload) return
    lock.current = true
    setBusy(true)
    setError(null)
    setMessage(null)
    let saved = false
    try {
      if (!reviewer.trim() || !rationale.trim())
        throw new Error("Reviewer name and rationale are required.")
      const payload =
        decision === "correct" ? correctionPayload(draft) : undefined
      await saveReview({
        observation_id: review.observation.id,
        decision,
        decided_by: reviewer.trim(),
        rationale: rationale.trim(),
        ...(payload ? { corrected_payload: payload } : {}),
      })
      saved = true
      const data = await getReview(review.observation.id)
      onSaved(data)
      setDraft(correctionDraft(data))
      setRationale("")
      setMessage("Review saved. Parameter sets have not changed.")
    } catch (err) {
      setError(
        `${errorMessage(err)}${saved ? " Review was saved. Reload it before taking another action." : " Check persisted history before retrying if the connection failed."}`,
      )
      // A failed transport can still have committed the decision. Require a read before another write.
      setNeedsReload(true)
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  async function reload() {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    try {
      const data = await getReview(review.observation.id)
      onSaved(data)
      setNeedsReload(false)
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  return (
    <div className="mt-5">
      <div className="flex items-center flex-wrap gap-2 mb-4">
        <span className="theme-badge theme-badge-info">
          {review.observation.review_status}
        </span>
        <span className="caption">
          {review.observation.company} ·{" "}
          {review.observation.source_family ?? "No source family"}
        </span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Values title="Original observation" values={review.observation} />
        <Values title="Effective reviewed values" values={review.effective} />
      </div>
      <form onSubmit={submit} className="mt-5">
        <fieldset disabled={busy || needsReload} className="space-y-4">
          <legend className="section-title mb-3">Record a decision</legend>
          <p className="caption">
            Reviewer is a self-reported name in this local app. Acceptance saves
            the review only; preview and apply rules below to update parameters.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="theme-field-label">
              Reviewer name
              <input
                className="theme-input w-full mt-1"
                value={reviewer}
                onChange={(event) => setReviewer(event.target.value)}
                required
              />
            </label>
            <label className="theme-field-label">
              Decision
              <select
                className="theme-input w-full mt-1"
                value={decision}
                onChange={(event) =>
                  setDecision(event.target.value as Decision)
                }
              >
                <option value="accept">Accept</option>
                <option value="correct">Adjust</option>
                <option value="reject">Reject</option>
              </select>
            </label>
          </div>
          {decision === "correct" && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {semanticFields.map((key) => (
                <label className="theme-field-label" key={key}>
                  {key.replaceAll("_", " ")}
                  {key === "statement_type" ? (
                    <select
                      className="theme-input w-full mt-1"
                      value={draft[key]}
                      onChange={(event) =>
                        setDraft({ ...draft, [key]: event.target.value })
                      }
                    >
                      {[
                        "measured",
                        "guidance",
                        "qualitative",
                        "analyst_assumption",
                        "intervention",
                      ].map((type) => (
                        <option key={type}>{type}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="theme-input w-full mt-1"
                      type={
                        key.startsWith("period_")
                          ? "date"
                          : ["value", "range_low", "range_high"].includes(key)
                            ? "number"
                            : "text"
                      }
                      step="any"
                      value={draft[key]}
                      onChange={(event) =>
                        setDraft({ ...draft, [key]: event.target.value })
                      }
                      required={["period_start", "period_end", "unit"].includes(
                        key,
                      )}
                    />
                  )}
                </label>
              ))}
              <p className="caption sm:col-span-2">
                Numbers use the displayed source unit: enter 8 for 8 percent.
                Blank optional fields are cleared. Source links and spans cannot
                be edited here.
              </p>
            </div>
          )}
          <label className="theme-field-label block">
            Review rationale
            <textarea
              className="theme-input w-full mt-1"
              rows={3}
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              required
            />
          </label>
          <button
            type="submit"
            className="theme-button-base theme-button-primary"
          >
            {busy ? "Saving review…" : "Save review decision"}
          </button>
        </fieldset>
      </form>
      {message && (
        <p role="status" className="theme-notice theme-notice-info mt-3">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="theme-notice theme-notice-error mt-3">
          {error}
        </p>
      )}
      {needsReload && (
        <button className="text-link mt-3" disabled={busy} onClick={reload}>
          Reload persisted review
        </button>
      )}
      <h3 className="font-semibold mt-6 mb-3">Decision history</h3>
      {!review.decisions.length && (
        <p className="caption">No review decisions yet.</p>
      )}
      <ol className="space-y-3">
        {[...review.decisions].reverse().map((item) => (
          <li key={item.id} className="border-t border-app pt-3">
            <p className="text-sm">
              Version {item.version} ·{" "}
              {item.decision === "correct" ? "adjust" : item.decision} ·{" "}
              {item.decided_by} · {fmtUtc(item.decided_at)}
            </p>
            <p className="body-copy mt-1">{item.rationale}</p>
            {item.corrected_payload && (
              <details className="mt-2">
                <summary className="text-link cursor-pointer">
                  Saved correction
                </summary>
                <Values
                  title="Corrected fields"
                  values={item.corrected_payload}
                />
              </details>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}
function Values({
  title,
  values,
}: {
  title: string
  values: Partial<SemanticValues> | null
}) {
  return (
    <section className="rounded-xl border border-app p-4 min-w-0">
      <h3 className="font-semibold mb-3">{title}</h3>
      {values ? (
        <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2 text-sm">
          {semanticFields
            .filter((key) => key in values)
            .map((key: SemanticField) => (
              <div key={key} className="contents">
                <dt className="text-muted">{key.replaceAll("_", " ")}</dt>
                <dd className="break-words">
                  {values[key] ?? "Not specified"}
                </dd>
              </div>
            ))}
        </dl>
      ) : (
        <p className="caption">
          Pending or rejected: no effective values eligible for rule
          application.
        </p>
      )}
    </section>
  )
}
