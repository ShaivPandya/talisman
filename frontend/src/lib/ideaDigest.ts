import type { IdeaScanCandidate } from "@/lib/api"

export function formatPct(value: number | null | undefined, digits = 1): string {
  return value == null ? "n/a" : `${value.toFixed(digits)}%`
}

export function formatSigned(value: number | null | undefined, digits = 0): string {
  if (value == null) return "n/a"
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`
}

/** The card as a chat draft, so "Discuss with Stan" starts from what the digest shows. */
export function stanDraftForCard(card: IdeaScanCandidate, week: string): string {
  const review = card.review
  const lines = [
    `Let's discuss ${card.ticker} (${card.company}), a ${card.direction} name from the weekly idea scan (${week}). It's a research lead, not a decision.`,
    "",
    `Presets: ${card.presets.map(p => p.name).join(", ")}`,
    `Signals: ${card.signals.map(s => s.label).join("; ") || "none"}`,
  ]
  if (card.macro_fit) {
    lines.push(`Macro: ${card.macro_fit.sector} ${formatSigned(card.macro_fit.score)} (${card.macro_fit.confidence}) — ${card.macro_fit.reason}`)
  }
  if (review?.why_now) lines.push(`Why now: ${review.why_now}`)
  if (review?.variant_view) lines.push(`Variant view: ${review.variant_view}`)
  for (const headline of review?.headlines ?? []) lines.push(`Headline: ${headline.title} (${headline.url})`)
  if (review?.missing_inputs?.length) lines.push(`Still missing: ${review.missing_inputs.join("; ")}`)
  lines.push("", "What would you check first, and what would change your mind?")
  return lines.join("\n")
}

/** The preset filter's starting thresholds; the backend's LiquidityCoverageFilter defaults. */
export const DEFAULT_LIQUIDITY_COVERAGE = { min_dollar_volume_industry_pct: 0.75, require_above_median_coverage: true }
