export interface AgentMessageCost {
  estimated_usd: number | null
  currency: "USD"
  complete: boolean
  model_calls: number
  priced_model_calls: number
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
}

/** Cost is supplied and saved by the server; old messages have no cost metadata. */
export function normalizeMessageCost(value: unknown): AgentMessageCost | undefined {
  if (!value || typeof value !== "object") return undefined
  const cost = value as Record<string, unknown>
  if (cost.currency !== "USD" || typeof cost.complete !== "boolean") return undefined
  if (cost.estimated_usd !== null && (
    typeof cost.estimated_usd !== "number" || !Number.isFinite(cost.estimated_usd) || cost.estimated_usd < 0
  )) return undefined
  const counts = ["model_calls", "priced_model_calls", "input_tokens", "output_tokens", "cache_read_input_tokens"]
  if (counts.some(key => typeof cost[key] !== "number" || !Number.isSafeInteger(cost[key]) || (cost[key] as number) < 0)) {
    return undefined
  }
  return cost as unknown as AgentMessageCost
}

export function messageCostLabel(cost: AgentMessageCost): string {
  if (cost.estimated_usd === null) return "Cost unavailable"
  const amount = cost.estimated_usd
  const formatted = amount > 0 && amount < 0.0001
    ? "<$0.0001"
    : `$${amount.toFixed(amount > 0 && amount < 0.01 ? 4 : 2)}`
  return `Est. ${formatted}${cost.complete ? "" : "+"}`
}

export function messageCostDetail(cost: AgentMessageCost): string {
  const details = cost.estimated_usd === null
    ? "Cost unavailable: model pricing or token usage was not reported."
    : cost.complete
      ? "Estimated model cost for this reply, including its tool-call rounds."
      : `Partial estimate: pricing and usage available for ${cost.priced_model_calls} of ${cost.model_calls} model calls.`
  return [
    details,
    `${cost.model_calls} model calls · ${cost.input_tokens.toLocaleString()} input tokens · ${cost.output_tokens.toLocaleString()} output tokens`,
    `${cost.cache_read_input_tokens.toLocaleString()} cached input tokens`,
    "USD at standard API rates. Excludes other tool fees and background jobs.",
  ].join("\n")
}
