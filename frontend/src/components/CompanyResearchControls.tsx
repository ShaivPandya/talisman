import { useEffect, useId, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, Loader2, Play, Save, Settings2 } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { isPrivateSourceUrl } from "@/lib/sourceLinks"

import { Dialog } from "@/components/shared/Dialog"
import {
  fetchCompanyResearchReport,
  fetchCompanyResearchSettings,
  fetchCompanyResearchStatus,
  startCompanyResearch,
  updateCompanyResearchSettings,
  type CompanyResearchKind,
  type CompanyResearchReportStatus,
  type CompanyResearchSettings,
  type CompanyResearchStatus,
} from "@/lib/api"
import { invalidateApprovalSummaries } from "@/lib/approvalQueries"

const KINDS: CompanyResearchKind[] = ["overview", "management_quality"]
const LABELS: Record<CompanyResearchKind, string> = {
  overview: "Overview",
  management_quality: "Management quality",
}
const PHASES: Record<string, string> = {
  queued: "Queued",
  planning: "Confirming company and fiscal quarters",
  sources: "Gathering sources",
  verification: "Checking evidence and coverage",
  report: "Writing full report",
  formatting: "Preparing company sheet",
  saving: "Saving company sheet",
}
const BUTTON = "theme-button-base min-h-10 px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"

function isActive(report?: CompanyResearchReportStatus) {
  return report?.status === "queued" || report?.status === "running"
}

function statusText(report: CompanyResearchReportStatus) {
  if (report.status === "done") return "Saved to company sheet"
  if (report.status === "error" || report.status === "incomplete") return report.error || "Research is incomplete; completed evidence is retained."
  if (report.status === "cancelled") return report.error || "Research was cancelled."
  return PHASES[report.progress?.phase ?? report.status] ?? "Researching"
}

function PromptForm({ settings, onClose }: { settings: CompanyResearchSettings; onClose: () => void }) {
  const qc = useQueryClient()
  const id = useId()
  const [overview, setOverview] = useState(settings.overview_prompt)
  const [management, setManagement] = useState(settings.management_quality_prompt)
  const mutation = useMutation({
    mutationFn: () => updateCompanyResearchSettings({
      overview_prompt: overview,
      management_quality_prompt: management,
    }),
    onSuccess: result => {
      qc.setQueryData(["company-research-settings"], result)
      onClose()
    },
  })
  const valid = Boolean(overview.trim() && management.trim() && overview.includes("{ticker}") && management.includes("{ticker}"))

  return (
    <form onSubmit={event => { event.preventDefault(); mutation.mutate() }} className="space-y-4">
      <p className="text-sm text-muted">
        Saved prompts apply to every company. Use {"{ticker}"} for the company symbol.
        Unsaved edits do not affect research; running jobs keep the prompts they started with.
      </p>
      <div className="space-y-2">
        <label htmlFor={`${id}-overview`} className="block text-sm font-medium text-app">Company overview prompt</label>
        <textarea id={`${id}-overview`} value={overview} onChange={event => setOverview(event.target.value)}
          rows={10} maxLength={30_000} required
          className="theme-input w-full rounded-lg p-3 text-sm leading-6" />
      </div>
      <div className="space-y-2">
        <label htmlFor={`${id}-management`} className="block text-sm font-medium text-app">Management quality prompt</label>
        <textarea id={`${id}-management`} value={management} onChange={event => setManagement(event.target.value)}
          rows={12} maxLength={30_000} required
          className="theme-input w-full rounded-lg p-3 text-sm leading-6" />
      </div>
      {!valid && <p className="text-sm text-red-600">Both prompts must contain text and {"{ticker}"}.</p>}
      {mutation.error && <p role="alert" className="text-sm text-red-600">{mutation.error.message}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onClose} disabled={mutation.isPending} className={`${BUTTON} theme-button-secondary`}>Cancel</button>
        <button type="submit" disabled={!valid || mutation.isPending} className={`${BUTTON} theme-button-primary`}>
          {mutation.isPending ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Save size={16} aria-hidden="true" />}
          Save Research Prompts
        </button>
      </div>
    </form>
  )
}

function PromptEditor({ onClose }: { onClose: () => void }) {
  const query = useQuery({
    queryKey: ["company-research-settings"],
    queryFn: fetchCompanyResearchSettings,
    refetchOnWindowFocus: false,
  })
  if (query.isPending || query.isFetching) return <p role="status" className="text-sm text-muted">Loading research prompts…</p>
  if (query.error) return <p role="alert" className="text-sm text-red-600">{query.error.message}</p>
  return <PromptForm settings={query.data} onClose={onClose} />
}

