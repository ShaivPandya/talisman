import type { AgentWorkflow, PortfolioPosition, ThesisMeta } from "@/lib/api"

export interface ComposerTrigger {
  kind: "workflow" | "mention" | "ticker"
  start: number
  end: number
  query: string
}

export interface ComposerSuggestion {
  id: string
  label: string
  description: string
  insertion: string
  workflow?: AgentWorkflow
}

export function composerTrigger(input: string, start: number, end: number): ComposerTrigger | null {
  if (start !== end) return null
  const before = input.slice(0, start)
  const slash = before.match(/^\s*\/([^:@\n]*)$/)
  if (slash) return { kind: "workflow", start: before.indexOf("/"), end, query: slash[1] }
  const tokenEnd = end + (input.slice(end).match(/^[A-Za-z0-9._=-]*/)?.[0].length ?? 0)
  const ticker = before.match(/^\s*\/workflow:[A-Za-z0-9_]+:([A-Za-z0-9._=-]*)$/)
  if (ticker) return { kind: "ticker", start: before.lastIndexOf(":") + 1, end: tokenEnd, query: ticker[1] }
  // A mention starts at a word boundary, so typing an email does not open the menu.
  const mention = before.match(/(?:^|\s)@([A-Za-z0-9._=-]*)$/)
  return mention ? { kind: "mention", start: end - mention[1].length - 1, end: tokenEnd, query: mention[1] } : null
}

export function mentionSuggestions(
  positions: PortfolioPosition[],
  theses: ThesisMeta[],
  screenTicker?: string,
): ComposerSuggestion[] {
  const tickers = new Set<string>()
  if (screenTicker) tickers.add(screenTicker.toUpperCase())
  for (const position of positions) tickers.add(position.ticker.toUpperCase())
  for (const thesis of theses) tickers.add(thesis.ticker.toUpperCase())
  const suggestions: ComposerSuggestion[] = [...tickers].map(ticker => ({
    id: `ticker:${ticker}`, label: ticker, insertion: ticker,
    description: ticker === screenTicker?.toUpperCase() ? "Ticker · current page" : "Ticker",
  }))
  const positionTickers = new Set<string>()
  for (const position of positions) {
    const ticker = position.ticker.toUpperCase()
    if (positionTickers.has(ticker)) continue
    positionTickers.add(ticker)
    suggestions.push({
      id: `position:${ticker}`, label: `${ticker} position`, insertion: `${ticker} position`,
      description: `${position.direction} · ${position.asset}`,
    })
  }
  for (const thesis of theses) {
    if (thesis.status === "missing") continue
    const ticker = thesis.ticker.toUpperCase()
    suggestions.push({
      id: `thesis:${ticker}`, label: `${ticker} thesis`, insertion: `${ticker} thesis`,
      description: `Investment thesis · ${thesis.status.replaceAll("_", " ")}`,
    })
  }
  return suggestions
}

export function filterComposerSuggestions(
  trigger: ComposerTrigger,
  workflows: AgentWorkflow[],
  mentions: ComposerSuggestion[],
): ComposerSuggestion[] {
  const query = trigger.query.toLowerCase().replaceAll("_", " ").trim()
  const candidates = trigger.kind === "workflow"
    ? workflows.map(workflow => ({
        id: workflow.name, label: workflow.label, description: workflow.description,
        insertion: `/workflow:${workflow.name}${workflow.requiresTicker ? ":" : ""}`, workflow,
      }))
    : mentions.filter(mention => trigger.kind !== "ticker" || mention.id.startsWith("ticker:"))
  const matches = candidates.filter(candidate =>
    `${candidate.label} ${candidate.id.replaceAll("_", " ")}`.toLowerCase().includes(query),
  )
  if (trigger.kind !== "workflow" && /^[A-Za-z0-9][A-Za-z0-9._=-]*$/.test(trigger.query)) {
    const ticker = trigger.query.toUpperCase()
    if (!mentions.some(mention => mention.id === `ticker:${ticker}`)) {
      matches.push({ id: `manual:${ticker}`, label: ticker, description: "Use ticker", insertion: ticker })
    }
  }
  return matches
}
