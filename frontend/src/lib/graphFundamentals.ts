/** Pure chart state and calculations. Shared by chart, table, CSV and unit tests. */
export type Period = "quarters" | "ltm" | "annual"
export type Transform = "none" | "yoy" | "change" | "index" | "cagr"
export type GraphRange = "Auto" | "1Y" | "3Y" | "5Y" | "10Y" | "Custom"
export interface FundamentalField {
  id: string
  label: string
  category: string
  unit: string
  formula: string
  estimates: boolean
}
export interface FundamentalPoint {
  date: string
  value: number | null
  estimate?: boolean
  period_label?: string
  reason?: string | null
  filed?: string | null
  filing_url?: string | null
  analysts?: number | null
  as_of?: string
  basis?: string
  source?: string
}
export interface FundamentalSeries {
  ticker: string
  field: string
  unit: string
  currency: string | null
  source: string | null
  as_of: string | null
  formula?: string
  computed?: boolean
  reason?: string
  points: FundamentalPoint[]
  estimate_coverage: { supported: boolean; reason: string }
}
export interface FundamentalResponse {
  series: FundamentalSeries[]
  start_date: string
  end_date: string | null
  period: Period
  history_policy?: string
}
export interface ChartSeries {
  id: string
  ticker?: string
  field?: string
  a?: string
  b?: string
  operation?: "subtract" | "divide" | "add" | "multiply"
  label: string
  color: string
  width: number
  visualization: "line" | "bar"
  style: "solid" | "dashed"
  transform: Transform
  estimates: boolean
}
export interface ChartPane {
  id: string
  field?: string
  series: ChartSeries[]
}
export interface ChartState {
  version: 1
  tickers: string[]
  period: Period
  range: GraphRange
  start_date?: string | null
  end_date?: string | null
  panes: ChartPane[]
}
export interface SavedChart {
  chart_id: string
  name: string
  created_at: string
  updated_at: string
  state?: ChartState
}
export interface DisplaySeries {
  config: ChartSeries
  label: string
  unit: string
  currency: string | null
  points: FundamentalPoint[]
  source?: string | null
  as_of?: string | null
  formula?: string
  reason?: string
}
export const COLORS = ["#38bdf8", "#a78bfa", "#fbbf24", "#34d399", "#fb7185", "#fb923c"]
export const TRANSFORMS: { value: Transform; label: string }[] = [
  { value: "none", label: "None" },
  { value: "yoy", label: "Year over year %" },
  { value: "change", label: "% change from start" },
  { value: "index", label: "Indexed to 100" },
  { value: "cagr", label: "3Y rolling CAGR" },
]
export const newId = () => globalThis.crypto.randomUUID()
export function baseSeries(ticker: string, field: string, index: number): ChartSeries {
  return {
    id: newId(),
    ticker,
    field,
    label: "",
    color: COLORS[index % COLORS.length],
    width: 2,
    visualization: "line",
    style: "solid",
    transform: "none",
    estimates: false,
  }
}
export function defaultChart(): ChartState {
  const tickers = ["SPGI", "MCO", "MSCI", "MORN"]
  return {
    version: 1,
    tickers,
    period: "quarters",
    range: "5Y",
    panes: ["roic", "fcf_yield", "operating_margin"].map((field) => ({
      id: newId(),
      field,
      series: tickers.map((ticker, i) => baseSeries(ticker, field, i)),
    })),
  }
}
const finite = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v)
const DAY = 86400000

