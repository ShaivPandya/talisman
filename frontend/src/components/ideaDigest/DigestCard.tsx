import { Link } from "react-router-dom"
import { ArrowDownRight, ArrowUpRight, ExternalLink, Lightbulb, MessageCircle, X } from "lucide-react"

import { StatusBadge, type StatusTone } from "@/components/shared/StatusBadge"
import type { IdeaScanCandidate } from "@/lib/api"
import { formatPct, formatSigned, momentumLines } from "@/lib/ideaDigest"
import { cn } from "@/lib/utils"

const REVIEW_STATUS: Record<IdeaScanCandidate["review_status"], { label: string; tone: StatusTone }> = {
  reviewed: { label: "Reviewed", tone: "success" },
  review_failed: { label: "Review failed", tone: "error" },
  not_reviewed_budget: { label: "Not reviewed (budget)", tone: "warning" },
  not_reviewed_cap: { label: "Not reviewed (review cap)", tone: "neutral" },
}

const NEXT_ACTION_TONE: Record<string, StatusTone> = { research: "info", watch: "neutral", avoid: "warning" }

function percentile(value: number | null | undefined): string {
  return value == null ? "n/a" : `${Math.round(value * 100)}`
}

function metricChips(card: IdeaScanCandidate): string[] {
  const m = card.metrics ?? {}
  const chips = [
    m.market_cap != null ? `Mkt cap $${(m.market_cap / 1e9).toFixed(1)}B` : null,
    m.price_to_book != null ? `P/B ${m.price_to_book.toFixed(2)}` : null,
    m.rev_yoy_avg != null ? `Rev YoY ${formatPct(m.rev_yoy_avg)}` : null,
    m.eps_yoy_avg != null ? `EPS YoY ${formatPct(m.eps_yoy_avg)}` : null,
    m.return_52w != null ? `52w ${formatPct(m.return_52w)}` : null,
    m.return_3m != null ? `3m ${formatPct(m.return_3m)}` : null,
    m.enterpriseToEbitda != null ? `EV/EBITDA ${m.enterpriseToEbitda.toFixed(1)}` : null,
  ]
  return chips.filter((chip): chip is string => chip != null)
}

interface DigestCardProps {
  card: IdeaScanCandidate
  busy: boolean
  onPromote: () => void
  onDiscuss: () => void
  onDismiss: () => void
}

