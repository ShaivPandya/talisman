import { useState } from "react"
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react"

import { Notice } from "@/components/shared/Notice"
import type { IdeaScanMacroRow, IdeaScanMacroView } from "@/lib/api"
import { cn } from "@/lib/utils"

function scoreClass(score: number): string {
  if (score >= 1) return "text-positive"
  if (score <= -1) return "text-negative"
  return "text-muted"
}

function scoreLabel(score: number): string {
  return score > 0 ? `+${score}` : String(score)
}

function MacroRow({ row }: { row: IdeaScanMacroRow }) {
  const [open, setOpen] = useState(false)
  const changed = row.previous_score != null && row.previous_score !== row.score
  return (
    <li className="py-2.5">
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        className="flex w-full items-start gap-3 text-left"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={14} className="mt-1 shrink-0 text-subtle" /> : <ChevronRight size={14} className="mt-1 shrink-0 text-subtle" />}
        <span className="w-44 shrink-0 text-sm font-medium text-app max-sm:w-32">{row.sector}</span>
        <span className={cn("w-8 shrink-0 text-sm font-semibold tabular-nums", scoreClass(row.score))}>{scoreLabel(row.score)}</span>
        <span className="min-w-0 flex-1 text-sm text-muted">
          {row.reason}
          <span className="ml-2 text-xs text-subtle">{row.confidence} confidence</span>
          {changed && (
            <span className="ml-2 text-xs text-subtle">
              was {scoreLabel(row.previous_score ?? 0)}
            </span>
          )}
        </span>
      </button>
      {open && (
        <div className="ml-7 mt-2 space-y-1.5 text-xs text-muted">
          {changed && row.change_explanation && (
            <p>
              <span className="font-medium text-app">Why it changed: </span>
              {row.change_explanation}
            </p>
          )}
          <ul className="space-y-1">
            {row.evidence.map(item => (
              <li key={`${item.type}-${item.ref}-${item.detail}`}>
                {item.type === "search" ? (
                  <a href={item.ref} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 text-[hsl(var(--accent))] hover:underline">
                    <ExternalLink size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
                    <span>{item.detail || item.ref}</span>
                  </a>
                ) : (
                  <span>
                    <span className="font-mono text-[11px] text-subtle">{item.ref}</span> — {item.detail}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  )
}

export function MacroViewPanel({ view }: { view: IdeaScanMacroView | undefined }) {
  if (!view) return null
  return (
    <section className="theme-surface rounded-xl p-4" aria-labelledby="macro-view-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="macro-view-heading" className="text-sm font-semibold text-app">
          Macro view by sector
        </h2>
        {view.model && <span className="text-xs text-subtle">{view.model}</span>}
      </div>
      {view.status !== "ok" ? (
        <Notice tone="warning" className="mt-3">
          {view.error || "The macro view did not run this week."} Candidates are ranked on screens alone.
        </Notice>
      ) : (
        <>
          {view.summary && <p className="mt-2 text-sm text-muted">{view.summary}</p>}
          {view.rows.length === 0 ? (
            <p className="mt-3 text-sm text-muted">No sector rows had verifiable evidence this week.</p>
          ) : (
            <ul className="mt-2 divide-y divide-[hsl(var(--border))]">
              {view.rows.map(row => (
                <MacroRow key={row.sector} row={row} />
              ))}
            </ul>
          )}
          {view.dropped.length > 0 && (
            <p className="mt-2 text-xs text-subtle">
              Dropped: {view.dropped.map(d => `${d.sector} (${d.reason})`).join("; ")}
            </p>
          )}
          {view.sources.length > 0 && (
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer text-muted">Sources ({view.sources.length})</summary>
              <ul className="mt-2 space-y-1">
                {view.sources.map(source => (
                  <li key={source.url}>
                    <a href={source.url} target="_blank" rel="noreferrer" className="text-[hsl(var(--accent))] hover:underline">
                      {source.title || source.url}
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  )
}