export function transformPoints(
  points: FundamentalPoint[],
  transform: Transform,
  _period: Period,
  start: string,
): FundamentalPoint[] {
  const baseline = points.find((p) => p.date >= start && !p.estimate && finite(p.value))?.value
  const actual = points.filter((p) => !p.estimate)
  return points.map((p) => {
    if (transform === "none") return { ...p }
    let value: number | null = null
    let reason: string | null = null
    if ((transform === "change" || transform === "index") && finite(p.value) && finite(baseline) && baseline !== 0) {
      value = transform === "index" ? (p.value / baseline) * 100 : ((p.value - baseline) / Math.abs(baseline)) * 100
    } else if (transform === "yoy" || transform === "cagr") {
      const years = transform === "cagr" ? 3 : 1
      // Match by calendar distance, not by array position across missing periods.
      const target = new Date(`${p.date}T00:00:00Z`)
      target.setUTCFullYear(target.getUTCFullYear() - years)
      const previous = actual
        .filter((row) => Math.abs(Date.parse(row.date) - target.getTime()) <= 16 * DAY)
        .sort(
          (a, b) => Math.abs(Date.parse(a.date) - target.getTime()) - Math.abs(Date.parse(b.date) - target.getTime()),
        )[0]
      if (finite(p.value) && finite(previous?.value) && previous.value !== 0) {
        if (transform === "yoy") value = ((p.value - previous.value) / Math.abs(previous.value)) * 100
        else if (p.value > 0 && previous.value > 0) value = (Math.pow(p.value / previous.value, 1 / 3) - 1) * 100
      }
    }
    if (!finite(value)) {
      value = null
      reason =
        transform === "cagr"
          ? "CAGR requires positive endpoints and three years of history."
          : "Missing comparison period or zero baseline."
    }
    return { ...p, value, reason }
  })
}

export function arithmetic(a: DisplaySeries, b: DisplaySeries, config: ChartSeries): DisplaySeries {
  const operation = config.operation!
  const label =
    config.label || `${a.label} ${{ subtract: "−", divide: "/", add: "+", multiply: "×" }[operation]} ${b.label}`
  if (a.points.map((p) => p.date).join() !== b.points.map((p) => p.date).join())
    throw new Error(
      "Arithmetic inputs must share the same period grid. Choose series with matching reporting dates and estimate settings.",
    )
  if ((operation === "subtract" || operation === "add") && (a.unit !== b.unit || a.currency !== b.currency))
    throw new Error("Addition and subtraction require matching units and currencies.")
  if ((a.currency || b.currency) && a.currency !== b.currency)
    throw new Error("Arithmetic across different currencies requires FX conversion, which is unavailable.")
  const same = a.unit === b.unit && a.currency === b.currency
  const unit =
    operation === "divide"
      ? same
        ? "ratio"
        : `${a.unit}/${b.unit}`
      : operation === "multiply"
        ? `${a.unit}×${b.unit}`
        : a.unit
  const currency = operation === "add" || operation === "subtract" ? a.currency : null
  return {
    config,
    label,
    unit,
    currency,
    source: "Calculated from chart series",
    points: a.points.map((p, i) => {
      const q = b.points[i]
      const x = p.value,
        y = q.value
      const result =
        finite(x) && finite(y)
          ? operation === "add"
            ? x + y
            : operation === "subtract"
              ? x - y
              : operation === "multiply"
                ? x * y
                : y === 0
                  ? null
                  : x / y
          : null
      return {
        ...p,
        value: finite(result) ? result : null,
        estimate: p.estimate || q.estimate,
        reason: finite(result) ? null : "Missing input or division by zero.",
      }
    }),
  }
}

