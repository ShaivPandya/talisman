import { useEffect, useRef, useState } from "react"
import {
  getParameterEvidence,
  type EvidenceExcerpt,
  type ParameterEvidenceRead,
} from "@/lib/api"
import { fmtUtc } from "@/lib/format"
import { errorMessage } from "@/lib/scenarios"

export interface EvidenceSelection {
  title: string
  excerpt?: EvidenceExcerpt
  parameterSetId?: string
  parameter?: string
}

export function EvidencePanel({
  selection,
  onClose,
}: {
  selection: EvidenceSelection
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [data, setData] = useState<ParameterEvidenceRead | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const node = dialog.current
    node?.showModal()
    return () => node?.close()
  }, [])
  useEffect(() => {
    let cancelled = false
    if (selection.parameterSetId && selection.parameter) {
      getParameterEvidence(selection.parameterSetId, selection.parameter)
        .then((result) => {
          if (!cancelled) setData(result)
        })
        .catch((err) => {
          if (!cancelled) setError(errorMessage(err))
        })
    }
    return () => {
      cancelled = true
    }
  }, [selection])
  const excerpts = selection.excerpt ? [selection.excerpt] : data?.excerpts
  return (
    <dialog
      ref={dialog}
      onCancel={onClose}
      className="evidence-dialog theme-surface"
      aria-labelledby="evidence-title"
    >
      <header className="flex items-start justify-between gap-4 mb-4">
        <div>
          <p className="theme-eyebrow">Source evidence</p>
          <h2 id="evidence-title" className="text-lg font-semibold">
            {selection.title}
          </h2>
        </div>
        <button
          className="theme-button-base theme-button-secondary shrink-0"
          onClick={onClose}
          autoFocus
        >
          Close
        </button>
      </header>
      {error && (
        <p role="alert" className="theme-notice theme-notice-error">
          {error}
        </p>
      )}
      {data && (
        <div className="mb-4">
          <span
            className={`theme-badge ${data.evidence.assumption ? "theme-badge-warning" : "theme-badge-info"}`}
          >
            {data.evidence.assumption ? "Assumption" : "Observation backed"}
          </span>
          {data.evidence.rationale && (
            <p className="body-copy mt-2">{data.evidence.rationale}</p>
          )}
          {data.updates.map((update) => (
            <div
              key={update.id}
              className="mt-3 border-t border-app pt-3 text-sm"
            >
              <p>
                {update.rule_key
                  ? `Rule: ${update.rule_key} · v${update.rule_version}`
                  : "Analyst override · no mapping rule"}
              </p>
              {update.rule_id && (
                <p className="mono-text caption break-all">
                  Rule ID: {update.rule_id}
                </p>
              )}
              <p>{update.rationale}</p>
            </div>
          ))}
        </div>
      )}
      {!excerpts && !error && <p role="status">Loading evidence…</p>}
      {excerpts?.length === 0 && (
        <p className="caption">
          No source observations are linked to this assumption.
        </p>
      )}
      <div className="space-y-4">
        {excerpts?.map((excerpt, index) => (
          <EvidenceExcerptView key={index} excerpt={excerpt} />
        ))}
      </div>
    </dialog>
  )
}

export function EvidenceExcerptView({ excerpt }: { excerpt: EvidenceExcerpt }) {
  return (
    <article className="rounded-xl border border-app p-4">
      <p className="mono-text text-xs break-all">
        {excerpt.source_id ?? "Unresolved source"}
      </p>
      {excerpt.observation_id && (
        <p className="caption break-all">
          Observation: {excerpt.observation_id}
        </p>
      )}
      <p className="caption mt-1">
        Published {fmtUtc(excerpt.publication_ts)}
        {excerpt.char_start !== null
          ? ` · characters ${excerpt.char_start}–${excerpt.char_end}`
          : ""}
        {excerpt.page !== null ? ` · page ${excerpt.page}` : ""}
      </p>
      {excerpt.unavailable_reason ? (
        <p className="theme-notice theme-notice-warning mt-3">
          {excerpt.unavailable_reason}
        </p>
      ) : (
        <blockquote className="evidence-passage mt-3">
          {excerpt.before} <mark>{excerpt.quote}</mark> {excerpt.after}
        </blockquote>
      )}
      {excerpt.url && /^https?:\/\//i.test(excerpt.url) && (
        <a
          className="text-link inline-block mt-3 text-sm"
          href={excerpt.url}
          target="_blank"
          rel="noreferrer"
        >
          Open original document ↗
        </a>
      )}
    </article>
  )
}
