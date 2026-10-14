import type { PositionRiskSourceStatus } from "@/lib/api"

export interface RiskDashboardPosition {
  position_id: string
  ticker: string
  underlying_ticker: string
  price_symbol: string
  asset: string | null
  sector: string | null
  group_name: string | null
  role: "position" | "hedge"
  instrument_type: string
  direction: string
  quantity: number | null
  contract_multiplier: number | null
  currency: string | null
  price: number | null
  price_as_of: string | null
  fx_rate_to_usd: number | null
  fx_as_of: string | null
  exposure_multiplier: number
  signed_notional: number | null
  gross_notional: number | null
  weight_pct: number | null
  premium_usd: number | null
  option_type: string | null
  option_strike: number | null
  option_expiration: string | null
  beta_eligible: boolean
  beta_status: string
  beta_spy: number | null
  beta_iwm: number | null
  beta_spy_observations: number
  beta_iwm_observations: number
  beta_spy_as_of: string | null
  beta_iwm_as_of: string | null
  beta_contribution_spy: number | null
  beta_contribution_iwm: number | null
  risk_score: number | null
  risk_level: string | null
  drivers: Array<Record<string, unknown>>
  issues: string[]
}

export interface RiskExposureBucket {
  name: string
  gross_usd: number
  net_usd: number
  gross_share_pct: number | null
  position_count: number
}

export interface RiskBetaAggregate {
  primary: number | null
  hedges: number | null
  combined: number | null
  covered_count: number
  eligible_count: number
  covered_gross_pct: number | null
}

export interface RiskDashboardView {
  summary: {
    long_usd: number | null
    short_usd: number | null
    gross_usd: number | null
    net_usd: number | null
    long_pct: number | null
    short_pct: number | null
    gross_pct: number | null
    net_pct: number | null
  }
  breakdowns: Record<"underlying" | "sector" | "asset" | "group", RiskExposureBucket[]>
  betas: Record<"SPY" | "IWM", RiskBetaAggregate>
  coverage: {
    position_count: number
    linear_count: number
    valued_linear_count: number
    option_count: number
    priced_option_count: number
    classification_gap_count: number
  }
}

export interface PortfolioRiskDashboard {
  version: number
  computed_at: string
  as_of: string | null
  base_currency: "USD"
  book_size: number
  book_is_default: boolean
  holdings_fingerprint: string
  quality: "ok" | "degraded"
  positions: RiskDashboardPosition[]
  views: { all_holdings: RiskDashboardView; primary_positions: RiskDashboardView }
  stress: {
    as_of?: string | null
    computed_at?: string
    position_count?: number
    average_risk_score?: number | null
    max_risk_score?: number | null
    quality?: string
    risk_buckets?: { high?: number; medium?: number; low?: number }
    source_status?: Record<string, PositionRiskSourceStatus>
  } | null
  source_status: Record<string, { provider?: string; basis?: string; as_of?: string | null; error?: string | null; quality?: string }>
  beta_method: {
    method: string
    lookback_days: number
    halflife_observations: number
    minimum_observations: number
    shrink_to_one: number
  }
  freshness: {
    stale?: boolean
    holdings_changed?: boolean
    book_changed?: boolean
    market?: { expected_as_of_date?: string; fresh?: boolean; reason?: string | null }
    refresh_error?: string | null
  }
  snapshot_meta: { refresh_status?: string; error?: string | null; as_of?: string | null }
}

export interface RiskDashboardJob {
  job_id: string
  status: "queued" | "running" | "done" | "error" | "cancelled"
  result?: PortfolioRiskDashboard | null
  error?: string | null
}

export function riskMoney(value: number | null | undefined, decimals = 0): string {
  return value == null || !Number.isFinite(value) ? "Unavailable" : new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: decimals, minimumFractionDigits: decimals,
  }).format(value)
}

export function riskPercent(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "Unavailable" : `${value.toFixed(1)}%`
}

export function riskBeta(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "Unavailable" : `${value.toFixed(3)}×`
}

export function riskDate(value: string | null | undefined): string {
  if (!value) return "Unavailable"
  const date = new Date(value.length === 10 ? `${value}T12:00:00Z` : value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}
