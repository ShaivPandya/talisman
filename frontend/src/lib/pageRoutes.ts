import { matchRoutes } from "react-router-dom"
import { lazyPage } from "@/lib/lazyPage"

const LoginPage = lazyPage(() => import("@/pages/LoginPage"), "LoginPage")
const PortfolioDashboard = lazyPage(() => import("@/pages/PortfolioDashboard"), "PortfolioDashboard")
const PortfolioRisk = lazyPage(() => import("@/pages/PortfolioRisk"), "PortfolioRisk")
const PortfolioEditorPage = lazyPage(() => import("@/pages/PortfolioEditorPage"), "PortfolioEditorPage")
const PortfolioAnalyzer = lazyPage(() => import("@/pages/PortfolioAnalyzer"), "PortfolioAnalyzer")
const HedgingTool = lazyPage(() => import("@/pages/HedgingTool"), "HedgingTool")
const PortfolioSizer = lazyPage(() => import("@/pages/PortfolioSizer"), "PortfolioSizer")
const Momentum = lazyPage(() => import("@/pages/Momentum"), "Momentum")
const ChartPage = lazyPage(() => import("@/pages/ChartPage"), "ChartPage")
const CompanyExplorer = lazyPage(() => import("@/pages/CompanyExplorer"), "CompanyExplorer")
const Screeners = lazyPage(() => import("@/pages/Screeners"), "Screeners")
const Financials = lazyPage(() => import("@/pages/Financials"), "Financials")
const IndexDashboard = lazyPage(() => import("@/pages/IndexDashboard"), "IndexDashboard")
const FXDashboard = lazyPage(() => import("@/pages/FXDashboard"), "FXDashboard")
const CommodityDashboard = lazyPage(() => import("@/pages/CommodityDashboard"), "CommodityDashboard")
const MarketTechnicals = lazyPage(() => import("@/pages/MarketTechnicals"), "MarketTechnicals")
const SectorMetrics = lazyPage(() => import("@/pages/SectorMetrics"), "SectorMetrics")
const Positioning = lazyPage(() => import("@/pages/Positioning"), "Positioning")
const FXModel = lazyPage(() => import("@/pages/FXModel"), "FXModel")
const EconomicGrowth = lazyPage(() => import("@/pages/EconomicGrowth"), "EconomicGrowth")
const LaborMarket = lazyPage(() => import("@/pages/LaborMarket"), "LaborMarket")
const Housing = lazyPage(() => import("@/pages/Housing"), "Housing")
const Liquidity = lazyPage(() => import("@/pages/Liquidity"), "Liquidity")
const CountryDashboard = lazyPage(() => import("@/pages/CountryDashboard"), "CountryDashboard")
const CentralBanks = lazyPage(() => import("@/pages/CentralBanks"), "CentralBanks")
const IndustryMonitor = lazyPage(() => import("@/pages/IndustryMonitor"), "IndustryMonitor")
const YieldCurve = lazyPage(() => import("@/pages/YieldCurve"), "YieldCurve")
const BondDashboard = lazyPage(() => import("@/pages/BondDashboard"), "BondDashboard")
const CommoditiesCurve = lazyPage(() => import("@/pages/CommoditiesCurve"), "CommoditiesCurve")
const CommodityResearch = lazyPage(() => import("@/pages/CommodityResearch"), "CommodityResearch")
const PortfolioNews = lazyPage(() => import("@/pages/PortfolioNews"), "PortfolioNews")
const AlternativeData = lazyPage(() => import("@/pages/AlternativeData"), "AlternativeData")
const Sentiment = lazyPage(() => import("@/pages/Sentiment"), "Sentiment")
const SignalAggregator = lazyPage(() => import("@/pages/SignalAggregator"), "SignalAggregator")
const OntologyWorkbench = lazyPage(() => import("@/pages/OntologyWorkbench"), "OntologyWorkbench")
const ThesisManager = lazyPage(() => import("@/pages/ThesisManager"), "ThesisManager")
const Workspace = lazyPage(() => import("@/pages/Workspace"), "Workspace")
const PositionDossier = lazyPage(() => import("@/pages/PositionDossier"), "PositionDossier")
const IdeaWatchlist = lazyPage(() => import("@/pages/IdeaWatchlist"), "IdeaWatchlist")
const IdeaDetail = lazyPage(() => import("@/pages/IdeaDetail"), "IdeaDetail")
const DCFModel = lazyPage(() => import("@/pages/DCFModel"), "DCFModel")
const AISettings = lazyPage(() => import("@/pages/AISettings"), "AISettings")
const PolicyMatrixSettings = lazyPage(() => import("@/pages/PolicyMatrixSettings"), "PolicyMatrixSettings")
const PersonalizationSettings = lazyPage(() => import("@/pages/PersonalizationSettings"), "PersonalizationSettings")

