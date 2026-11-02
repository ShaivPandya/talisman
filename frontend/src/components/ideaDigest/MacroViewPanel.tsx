import { useState } from "react"
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react"

import { Notice } from "@/components/shared/Notice"
import type { IdeaScanEvidence, IdeaScanMacroApproach, IdeaScanMacroRow, IdeaScanMacroView } from "@/lib/api"
import { cn } from "@/lib/utils"

function scoreClass(score: number): string {
  if (score >= 1) return "text-positive"
  if (score <= -1) return "text-negative"
  return "text-muted"
}

function scoreLabel(score: number): string {
  return score > 0 ? `+${score}` : String(score)
}

function EvidenceList({ items }: { items: IdeaScanEvidence[] }) {
  return (
    <ul className="space-y-1">
      {items.map(item => (
        <li key={`${item.type}-${item.ref}-${item.detail}`}>
          {item.type === "search" ? (
            <a href={item.ref} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 text-[hsl(var(--accent))] hover:underline">
              <ExternalLink size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>{item.detail || item.ref}</span>
            </a>
          ) : item.type === "digest" ? (
            <span>
              <span className="text-subtle">News digest{item.date ? ` ${item.date}` : ""}: </span>
              <span className="text-app">{item.headline || item.ref}</span>
              {item.detail && <> — {item.detail}</>}
            </span>
          ) : (
            <span>
              <span className="font-mono text-[11px] text-subtle">{item.ref}</span> — {item.detail}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

const APPROACH_LINKS = {
  industry_monitor: "/industry-monitor",
  market_prices: "/economic-growth",
  economic_indicators: "/economic-growth",
  news: "/portfolio-news",
}

function ApproachPanel({ approach, index }: { approach: IdeaScanMacroApproach; index: number }) {
  return (
    <section className="rounded-lg border border-app p-3" aria-labelledby={`macro-approach-${approach.key}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`macro-approach-${approach.key}`} className="text-sm font-semibold text-app">
          {index + 1}. {approach.title}
        </h3>
        <span className="text-xs text-subtle">{approach.status === "unavailable" ? "Evidence unavailable" : `${approach.confidence} confidence`}</span>
      </div>
      <p className="mt-2 text-sm text-muted"><span className="font-medium text-app">What we see: </span>{approach.signal}</p>
      {approach.interpretation && <p className="mt-2 text-sm text-muted"><span className="font-medium text-app">What it suggests: </span>{approach.interpretation}</p>}
      {approach.caveats && <p className="mt-2 text-xs text-muted"><span className="font-medium text-app">Limitations: </span>{approach.caveats}</p>}
      {approach.sources.map(source => (
        <p key={source.key} className="mt-1 text-xs text-subtle">
          As of {source.as_of || "unknown"}{source.stale ? " · stale or incomplete" : ""}{source.refreshed ? " · refresh completed" : ""}
        </p>
      ))}
      <div className="mt-2 flex flex-wrap items-start gap-3 text-xs">
        <a href={APPROACH_LINKS[approach.key]} className="text-[hsl(var(--accent))] hover:underline">Open source dashboard</a>
        {approach.evidence.length > 0 && (
          <details className="min-w-0 flex-1 text-muted">
            <summary className="cursor-pointer">Evidence ({approach.evidence.length})</summary>
            <div className="mt-2"><EvidenceList items={approach.evidence} /></div>
          </details>
        )}
      </div>
    </section>
  )
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
          <EvidenceList items={row.evidence} />
        </div>
      )}
    </li>
  )
}

function newsLine(news: IdeaScanMacroView["news"]): string {
  if (!news) return "No uploaded news digests used; web news may be included in cited sources."
  const dates = news.digests.map(d => d.generated_date).filter((d): d is string => Boolean(d)).sort()
  if (news.stories === 0 || dates.length === 0) return "No news digests in the lookback window; web news may be included in cited sources."
  const span = dates[0] === dates[dates.length - 1] ? dates[0] : `${dates[0]} to ${dates[dates.length - 1]}`
  const count = news.digests.length
  return `Read with ${news.stories} stories from ${count} news digest${count === 1 ? "" : "s"} (${span}).`
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
          <p className="mt-1 text-xs text-subtle">{newsLine(view.news)}</p>
          {view.approaches?.length ? (
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {view.approaches.map((approach, index) => <ApproachPanel key={approach.key} approach={approach} index={index} />)}
            </div>
          ) : (
            <p className="mt-3 text-xs text-subtle">This saved digest predates the four-source breakdown. Run a new scan to generate it.</p>
          )}
          {view.synthesis ? (
            <section className="mt-4 rounded-lg border border-app p-3" aria-labelledby="macro-synthesis-heading">
              <h3 id="macro-synthesis-heading" className="text-sm font-semibold text-app">Combined macro outlook</h3>
              <p className="mt-1 text-xs text-subtle">{view.synthesis.horizon} · {view.synthesis.confidence} confidence</p>
              <p className="mt-2 text-sm text-muted">{view.synthesis.outlook}</p>
              <p className="mt-2 text-sm text-muted"><span className="font-medium text-app">Where signals agree: </span>{view.synthesis.agreements}</p>
              <p className="mt-2 text-sm text-muted"><span className="font-medium text-app">Where signals conflict: </span>{view.synthesis.conflicts}</p>
              {view.synthesis.watchpoints.length > 0 && (
                <div className="mt-3 text-sm text-muted">
                  <h4 className="font-medium text-app">What would change the view</h4>
                  <ul className="mt-1 list-disc space-y-1 pl-5">{view.synthesis.watchpoints.map(point => <li key={point}>{point}</li>)}</ul>
                </div>
              )}
              <details className="mt-3 text-xs text-muted">
                <summary className="cursor-pointer">Outlook evidence</summary>
                <div className="mt-2"><EvidenceList items={view.synthesis.evidence} /></div>
              </details>
            </section>
          ) : Boolean(view.approaches?.length) && (
            <p className="mt-3 text-sm text-muted">A consolidated outlook with verifiable evidence was unavailable for this run.</p>
          )}
          <h3 className="mt-4 text-sm font-semibold text-app">Sector implications</h3>
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
