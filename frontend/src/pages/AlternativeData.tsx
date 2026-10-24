import { useMemo, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useSearchParams } from "react-router-dom"
import { ArrowUpRight, Check, Database, Loader2, MapPin, Search } from "lucide-react"
import { PageHeader } from "@/components/shared/PageHeader"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { TimeSeriesChart } from "@/components/shared/TimeSeriesChart"
import {
  confirmAlternativeDataSite, fetchAlternativeDataCatalog, removeAlternativeDataSite, runAlternativeDataQuery, suggestAlternativeDataSites,
  confirmAlternativeDataMapping, removeAlternativeDataMapping,
  type AlternativeCitation, type AlternativeResult, type AlternativeSite, type AlternativeSource, type AlternativeMapping,
} from "@/lib/api"

const inputClass = "theme-input min-h-10 w-full rounded-lg border border-app bg-card px-3 py-2 text-sm"
const buttonClass = "theme-button-base theme-button-secondary min-h-10 px-3 text-sm disabled:opacity-50"

function CitationLinks({ citations }: { citations: AlternativeCitation[] }) {
  return <ul className="flex flex-wrap gap-x-4 gap-y-2 text-xs">{citations.map((c, i) =>
    <li key={`${c.url}-${i}`}><a href={c.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent underline underline-offset-2">
      {c.title}<ArrowUpRight className="h-3 w-3" /></a></li>)}</ul>
}

function displayDate(value?: string | null) {
  if (!value) return "Not reported"
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(`${value}T00:00:00`).toLocaleDateString()
    : new Date(value).toLocaleString()
}

function chartDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value
}