export { LoginPage }

export const PAGE_ROUTES = [
  { path: "/", page: PortfolioDashboard },
  { path: "/portfolio/edit", page: PortfolioEditorPage },
  { path: "/risk", page: PortfolioRisk },
  { path: "/workspace", page: Workspace },
  { path: "/dossier/:ticker", page: PositionDossier },
  { path: "/ideas", page: IdeaWatchlist },
  { path: "/ideas/:id", page: IdeaDetail },
  { path: "/theses", page: ThesisManager },
  { path: "/analyzer", page: PortfolioAnalyzer },
  { path: "/hedging-tool", page: HedgingTool },
  { path: "/sizer", page: PortfolioSizer },
  { path: "/momentum", page: Momentum },
  { path: "/signal-aggregator", page: SignalAggregator },
  { path: "/ontology", page: OntologyWorkbench },
  { path: "/chart", page: ChartPage },
  { path: "/explore", page: CompanyExplorer },
  { path: "/explore/:ticker", page: CompanyExplorer },
  { path: "/screeners", page: Screeners },
  { path: "/financials", page: Financials },
  { path: "/dcf-model", page: DCFModel },
  { path: "/index-dashboard", page: IndexDashboard },
  { path: "/fx-dashboard", page: FXDashboard },
  { path: "/commodities", page: CommodityDashboard },
  { path: "/market-technicals", page: MarketTechnicals },
  { path: "/sector-metrics", page: SectorMetrics },
  { path: "/positioning", page: Positioning },
  { path: "/sentiment", page: Sentiment },
  { path: "/fx-model", page: FXModel },
  { path: "/economic-growth", page: EconomicGrowth },
  { path: "/labor-market", page: LaborMarket },
  { path: "/housing", page: Housing },
  { path: "/liquidity", page: Liquidity },
  { path: "/country-dashboard", page: CountryDashboard },
  { path: "/central-banks", page: CentralBanks },
  { path: "/industry-monitor", page: IndustryMonitor },
  { path: "/yield-curve", page: YieldCurve },
  { path: "/bond-dashboard", page: BondDashboard },
  { path: "/commodities-curve", page: CommoditiesCurve },
  { path: "/commodity-research", page: CommodityResearch },
  { path: "/portfolio-news", page: PortfolioNews },
  { path: "/alternative-data", page: AlternativeData },
  { path: "/settings/ai", page: AISettings },
  { path: "/settings/policy-matrix", page: PolicyMatrixSettings },
  { path: "/settings/personalization", page: PersonalizationSettings },
] as const

export const ROUTE_REDIRECTS: Record<string, string> = {
  "/portfolio": "/",
  "/optimizer": "/analyzer",
  "/quality": "/screeners",
  "/short-screen": "/screeners",
  "/fundamental-momentum": "/screeners",
}

export function findPageRoute(pathname: string) {
  const path = ROUTE_REDIRECTS[pathname] ?? pathname
  return matchRoutes([...PAGE_ROUTES], path)?.at(-1)
}

export function preloadRoute(pathname: string) {
  const page = pathname === "/login" ? LoginPage : findPageRoute(pathname)?.route.page
  return page?.preload().then(() => undefined) ?? Promise.resolve()
}
