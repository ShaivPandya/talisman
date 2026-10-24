import {
  Activity,
  ArrowLeftRight,
  Banknote,
  Bot,
  Boxes,
  BriefcaseBusiness,
  Building2,
  Calculator,
  ChartArea,
  ChartCandlestick,
  ChartLine,
  ChartPie,
  ChartSpline,
  Droplets,
  Factory,
  FileSpreadsheet,
  Filter,
  Globe,
  Grid3x3,
  House,
  Landmark,
  LayoutDashboard,
  Library,
  Lightbulb,
  ListChecks,
  ListFilter,
  Microscope,
  Network,
  Newspaper,
  Palette,
  PencilLine,
  Percent,
  Radar,
  Rocket,
  Satellite,
  Scale,
  ScrollText,
  ShieldAlert,
  Smile,
  TrendingUp,
  Umbrella,
  Users,
  type LucideIcon,
} from "lucide-react"

export interface NavPage {
  label: string
  path: string
  icon: LucideIcon
  /** Locked pages can't be hidden, so Settings always stays reachable. */
  locked?: boolean
}

export interface NavSection {
  label: string
  pages: NavPage[]
}

export const PERSONALIZATION_PATH = "/settings/personalization"

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Core",
    pages: [
      { label: "Portfolio Dashboard", path: "/", icon: LayoutDashboard },
      { label: "Portfolio Risk", path: "/risk", icon: ShieldAlert },
      { label: "Edit Portfolio", path: "/portfolio/edit", icon: PencilLine },
      { label: "Workspace", path: "/workspace", icon: ListChecks },
      { label: "Investment Theses", path: "/theses", icon: ScrollText },
      { label: "Idea Watchlist", path: "/ideas", icon: Lightbulb },
    ],
  },
  {
    label: "Labs",
    pages: [
      { label: "Portfolio Analyzer", path: "/analyzer", icon: Microscope },
      { label: "Portfolio Sizer", path: "/sizer", icon: Scale },
      { label: "Hedging Tool", path: "/hedging-tool", icon: Umbrella },
      { label: "Chart", path: "/chart", icon: ChartCandlestick },
      { label: "Company Explorer", path: "/explore", icon: Building2 },
      { label: "Screeners", path: "/screeners", icon: ListFilter },
      { label: "Financials", path: "/financials", icon: FileSpreadsheet },
      { label: "DCF Model", path: "/dcf-model", icon: Calculator },
      { label: "FX Model", path: "/fx-model", icon: ArrowLeftRight },
      { label: "Momentum", path: "/momentum", icon: Rocket },
    ],
  },
  {
    label: "Monitors",
    pages: [
      { label: "Signal Aggregator", path: "/signal-aggregator", icon: Radar },
      { label: "Ontology Workbench", path: "/ontology", icon: Network },
      { label: "Alternative Data", path: "/alternative-data", icon: Satellite },
      { label: "Market Technicals", path: "/market-technicals", icon: Activity },
      { label: "News Digests", path: "/portfolio-news", icon: Newspaper },
      { label: "Sentiment", path: "/sentiment", icon: Smile },
      { label: "Positioning", path: "/positioning", icon: Users },
      { label: "Central Bank Monitor", path: "/central-banks", icon: Landmark },
      { label: "Industry Monitor", path: "/industry-monitor", icon: Factory },
      { label: "Sector Metrics", path: "/sector-metrics", icon: ChartPie },
    ],
  },
  {
    label: "Macro",
    pages: [
      { label: "Economic Growth", path: "/economic-growth", icon: TrendingUp },
      { label: "Labor Market", path: "/labor-market", icon: BriefcaseBusiness },
      { label: "Housing", path: "/housing", icon: House },
      { label: "Liquidity", path: "/liquidity", icon: Droplets },
      { label: "Yield Curve", path: "/yield-curve", icon: ChartSpline },
      { label: "Bond Dashboard", path: "/bond-dashboard", icon: Percent },
      { label: "Country Dashboard", path: "/country-dashboard", icon: Globe },
    ],
  },
  {
    label: "Assets",
    pages: [
      { label: "Index Dashboard", path: "/index-dashboard", icon: ChartLine },
      { label: "FX Dashboard", path: "/fx-dashboard", icon: Banknote },
      { label: "Commodity Dashboard", path: "/commodities", icon: Boxes },
      { label: "Commodities Curve", path: "/commodities-curve", icon: ChartArea },
      { label: "Commodity Proxy Screener", path: "/commodity-research", icon: Filter },
    ],
  },
  {
    label: "Settings",
    pages: [
      { label: "AI Settings", path: "/settings/ai", icon: Bot },
      { label: "Policy Matrix", path: "/settings/policy-matrix", icon: Grid3x3 },
      { label: "Personalization", path: PERSONALIZATION_PATH, icon: Palette, locked: true },
      { label: "Source Library", path: "/source-files", icon: Library },
    ],
  },
]

export const HIDEABLE_PATHS = new Set(
  NAV_SECTIONS.flatMap(section => section.pages.filter(page => !page.locked).map(page => page.path)),
)

export function getRouteLabel(pathname: string) {
  for (const section of NAV_SECTIONS) {
    const match = section.pages.find(page => page.path === pathname)
    if (match) return match.label
  }
  if (pathname.startsWith("/dossier/")) return "Position Dossier"
  if (pathname === "/explore" || pathname.startsWith("/explore/")) return "Company Explorer"
  if (pathname.startsWith("/ideas/") && pathname !== "/ideas") return "Idea Detail"
  return "Talisman"
}
