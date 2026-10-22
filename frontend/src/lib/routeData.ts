import type { QueryKey } from "@tanstack/react-query"
import {
  fetchAlternativeDataCatalog, fetchBondDashboard, fetchCentralBanks, fetchCommodities,
  fetchCommoditiesCurve, fetchCommodityResearch, fetchCountryDashboard, fetchDossier,
  fetchEconomicGrowth, fetchFinancialPolicyMatrixSettings, fetchFxDashboard, fetchFxModelPairs,
  fetchHedgePositions, fetchHedgingToolPrefill, fetchHousing, fetchIdea, fetchIdeas,
  fetchIndexDashboard, fetchIndustryMonitor, fetchLaborMarket, fetchLiquidity, fetchLLMSettings,
  fetchVixTermStructure, fetchMomentum, fetchOntologyRuns, fetchPortfolio, fetchPortfolioNews,
  fetchPortfolioPositions, fetchPortfolioRiskDashboard, fetchPortfolioSettings,
  fetchPositioningInstruments, fetchSectorMetrics, fetchSentimentPutCall, fetchSizerPrefill,
  fetchThesisMeta, fetchWorkspace, fetchYieldCurve,
} from "@/lib/api"
import { findPageRoute } from "@/lib/pageRoutes"
import { queryClient } from "@/lib/queryClient"

function initialQuery<T>(queryKey: QueryKey, queryFn: () => Promise<T>, staleTime = 300_000) {
  return { queryKey, queryFn, staleTime, retry: 1 as const }
}

// Route prefetch and form observers share requests and freshness. The portfolio
// prefix also lets dashboard/approval invalidations refresh their source data.
export const hedgingPrefillQuery = initialQuery(["hedging-tool", "prefill"], fetchHedgingToolPrefill, 5_000)
export const sizerPrefillQuery = initialQuery(["portfolio", "sizer-prefill"], fetchSizerPrefill, 300_000)
export const portfolioPositionsQuery = initialQuery(["portfolio", "positions"], () => fetchPortfolioPositions(), 300_000)
export const allPortfolioPositionsQuery = initialQuery(["portfolio", "positions", "with-hedges"], () => fetchPortfolioPositions(true))
export const hedgePositionsQuery = initialQuery(["portfolio", "hedges"], fetchHedgePositions, 300_000)
export const portfolioSettingsQuery = initialQuery(["portfolio", "settings"], fetchPortfolioSettings, 300_000)

// Only the first automatic query is started here. Remaining queries and
// user-triggered analyses stay with their page. Keys and freshness match the
// existing hooks, so mounting a page joins the request rather than duplicating it.
const routeQueries = {
  "/": initialQuery(["portfolio", "This Week"], () => fetchPortfolio("This Week")),
  "/portfolio/edit": portfolioPositionsQuery,
  "/risk": { ...initialQuery(["portfolio-risk-dashboard"], fetchPortfolioRiskDashboard, 60_000), retry: false },
  "/workspace": initialQuery(["workspace"], fetchWorkspace, 60_000),
  "/ideas": initialQuery(["ideas"], () => fetchIdeas({ include_archived: false, limit: 300 }), 30_000),
  "/theses": initialQuery(["thesis", "meta"], fetchThesisMeta),
  "/analyzer": initialQuery(["llm-settings"], fetchLLMSettings, 30_000),
  "/hedging-tool": hedgingPrefillQuery,
  "/sizer": sizerPrefillQuery,
  "/momentum": initialQuery(["momentum"], fetchMomentum),
  "/ontology": initialQuery(["ontology-runs"], () => fetchOntologyRuns(150), 60_000),
  "/index-dashboard": initialQuery(["index-dashboard", "This Week"], () => fetchIndexDashboard("This Week")),
  "/fx-dashboard": initialQuery(["fx-dashboard", "This Week"], () => fetchFxDashboard("This Week")),
  "/commodities": initialQuery(["commodities", "This Week"], () => fetchCommodities("This Week")),
  "/market-technicals": initialQuery(["vix-term-structure"], fetchVixTermStructure),
  "/sector-metrics": initialQuery(["sector-metrics"], () => fetchSectorMetrics(), 3_600_000),
  "/positioning": initialQuery(["positioning-instruments"], fetchPositioningInstruments),
  "/sentiment": initialQuery(["sentiment-put-call"], () => fetchSentimentPutCall(180)),
  "/fx-model": initialQuery(["fx-model-pairs"], fetchFxModelPairs),
  "/economic-growth": initialQuery(["economic-growth"], fetchEconomicGrowth),
  "/labor-market": initialQuery(["labor-market"], () => fetchLaborMarket()),
  "/housing": initialQuery(["housing"], () => fetchHousing()),
  "/liquidity": initialQuery(["liquidity"], () => fetchLiquidity()),
  "/country-dashboard": initialQuery(["country-dashboard", "Inflation"], () => fetchCountryDashboard("Inflation"), 86_400_000),
  "/central-banks": initialQuery(["central-banks", 0], () => fetchCentralBanks(), 3_600_000),
  "/industry-monitor": initialQuery(["industry-monitor", false], () => fetchIndustryMonitor(false), 3_600_000),
  "/yield-curve": initialQuery(["yield-curve", 90, "US"], () => fetchYieldCurve(90, "US")),
  "/bond-dashboard": initialQuery(["bond-dashboard"], () => fetchBondDashboard()),
  "/commodities-curve": initialQuery(["commodities-curve", "CL", 30], () => fetchCommoditiesCurve("CL", 30)),
  "/commodity-research": initialQuery(["commodity-research", "v3"], () => fetchCommodityResearch()),
  "/portfolio-news": initialQuery(["portfolio-news"], fetchPortfolioNews, 60_000),
  "/settings/ai": initialQuery(["llm-settings"], fetchLLMSettings, 30_000),
  "/settings/policy-matrix": initialQuery(["financial-policy-matrix"], fetchFinancialPolicyMatrixSettings, 30_000),
} satisfies Record<string, { queryKey: QueryKey; queryFn: () => Promise<unknown>; staleTime: number; retry: number | false }>

export function preloadRouteData(href: string) {
  const url = new URL(href, window.location.origin)
  const match = findPageRoute(url.pathname)
  if (!match) return
  const { path } = match.route
  let query: (typeof routeQueries)[keyof typeof routeQueries] | undefined
  if (path === "/dossier/:ticker") {
    const ticker = match.params.ticker!
    query = initialQuery(["dossier", ticker], () => fetchDossier(ticker), 60_000)
  } else if (path === "/ideas/:id") {
    const id = match.params.id!
    query = initialQuery(["idea", id], () => fetchIdea(id), 15_000)
  } else if (path === "/explore/:ticker") {
    const ticker = match.params.ticker!.trim().toUpperCase()
    // The chart uses POST and needs the CSRF token from /auth/me. Start the
    // explorer's independent GET instead; POSTs stay behind authentication.
    query = initialQuery(["dossier", ticker], () => fetchDossier(ticker), 60_000)
  } else if (path === "/alternative-data") {
    const ticker = url.searchParams.get("ticker") || ""
    query = initialQuery(["alternative-data-catalog", ticker], () => fetchAlternativeDataCatalog(ticker), 30_000)
  } else {
    query = routeQueries[path as keyof typeof routeQueries]
  }
  if (!query) return
  // Don't block a route's shell on slow data. The page's query renders its
  // normal loading/error state and observes this same in-flight request.
  void queryClient.ensureQueryData({ ...query, revalidateIfStale: true }).catch(() => {})
}
