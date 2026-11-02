import { useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Download, ExternalLink, RotateCw, Trash2 } from "lucide-react"
import { useRegisterScreenContext } from "@/contexts/ScreenContext"
import { ErrorMessage, LoadingSpinner } from "@/components/shared/LoadingSpinner"
import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer"
import { deleteResearch, fetchResearchReport, RESEARCH_CATEGORIES, reindexResearch, researchDownloadUrl, retryResearch, updateResearchCategory, type ResearchCategory } from "@/lib/api"

const stages = ["queued", "reading", "condensing", "checking"]
const labels: Record<string, string> = { queued: "Queued", reading: "Reading PDF", condensing: "Condensing", checking: "Checking", ready: "Ready", needs_review: "Needs review", failed: "Failed" }

export function ResearchReader() {
  const { id = "" } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const report = useQuery({ queryKey: ["research-report", id], queryFn: () => fetchResearchReport(id), refetchInterval: query => { const data = query.state.data; return data && (stages.includes(data.status) || data.index_status === "pending") ? 4000 : false } })
  useRegisterScreenContext(report.data ? {
    pageName: "Research report", summary: `${report.data.title || report.data.filename}. Report ID: ${id}. Status: ${report.data.status}.`,
    metrics: { report_id: id, category: report.data.category || "Selecting", institution: report.data.institution || "Not provided" },
    correspondingTools: ["read_research_report", "search_research"],
  } : null)
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["research-report", id] }), qc.invalidateQueries({ queryKey: ["research"] })])
  const category = useMutation({ mutationFn: (value: ResearchCategory) => updateResearchCategory(id, value), onSuccess: refresh })
  const retry = useMutation({ mutationFn: () => retryResearch(id), onSuccess: refresh })
  const reindex = useMutation({ mutationFn: () => reindexResearch(id), onSuccess: refresh })
  const remove = useMutation({ mutationFn: () => deleteResearch(id), onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["research"] }); qc.removeQueries({ queryKey: ["research-report", id] }); navigate("/research") } })
  if (report.isPending) return <LoadingSpinner message="Loading research…" />
  if (report.error) return <ErrorMessage message={report.error.message} />
  const data = report.data
  if (!data) return null
  const processing = stages.includes(data.status)
  const error = category.error || retry.error || remove.error || reindex.error
  return <div className="mx-auto max-w-6xl space-y-6">
    <Link to="/research" className="inline-flex items-center gap-2 text-sm text-muted hover:text-app"><ArrowLeft size={16} /> Research library</Link>
    {params.has("existing") && <p role="status" className="rounded-lg border border-app bg-card-muted p-3 text-sm text-muted">This PDF is already in your library. You’re viewing the existing report.</p>}
    <header className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {data.can_manage ? <label><span className="sr-only">Report category</span><select value={data.category || ""} disabled={category.isPending} onChange={event => category.mutate(event.target.value as ResearchCategory)} className="rounded-full border border-app bg-input px-3 py-2 text-sm text-app">{!data.category && <option value="" disabled>Selecting category…</option>}{Object.entries(RESEARCH_CATEGORIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label> : <span>{data.category && RESEARCH_CATEGORIES[data.category]}</span>}
          {data.category_source === "automatic" && data.category && <span>Auto-classified</span>}{data.category_uncertain && <span className="text-amber-600">Review category</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          <a href={researchDownloadUrl(id, "original")} target="_blank" rel="noreferrer" className="theme-button-base theme-button-secondary gap-2 px-3"><ExternalLink size={15} /> Original PDF</a>
          {data.current_revision && <a href={researchDownloadUrl(id, "markdown")} className="theme-button-base theme-button-primary gap-2 px-3"><Download size={15} /> Download .md</a>}
        </div>
      </div>
      <h1 className="max-w-4xl break-words text-2xl font-semibold leading-tight tracking-tight text-app sm:text-3xl">{data.title || data.filename}</h1>
      {data.subtitle && <p className="text-lg text-muted">{data.subtitle}</p>}
      <p className="text-sm text-muted">{[data.institution, data.publication_date, data.authors.join(", ")].filter(Boolean).join(" · ")}</p>
      <p className="text-xs text-subtle">{data.page_count} original pages · Uploaded {new Date(data.created_at).toLocaleDateString()}{data.current_revision && ` · ${data.revisions.length} ${data.revisions.length === 1 ? "version" : "versions"}`}</p>
    </header>
    {error && <p role="alert" className="text-sm text-red-600">{error.message}</p>}
    <section aria-label="Processing status" aria-live="polite" className="rounded-xl border border-app bg-card-muted p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-medium text-app">{labels[data.status]}{processing && data.progress && data.progress.total > 0 ? ` · ${data.progress.done} of ${data.progress.total}` : ""}</p>{processing && <p className="mt-1 text-xs text-muted">You can leave this page. Processing continues in the background.</p>}</div>{data.can_manage && !processing && <button onClick={() => retry.mutate()} disabled={retry.isPending} className="theme-button-base theme-button-secondary gap-2 px-3"><RotateCw size={14} />{data.status === "ready" ? "Reprocess" : "Retry processing"}</button>}</div>
      {processing && <ol className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">{stages.map((stage, index) => <li key={stage} className={`border-t-2 pt-2 ${index <= stages.indexOf(data.status) ? "border-current text-link" : "border-app text-subtle"}`}>{labels[stage]}</li>)}</ol>}
      {data.error && <p className="mt-3 text-sm text-red-600">{data.error}</p>}
      {data.issues.length > 0 && <div className="mt-3 text-sm text-muted"><p className="font-medium text-app">The source check found issues:</p><ul className="mt-2 list-disc space-y-1 pl-5">{data.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul></div>}
      {data.current_revision && data.status !== "ready" && <p className="mt-3 text-xs text-muted">The last successfully checked version remains available below.</p>}
      {data.current_revision && <p className="mt-3 text-xs text-muted">{data.index_status === "ready" ? "Searchable and citable by Stan." : data.index_status === "failed" ? data.index_error : "Adding this report to Stan’s research search…"}{data.index_status === "failed" && data.can_manage && <button disabled={reindex.isPending} onClick={() => reindex.mutate()} className="ml-2 text-link underline">Retry search indexing</button>}</p>}
    </section>
    {data.content && <div className="grid items-start gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <nav aria-label="Report contents" className="max-h-[70vh] overflow-auto rounded-xl border border-app p-4 lg:sticky lg:top-6"><p className="mb-3 text-xs font-semibold uppercase tracking-wider text-subtle">Contents</p><ul className="space-y-2">{data.sections?.filter(section => section.heading).map(section => <li key={section.id} style={{ paddingLeft: Math.max(0, section.level - 2) * 10 }}><a href={`#${section.id}`} className="text-sm leading-5 text-muted hover:text-link">{section.heading}</a></li>)}</ul></nav>
      <article className="min-w-0 rounded-xl border border-app bg-card p-5 sm:p-8" aria-label="Condensed research">
        {data.sections?.map(section => <section key={section.id} id={section.id} className="mb-7 scroll-mt-6 last:mb-0">
          {section.heading && <div className="mb-3 flex items-baseline justify-between gap-3"><div role="heading" aria-level={section.level} className={`${section.level <= 2 ? "text-xl" : "text-lg"} font-semibold text-app`}>{section.heading}</div><a href={`${researchDownloadUrl(id, "original")}#page=${section.pages[0]}`} target="_blank" rel="noreferrer" className="shrink-0 text-xs text-subtle hover:text-link">p. {section.pages[0]}</a></div>}
          {section.source_retained && <p className="mb-3 text-xs text-muted">Extracted source text retained for this section.</p>}
          <MarkdownRenderer content={section.output.paragraph} />
          {section.output.visuals.map((visual, index) => <div key={index} className="my-4 border-l-2 border-strong bg-card-muted px-4 py-2"><MarkdownRenderer content={visual} /></div>)}
        </section>)}
      </article>
    </div>}
    {data.can_manage && <footer className="border-t border-app pt-5">
      {confirmDelete ? <div role="group" aria-label="Confirm deletion" className="flex flex-wrap items-center gap-3"><p className="mr-auto text-sm text-muted">Delete this PDF and all its versions? Stan will stop using it.</p><button disabled={remove.isPending} onClick={() => remove.mutate()} className="theme-button-base theme-button-secondary px-3 text-red-600">Delete report</button><button autoFocus disabled={remove.isPending} onClick={() => setConfirmDelete(false)} className="theme-button-base theme-button-secondary px-3">Cancel</button></div> : <button onClick={() => setConfirmDelete(true)} className="flex items-center gap-2 text-xs text-muted hover:text-red-600"><Trash2 size={14} /> Delete report</button>}
    </footer>}
  </div>
}
