import { metricEntry, type MetricUnit } from "./metrics"

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtUsdMillions(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `$${fmtNumber(value, 0)}m`
}

export function fmtUsdBillions(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `$${fmtNumber(value, 1)}bn`
}

export function fmtRatioPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${fmtNumber(value * 100, 1)}%`
}

export function fmtCountMillions(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${fmtNumber(value, 1)}m`
}

export function fmtByUnit(value: number | null | undefined, unit: MetricUnit): string {
  switch (unit) {
    case "usd_millions":
      return fmtUsdMillions(value)
    case "usd_billions":
      return fmtUsdBillions(value)
    case "ratio":
      return fmtRatioPct(value)
    case "transactions_millions":
    case "count":
      return fmtCountMillions(value)
    default:
      return fmtNumber(value, 2)
  }
}

export function fmtMetricValue(value: number | null | undefined, metricKey: string): string {
  return fmtByUnit(value, metricEntry(metricKey).unit)
}

export function fmtUtc(iso: string | null | undefined): string {
  if (!iso) return "—"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toISOString().replace(".000Z", "Z")
}

export function shortHash(value: string | null | undefined, size = 10): string {
  if (!value) return "—"
  return value.length <= size ? value : value.slice(0, size)
}
