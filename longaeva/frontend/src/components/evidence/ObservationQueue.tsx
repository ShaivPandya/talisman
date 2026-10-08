import { useEffect, useState, type FormEvent } from "react"
import { listObservations, type Observation } from "@/lib/evidence"
import { errorMessage } from "@/lib/scenarios"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { TourTarget } from "@/components/tour/TourTarget"
import type { UpdateParams } from "./PassageSearch"

const PAGE_SIZE = 20
export function ObservationQueue({
  params,
  update,
}: {
  params: URLSearchParams
  update: UpdateParams
}) {
  const company = params.get("review_company") ?? ""
  const status = params.get("review_status") ?? ""
  const source = params.get("source_id") ?? ""
  const parsed = Number(params.get("queue_offset") ?? 0)
  const offset = Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0
  const [rows, setRows] = useState<Observation[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let cancelled = false
    listObservations({
      company,
      review_status: status,
      source_id: source,
      offset,
      limit: PAGE_SIZE + 1,
    })
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [company, status, source, offset, attempt])
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setError(null)
    setRows(null)
    setAttempt((value) => value + 1)
    update({
      review_company: String(form.get("review_company") ?? "").trim() || null,
      review_status: String(form.get("review_status") ?? "") || null,
      queue_offset: null,
      observation: null,
    })
  }
  return (
    <TourTarget id={params.get("observation") ? undefined : "evidence-review"} status={error ? "error" : !rows ? "loading" : rows.length ? "ready" : "empty"} message={error || (rows?.length === 0 ? "No observations match this queue. Clear filters or import the packaged demo with make seed." : null)} onRetry={() => { setError(null); setRows(null); setAttempt((value) => value + 1) }}>
    <SurfaceCard className="p-5 mb-5">
      <h2 className="section-title mb-3">Observation queue</h2>
      <p className="caption mb-3">
        Stored observations across publication dates. Source evidence and
        mapping eligibility are checked against your origin cutoff.
      </p>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <label className="theme-field-label">
          Observation company
          <input
            name="review_company"
            defaultValue={company}
            className="theme-input w-full mt-1"
            placeholder="All companies"
          />
        </label>
        <label className="theme-field-label">
          Review status
          <select
            name="review_status"
            defaultValue={status}
            className="theme-input w-full mt-1"
          >
            <option value="">All statuses</option>
            {["pending", "accepted", "corrected", "rejected"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <button
          className="theme-button-base theme-button-secondary"
          type="submit"
        >
          Filter observations
        </button>
      </form>
      {source && (
        <p className="caption mt-3 break-all">
          Source: {source}{" "}
          <button
            className="text-link ml-2"
            onClick={() =>
              update({ source_id: null, queue_offset: null, observation: null })
            }
          >
            Clear source filter
          </button>
        </p>
      )}
      {error && (
        <p role="alert" className="theme-notice theme-notice-error mt-3">
          {error}
        </p>
      )}
      {!rows && !error && (
        <p role="status" className="mt-4">
          Loading observations…
        </p>
      )}
      {rows && (
        <>
          {!rows.length && (
            <p className="body-copy mt-4">
              No stored observations match. Collection and extraction populate
              this queue; this page reviews existing observations.
            </p>
          )}
          <div className="grid gap-3 mt-4 md:grid-cols-2">
            {rows.slice(0, PAGE_SIZE).map((row) => (
              <article
                key={row.id}
                className="rounded-xl border border-app p-4"
              >
                <div className="flex justify-between flex-wrap gap-2">
                  <h3 className="font-semibold">
                    {row.company} · {row.activity_type ?? row.statement_type}
                  </h3>
                  <span className="theme-badge theme-badge-neutral">
                    {row.review_status}
                  </span>
                </div>
                <p className="caption mt-2">
                  {row.statement_type} ·{" "}
                  {row.geography ?? "Geography unspecified"} ·{" "}
                  {row.period_start} – {row.period_end}
                </p>
                <p className="text-sm mt-2">
                  {row.value ??
                    (row.range_low !== null
                      ? `${row.range_low}–${row.range_high ?? "?"}`
                      : "Qualitative")}{" "}
                  {row.unit} · {row.basis ?? "Basis unspecified"}
                </p>
                {row.review_status === "corrected" && (
                  <p className="caption">
                    Original extraction shown; open review for effective values.
                  </p>
                )}
                <button
                  className="text-link mt-3"
                  onClick={() => update({ observation: row.id })}
                >
                  Review observation
                </button>
              </article>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3 mt-4">
            <button
              className="theme-button-base theme-button-secondary"
              disabled={offset === 0}
              onClick={() =>
                update({
                  queue_offset: String(Math.max(0, offset - PAGE_SIZE)),
                  observation: null,
                })
              }
            >
              Previous observations
            </button>
            <span className="caption">
              Page {Math.floor(offset / PAGE_SIZE) + 1}
            </span>
            <button
              className="theme-button-base theme-button-secondary"
              disabled={rows.length <= PAGE_SIZE}
              onClick={() =>
                update({
                  queue_offset: String(offset + PAGE_SIZE),
                  observation: null,
                })
              }
            >
              Next observations
            </button>
          </div>
        </>
      )}
    </SurfaceCard>
    </TourTarget>
  )
}