function FullResearchReport({ ticker, kind, jobId, status }: { ticker: string; kind: CompanyResearchKind; jobId?: string; status: CompanyResearchReportStatus["status"] }) {
  const [expanded, setExpanded] = useState(false)
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ["company-research-report", ticker, kind, jobId],
    queryFn: () => fetchCompanyResearchReport(ticker, kind, jobId),
    enabled: expanded,
    staleTime: 60_000,
    refetchInterval: expanded && (status === "running" || status === "queued") ? 10_000 : false,
  })
  useEffect(() => {
    if (status === "running" || status === "queued") return
    // A run can finish with partial evidence as well as a completed report.
    void qc.invalidateQueries({ queryKey: ["company-research-report", ticker, kind, jobId] })
  }, [qc, ticker, kind, jobId, status])
  return (
    <details onToggle={event => setExpanded(event.currentTarget.open)} className="min-w-0 rounded-lg border border-app">
      <summary className="flex min-h-10 cursor-pointer items-center gap-2 px-3 py-2 text-sm font-medium text-app">
        <BookOpen size={15} aria-hidden="true" /> Full {LABELS[kind].toLowerCase()} research
      </summary>
      {expanded && (
        <div className="min-w-0 space-y-3 border-t border-app p-3 sm:p-4">
          {query.isPending && <p role="status" className="text-sm text-muted">Loading full report…</p>}
          {query.error && <p role="alert" className="text-sm text-red-600">{query.error.message}</p>}
          {query.data && (
            <>
              <p className="text-xs text-subtle">
                Researched {new Date(query.data.generated_at).toLocaleString()} · {query.data.sources.length} {query.data.sources.length === 1 ? "source" : "sources"}
                {!query.data.summary_applied && " · Company sheet has not been updated"}
                {query.data.complete === false && " · Incomplete evidence; verification is still required"}
              </p>
              {query.data.sources.some(source => isPrivateSourceUrl(source.url)) && (
                <div aria-label="Private research sources" className="rounded border border-app bg-card-muted p-2 text-xs text-muted">
                  <span className="font-medium">Private uploads: </span>
                  {query.data.sources.filter(source => isPrivateSourceUrl(source.url)).map(source => (
                    <a key={source.url} href={source.url} className="mr-3 text-link underline">{source.title}</a>
                  ))}
                </div>
              )}
              <div className="min-w-0 space-y-3 break-words text-sm leading-6 text-app">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                  a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-link underline underline-offset-2">{children}</a>,
                  table: ({ children }) => <div className="max-w-full overflow-x-auto"><table className="min-w-[64rem] border-collapse text-left text-xs">{children}</table></div>,
                  th: ({ children }) => <th className="min-w-40 border border-app bg-card-muted p-2 align-top font-semibold">{children}</th>,
                  td: ({ children }) => <td className="min-w-40 border border-app p-2 align-top">{children}</td>,
                  h1: ({ children }) => <h1 className="mt-6 text-xl font-semibold">{children}</h1>,
                  h2: ({ children }) => <h2 className="mt-6 text-lg font-semibold">{children}</h2>,
                  h3: ({ children }) => <h3 className="mt-4 font-semibold">{children}</h3>,
                  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
                }}>{query.data.content}</ReactMarkdown>
              </div>
            </>
          )}
        </div>
      )}
    </details>
  )
}