export function displaySeries(
  state: ChartState,
  data: FundamentalResponse,
  catalog: FundamentalField[],
): Map<string, DisplaySeries> {
  const configs = new Map(state.panes.flatMap((p) => p.series).map((s) => [s.id, s]))
  const output = new Map<string, DisplaySeries>()
  const visiting = new Set<string>()
  function resolve(id: string): DisplaySeries {
    if (output.has(id)) return output.get(id)!
    const config = configs.get(id)
    if (!config || visiting.has(id)) throw new Error("An arithmetic input is missing or circular.")
    visiting.add(id)
    let result: DisplaySeries
    if (config.operation) result = arithmetic(resolve(config.a!), resolve(config.b!), config)
    else {
      const raw = data.series.find((s) => s.ticker === config.ticker && s.field === config.field)
      const field = catalog.find((f) => f.id === config.field)
      result = {
        config,
        label: config.label || `${config.ticker} · ${field?.label ?? config.field}`,
        unit: raw?.unit ?? field?.unit ?? "ratio",
        currency: raw?.currency ?? null,
        source: raw?.source,
        as_of: raw?.as_of,
        formula: raw?.formula,
        reason: raw?.reason,
        points: (raw?.points ?? []).filter((p) => config.estimates || !p.estimate),
      }
    }
    const points = transformPoints(result.points, config.transform, state.period, data.start_date)
    result = {
      ...result,
      label:
        config.transform === "none"
          ? result.label
          : `${result.label} · ${TRANSFORMS.find((t) => t.value === config.transform)?.label}`,
      points,
      unit: config.transform === "none" ? result.unit : config.transform === "index" ? "index" : "percent",
      currency: config.transform === "none" ? result.currency : null,
    }
    visiting.delete(id)
    output.set(id, result)
    return result
  }
  for (const id of configs.keys()) {
    try {
      resolve(id)
    } catch (error) {
      output.set(id, {
        config: configs.get(id)!,
        label: configs.get(id)!.label || "Calculated series",
        unit: "ratio",
        currency: null,
        points: [],
        reason: error instanceof Error ? error.message : "Could not calculate this series.",
      })
    }
  }
  return output
}