function AlternativeDataResultView({ result }: { result: AlternativeResult }) {
  const [chosenMetric, setChosenMetric] = useState<string | null>(null)
  const { metrics, metric, series, chartData } = useMemo(() => {
    const metrics = [...new Set(result.observations.map(r => r.metric))]
    const metric = chosenMetric && metrics.includes(chosenMetric) ? chosenMetric : metrics[0]
    const series = result.observations.filter(r => r.metric === metric)
    return { metrics, metric, series, chartData: series.map(r => ({ date: chartDate(r.date), value: r.value })) }
  }, [result.observations, chosenMetric])
  return <SurfaceCard className="space-y-5 p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="section-title">Source result</h2><p className="mt-1 text-xs text-muted">{result.attribution}</p></div>
      <span className="rounded-full border border-app px-3 py-1 text-xs">{result.status.replace(/_/g, " ")}</span></div>
    <dl className="grid gap-4 text-sm sm:grid-cols-3">
      <div><dt className="text-xs text-subtle">Observed through</dt><dd>{displayDate(result.as_of)}</dd></div>
      <div><dt className="text-xs text-subtle">Retrieved</dt><dd>{displayDate(result.fetched_at)}</dd></div>
      <div><dt className="text-xs text-subtle">Freshness</dt><dd>{result.freshness?.stale ? "Stale observations" : result.freshness?.status === "known" ? "Within source allowance" : "Unknown"}</dd></div>
    </dl>
    {result.warnings?.length ? <ul className="space-y-2 rounded-lg border border-app bg-card-muted p-3 text-sm text-muted">{
      result.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul> : null}
    {result.availability?.missing_credentials.length ? <p className="text-sm text-muted">Required credentials: {result.availability.missing_credentials.join(", ")}</p> : null}
    {metrics.length > 0 ? <>
      <label className="block text-sm">Measurement<select aria-label="Measurement" className={`${inputClass} mt-1`} value={metric} onChange={e => setChosenMetric(e.target.value)}>
        {metrics.map(m => <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}</select></label>
      <TimeSeriesChart data={chartData} label={metric} height={260} timeframe="1y" />
      <div className="max-h-72 overflow-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">Date</th><th className="p-2">Value</th><th className="p-2">Unit</th><th className="p-2">Coverage / dimensions</th></tr></thead>
        <tbody>{series.map((r, i) => <tr key={`${r.date}-${i}`} className="border-t border-app"><td className="p-2">{r.date}</td><td className="p-2">{r.value == null ? "Insufficient data" : r.value.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td><td className="p-2">{r.unit}</td><td className="p-2">{r.dimensions ? JSON.stringify(r.dimensions) : "—"}</td></tr>)}</tbody>
      </table></div>
    </> : null}
    {result.snapshot ? <SnapshotView snapshot={result.snapshot} /> : null}
    {result.status === "empty" ? <p className="text-sm text-muted">No observations matched this query. Missing data are not zero.</p> : null}
    <CitationLinks citations={result.citations} />
  </SurfaceCard>
}

function SnapshotView({ snapshot }: { snapshot: Record<string, unknown> }) {
  const rows = Object.entries(snapshot).find(([, value]) => Array.isArray(value))
  const items = rows?.[1] as Record<string, unknown>[] | undefined
  if (items?.length && typeof items[0] === "object") {
    const columns = [...new Set(items.flatMap(item => Object.keys(item)))].filter(k => !["footprint", "tags"].includes(k)).slice(0, 8)
    return <div className="max-h-96 overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{columns.map(k => <th key={k} className="whitespace-nowrap p-2">{k.replace(/_/g, " ")}</th>)}</tr></thead>
      <tbody>{items.map((item, i) => <tr key={i} className="border-t border-app">{columns.map(k => <td key={k} className="max-w-64 break-words p-2">{
        typeof item[k] === "string" && /^https:\/\//.test(item[k] as string)
          ? <a className="text-accent underline" href={item[k] as string} target="_blank" rel="noreferrer">Open source</a>
          : typeof item[k] === "object" ? JSON.stringify(item[k]) : String(item[k] ?? "—")}</td>)}</tr>)}</tbody>
    </table></div>
  }
  return <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-card-muted p-3 text-xs">{JSON.stringify(snapshot, null, 2)}</pre>
}

function initialParameters(source: AlternativeSource, encoded?: string | null): Record<string, string> {
  const values: Record<string, string> = {}
  for (const [key, field] of Object.entries(source.parameter_schema.properties)) if (field.default != null) values[key] = String(field.default)
  if (encoded) {
    try { for (const [key, value] of Object.entries(JSON.parse(encoded))) values[key] = Array.isArray(value) ? value.join(", ") : String(value) } catch { /* Ignore invalid share-link parameters. */ }
  }
  return values
}

function SourceQuery({ source, ticker, sites, mappings, encoded }: { source: AlternativeSource; ticker: string; sites: AlternativeSite[]; mappings: AlternativeMapping[]; encoded?: string | null }) {
  const [values, setValues] = useState(() => initialParameters(source, encoded))
  const query = useMutation({ mutationFn: runAlternativeDataQuery })
  const state = source.operations?.[values.operation] ?? source.availability
  const blocked = source.access === "unavailable" || !["ready", "bulk_only", "unavailable"].includes(state.status)
  const hasGeography = "bbox" in source.parameter_schema.properties
  const needsSite = hasGeography && (Boolean(ticker) || values.operation === "indices") && !values.site_id
  function submit(event: FormEvent) {
    event.preventDefault()
    const parameters: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values)) {
      if (!value.trim() || (key === "bbox" && values.site_id)) continue
      const field = source.parameter_schema.properties[key]
      if (!field) continue
      parameters[key] = field.type === "integer" ? Number(value) : field.type === "array" ? value.split(",").map(v => Number(v.trim())) : value
    }
    query.mutate({ source_id: source.source_id, parameters, ticker: ticker || undefined })
  }
  return <div className="space-y-5">
    <SurfaceCard className="space-y-5 p-5">
      <div><p className="theme-eyebrow">{source.group_label}</p><h2 className="mt-1 text-xl font-semibold">{source.name}</h2><p className="mt-2 text-sm text-muted">{source.question}</p></div>
      <p className="text-sm text-muted">{source.coverage}</p><p className="text-xs text-subtle">Updates: {source.cadence}</p>
      <form onSubmit={submit} className="space-y-4"><div className="grid gap-4 sm:grid-cols-2">{Object.entries(source.parameter_schema.properties).map(([key, field]) => {
        if (source.reviewed_field && key === source.reviewed_field) return null
        if (key === "mapping_id") return <label key={key} className="block text-sm">Reviewed {source.reviewed_field}
          <select aria-label="Reviewed company mapping" className={`${inputClass} mt-1`} value={values.mapping_id ?? ""} onChange={e => setValues(previous => ({ ...previous, mapping_id: e.target.value }))}>
            <option value="">Select a reviewed mapping</option>{mappings.filter(m => m.source_id === source.source_id).map(m => <option key={m.mapping_id} value={m.mapping_id}>{m.value}</option>)}
          </select></label>
        if ((key === "bbox" && ticker) || (key === "site_id" && !ticker && !sites.length)) return null
        const label = key.replace(/_/g, " ")
        const change = (value: string) => setValues(previous => ({ ...previous, [key]: value }))
        return <label key={key} className="block text-sm capitalize">{label}{source.parameter_schema.required.includes(key) ? " *" : ""}
          {key === "site_id" ? <select aria-label="Confirmed site" className={`${inputClass} mt-1`} value={values[key] ?? ""} onChange={e => change(e.target.value)}>
            <option value="">Select a confirmed site</option>{sites.map(site => <option key={site.site_id} value={site.site_id}>{site.name}</option>)}</select>
            : field.enum ? <select aria-label={label} className={`${inputClass} mt-1`} value={values[key] ?? ""} onChange={e => change(e.target.value)}>{field.enum.map(value => <option key={value}>{value}</option>)}</select>
              : <input aria-label={label} className={`${inputClass} mt-1`} type={field.format === "date" ? "date" : field.type === "integer" ? "number" : "text"}
                  min={field.minimum} max={field.maximum} value={values[key] ?? ""} placeholder={key === "bbox" ? "west, south, east, north" : ""}
                  required={source.parameter_schema.required.includes(key)} onChange={e => change(e.target.value)} />}
          <span className="mt-1 block text-xs normal-case text-subtle">{field.description}</span>
        </label>
      })}</div>
        <div className="rounded-lg border border-app bg-card-muted p-3 text-sm text-muted">{state.message || source.notes}
          {state.missing_credentials.length ? <p className="mt-2">Setup required: {state.missing_credentials.join(", ")}. Add credentials to the server's Secret Manager configuration.</p> : null}
          {needsSite ? <p className="mt-2">Confirm a company site below before requesting geographic measurements.</p> : null}</div>
        <button className={buttonClass} type="submit" disabled={blocked || needsSite || query.isPending}>{query.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}{query.isPending ? "Fetching source…" : "Fetch data"}</button>
        {query.error ? <p role="alert" className="text-sm text-negative">{String(query.error)}</p> : null}
      </form>
      {source.reviewed_field ? <CompanyMappingReview source={source} ticker={ticker} mappings={mappings.filter(m => m.source_id === source.source_id)} /> : null}
      <CitationLinks citations={[{ title: "Official source", url: source.url }, { title: "License and access", url: source.license_url }]} />
    </SurfaceCard>
    {query.data ? <AlternativeDataResultView result={query.data} /> : null}
  </div>
}

function CompanyMappingReview({ source, ticker, mappings }: { source: AlternativeSource; ticker: string; mappings: AlternativeMapping[] }) {
  const client = useQueryClient()
  const [value, setValue] = useState("")
  const [citation, setCitation] = useState("")
  const confirm = useMutation({
    mutationFn: confirmAlternativeDataMapping,
    onSuccess: () => { setValue(""); setCitation(""); void client.invalidateQueries({ queryKey: ["alternative-data-catalog"] }) },
  })
  const remove = useMutation({ mutationFn: removeAlternativeDataMapping, onSuccess: () => { void client.invalidateQueries({ queryKey: ["alternative-data-catalog"] }) } })
  if (!ticker) return <p className="text-sm text-muted">Enter a company ticker to review an exact {source.reviewed_field} mapping. Company names and article titles are never guessed from tickers. Federal Register agency searches can run without a company.</p>
  return <section className="space-y-3 border-t border-app pt-4" aria-label="Review company mapping">
    <p className="text-sm text-muted">Confirm the exact {source.reviewed_field} used by this source and cite evidence connecting it to {ticker}.</p>
    {mappings.map(mapping => <div key={mapping.mapping_id} className="space-y-2 rounded-lg border border-app p-3">
      <div className="flex items-center justify-between gap-3"><span className="text-sm">{mapping.value} · reviewed</span>
        <button type="button" className="text-xs underline" disabled={remove.isPending} onClick={() => remove.mutate(mapping.mapping_id)}>Remove mapping</button></div>
      <CitationLinks citations={mapping.citations} />
    </div>)}
    <form className="grid gap-3 sm:grid-cols-2" onSubmit={event => { event.preventDefault(); confirm.mutate({ ticker, source_id: source.source_id, value, citations: [{ title: "Reviewed company relationship", url: citation }] }) }}>
      <label className="text-sm">Exact {source.reviewed_field}<input aria-label="Exact reviewed name or title" className={`${inputClass} mt-1`} required maxLength={160} value={value} onChange={e => setValue(e.target.value)} /></label>
      <label className="text-sm">Evidence URL<input aria-label="Mapping evidence URL" type="url" className={`${inputClass} mt-1`} required value={citation} onChange={e => setCitation(e.target.value)} /></label>
      <button type="submit" className={buttonClass} disabled={confirm.isPending}>Confirm company mapping</button>
    </form>
    {confirm.isError || remove.isError ? <p role="alert" className="text-sm text-negative">{String(confirm.error ?? remove.error)}</p> : null}
  </section>
}

function CompanySites({ ticker, sites, proposals }: { ticker: string; sites: AlternativeSite[]; proposals: AlternativeSite[] }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState("")
  const [area, setArea] = useState("")
  const [citation, setCitation] = useState("")
  const suggest = useMutation({ mutationFn: suggestAlternativeDataSites, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alternative-data-catalog", ticker] }) })
  const confirm = useMutation({ mutationFn: confirmAlternativeDataSite, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alternative-data-catalog", ticker] }) })
  const remove = useMutation({ mutationFn: removeAlternativeDataSite, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alternative-data-catalog", ticker] }) })
  const candidates = suggest.data?.proposals ?? proposals
  const shown = candidates.filter(candidate => !sites.some(site => site.proposal_id === candidate.proposal_id))
  return <SurfaceCard className="space-y-4 p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="section-title">Company sites · {ticker}</h2><p className="mt-1 text-sm text-muted">Review cited ownership and coordinates before confirming a site.</p></div>
      <button type="button" className={buttonClass} disabled={suggest.isPending} onClick={() => suggest.mutate(ticker)}>{suggest.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <MapPin className="h-4 w-4" />}Suggest sites</button></div>
    {sites.map(site => <div key={site.site_id} className="rounded-lg border border-app p-3"><div className="flex items-center justify-between gap-3"><p className="flex items-center gap-2 text-sm"><Check className="h-4 w-4 text-positive" />{site.name} · confirmed</p><button type="button" className="text-xs text-muted underline" disabled={remove.isPending} onClick={() => site.site_id && remove.mutate(site.site_id)}>Remove site</button></div><p className="my-2 text-xs text-subtle">{site.bbox.join(", ")}</p><CitationLinks citations={site.citations} /></div>)}
    {shown.map(site => <div key={site.proposal_id} className="space-y-3 rounded-lg border border-app p-3"><h3 className="font-medium">{site.name}</h3><p className="text-xs text-muted">Proposed area: {site.bbox.join(", ")}</p><CitationLinks citations={site.citations} />
      <button type="button" className={buttonClass} disabled={confirm.isPending} onClick={() => confirm.mutate({ ticker, name: site.name, bbox: site.bbox, citations: site.citations, proposal_id: site.proposal_id })}>Confirm site</button></div>)}
    {suggest.data && !candidates.length ? <p className="text-sm text-muted">No sites with verified citations were proposed. Enter a known site below.</p> : null}
    <details className="rounded-lg border border-app p-3"><summary className="cursor-pointer text-sm font-medium">Confirm a known site</summary>
      <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={event => { event.preventDefault(); confirm.mutate({ ticker, name, bbox: area.split(",").map(Number), citations: citation ? [{ title: "Site ownership reference", url: citation }] : [] }) }}>
        <label className="text-sm">Site name<input className={`${inputClass} mt-1`} required value={name} onChange={e => setName(e.target.value)} /></label>
        <label className="text-sm">Area bounds<input className={`${inputClass} mt-1`} required placeholder="west, south, east, north" value={area} onChange={e => setArea(e.target.value)} /></label>
        <label className="text-sm sm:col-span-2">Ownership reference (optional)<input type="url" className={`${inputClass} mt-1`} placeholder="https://…" value={citation} onChange={e => setCitation(e.target.value)} /></label>
        <p className="text-xs text-subtle sm:col-span-2">By confirming, you associate this area with {ticker}. Maximum 25 km² per site and five sites per company.</p><button className={buttonClass} disabled={confirm.isPending} type="submit">Confirm entered site</button>
      </form>
    </details>
    {suggest.error || confirm.error || remove.error ? <p role="alert" className="text-sm text-negative">{String(suggest.error ?? confirm.error ?? remove.error)}</p> : null}
  </SurfaceCard>
}

export function AlternativeData() {
  const [searchParams, setSearchParams] = useSearchParams()
  const ticker = searchParams.get("ticker") || ""
  const [tickerDraft, setTickerDraft] = useState(ticker)
  const [search, setSearch] = useState("")
  const [group, setGroup] = useState("")
  const [available, setAvailable] = useState(false)
  const catalog = useQuery({ queryKey: ["alternative-data-catalog", ticker], queryFn: () => fetchAlternativeDataCatalog(ticker), staleTime: 30_000 })
  const selectedId = searchParams.get("source")
  const selected = catalog.data?.sources.find(s => s.source_id === selectedId)
  const filtered = useMemo(() => (catalog.data?.sources ?? []).filter(source => (!group || source.group === group) && (!available || source.availability.status === "ready") &&
    `${source.name} ${source.question} ${source.coverage}`.toLowerCase().includes(search.toLowerCase())), [catalog.data, group, available, search])
  function selectSource(source: AlternativeSource) { setSearchParams(previous => { const next = new URLSearchParams(previous); next.set("source", source.source_id); next.delete("parameters"); return next }) }
  return <div className="space-y-6">
    <PageHeader eyebrow="Shared research sources" title="Alternative Data" subtitle="Find evidence for a company question. Every result includes source links, observation dates, and coverage limitations." />
    <SurfaceCard className="flex flex-wrap items-end gap-3 p-4">
      <form className="flex items-end gap-2" onSubmit={event => { event.preventDefault(); setSearchParams(previous => { const next = new URLSearchParams(previous); if (tickerDraft.trim()) next.set("ticker", tickerDraft.trim().toUpperCase()); else next.delete("ticker"); return next }) }}>
        <label className="text-xs text-muted">Company ticker<input className={`${inputClass} mt-1 max-w-44 uppercase`} placeholder="Optional, e.g. MSFT" value={tickerDraft} onChange={e => setTickerDraft(e.target.value)} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9.=-]*" /></label><button className={buttonClass}>Use company</button>
      </form>
      <label className="min-w-48 flex-1 text-xs text-muted">Search sources<div className="relative mt-1"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4" /><input aria-label="Search alternative data" className={`${inputClass} pl-9`} placeholder="Question, source, or coverage" value={search} onChange={e => setSearch(e.target.value)} /></div></label>
      <label className="text-xs text-muted">Question group<select aria-label="Question group" className={`${inputClass} mt-1`} value={group} onChange={e => setGroup(e.target.value)}><option value="">All questions</option>{Object.entries(catalog.data?.groups ?? {}).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={available} onChange={e => setAvailable(e.target.checked)} />Ready sources</label>
    </SurfaceCard>
    {catalog.isPending ? <p role="status" className="text-sm text-muted">Loading source catalog…</p> : null}{catalog.error ? <p role="alert" className="text-negative">{String(catalog.error)}</p> : null}
    <div className="grid items-start gap-5 xl:grid-cols-[21rem_minmax(0,1fr)]"><div className="space-y-5">{Object.entries(catalog.data?.groups ?? {}).map(([key, label]) => {
      const sources = filtered.filter(s => s.group === key)
      return sources.length ? <section key={key}><h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-subtle">{label}</h2><div className="space-y-2">{sources.map(source =>
        <button key={source.source_id} type="button" onClick={() => selectSource(source)} aria-pressed={source.source_id === selectedId} className={`w-full rounded-xl border p-4 text-left transition-colors ${source.source_id === selectedId ? "border-accent bg-card-muted" : "border-app bg-card hover:bg-card-muted"}`}>
          <span className="block text-sm font-semibold">{source.name}</span><span className="mt-1 block text-xs leading-relaxed text-muted">{source.question}</span><span className="mt-3 block text-xs text-subtle">{source.availability.status.replace(/_/g, " ")}{source.latest_result?.as_of ? ` · ${source.latest_result.as_of.slice(0, 10)}` : ""}</span>
        </button>)}</div></section> : null
    })}{catalog.data && !filtered.length ? <p className="text-sm text-muted">No matching sources. Try another question or availability filter.</p> : null}</div>
      <div className="min-w-0 space-y-5">{selected ? <SourceQuery key={`${selected.source_id}:${ticker}`} source={selected} ticker={ticker} sites={catalog.data?.sites ?? []} mappings={catalog.data?.reviewed_mappings ?? []} encoded={searchParams.get("parameters")} />
        : <SurfaceCard className="p-8"><Database className="mb-4 h-7 w-7 text-accent" /><h2 className="section-title">Choose the question, then the source</h2><p className="mt-3 max-w-xl text-sm leading-relaxed text-muted">Browse a series, inspect a physical site, or follow a trade flow. Source availability and freshness travel with the evidence into chat, research, and analyzer briefs.</p>{ticker ? <Link className="mt-4 inline-block text-sm text-accent underline" to={`/dossier/${encodeURIComponent(ticker)}`}>Open company dossier</Link> : null}</SurfaceCard>}
        {ticker ? <CompanySites key={ticker} ticker={ticker} sites={catalog.data?.sites ?? []} proposals={catalog.data?.site_proposals ?? []} /> : null}
      </div>
    </div>
  </div>
}