export function CompanyResearchControls({ ticker }: { ticker: string }) {
  const normalizedTicker = ticker.trim().toUpperCase()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const completedRef = useRef(new Set<string>())
  const query = useQuery({
    queryKey: ["company-research", normalizedTicker],
    queryFn: () => fetchCompanyResearchStatus(normalizedTicker),
    refetchIntervalInBackground: false,
    refetchInterval: state => KINDS.some(kind => isActive(state.state.data?.reports[kind])) ? 5000 : false,
  })
  const mutation = useMutation({
    mutationFn: ({ target, kinds, resumeRunId, extendTime }: { target: string; kinds: CompanyResearchKind[]; resumeRunId?: string; extendTime?: boolean }) => startCompanyResearch(target, kinds, resumeRunId, extendTime),
    onSuccess: (result, variables) => {
      qc.setQueryData<CompanyResearchStatus>(["company-research", variables.target], current => ({
        ticker: variables.target,
        reports: {
          overview: { status: "idle" },
          management_quality: { status: "idle" },
          ...current?.reports,
          ...result.reports,
        },
      }))
      void qc.invalidateQueries({ queryKey: ["company-research", variables.target] })
    },
  })
  const running = KINDS.some(kind => isActive(query.data?.reports[kind]))
  const budgets = [...new Map(KINDS.flatMap(kind => {
    const budget = query.data?.reports[kind]?.budget
    return budget ? [[budget.run_id, budget] as const] : []
  })).values()]

  useEffect(() => {
    let completed = false
    for (const kind of KINDS) {
      const report = query.data?.reports[kind]
      const key = `${normalizedTicker}:${kind}:${report?.job_id}`
      if (report?.status !== "done" || completedRef.current.has(key)) continue
      completedRef.current.add(key)
      completed = true
    }
    if (!completed) return
    void qc.invalidateQueries({ queryKey: ["dossier", normalizedTicker] }, { cancelRefetch: false })
    void qc.invalidateQueries({ queryKey: ["idea"] }, { cancelRefetch: false })
    void qc.invalidateQueries({ queryKey: ["ideas"] }, { cancelRefetch: false })
    void invalidateApprovalSummaries(qc)
  }, [query.data, normalizedTicker, qc])

  return (
    <section aria-label="Company research" className="mb-4 min-w-0 space-y-3 rounded-lg border border-app p-3">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => mutation.mutate({ target: normalizedTicker, kinds: KINDS })}
          disabled={running || mutation.isPending || query.isPending || Boolean(query.error)}
          className={`${BUTTON} theme-button-primary`}>
          {running || mutation.isPending ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
          Run Company Research
        </button>
        <button type="button" onClick={() => setEditing(true)} className={`${BUTTON} theme-button-secondary`}>
          <Settings2 size={16} aria-hidden="true" /> Edit Research Prompts
        </button>
        <p className="text-xs text-subtle">Researches and saves overview and management quality. Each new run allows up to 80 minutes and $25 total.</p>
      </div>
      {query.error && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-red-600" role="alert">
          <span>Could not load research status: {query.error.message}</span>
          <button type="button" className={`${BUTTON} theme-button-secondary`} onClick={() => void query.refetch()}>Reload research status</button>
        </div>
      )}
      {mutation.error && <p role="alert" className="text-sm text-red-600">{mutation.error.message}</p>}
      {budgets.map(budget => {
        const reports = KINDS.map(kind => query.data?.reports[kind]).filter(report => report?.budget?.run_id === budget.run_id)
        const active = reports.some(isActive)
        const completed = reports.every(report => report?.status === "done")
        const remaining = Math.ceil(budget.remaining_seconds / 60)
        const allowanceStatus = completed ? "Run completed" : active
          ? budget.remaining_seconds > 0 ? `${remaining} minutes remaining` : "Time allowance exhausted"
          : budget.remaining_seconds > 0 ? `Run stopped; ${remaining} minutes left to resume` : "Run stopped; resume window expired"
        return (
          <p key={budget.run_id} className="text-xs text-subtle" aria-label="Research allowance">
            {Math.floor(budget.elapsed_seconds / 60)} / {Math.round(budget.max_seconds / 60)} minutes · ${budget.charged_usd.toFixed(2)} budget used
            {budget.reserved_usd > 0 && ` + $${budget.reserved_usd.toFixed(2)} reserved`} / ${budget.max_cost_usd.toFixed(2)} total
            {` · ${allowanceStatus}`}
            {" · Cost includes a conservative margin; resume keeps the original spending ceiling."}
          </p>
        )
      })}
      {KINDS.map(kind => {
        const report = query.data?.reports[kind]
        if (!report || report.status === "idle") return null
        const failed = report.status === "error" || report.status === "cancelled" || report.status === "incomplete"
        return (
          <div key={kind} className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm" role={failed ? "alert" : "status"}>
              {isActive(report) && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
              <span className="font-medium text-app">{LABELS[kind]}:</span>
              <span className={failed ? "text-red-600" : report.status === "done" ? "text-green-600 dark:text-green-400" : "text-muted"}>
                {statusText(report)}
              </span>
              {failed && (!report.run_id || report.resumable || report.continuable) && (
                <button type="button" className={`${BUTTON} theme-button-secondary`}
                  disabled={mutation.isPending || running} onClick={() => mutation.mutate({ target: normalizedTicker, kinds: [kind], resumeRunId: report.run_id, extendTime: report.continuable })}>
                  {report.continuable ? "Continue" : report.run_id ? "Resume" : "Retry"} {LABELS[kind].toLowerCase()}{report.continuable ? " (30 min)" : ""}
                </button>
              )}
            </div>
            {report.continuable && <p className="text-xs text-subtle">One additional 30-minute window reuses saved work and the remaining original budget. The total spending ceiling does not increase.</p>}
            {report.progress && (
              <p className="text-xs text-subtle">
                {report.progress.quarters_total != null && `${report.progress.quarters_completed ?? 0} / ${report.progress.quarters_total} quarters researched. `}
                {report.progress.topics_total != null && `${report.progress.topics_completed ?? 0} / ${report.progress.topics_total} overview topics researched. `}
                {report.progress.evidence_gaps != null && `${report.progress.evidence_gaps} evidence gaps identified.`}
              </p>
            )}
            {report.report_available && <FullResearchReport key={report.job_id ?? kind} ticker={normalizedTicker} kind={kind} jobId={report.job_id} status={report.status} />}
          </div>
        )
      })}
      <Dialog open={editing} onOpenChange={setEditing} title="Edit Research Prompts"
        description="Global prompts for company overview and management-quality research.">
        {editing && <PromptEditor onClose={() => setEditing(false)} />}
      </Dialog>
    </section>
  )
}
