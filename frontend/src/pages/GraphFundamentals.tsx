import { useEffect, useId, useMemo, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"
import { Download, Plus, Save, Share2, Trash2 } from "lucide-react"
import { PageHeader } from "@/components/shared/PageHeader"
import { FundamentalPane } from "@/components/graph-fundamentals/FundamentalPane"
import { SeriesEditor } from "@/components/graph-fundamentals/SeriesEditor"
import {
  deleteFundamentalChart,
  fetchFundamentalCatalog,
  fetchFundamentalChart,
  fetchFundamentalCharts,
  fetchGraphFundamentals,
  saveFundamentalChart,
  searchFundamentalSecurities,
} from "@/lib/api"
import {
  arithmetic,
  baseSeries,
  chartCsv,
  decodeChart,
  defaultChart,
  displaySeries,
  encodeChart,
  formatValue,
  newId,
  removeSeries,
  tableRows,
  validateChart,
  visibleDates,
} from "@/lib/graphFundamentals"
import type {
  ChartSeries,
  ChartState,
  DisplaySeries,
  FundamentalField,
  GraphRange,
  Period,
} from "@/lib/graphFundamentals"

const control =
  "rounded-md border border-border bg-surface px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-sky-500/50"
const button = `${control} inline-flex items-center justify-center gap-1.5 hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40`
function initialChart(encoded: string | null) {
  try {
    return { state: encoded ? decodeChart(encoded) : defaultChart(), error: "" }
  } catch (error) {
    return { state: defaultChart(), error: String(error) }
  }
}

export function GraphFundamentals() {
  const [params, setParams] = useSearchParams()
  const [initial] = useState(() => initialChart(params.get("chart")))
  const [state, setState] = useState<ChartState>(initial.state)
  const [notice, setNotice] = useState(initial.error)
  const [search, setSearch] = useState("")
  const [debounced, setDebounced] = useState("")
  const [browse, setBrowse] = useState(false)
  const [category, setCategory] = useState("All fields")
  const [destination, setDestination] = useState("new")
  const [view, setView] = useState<"chart" | "table">("chart")
  const [chartId, setChartId] = useState<string>()
  const [name, setName] = useState("")
  const [busy, setBusy] = useState(false)
  const [savedOffset, setSavedOffset] = useState(0)
  const [arithmeticOpen, setArithmeticOpen] = useState(false)
  const [operandA, setOperandA] = useState("")
  const [operandB, setOperandB] = useState("")
  const [operation, setOperation] = useState<NonNullable<ChartSeries["operation"]>>("subtract")
  const [arithmeticLabel, setArithmeticLabel] = useState("")
  const queryClient = useQueryClient()
  const syncId = useId()
  const catalogQuery = useQuery({
    queryKey: ["graph-fundamentals-catalog"],
    queryFn: fetchFundamentalCatalog,
    staleTime: Infinity,
  })
  const fields = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data])
  const saved = useQuery({
    queryKey: ["fundamental-charts", savedOffset],
    queryFn: () => fetchFundamentalCharts(savedOffset),
  })
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search])
  const securities = useQuery({
    queryKey: ["fundamental-securities", debounced],
    queryFn: () => searchFundamentalSecurities(debounced),
    enabled: debounced.length > 0,
    staleTime: 300000,
  })
  const allConfigs = useMemo(() => state.panes.flatMap((p) => p.series), [state.panes])
  const bases = allConfigs.filter((s) => !s.operation)
  const request = {
    tickers: [...new Set(bases.map((s) => s.ticker!))].sort(),
    fields: [...new Set(bases.map((s) => s.field!))].sort(),
    series: [
      ...new Map(bases.map((s) => [`${s.ticker}:${s.field}`, { ticker: s.ticker!, field: s.field! }])).values(),
    ].sort((a, b) => `${a.ticker}:${a.field}`.localeCompare(`${b.ticker}:${b.field}`)),
    period: state.period,
    range: state.range,
    ...(state.range === "Custom" ? { start_date: state.start_date, end_date: state.end_date } : {}),
  }
  const customValid =
    state.range !== "Custom" ||
    Boolean(
      state.start_date &&
        state.end_date &&
        state.end_date >= state.start_date &&
        Date.parse(state.end_date) - Date.parse(state.start_date) <= 3660 * 86400000,
    )
  const dataQuery = useQuery({
    queryKey: ["graph-fundamentals", request],
    queryFn: () => fetchGraphFundamentals(request),
    enabled: bases.length > 0 && customValid,
    staleTime: 3600000,
    retry: false,
  })
  const resolved = useMemo(
    () => (dataQuery.data ? displaySeries(state, dataQuery.data, fields) : new Map<string, DisplaySeries>()),
    [state, dataQuery.data, fields],
  )
  const displayed = useMemo(
    () => allConfigs.map((s) => resolved.get(s.id)).filter((s): s is DisplaySeries => !!s),
    [allConfigs, resolved],
  )
  const paneSeries = useMemo(
    () =>
      new Map(
        state.panes.map((p) => [p.id, p.series.map((s) => resolved.get(s.id)).filter((s): s is DisplaySeries => !!s)]),
      ),
    [state.panes, resolved],
  )
  const start = dataQuery.data?.start_date ?? "0000-01-01"
  const end = dataQuery.data?.end_date ?? null
  const dates = useMemo(() => visibleDates(displayed, start, end), [displayed, start, end])
  const rows = useMemo(() => tableRows(displayed, start, end), [displayed, start, end])
  const categories = ["All fields", ...new Set(fields.map((f) => f.category))]
  const filteredFields = fields.filter(
    (f) =>
      (category === "All fields" || category === f.category) &&
      (!search.trim() || `${f.label} ${f.category}`.toLowerCase().includes(search.toLowerCase())),
  )
  function paneTitle(field: string | undefined, index: number) {
    return field ? (fields.find((f) => f.id === field)?.label ?? field) : `Pane ${index + 1}`
  }
  const paneOptions = state.panes.map((p, i) => ({ id: p.id, label: paneTitle(p.field, i) }))
  useEffect(() => {
    const encoded = encodeChart(state)
    const timer = setTimeout(() => {
      if (params.get("chart") !== encoded) setParams({ chart: encoded }, { replace: true })
    }, 350)
    return () => clearTimeout(timer)
  }, [state, params, setParams])
  function update(change: (previous: ChartState) => ChartState) {
    setState((previous) => change(previous))
    setNotice("")
  }
  function addTicker(raw: string) {
    const ticker = raw.trim().toUpperCase()
    if (!/^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/.test(ticker)) {
      setNotice("Enter a valid ticker symbol.")
      return
    }
    if (state.tickers.includes(ticker)) {
      setNotice(`${ticker} is already in this chart.`)
      return
    }
    const templates = state.panes.filter((p) => p.field)
    if (state.tickers.length >= 6 || allConfigs.length + templates.length > 24) {
      setNotice("Charts support at most 6 tickers and 24 series.")
      return
    }
    update((previous) => ({
      ...previous,
      tickers: [...previous.tickers, ticker],
      panes: previous.panes.map((p) =>
        p.field ? { ...p, series: [...p.series, baseSeries(ticker, p.field, previous.tickers.length)] } : p,
      ),
    }))
    setSearch("")
  }
  function addField(field: FundamentalField) {
    const target = state.panes.find((p) => p.id === destination)
    const additions = state.tickers
      .filter((t) => !target?.series.some((s) => s.ticker === t && s.field === field.id))
      .map((ticker, index) => baseSeries(ticker, field.id, index))
    if ((!target && state.panes.length >= 4) || allConfigs.length + additions.length > 24) {
      setNotice("Charts support at most 4 panes and 24 series. Choose an existing pane or remove a series.")
      return
    }
    update((previous) => ({
      ...previous,
      panes: target
        ? previous.panes.map((p) => (p.id === target.id ? { ...p, series: [...p.series, ...additions] } : p))
        : [...previous.panes, { id: newId(), field: field.id, series: additions }],
    }))
    setSearch("")
    setBrowse(false)
  }
  function editSeries(id: string, patch: Partial<ChartSeries>) {
    update((previous) => ({
      ...previous,
      panes: previous.panes.map((p) => ({ ...p, series: p.series.map((s) => (s.id === id ? { ...s, ...patch } : s)) })),
    }))
  }
  function moveSeries(series: ChartSeries, target: string) {
    if (target === "new" && state.panes.length >= 4) {
      setNotice("Remove a pane before adding a fifth pane.")
      return
    }
    update((previous) => {
      const panes = previous.panes.map((p) => ({ ...p, series: p.series.filter((s) => s.id !== series.id) }))
      if (target === "new") panes.push({ id: newId(), series: [series] })
      else {
        const p = panes.find((p) => p.id === target)
        if (p) p.series.push(series)
      }
      return { ...previous, panes: panes.filter((p) => p.series.length) }
    })
  }
  function removeTicker(ticker: string) {
    if (state.tickers.length === 1) {
      setNotice("Keep at least one ticker.")
      return
    }
    update((previous) => {
      let next = previous
      for (const s of previous.panes.flatMap((p) => p.series).filter((s) => s.ticker === ticker))
        next = removeSeries(next, s.id)
      return { ...next, tickers: previous.tickers.filter((t) => t !== ticker) }
    })
  }
  async function persist(saveAs = false) {
    if (!name.trim()) {
      setNotice("Enter a name before saving.")
      return
    }
    setBusy(true)
    try {
      const result = await saveFundamentalChart(name.trim(), validateChart(state), saveAs ? undefined : chartId)
      setChartId(result.chart_id)
      setNotice(`Saved ${result.name}.`)
      await queryClient.invalidateQueries({ queryKey: ["fundamental-charts"] })
    } catch (error) {
      setNotice(String(error))
    } finally {
      setBusy(false)
    }
  }
  async function openSaved(id: string) {
    if (!id) return
    setBusy(true)
    try {
      const result = await fetchFundamentalChart(id)
      setState(validateChart(result.state))
      setChartId(id)
      setName(result.name)
      setNotice("Chart opened; values refresh from current sources.")
    } catch (error) {
      setNotice(String(error))
    } finally {
      setBusy(false)
    }
  }
  async function removeSaved() {
    if (!chartId) return
    setBusy(true)
    try {
      await deleteFundamentalChart(chartId)
      setChartId(undefined)
      setName("")
      setNotice("Saved chart deleted.")
      await queryClient.invalidateQueries({ queryKey: ["fundamental-charts"] })
    } catch (error) {
      setNotice(String(error))
    } finally {
      setBusy(false)
    }
  }
  async function share() {
    const url = new URL(window.location.href)
    try {
      url.search = new URLSearchParams({ chart: encodeChart(validateChart(state)) }).toString()
    } catch (error) {
      setNotice(String(error))
      return
    }
    try {
      await navigator.clipboard.writeText(url.href)
      setNotice("Chart link copied. Recipients must already be able to sign in.")
    } catch {
      setNotice(`Copy this chart link: ${url.href}`)
    }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([chartCsv(displayed, start, end)], { type: "text/csv;charset=utf-8" }))
    const a = document.createElement("a")
    a.href = url
    a.download = "graph-fundamentals.csv"
    a.click()
    URL.revokeObjectURL(url)
  }
  function addArithmetic() {
    const a = resolved.get(operandA),
      b = resolved.get(operandB)
    if (!a || !b) {
      setNotice("Choose two series with loaded data.")
      return
    }
    if (allConfigs.length >= 24 || (destination === "new" && state.panes.length >= 4)) {
      setNotice("Charts support 4 panes and 24 series.")
      return
    }
    const series: ChartSeries = {
      ...baseSeries("", "", allConfigs.length),
      ticker: undefined,
      field: undefined,
      a: operandA,
      b: operandB,
      operation,
      label: arithmeticLabel,
    }
    try {
      arithmetic(a, b, series)
    } catch (error) {
      setNotice(String(error))
      return
    }
    update((previous) => ({
      ...previous,
      panes:
        destination === "new" || !previous.panes.some((p) => p.id === destination)
          ? [...previous.panes, { id: newId(), series: [series] }]
          : previous.panes.map((p) => (p.id === destination ? { ...p, series: [...p.series, series] } : p)),
    }))
    setArithmeticOpen(false)
  }
  return (
    <div className="space-y-4">
      <PageHeader
        title="Graph Fundamentals"
        eyebrow="Compare businesses"
        subtitle="Reported fundamentals, historical valuations and peer comparisons on one timeline."
        actions={
          <>
            <button
              className={button}
              onClick={() => {
                setState(defaultChart())
                setChartId(undefined)
                setName("")
                setNotice("")
              }}
            >
              Reset chart
            </button>
            <button
              className={button}
              onClick={() => {
                void share()
              }}
              disabled={!allConfigs.length}
            >
              <Share2 size={13} />
              Share
            </button>
            <button className={button} onClick={download} disabled={!displayed.length}>
              <Download size={13} />
              Export CSV
            </button>
          </>
        }
      />
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-3">
        <label className="grid gap-1 text-xs text-muted">
          Range
          <select
            className={control}
            value={state.range}
            onChange={(e) => update((p) => ({ ...p, range: e.target.value as GraphRange }))}
          >
            {["Auto", "1Y", "3Y", "5Y", "10Y", "Custom"].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        {state.range === "Custom" ? (
          <>
            <label className="grid gap-1 text-xs text-muted">
              Start date
              <input
                className={control}
                type="date"
                value={state.start_date ?? ""}
                onChange={(e) => update((p) => ({ ...p, start_date: e.target.value }))}
              />
            </label>
            <label className="grid gap-1 text-xs text-muted">
              End date
              <input
                className={control}
                type="date"
                value={state.end_date ?? ""}
                onChange={(e) => update((p) => ({ ...p, end_date: e.target.value }))}
              />
            </label>
          </>
        ) : null}
        <label className="grid gap-1 text-xs text-muted">
          Period
          <select
            className={control}
            value={state.period}
            onChange={(e) => update((p) => ({ ...p, period: e.target.value as Period }))}
          >
            <option value="quarters">Quarters</option>
            <option value="ltm">LTM</option>
            <option value="annual">Annual</option>
          </select>
        </label>
        <div className="flex gap-1" role="group" aria-label="View">
          <button
            className={`${button} ${view === "chart" ? "border-sky-500 text-sky-400" : ""}`}
            aria-pressed={view === "chart"}
            onClick={() => setView("chart")}
          >
            Chart
          </button>
          <button
            className={`${button} ${view === "table" ? "border-sky-500 text-sky-400" : ""}`}
            aria-pressed={view === "table"}
            onClick={() => setView("table")}
          >
            Table
          </button>
        </div>
        <div className="ml-auto text-xs text-muted">
          {state.tickers.length}/6 tickers · {state.panes.length}/4 panes · {allConfigs.length}/24 series
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          className={`${control} min-w-44`}
          aria-label="Chart name"
          placeholder="Name this chart"
          value={name}
          maxLength={160}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          className={button}
          disabled={busy || !allConfigs.length}
          onClick={() => {
            void persist()
          }}
        >
          <Save size={13} />
          Save
        </button>
        <button
          className={button}
          disabled={busy || !allConfigs.length}
          onClick={() => {
            void persist(true)
          }}
        >
          Save As
        </button>
        <label className="sr-only" htmlFor="saved-fundamental-chart">
          Saved charts
        </label>
        <select
          id="saved-fundamental-chart"
          className={control}
          value={saved.data?.some((c) => c.chart_id === chartId) ? chartId : ""}
          disabled={busy}
          onChange={(e) => {
            void openSaved(e.target.value)
          }}
        >
          <option value="">Open saved chart…</option>
          {saved.data?.map((c) => (
            <option key={c.chart_id} value={c.chart_id}>
              {c.name}
            </option>
          ))}
        </select>
        <button
          className={button}
          title="Delete saved chart"
          aria-label="Delete saved chart"
          disabled={!chartId || busy}
          onClick={() => {
            void removeSaved()
          }}
        >
          <Trash2 size={13} />
        </button>
        {chartId ? (
          <button
            className={button}
            disabled={busy}
            onClick={() => {
              void persist()
            }}
          >
            Rename to current name
          </button>
        ) : null}
        {savedOffset > 0 ? (
          <button className={button} onClick={() => setSavedOffset((p) => Math.max(0, p - 50))}>
            Previous saved
          </button>
        ) : null}
        {saved.data?.length === 50 ? (
          <button className={button} onClick={() => setSavedOffset((p) => p + 50)}>
            More saved
          </button>
        ) : null}
      </div>
      {notice ? (
        <p role="status" className="break-all rounded-lg border border-border bg-surface p-3 text-sm">
          {notice}
        </p>
      ) : null}
      {!customValid ? (
        <p role="alert" className="text-sm text-amber-500">
          Choose start and end dates in order, no more than ten years apart.
        </p>
      ) : null}
      {catalogQuery.error || dataQuery.error || saved.error ? (
        <p role="alert" className="text-sm text-red-400">
          {String(catalogQuery.error ?? dataQuery.error ?? saved.error)}{" "}
          <button
            className="underline"
            onClick={() => {
              void catalogQuery.refetch()
              void dataQuery.refetch()
              void saved.refetch()
            }}
          >
            Retry
          </button>
        </p>
      ) : null}
      <div className="grid min-w-0 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="order-2 space-y-3 lg:order-1" aria-label="Series editor">
          <div className="rounded-xl border border-border bg-surface p-3">
            <label className="mb-1 block text-xs font-semibold" htmlFor="fundamental-search">
              Add securities or fields
            </label>
            <input
              id="fundamental-search"
              className={`${control} w-full`}
              value={search}
              placeholder="Ticker, company or metric…"
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && search.trim()) {
                  e.preventDefault()
                  addTicker(search)
                }
              }}
            />
            <label className="mt-2 block text-xs text-muted">
              Add fields to
              <select
                className={`${control} mt-1 w-full`}
                value={state.panes.some((p) => p.id === destination) ? destination : "new"}
                onChange={(e) => setDestination(e.target.value)}
              >
                <option value="new">New pane</option>
                {paneOptions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            {search.trim() ? (
              <div
                className="mt-2 max-h-72 space-y-1 overflow-y-auto rounded-md border border-border p-2"
                role="region"
                aria-label="Securities and fields suggestions"
              >
                <p className="text-[10px] font-semibold uppercase text-muted">Securities</p>
                {securities.data?.map((s) => (
                  <button
                    key={s.ticker}
                    className="block w-full rounded px-1 py-1 text-left text-xs hover:bg-surface-hover"
                    onClick={() => addTicker(s.ticker)}
                  >
                    <strong>{s.ticker}</strong> · {s.name}
                  </button>
                ))}
                <button className="block text-xs text-sky-400" onClick={() => addTicker(search)}>
                  Add ticker {search.toUpperCase()}
                </button>
                <p className="pt-2 text-[10px] font-semibold uppercase text-muted">Fields</p>
                {filteredFields.slice(0, 10).map((f) => (
                  <button
                    key={f.id}
                    className="block w-full rounded px-1 py-1 text-left text-xs hover:bg-surface-hover"
                    onClick={() => addField(f)}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            ) : null}
            <button className="mt-2 text-xs text-sky-400 hover:underline" onClick={() => setBrowse((p) => !p)}>
              Browse all fields…
            </button>
            {browse ? (
              <div className="mt-2 space-y-2">
                <select
                  aria-label="Field category"
                  className={`${control} w-full`}
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  {categories.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
                <div className="max-h-64 overflow-y-auto">
                  {filteredFields.map((f) => (
                    <button
                      key={f.id}
                      title={f.formula}
                      className="block w-full rounded p-2 text-left text-xs hover:bg-surface-hover"
                      onClick={() => addField(f)}
                    >
                      {f.label}
                      <span className="ml-1 text-[10px] text-muted">{f.unit}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-1">
            {state.tickers.map((t, i) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs"
                style={{ color: baseSeriesColor(i) }}
              >
                {t}
                <button aria-label={`Remove ticker ${t}`} onClick={() => removeTicker(t)} className="ml-1 text-muted">
                  ×
                </button>
              </span>
            ))}
          </div>
          {state.panes.map((pane, index) => (
            <section key={pane.id} className="space-y-2 rounded-xl border border-border p-3">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold">{paneTitle(pane.field, index)}</h2>
                <button
                  className="text-[10px] text-muted hover:text-red-400"
                  onClick={() =>
                    update((previous) => {
                      let next = previous
                      for (const s of pane.series) next = removeSeries(next, s.id)
                      return next
                    })
                  }
                >
                  Remove pane
                </button>
              </div>
              {pane.series.map((s) => (
                <SeriesEditor
                  key={s.id}
                  series={s}
                  fields={fields}
                  paneId={pane.id}
                  panes={paneOptions}
                  onChange={(patch) => editSeries(s.id, patch)}
                  onRemove={() => update((p) => removeSeries(p, s.id))}
                  onMove={(target) => moveSeries(s, target)}
                />
              ))}
            </section>
          ))}
          <button className={`${button} w-full`} onClick={() => setArithmeticOpen((p) => !p)}>
            <Plus size={13} />
            Add spread or ratio
          </button>
          {arithmeticOpen ? (
            <div className="space-y-2 rounded-xl border border-border p-3">
              <label className="block text-xs">
                Series A
                <select className={`${control} w-full`} value={operandA} onChange={(e) => setOperandA(e.target.value)}>
                  <option value="">Choose series</option>
                  {displayed.map((s) => (
                    <option key={s.config.id} value={s.config.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs">
                Operation
                <select
                  className={`${control} w-full`}
                  value={operation}
                  onChange={(e) => setOperation(e.target.value as typeof operation)}
                >
                  <option value="subtract">A − B</option>
                  <option value="divide">A / B</option>
                  <option value="add">A + B</option>
                  <option value="multiply">A × B</option>
                </select>
              </label>
              <label className="block text-xs">
                Series B
                <select className={`${control} w-full`} value={operandB} onChange={(e) => setOperandB(e.target.value)}>
                  <option value="">Choose series</option>
                  {displayed.map((s) => (
                    <option key={s.config.id} value={s.config.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs">
                Result label
                <input
                  className={`${control} w-full`}
                  value={arithmeticLabel}
                  maxLength={160}
                  onChange={(e) => setArithmeticLabel(e.target.value)}
                />
              </label>
              <p className="text-[10px] text-muted">Result uses the “Add fields to” destination above.</p>
              <button className={button} onClick={addArithmetic}>
                Add calculated series
              </button>
            </div>
          ) : null}
        </aside>
        <main className="order-1 min-w-0 space-y-3 lg:order-2" aria-label="Fundamental comparisons">
          {dataQuery.isFetching ? (
            <p role="status" className="rounded-lg border border-border p-6 text-center text-sm text-muted">
              Loading fundamentals once per ticker…
            </p>
          ) : null}
          {state.panes.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-12 text-center text-sm text-muted">
              Choose a field to create a pane.
            </div>
          ) : null}
          {view === "chart" ? (
            state.panes.map((pane, i) => (
              <FundamentalPane
                key={pane.id}
                title={paneTitle(pane.field, i)}
                series={paneSeries.get(pane.id)!}
                dates={dates}
                syncId={syncId}
                bottom={i === state.panes.length - 1}
                period={state.period}
              />
            ))
          ) : (
            <div className="max-h-[900px] overflow-auto rounded-xl border border-border">
              <table className="w-full whitespace-nowrap text-xs">
                <caption className="p-3 text-left text-muted">
                  Values match the chart and CSV. Estimates are marked in period rows; full precision is exported.
                </caption>
                <thead className="sticky top-0 bg-surface">
                  <tr>
                    <th className="p-3 text-left">Period end</th>
                    {displayed.map((s) => (
                      <th key={s.config.id} className="p-3 text-right" style={{ color: s.config.color }}>
                        {s.label}
                        <div className="font-normal text-muted">
                          {s.currency} {s.unit}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={String(row.date)} className="border-t border-border">
                      <th className="p-3 text-left font-normal">
                        {row.date}
                        {displayed.some((s) => s.points.some((p) => p.date === row.date && p.estimate))
                          ? " · Estimate"
                          : ""}
                      </th>
                      {displayed.map((s) => {
                        const point = s.points.find((p) => p.date === row.date)
                        return (
                          <td key={s.config.id} className="p-3 text-right" title={point?.reason ?? s.formula}>
                            {formatValue(row[s.config.id] as number | null, s.unit, s.currency)}
                            {point?.estimate ? " E" : ""}
                            {point?.filing_url ? (
                              <a
                                className="ml-1 text-sky-400"
                                href={point.filing_url}
                                target="_blank"
                                rel="noreferrer"
                                aria-label={`Filing for ${s.label} ${row.date}`}
                              >
                                ↗
                              </a>
                            ) : null}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[11px] leading-relaxed text-muted">
            Actuals: SEC EDGAR, with labeled yfinance statement fallback. Market values are computed from historical
            prices and reported shares. Values use reported currencies; no FX conversion. Dotted tails: yfinance
            EPS/revenue consensus, observed when fetched; accounting basis may differ from GAAP actuals. No LTM or
            derived estimates. Quarter returns use quarterly flows; LTM and Annual returns use annual flows. Filing
            selection follows Financials; this is not a point-in-time backtest.
          </p>
        </main>
      </div>
    </div>
  )
}
function baseSeriesColor(i: number) {
  return ["#38bdf8", "#a78bfa", "#fbbf24", "#34d399", "#fb7185", "#fb923c"][i % 6]
}
