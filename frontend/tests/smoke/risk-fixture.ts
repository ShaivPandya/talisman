import type { PortfolioRiskDashboard, RiskDashboardPosition } from "../../src/lib/portfolioRisk"

function position(overrides: Partial<RiskDashboardPosition>): RiskDashboardPosition {
  return {
    position_id: "primary-aapl", ticker: "AAPL", underlying_ticker: "AAPL", price_symbol: "AAPL",
    asset: "equity", sector: "Technology", group_name: null, role: "position", instrument_type: "security",
    direction: "long", quantity: 100, contract_multiplier: 1, currency: "USD", price: 100,
    price_as_of: "2026-10-14", fx_rate_to_usd: 1, fx_as_of: "2026-10-14", exposure_multiplier: 1,
    signed_notional: 10_000, gross_notional: 10_000, weight_pct: 10, premium_usd: null,
    option_type: null, option_strike: null, option_expiration: null,
    beta_eligible: true, beta_status: "eligible", beta_spy: 1.4, beta_iwm: 1.2,
    beta_spy_observations: 400, beta_iwm_observations: 400, beta_spy_as_of: "2026-10-14", beta_iwm_as_of: "2026-10-14",
    beta_contribution_spy: 0.14, beta_contribution_iwm: 0.12,
    risk_score: 0.4, risk_level: "medium", drivers: [{ detail: "Sector stress" }], issues: [], ...overrides,
  }
}

const positions = [
  position({}),
  position({ position_id: "hedge-iwm", ticker: "IWM", underlying_ticker: "IWM", price_symbol: "IWM", role: "hedge", sector: "Equity index", group_name: "Hedging", direction: "short", quantity: 50, signed_notional: -5000, gross_notional: 5000, weight_pct: -5, beta_spy: 1.2, beta_iwm: 1, beta_contribution_spy: -0.06, beta_contribution_iwm: -0.05, risk_score: null, risk_level: null, drivers: [] }),
  position({ position_id: "primary-gld", ticker: "GLD", underlying_ticker: "GLD", price_symbol: "GLD", asset: "commodity", sector: null, group_name: "Macro", quantity: 20, price: 200, signed_notional: 4000, gross_notional: 4000, weight_pct: 4, beta_eligible: false, beta_status: "unsupported_asset", beta_spy: null, beta_iwm: null, beta_contribution_spy: null, beta_contribution_iwm: null, beta_spy_observations: 0, beta_iwm_observations: 0, risk_score: 0.2, risk_level: "low" }),
  position({ position_id: "option-aapl", instrument_type: "option", price_symbol: "AAPL261218C00100000", quantity: 1, price: 2, contract_multiplier: 100, signed_notional: null, gross_notional: null, weight_pct: null, premium_usd: 200, option_type: "call", option_strike: 100, option_expiration: "2026-12-18", beta_eligible: false, beta_status: "excluded_option", beta_spy: null, beta_iwm: null, beta_contribution_spy: null, beta_contribution_iwm: null, beta_spy_observations: 0, beta_iwm_observations: 0 }),
]

function buckets(includeHedges: boolean, dimension: "underlying" | "sector" | "asset" | "group") {
  const gross = includeHedges ? 19_000 : 14_000
  const values: Array<[string, number, number, number]> = dimension === "asset"
    ? [["equity", includeHedges ? 15_000 : 10_000, includeHedges ? 5000 : 10_000, includeHedges ? 2 : 1], ["commodity", 4000, 4000, 1]]
    : [[dimension === "underlying" ? "AAPL" : dimension === "sector" ? "Technology" : "Ungrouped", 10_000, 10_000, 1],
      [dimension === "underlying" ? "GLD" : dimension === "sector" ? "Unclassified" : "Macro", 4000, 4000, 1],
      ...(includeHedges ? [[dimension === "underlying" ? "IWM" : dimension === "sector" ? "Equity index" : "Hedging", 5000, -5000, 1] as [string, number, number, number]] : [])]
  return values.map(([name, gross_usd, net_usd, position_count]) => ({ name, gross_usd, net_usd, position_count, gross_share_pct: gross_usd / gross * 100 }))
}

function view(includeHedges: boolean): PortfolioRiskDashboard["views"]["all_holdings"] {
  return {
    summary: { long_usd: 14_000, long_pct: 14, short_usd: includeHedges ? 5000 : 0, short_pct: includeHedges ? 5 : 0, gross_usd: includeHedges ? 19_000 : 14_000, gross_pct: includeHedges ? 19 : 14, net_usd: includeHedges ? 9000 : 14_000, net_pct: includeHedges ? 9 : 14 },
    breakdowns: { underlying: buckets(includeHedges, "underlying"), sector: buckets(includeHedges, "sector"), asset: buckets(includeHedges, "asset"), group: buckets(includeHedges, "group") },
    betas: {
      SPY: { primary: 0.14, hedges: includeHedges ? -0.06 : 0, combined: includeHedges ? 0.08 : 0.14, covered_count: includeHedges ? 2 : 1, eligible_count: includeHedges ? 2 : 1, covered_gross_pct: includeHedges ? 15_000 / 19_000 * 100 : 10_000 / 14_000 * 100 },
      IWM: { primary: 0.12, hedges: includeHedges ? -0.05 : 0, combined: includeHedges ? 0.07 : 0.12, covered_count: includeHedges ? 2 : 1, eligible_count: includeHedges ? 2 : 1, covered_gross_pct: includeHedges ? 15_000 / 19_000 * 100 : 10_000 / 14_000 * 100 },
    },
    coverage: { position_count: includeHedges ? 4 : 3, linear_count: includeHedges ? 3 : 2, valued_linear_count: includeHedges ? 3 : 2, option_count: 1, priced_option_count: 1, classification_gap_count: 0 },
  }
}

export const riskDashboardFixture: PortfolioRiskDashboard = {
  version: 1, computed_at: "2026-10-14T21:00:00Z", as_of: "2026-10-14", base_currency: "USD", book_size: 100_000,
  book_is_default: true, holdings_fingerprint: "synthetic-fixture", quality: "ok", positions,
  views: { all_holdings: view(true), primary_positions: view(false) },
  stress: { as_of: "2026-10-14", position_count: 3, average_risk_score: 0.3, max_risk_score: 0.4, risk_buckets: { high: 0, medium: 1, low: 2 }, quality: "ok", source_status: {} },
  source_status: { prices: { provider: "yfinance", basis: "daily_close", as_of: "2026-10-14" }, portfolio: { provider: "ontology", as_of: "2026-10-14" }, stress: { quality: "ok", as_of: "2026-10-14" } },
  beta_method: { method: "ewma_cov_var", lookback_days: 730, halflife_observations: 63, minimum_observations: 60, shrink_to_one: 0.2 },
  freshness: { stale: false }, snapshot_meta: {},
}
