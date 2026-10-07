import { apiGet, apiPost } from "./api"

export interface MultipleBand {
  low: number
  mid: number
  high: number
  n_quarters: number
  window_start: string
  window_end: string
  source: string
  source_label: string
  method_label: string
  periods: string[]
}
export interface ValuationBridge {
  status: "ok" | "unsupported"
  reason: string | null
  run_id: string
  cutoff_ts: string
  metric: string
  n_paths: number
  n_quarters: number
  assumptions: {
    name: string
    value: number | null
    unit: string
    source: string
  }[]
  forward_eps: {
    mean: number
    p10: number
    p50: number
    p90: number
    n_paths: number
  } | null
  multiple_band: MultipleBand | null
  grid:
    | {
        eps_quantile: string
        multiple_role: string
        multiple: number
        value_per_share: number
        equity_usd_millions: number
      }[]
    | null
  earnings_driven: {
    multiple: number
    value_per_share: Record<string, number>
    equity_usd_millions: Record<string, number>
    spread_per_share: number
    spread_equity_usd_millions: number
  } | null
  multiple_driven: {
    forward_eps: number
    value_per_share: Record<string, number>
    equity_usd_millions: Record<string, number>
    spread_per_share: number
    spread_equity_usd_millions: number
  } | null
  outer_envelope: {
    low_per_share: number
    high_per_share: number
    low_equity_usd_millions: number
    high_equity_usd_millions: number
    label: string
  } | null
}
export interface ValuationActions {
  status: "ok" | "unsupported"
  reason: string | null
  label: string
  run_id: string
  bridge: ValuationBridge
  reference_price: {
    price: number
    period_label: string | null
    acceptance_utc: string | null
    source: string
    source_label: string
    price_source_id: string | null
    price_quote: string | null
  } | null
  position: { shares: number; direction: string; source: string }
  rule: {
    version: number
    label: string
    rule_hash: string
    costs: Record<string, number>
    thresholds: Record<string, number>
    sizing: Record<string, number>
    holding_period_trading_days: number
    demo_position: { shares: number; direction: string }
  }
  decision: string
  margin: number | null
  value_per_share: number | null
  actions: {
    action: string
    label: string
    is_no_action: boolean
    selected: boolean
    target_shares: number | null
    costs: {
      traded_notional: number
      transaction_cost: number
      slippage_cost: number
      market_impact_cost: number
      funding_cost: number
      total_cost: number
      total_cost_bps: number
    } | null
    gaps:
      | {
          name: string
          value_per_share: number
          net_gap: number
          label: string
        }[]
      | null
  }[]
}
export interface ValuationMultiples {
  status: "ok" | "unsupported"
  reason: string | null
  cutoff_ts: string | null
  source_basis: string
  method_label: string
  band: MultipleBand | null
  rows: {
    period_label: string
    avg_purchase_price: number
    ttm_eps: number
    trailing_pe: number
    price_url: string
    price_acceptance_utc: string
    price_quote: string
  }[]
}
export const getValuationActions = (id: string) =>
  apiPost<ValuationActions>("/valuation/actions", { run_id: id })
export const getValuationMultiples = (cutoff: string) =>
  apiGet<ValuationMultiples>(
    `/valuation/multiples?cutoff_ts=${encodeURIComponent(cutoff)}`,
  )
