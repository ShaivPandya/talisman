import type { ToolCall } from "@/hooks/agentChatShared"

// ---------------------------------------------------------------------------
// Friendly tool labels
// ---------------------------------------------------------------------------

export const TOOL_LABELS: Record<string, string> = {
  get_thesis: "Thesis",
  get_thesis_evaluations: "Thesis Evaluations",
  get_liquidity: "Liquidity",
  get_market_breadth: "Market Breadth",
  get_vix_term_structure: "VIX Term Structure",
  get_positioning: "Positioning",
  get_economic_growth: "Economic Growth",
  get_labor_market: "Labor Market",
  get_sector_metrics: "Sector Metrics",
  get_portfolio: "Portfolio",
  get_yield_curve: "Yield Curve",
  get_sentiment: "Sentiment",
  get_central_banks: "Central Banks",
  get_industry_monitor: "Industry Monitor",
  get_signal_aggregator: "Signal Aggregator",
  query_ontology: "Ontology Query",
  search_web: "Web Search",
  search_knowledge_base: "Knowledge Base",
  get_dossier: "Position Dossier",
  get_catalysts: "Catalysts",
  propose_thesis_status_change: "Thesis Status Proposal",
  propose_action_item: "Action Item Proposal",
  propose_catalyst: "Catalyst Proposal",
  propose_catalyst_status_change: "Catalyst Status Proposal",
  propose_kill_condition: "Kill Condition Proposal",
  propose_kill_condition_status_change: "Kill Condition Status Proposal",
  propose_watch_trigger: "Watch Trigger Proposal",
  propose_portfolio_positions_update: "Portfolio Update Proposal",
  propose_hedge_positions_update: "Hedge Update Proposal",
  propose_thesis_content_update: "Thesis Content Proposal",
}

const PROPOSAL_TOOL_PREFIXES = ["propose_", "create_", "update_", "complete_", "dismiss_", "cancel_", "fire_"]

export function toolEffectScope(name: string): "read_only" | "internal_state" {
  return PROPOSAL_TOOL_PREFIXES.some(prefix => name.startsWith(prefix)) ? "internal_state" : "read_only"
}

export function toolStateLabel(status: ToolCall["status"]): string {
  switch (status) {
    case "pending":
      return "Pending"
    case "running":
      return "Running"
    case "ok":
      return "Complete"
    case "blocked":
      return "Blocked"
    case "timeout":
      return "Timed out"
    case "retrying":
      return "Retrying"
    case "partial":
      return "Partial"
    case "cancelled":
      return "Cancelled"
    case "error":
    default:
      return "Failed"
  }
}

export function humanizeToolName(name: string): string {
  return name
    .replace(/^propose_/, "")
    .split("_")
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

export function formatDuration(ms: number): string {
  return ms < 1000 ? `${Math.max(1, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/** A date reads as a date, a timestamp as a date and time. Anything else is shown as sent. */
export function formatAsOf(asOf: string): string {
  const date = new Date(DATE_ONLY.test(asOf) ? `${asOf}T12:00:00` : asOf)
  if (Number.isNaN(date.getTime())) return asOf
  return DATE_ONLY.test(asOf)
    ? date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
}
