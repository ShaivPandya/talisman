import { useEffect, useState, type FormEvent } from "react"
import {
  searchPassages,
  type PassageSearch as SearchResult,
} from "@/lib/evidence"
import { errorMessage } from "@/lib/scenarios"
import { fmtUtc } from "@/lib/format"
import { SurfaceCard } from "@/components/shared/SurfaceCard"

export type UpdateParams = (changes: Record<string, string | null>) => void

export function PassageSearch({
  params,
  cutoff,
  update,
}: {
  params: URLSearchParams
  cutoff: string
  update: UpdateParams
}) {
  const [result, setResult] = useState<SearchResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const q = params.get("q") ?? ""
  const company = params.get("company") ?? ""
  const start = params.get("period_start") ?? ""
  const end = params.get("period_end") ?? ""
  const timestamp = params.get("cutoff_ts") ?? cutoff
  useEffect(() => {
    let cancelled = false
    if (q)
      searchPassages({
        q,
        company,
        period_start: start,
        period_end: end,
        cutoff_ts: timestamp,
        limit: 50,
      })
        .then((data) => {
          if (!cancelled) setResult(data)
        })
        .catch((err) => {
          if (!cancelled) setError(errorMessage(err))
        })
    return () => {
      cancelled = true
    }
  }, [q, company, start, end, timestamp, attempt])
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const changes = Object.fromEntries(
      ["q", "company", "period_start", "period_end", "cutoff_ts"].map((key) => [
        key,
        String(form.get(key) ?? "").trim() || null,
      ]),
    )
    if (
      changes.period_start &&
      changes.period_end &&
      changes.period_start > changes.period_end
    ) {
      setError("Period start must be on or before period end.")
      return
    }
    if (
      !changes.cutoff_ts ||
      !/(Z|[+-]\d{2}:\d{2})$/i.test(changes.cutoff_ts) ||
      !Number.isFinite(Date.parse(changes.cutoff_ts))
    ) {
      setError(
        "Enter a cutoff timestamp with a timezone, such as 2024-07-23T20:05:38Z.",
      )
      return
    }
    setError(null)
    setResult(null)
    setAttempt((value) => value + 1)
    update({
      ...changes,
      source_id: null,
      observation: null,
      queue_offset: null,
    })
  }
  return (
    <SurfaceCard className="p-5 mb-5">
      <h2 className="section-title mb-2">Search dated passages</h2>
      <p className="caption mb-4">
        Search uses source reporting periods. The review queue below lists
        stored observations; applying rules always uses the selected parameter
        set’s cutoff.
      </p>
      <form
        onSubmit={submit}
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      >
        <label className="theme-field-label">
          Search terms
          <input
            className="theme-input w-full mt-1"
            name="q"
            defaultValue={q}
            placeholder="cross-border"
            required
          />
        </label>
        <label className="theme-field-label">
          Source company
          <input
            className="theme-input w-full mt-1"
            name="company"
            defaultValue={company}
            placeholder="All · exact name, e.g. visa"
          />
        </label>
        <label className="theme-field-label">
          Publication cutoff (UTC or offset)
          <input
            className="theme-input w-full mt-1"
            name="cutoff_ts"
            defaultValue={timestamp}
            required
          />
        </label>
        <label className="theme-field-label">
          Source period start
          <input
            className="theme-input w-full mt-1"
            type="date"
            name="period_start"
            defaultValue={start}
          />
        </label>
        <label className="theme-field-label">
          Source period end
          <input
            className="theme-input w-full mt-1"
            type="date"
            name="period_end"
            defaultValue={end}
          />
        </label>
        <div className="flex items-end">
          <button
            className="theme-button-base theme-button-primary"
            type="submit"
          >
            Search passages
          </button>
        </div>
      </form>
      {error && (
        <p role="alert" className="theme-notice theme-notice-error mt-4">
          {error}
        </p>
      )}
      {q && !result && !error && (
        <p role="status" className="mt-4">
          Searching passages…
        </p>
      )}
      {result && (
        <div className="mt-4 space-y-3">
          <p className="caption">
            {result.hits.length} results · cutoff {fmtUtc(result.cutoff_ts)}
            {result.hits.length === 50
              ? " · first 50 matches; refine your search"
              : ""}
          </p>
          {!result.hits.length && <p>No passages match these filters.</p>}
          {result.hits.map((hit) => (
            <article
              key={hit.document_text_id}
              className="rounded-xl border border-app p-4"
            >
              <p className="font-medium">
                {hit.company} · {hit.doc_type}
              </p>
              <p className="caption">
                Published {fmtUtc(hit.publication_ts)} · page {hit.page} ·
                characters {hit.char_start}–{hit.char_end}
              </p>
              <p className="caption">
                Source period: {hit.period_start ?? "Unknown"} –{" "}
                {hit.period_end ?? "Unknown"}
              </p>
              <p className="body-copy mt-2 break-words">
                {hit.snippet.replace(/<\/?b>/g, "")}
              </p>
              <details className="mt-2">
                <summary className="text-link cursor-pointer">
                  Read stored passage
                </summary>
                <p className="evidence-passage mt-2 whitespace-pre-wrap">
                  {hit.text}
                </p>
              </details>
              <div className="flex gap-4 flex-wrap mt-3">
                <button
                  className="text-link"
                  onClick={() =>
                    update({
                      source_id: hit.source_id,
                      review_company: null,
                      review_status: null,
                      queue_offset: null,
                      observation: null,
                    })
                  }
                >
                  Review observations from this source
                </button>
                {/^https?:\/\//i.test(hit.url) && (
                  <a
                    className="text-link"
                    href={hit.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Original document ↗
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </SurfaceCard>
  )
}
