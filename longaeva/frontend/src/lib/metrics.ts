export type MetricUnit =
  | "usd_millions"
  | "usd_billions"
  | "ratio"
  | "transactions_millions"
  | "count"
  | "unknown"

export interface MetricCatalogEntry {
  key: string
  label: string
  unit: MetricUnit
  basis?: string
}

export const METRIC_CATALOG: readonly MetricCatalogEntry[] = [
  { key: "service_revenue", label: "Service revenue", unit: "usd_millions", basis: "gaap" },
  { key: "data_processing_revenue", label: "Data processing revenue", unit: "usd_millions", basis: "gaap" },
  {
    key: "international_transaction_revenue",
    label: "International transaction revenue",
    unit: "usd_millions",
    basis: "gaap",
  },
  { key: "other_revenue", label: "Other revenue", unit: "usd_millions", basis: "gaap" },
  { key: "client_incentives", label: "Client incentives", unit: "usd_millions", basis: "gaap" },
  { key: "net_revenue", label: "Net revenue", unit: "usd_millions", basis: "gaap" },
  {
    key: "operating_expenses_ex_special_items",
    label: "Operating expenses (ex special items)",
    unit: "usd_millions",
    basis: "ex_special_items",
  },
  {
    key: "operating_profit_ex_special_items",
    label: "Operating profit (ex special items)",
    unit: "usd_millions",
    basis: "ex_special_items",
  },
  { key: "payments_volume_nominal_us", label: "Payments volume (nominal)", unit: "usd_billions", basis: "nominal" },
  { key: "domestic_payments_volume", label: "Domestic payments volume", unit: "usd_billions", basis: "nominal" },
  {
    key: "cross_border_ex_intra_europe_volume",
    label: "Cross-border volume (ex intra-Europe)",
    unit: "usd_billions",
    basis: "nominal",
  },
  {
    key: "processed_transactions_count",
    label: "Processed transactions",
    unit: "transactions_millions",
    basis: "count",
  },
  {
    key: "payments_volume_growth_constant",
    label: "Payments volume growth (constant dollar)",
    unit: "ratio",
    basis: "constant_dollar",
  },
  {
    key: "cross_border_ex_intra_europe_growth_constant",
    label: "Cross-border growth (constant dollar)",
    unit: "ratio",
    basis: "constant_dollar",
  },
  {
    key: "processed_transactions_growth",
    label: "Processed transactions growth",
    unit: "ratio",
    basis: "count",
  },
  { key: "cross_border_share", label: "Cross-border share", unit: "ratio", basis: "derived" },
  { key: "incentive_intensity", label: "Incentive intensity", unit: "ratio", basis: "derived" },
]

const BY_KEY = new Map(METRIC_CATALOG.map((entry) => [entry.key, entry]))

export const DEFAULT_FAN_METRIC = "net_revenue"

export const DRIVER_GROWTH_METRICS = [
  "payments_volume_growth_constant",
  "cross_border_ex_intra_europe_growth_constant",
  "processed_transactions_growth",
] as const

export function metricEntry(key: string): MetricCatalogEntry {
  return BY_KEY.get(key) ?? { key, label: key.replaceAll("_", " "), unit: "unknown" }
}

export function metricLabel(key: string): string {
  return metricEntry(key).label
}
