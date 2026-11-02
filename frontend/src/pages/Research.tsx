import { useDeferredValue, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import * as Dialog from "@radix-ui/react-dialog"
import { ArrowUpRight, FileText, Search, Upload, X } from "lucide-react"
import { PageHeader } from "@/components/shared/PageHeader"
import { ErrorMessage, LoadingSpinner } from "@/components/shared/LoadingSpinner"
import { fetchResearch, RESEARCH_CATEGORIES, uploadResearch, type ResearchCategory, type ResearchFilters, type ResearchReport } from "@/lib/api"

const active = new Set(["queued", "reading", "condensing", "checking"])
const labels: Record<string, string> = { queued: "Queued", reading: "Reading PDF", condensing: "Condensing", checking: "Checking", ready: "Ready", needs_review: "Needs review", failed: "Failed" }
const inputClass = "min-h-10 rounded-lg border border-app bg-input px-3 text-sm text-app"

function UploadResearch({ onUploaded }: { onUploaded: (id: string, duplicate: boolean) => void }) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [category, setCategory] = useState<ResearchCategory | "">("")
  const [fileError, setFileError] = useState("")
  const upload = useMutation({ mutationFn: () => uploadResearch(file!, category || undefined), onSuccess: result => { setOpen(false); onUploaded(result.report.id, result.duplicate) } })
  function chooseFile(selected?: File) {
    setFileError("")
    if (!selected) return
    if (!selected.name.toLowerCase().endsWith(".pdf") || selected.size > 30 * 1024 * 1024 || selected.size === 0) {
      setFile(null)
      setFileError("Choose a nonempty PDF up to 30 MiB.")
      return
    }
    setFile(selected)
  }
  return <Dialog.Root open={open} onOpenChange={value => { if (!upload.isPending) { setOpen(value); if (value) { setFile(null); setFileError(""); upload.reset() } } }}>
    <Dialog.Trigger className="theme-button-base theme-button-primary gap-2 px-4"><Upload size={16} /> Upload research</Dialog.Trigger>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
      <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-app bg-card p-6 shadow-xl">
        <div className="flex items-center justify-between"><Dialog.Title className="text-lg font-semibold text-app">Upload research</Dialog.Title><Dialog.Close disabled={upload.isPending} aria-label="Close upload" className="theme-icon-button"><X size={18} /></Dialog.Close></div>
        <Dialog.Description className="mt-2 text-sm leading-6 text-muted">Upload a research PDF. Talisman preserves its sections, evidence, and visuals in a condensed Markdown document.</Dialog.Description>
        <form className="mt-5 space-y-5" onSubmit={event => { event.preventDefault(); if (file) upload.mutate() }}>
          <div onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!upload.isPending) chooseFile(event.dataTransfer.files[0]) }} className="rounded-xl border border-dashed border-strong bg-card-muted p-6 text-center">
            <FileText className="mx-auto mb-3 text-muted" size={28} />
            <label htmlFor="research-file" className="block text-sm font-medium text-app">{file?.name || "Choose a PDF or drop it here"}</label>
            <input id="research-file" aria-label="Research PDF" type="file" accept="application/pdf,.pdf" disabled={upload.isPending} onChange={event => chooseFile(event.target.files?.[0])} className="mt-3 w-full text-sm text-muted file:mr-3 file:rounded-md file:border-0 file:bg-hover file:px-3 file:py-2 file:text-app" />
            <p className="mt-3 text-xs text-subtle">Scanned PDFs supported · Up to 30 MiB and 200 pages</p>
          </div>
          <label className="block space-y-2 text-sm text-app"><span>Category</span><select value={category} onChange={event => setCategory(event.target.value as ResearchCategory | "")} disabled={upload.isPending} className={`${inputClass} w-full`}>
            <option value="">Automatically select</option>{Object.entries(RESEARCH_CATEGORIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></label>
          <p className="text-xs leading-5 text-muted">Processing continues when you leave this page. Completed research becomes searchable and citable by Stan.</p>
          {(fileError || upload.error) && <p role="alert" className="text-sm text-red-600">{fileError || upload.error?.message}</p>}
          <button disabled={!file || upload.isPending} type="submit" className="theme-button-base theme-button-primary w-full disabled:opacity-50">{upload.isPending ? "Uploading…" : "Upload and condense"}</button>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}

function ResearchRow({ report }: { report: ResearchReport }) {
  return <li className="border-t border-app first:border-t-0">
    <Link to={`/research/${report.id}`} className="group flex gap-4 rounded-lg px-4 py-5 transition-colors hover:bg-hover focus-visible:outline focus-visible:outline-2">
      <span className="hidden h-11 w-10 shrink-0 items-center justify-center rounded-lg border border-app bg-card-muted text-muted sm:flex"><FileText size={20} /></span>
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted"><span>{report.category ? RESEARCH_CATEGORIES[report.category] : "Selecting category"}</span><span aria-hidden="true">·</span><span>{labels[report.status]}</span>{report.category_uncertain && <span className="text-amber-600">Review category</span>}</div>
        <h2 className="break-words text-base font-semibold leading-6 text-app group-hover:text-link">{report.title || report.filename}</h2>
        {report.subtitle && <p className="mt-1 text-sm text-muted">{report.subtitle}</p>}
        <p className="mt-2 text-xs text-subtle">{[report.institution, report.publication_date, `${report.page_count} pages`].filter(Boolean).join(" · ")}</p>
        {report.error && <p className="mt-2 text-xs text-red-600">{report.error}</p>}
      </div>
      <ArrowUpRight size={17} className="mt-1 shrink-0 text-subtle" />
    </Link>
  </li>
}

export function Research() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const query = params.get("q") || ""
  const deferredQuery = useDeferredValue(query)
  const rawCategory = params.get("category")
  const category = rawCategory && rawCategory in RESEARCH_CATEGORIES ? rawCategory as ResearchCategory : undefined
  const offset = Math.max(0, Number(params.get("offset")) || 0)
  const filters: ResearchFilters = { q: deferredQuery, category, institution: params.get("institution") || undefined, date_from: params.get("from") || undefined, date_to: params.get("to") || undefined, sort: params.get("sort") === "uploaded" ? "uploaded" : "publication", offset }
  const library = useQuery({ queryKey: ["research", filters], queryFn: () => fetchResearch(filters), refetchInterval: query => query.state.data?.reports.some(r => active.has(r.status)) ? 4000 : false })
  function filter(key: string, value: string) {
    setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); if (key !== "offset") next.delete("offset"); return next })
  }
  return <div className="mx-auto max-w-6xl space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><PageHeader title="Research" subtitle="Your research, condensed without losing the evidence." />{library.data?.can_manage && <UploadResearch onUploaded={(id, duplicate) => navigate(`/research/${id}${duplicate ? "?existing=1" : ""}`)} />}</div>
    <div aria-label="Research categories" className="flex flex-wrap gap-2 border-b border-app pb-4">
      <button onClick={() => filter("category", "")} aria-pressed={!category} className={`rounded-full border px-4 py-2 text-sm ${!category ? "border-strong bg-hover text-app" : "border-app text-muted"}`}>All research</button>
      {Object.entries(RESEARCH_CATEGORIES).map(([key, label]) => <button key={key} onClick={() => filter("category", key)} aria-pressed={category === key} className={`rounded-full border px-4 py-2 text-sm ${category === key ? "border-strong bg-hover text-app" : "border-app text-muted"}`}>{label}{" "}<span className="ml-2 text-subtle">{library.data?.counts[key as ResearchCategory] ?? 0}</span></button>)}
    </div>
    <div className="flex flex-wrap items-end gap-3">
      <label className="relative min-w-48 flex-1"><span className="sr-only">Search research</span><Search size={16} className="absolute left-3 top-3 text-subtle" /><input type="search" value={query} onChange={event => filter("q", event.target.value)} placeholder="Search titles, authors, or report content" className={`${inputClass} w-full pl-9`} /></label>
      <label className="space-y-1 text-xs text-muted"><span className="block">Institution</span><select aria-label="Institution" value={filters.institution || ""} onChange={event => filter("institution", event.target.value)} className={inputClass}><option value="">All institutions</option>{library.data?.institutions.map(name => <option key={name}>{name}</option>)}</select></label>
      <label className="space-y-1 text-xs text-muted"><span className="block">Published from</span><input type="date" value={filters.date_from || ""} onChange={event => filter("from", event.target.value)} className={inputClass} /></label>
      <label className="space-y-1 text-xs text-muted"><span className="block">Published to</span><input type="date" value={filters.date_to || ""} onChange={event => filter("to", event.target.value)} className={inputClass} /></label>
      <label className="space-y-1 text-xs text-muted"><span className="block">Sort by</span><select value={filters.sort} onChange={event => filter("sort", event.target.value)} className={inputClass}><option value="publication">Publication date</option><option value="uploaded">Recently uploaded</option></select></label>
    </div>
    {library.isPending && <LoadingSpinner message="Loading research…" />}
    {library.error && <ErrorMessage message={library.error.message} />}
    {library.data && <section className="theme-surface overflow-hidden" aria-label="Research reports">
      <div className="border-b border-app px-4 py-3 text-xs text-muted">{library.data.total} {library.data.total === 1 ? "report" : "reports"}</div>
      {library.data.reports.length ? <ul>{library.data.reports.map(report => <ResearchRow key={report.id} report={report} />)}</ul> : <div className="px-6 py-16 text-center"><FileText className="mx-auto mb-4 text-subtle" size={32} /><p className="text-base font-medium text-app">{query || category || filters.institution || filters.date_from || filters.date_to ? "No matching research" : "Build your research library"}</p><p className="mt-2 text-sm text-muted">Upload a PDF to preserve its analysis in a concise, readable document.</p></div>}
      {library.data.total > 50 && <div className="flex justify-between border-t border-app p-4"><button disabled={offset === 0} onClick={() => filter("offset", String(Math.max(0, offset - 50)))} className="theme-button-base theme-button-secondary px-3 disabled:opacity-40">Previous</button><button disabled={offset + 50 >= library.data.total} onClick={() => filter("offset", String(offset + 50))} className="theme-button-base theme-button-secondary px-3 disabled:opacity-40">Next</button></div>}
    </section>}
  </div>
}