export function paneIssue(series: DisplaySeries[]): string | null {
  if (new Set(series.map((s) => s.unit)).size > 1)
    return "This pane mixes incompatible units. Apply a compatible transform or move the series into separate panes."
  return null
}
export function mixedCurrencies(series: DisplaySeries[]): boolean {
  return new Set(series.map((s) => s.currency).filter(Boolean)).size > 1
}
export function visibleDates(series: DisplaySeries[], start: string, end: string | null): string[] {
  return [...new Set(series.flatMap((s) => s.points.map((p) => p.date)))]
    .filter((d) => d >= start && (!end || d <= end))
    .sort()
}
export function tableRows(
  series: DisplaySeries[],
  start: string,
  end: string | null,
): Record<string, string | number | null>[] {
  const lookup = new Map(series.map((s) => [s.config.id, new Map(s.points.map((p) => [p.date, p.value]))]))
  return visibleDates(series, start, end).map((date) =>
    Object.fromEntries([
      ["date", date],
      ...series.map((s) => [s.config.id, lookup.get(s.config.id)?.get(date) ?? null]),
    ]),
  )
}
export function chartCsv(series: DisplaySeries[], start: string, end: string | null): string {
  const cell = (v: unknown) => `"${String(v ?? "").replaceAll('"', '""')}"`
  const heading = ["Period end", ...series.map((s) => `${s.label} [${s.currency ? `${s.currency} ` : ""}${s.unit}]`)]
  return [
    heading.map(cell).join(","),
    ...tableRows(series, start, end).map((row) =>
      [row.date, ...series.map((s) => row[s.config.id])].map(cell).join(","),
    ),
  ].join("\r\n")
}
const URL_KEYS: Record<string, string> = {
  version: "v",
  tickers: "t",
  period: "p",
  range: "r",
  start_date: "s",
  end_date: "e",
  panes: "n",
  id: "i",
  field: "f",
  series: "h",
  ticker: "k",
  operation: "o",
  label: "l",
  color: "c",
  width: "w",
  visualization: "z",
  style: "y",
  transform: "x",
  estimates: "q",
}
const STATE_KEYS = Object.fromEntries(Object.entries(URL_KEYS).map(([a, b]) => [b, a]))
export function encodeChart(state: ChartState): string {
  const compact = JSON.stringify(state, (_key, value) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).map(([key, item]) => [URL_KEYS[key] ?? key, item]))
      : value,
  )
  return btoa(String.fromCharCode(...new TextEncoder().encode(compact)))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "")
}
export function decodeChart(encoded: string): ChartState {
  if (encoded.length > 45000) throw new Error("Shared chart is too large.")
  const text = new TextDecoder().decode(
    Uint8Array.from(atob(encoded.replaceAll("-", "+").replaceAll("_", "/")), (c) => c.charCodeAt(0)),
  )
  const parsed = JSON.parse(text)
  const value =
    parsed.version === 1
      ? parsed
      : JSON.parse(text, (_key, item) =>
          item && typeof item === "object" && !Array.isArray(item)
            ? Object.fromEntries(Object.entries(item).map(([key, value]) => [STATE_KEYS[key] ?? key, value]))
            : item,
        )
  return validateChart(value)
}
export function validateChart(value: unknown): ChartState {
  if (!value || typeof value !== "object") throw new Error("Invalid shared chart.")
  const state = value as ChartState
  const fail = () => {
    throw new Error("Invalid shared chart settings. Charts support 6 tickers, 4 panes and 24 series.")
  }
  if (
    state.version !== 1 ||
    !Array.isArray(state.tickers) ||
    state.tickers.length < 1 ||
    state.tickers.length > 6 ||
    new Set(state.tickers).size !== state.tickers.length ||
    state.tickers.some((t) => !/^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/.test(t))
  )
    fail()
  if (
    !["quarters", "ltm", "annual"].includes(state.period) ||
    !["Auto", "1Y", "3Y", "5Y", "10Y", "Custom"].includes(state.range)
  )
    fail()
  if (
    state.range === "Custom" &&
    (!state.start_date ||
      !state.end_date ||
      !Number.isFinite(Date.parse(state.start_date)) ||
      !Number.isFinite(Date.parse(state.end_date)) ||
      state.end_date < state.start_date ||
      (Date.parse(state.end_date) - Date.parse(state.start_date)) / DAY > 3660)
  )
    fail()
  if (
    !Array.isArray(state.panes) ||
    state.panes.length < 1 ||
    state.panes.length > 4 ||
    new Set(state.panes.map((p) => p.id)).size !== state.panes.length
  )
    fail()
  const series = state.panes.flatMap((p) => p.series)
  if (
    series.length > 24 ||
    state.panes.some((p) => !p.id || !Array.isArray(p.series) || p.series.length < 1) ||
    new Set(series.map((s) => s.id)).size !== series.length
  )
    fail()
  for (const s of series) {
    if (
      !s.id ||
      !/^#[0-9a-f]{6}$/i.test(s.color) ||
      !Number.isInteger(s.width) ||
      s.width < 1 ||
      s.width > 5 ||
      !["line", "bar"].includes(s.visualization) ||
      !["solid", "dashed"].includes(s.style) ||
      !TRANSFORMS.some((t) => t.value === s.transform) ||
      typeof s.label !== "string" ||
      s.label.length > 160 ||
      typeof s.estimates !== "boolean"
    )
      fail()
    if (
      s.operation
        ? !["add", "subtract", "divide", "multiply"].includes(s.operation) || !s.a || !s.b
        : !s.ticker || !state.tickers.includes(s.ticker) || typeof s.field !== "string"
    )
      fail()
  }
  const byId = new Map(series.map((s) => [s.id, s]))
  function visit(id: string, path: Set<string>) {
    const s = byId.get(id)
    if (!s || path.has(id)) fail()
    if (s!.operation) {
      const next = new Set(path).add(id)
      visit(s!.a!, next)
      visit(s!.b!, next)
    }
  }
  series.forEach((s) => visit(s.id, new Set()))
  return state
}
export function removeSeries(state: ChartState, id: string): ChartState {
  const removed = new Set([id])
  let count = 0
  do {
    count = removed.size
    for (const s of state.panes.flatMap((p) => p.series))
      if ((s.a && removed.has(s.a)) || (s.b && removed.has(s.b))) removed.add(s.id)
  } while (removed.size > count)
  return {
    ...state,
    panes: state.panes
      .map((p) => ({ ...p, series: p.series.filter((s) => !removed.has(s.id)) }))
      .filter((p) => p.series.length > 0),
  }
}
export function formatValue(value: number | null, unit: string, currency?: string | null): string {
  if (!finite(value)) return "—"
  const formatted = new Intl.NumberFormat("en-US", {
    notation: Math.abs(value) >= 1e6 ? "compact" : "standard",
    maximumFractionDigits: 2,
  }).format(value)
  return `${currency ? `${currency} ` : ""}${formatted}${unit === "percent" ? "%" : unit === "ratio" ? "×" : ""}`
}