export function DigestCard({ card, busy, onPromote, onDiscuss, onDismiss }: DigestCardProps) {
  const review = card.review?.status === "ok" ? card.review : null
  const status = REVIEW_STATUS[card.review_status] ?? REVIEW_STATUS.not_reviewed_cap
  const fit = card.macro_fit
  const short = card.direction === "short"
  const promoted = card.card_state === "promoted"

  return (
    <article className="rounded-xl border border-app/70 bg-card p-4" data-testid={`digest-card-${card.direction}-${card.ticker}`}>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <Link to={`/explore/${encodeURIComponent(card.ticker)}`} className="text-base font-semibold text-app hover:underline">
              {card.ticker}
            </Link>
            <span className="text-sm text-muted">{card.company}</span>
          </div>
          <p className="mt-0.5 text-xs text-subtle">
            {card.sector}
            {card.industry ? ` · ${card.industry}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          {review?.next_action && (
            <StatusBadge tone={NEXT_ACTION_TONE[review.next_action] ?? "neutral"}>Next: {review.next_action}</StatusBadge>
          )}
          {promoted && <StatusBadge tone="success">Promoted</StatusBadge>}
        </div>
      </header>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>
          Agreement <span className="font-semibold text-app tabular-nums">{card.final_score.toFixed(2)}</span>
          {card.macro_boost > 0 && <span className="text-positive"> (+{card.macro_boost.toFixed(2)} macro)</span>}
        </span>
        <span>Composite pct {percentile(card.factor_ranks?.composite_pct)}</span>
        <span>Quality {percentile(card.factor_ranks?.quality_pct)}</span>
        {!card.momentum && <span>Legacy price mom. percentile {percentile(card.factor_ranks?.price_momentum_pct)}</span>}
        {card.momentum && <span>Momentum credit {card.momentum.credit * 100}%</span>}
      </div>

      {card.momentum && (
        <div className="mt-3 space-y-1 text-xs text-muted" aria-label="Momentum signals">
          {momentumLines(card.momentum, card.direction).map(line => <p key={line}>{line}</p>)}
          <p className="text-subtle">{card.momentum.lookback_sessions} trading sessions · {card.momentum.start_date} – {card.momentum.end_date}</p>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {card.presets.map(preset => (
          <span key={preset.id} className="rounded-full bg-card-muted px-2 py-0.5 text-xs font-medium text-app">
            {preset.name}
          </span>
        ))}
      </div>
      <ul className="mt-2 space-y-0.5 text-xs text-muted">
        {card.signals.map(signal => (
          <li key={`${signal.preset_id}-${signal.label}`}>· {signal.label}</li>
        ))}
      </ul>
      {metricChips(card).length > 0 && <p className="mt-2 text-xs text-subtle">{metricChips(card).join(" · ")}</p>}

      {fit && (
        <p className="mt-3 flex items-start gap-1.5 text-sm">
          {fit.fit === "tailwind" ? (
            <ArrowUpRight size={15} className="mt-0.5 shrink-0 text-positive" aria-hidden="true" />
          ) : fit.fit === "headwind" ? (
            <ArrowDownRight size={15} className="mt-0.5 shrink-0 text-negative" aria-hidden="true" />
          ) : (
            <span className="mt-0.5 w-[15px] shrink-0 text-center text-subtle">·</span>
          )}
          <span>
            <span className="font-medium text-app">
              {fit.fit === "tailwind"
                ? `Macro supports this ${card.direction}`
                : fit.fit === "headwind"
                  ? `Macro works against this ${card.direction}`
                  : "Macro neutral"}{" "}
              ({fit.sector} {formatSigned(fit.score)}, {fit.confidence})
            </span>
            <span className="text-muted"> — {fit.reason}</span>
          </span>
        </p>
      )}

      {short && (
        <p className="mt-2 text-xs text-muted">
          Short interest {formatPct(card.short_data?.short_percent_of_float != null ? card.short_data.short_percent_of_float * 100 : null)} of float
          {card.short_data?.short_ratio != null ? ` · ${card.short_data.short_ratio} days to cover` : ""}
          {" · "}
          {card.days_to_earnings != null ? `${card.days_to_earnings} days to earnings` : "next earnings date unknown"}
          {" · "}borrow data not available
        </p>
      )}

      {review && (
        <div className="mt-3 space-y-2 border-t border-app/60 pt-3 text-sm">
          {review.trigger && (
            <p>
              <span className="font-medium text-app">Trigger: </span>
              <span className="text-muted">{review.trigger}</span>
            </p>
          )}
          {review.why_now && (
            <p>
              <span className="font-medium text-app">Why now: </span>
              <span className="text-muted">{review.why_now}</span>
            </p>
          )}
          {review.macro_fit && <p className="text-muted">{review.macro_fit}</p>}
          {(review.headlines?.length ?? 0) > 0 && (
            <ul className="space-y-1">
              {review.headlines?.map(headline => (
                <li key={headline.url}>
                  <a href={headline.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 text-[hsl(var(--accent))] hover:underline">
                    <ExternalLink size={12} className="mt-1 shrink-0" aria-hidden="true" />
                    <span>{headline.title}</span>
                  </a>
                  {headline.date && <span className="ml-1 text-xs text-subtle">{headline.date}</span>}
                </li>
              ))}
            </ul>
          )}
          {(review.missing_inputs?.length ?? 0) > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-subtle">Still missing</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted">
                {review.missing_inputs?.map(item => <li key={item}>{item}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
      {card.review?.status === "failed" && <p className="mt-3 text-xs text-negative">{card.review.error}</p>}

      <footer className="mt-4 flex flex-wrap gap-2">
        {promoted && card.idea_id ? (
          <Link to={`/ideas/${card.idea_id}`} className="theme-button-base theme-button-secondary px-3 text-sm">
            <Lightbulb size={14} aria-hidden="true" /> Open idea
          </Link>
        ) : (
          <button type="button" className="theme-button-base theme-button-primary px-3 text-sm" onClick={onPromote} disabled={busy}>
            <Lightbulb size={14} aria-hidden="true" /> Promote to Idea
          </button>
        )}
        <button type="button" className="theme-button-base theme-button-secondary px-3 text-sm" onClick={onDiscuss}>
          <MessageCircle size={14} aria-hidden="true" /> Discuss with Stan
        </button>
        <button
          type="button"
          className={cn("theme-button-base theme-button-ghost px-3 text-sm", promoted && "hidden")}
          onClick={onDismiss}
          disabled={busy}
        >
          <X size={14} aria-hidden="true" /> Dismiss
        </button>
      </footer>
    </article>
  )
}
