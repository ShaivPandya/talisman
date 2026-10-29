import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Play, Loader2 } from "lucide-react"
import {
  fetchActionExecutions, fetchActionExecution, fetchActionExecutionSettings,
  saveActionExecutionSettings, runActionItem, runActionItemBatch, retryActionExecution,
  cancelActionExecution, proposeActionExecutionCompletion,
  reviseActionExecution,
  type ActionExecution, type ActionExecutionSettings,
} from "@/lib/api"
import { invalidateApprovalSummaries } from "@/lib/approvalQueries"
import { Dialog } from "./Dialog"
import { MarkdownRenderer } from "./MarkdownRenderer"

const runsKey = ["action-item-executions"]
const settingsKey = ["action-item-execution-settings"]
const button = "rounded px-2 py-1 text-xs font-medium border border-app text-app hover:bg-[hsl(var(--muted-2))] disabled:opacity-50"
const active = (run?: ActionExecution) => !!run && ["queued", "running"].includes(run.status)
const labels: Record<string, string> = {
  queued: "Queued", running: "Researching", needs_input: "Needs input", failed: "Interrupted",
  cancelled: "Cancelled", awaiting_approvals: "Changes need approval", ready_for_review: "Ready for review",
  completion_proposed: "Completion awaiting approval",
  completed: "Completed",
}

function useExecutions() {
  return useQuery({ queryKey: runsKey, queryFn: fetchActionExecutions, staleTime: 2000,
    refetchInterval: q => q.state.data?.runs.some(active) ? 2500 : 30_000 })
}

export function ActionItemExecutionControls({ item, busy, onComplete, onDismiss }: {
  item: { id: string | number; description: string; action_type: string; ticker?: string | null }
  busy: boolean
  onComplete: () => void
  onDismiss: () => void
}) {
  const qc = useQueryClient()
  const runs = useExecutions()
  const config = useQuery({ queryKey: settingsKey, queryFn: fetchActionExecutionSettings, staleTime: 30_000 })
  const [open, setOpen] = useState(false)
  const [instructions, setInstructions] = useState("")
  const itemId = String(item.id).startsWith("action_item:") ? String(item.id) : `action_item:${item.id}`
  const run = runs.data?.runs.find(r => r.item_id === itemId)
  const detail = useQuery({ queryKey: [...runsKey, run?.run_id], queryFn: () => fetchActionExecution(run!.run_id),
    enabled: open && !!run, refetchInterval: q => open && (active(q.state.data) || ["awaiting_approvals", "completion_proposed"].includes(q.state.data?.status ?? "")) ? 2500 : false })
  const shown = detail.data ?? run
  const eligible = ["research", "review"].includes(item.action_type) && !!item.ticker && /thes[ie]s|valuation|multiple|consensus|\bdcf\b|kill condition|measurable.*trigger/i.test(item.description)
  const mutation = useMutation({
    mutationFn: async (action: "run" | "retry" | "cancel" | "complete" | "revise") => {
      if (action === "run") return runActionItem(item.id)
      if (!run) throw new Error("No execution is available")
      if (action === "retry") return retryActionExecution(run.run_id)
      if (action === "cancel") return cancelActionExecution(run.run_id)
      if (action === "revise") return reviseActionExecution(run.run_id, instructions)
      return proposeActionExecutionCompletion(run.run_id)
    },
    onSuccess: result => {
      qc.setQueryData([...runsKey, result.run_id], result)
      void qc.invalidateQueries({ queryKey: runsKey })
      void invalidateApprovalSummaries(qc)
      setOpen(true)
    },
  })
  return <>
    <div className="flex flex-wrap items-center gap-2 mt-2">
      {!run && eligible && config.data?.enabled && <button type="button" className={button} disabled={busy || mutation.isPending || !runs.isSuccess}
        onClick={() => mutation.mutate("run")}><Play size={12} className="inline mr-1" />Run with Stan</button>}
      {run && <>
        <span role="status" className="text-xs text-muted">{active(run) && <Loader2 size={12} className="inline mr-1 animate-spin" />}{labels[run.status] ?? run.status}</span>
        <button type="button" className={button} onClick={() => setOpen(true)}>{run.has_result ? "View Results" : "View Progress"}</button>
      </>}
      {!run && <button type="button" className={button} disabled={busy || !runs.isSuccess} onClick={onComplete}>Propose Complete</button>}
      <button type="button" className={button} disabled={busy || active(run)} onClick={onDismiss}>Propose Dismiss</button>
    </div>
    {(mutation.error || runs.error) && <p role="alert" className="mt-2 text-xs text-red-600">{(mutation.error ?? runs.error)?.message}</p>}
    <Dialog open={open} onOpenChange={setOpen} title="Action-item research" description={item.description}>
      {detail.error && <p role="alert" className="text-red-600">{detail.error.message}</p>}
      {shown && <div className="space-y-5 text-sm">
        <div className="flex flex-wrap gap-3 items-center"><span role="status" className="font-medium">{labels[shown.status] ?? shown.status}</span>
          {active(shown) && <span className="text-muted">{shown.phase.replaceAll("_", " ")}</span>}
          <span className="text-muted">Spent / reserved ${shown.charged_usd.toFixed(2)} of ${shown.max_cost_usd.toFixed(2)}</span>
        </div>
        {shown.error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-amber-900 dark:bg-amber-950 dark:text-amber-200">{shown.error}</p>}
        {shown.plan && <div><p className="font-semibold mb-2">Research scope</p><p>{shown.plan.scope}</p>
          <ul className="mt-2 list-disc pl-5">{shown.plan.requirements.map((r, i) => <li key={i}>{r}</li>)}</ul></div>}
        {shown.result && <>
          <MarkdownRenderer content={shown.result.report} />
          <div><p className="font-semibold mb-2">Completion checks</p><ul className="space-y-2">{shown.result.checks.map(c =>
            <li key={c.requirement_index}><span className="font-medium">{c.satisfied ? "Supported" : "Incomplete"}: </span>{shown.plan?.requirements[c.requirement_index]} — {c.evidence}</li>)}</ul></div>
          {shown.result.thesis_content && <details><summary className="cursor-pointer font-medium">Proposed thesis</summary><MarkdownRenderer content={shown.result.thesis_content} /></details>}
          {shown.result.kill_conditions.map((c, i) => <div key={i} className="rounded-lg border border-app p-3"><p>{c.condition}</p><p className="text-muted">{c.metric}: {c.threshold} · {c.cadence}</p></div>)}
          {shown.result.valuation_inputs.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left"><caption className="text-left font-semibold mb-2">Valuation inputs</caption><thead><tr><th>Input</th><th>Value</th><th>As of</th><th>Type</th></tr></thead><tbody>{shown.result.valuation_inputs.map(v => <tr key={v.name}><td>{v.name}</td><td>{v.value} {v.unit}</td><td>{v.as_of}</td><td>{v.kind}</td></tr>)}</tbody></table></div>}
          {shown.result.calculations.map(c => <p key={c.name} className="text-xs text-muted">{c.name}: {c.inputs.join(` ${c.operation} `)} = {c.result}</p>)}
        </>}
        {shown.evidence && <div><p className="font-semibold mb-2">Sources and evidence</p><div className="space-y-3">{shown.evidence.sources.map((s, i) =>
          <details key={`${s.url}-${i}`} className="rounded-lg border border-app p-3"><summary className="cursor-pointer"><a href={s.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">{s.title}</a> · {s.published_on ?? "Date unavailable"}</summary><p className="mt-2">{s.passage}</p><p className="mt-1 text-xs text-muted">{s.location}</p></details>)}</div>
          {shown.evidence.gaps.length > 0 && <p className="mt-2 text-muted">Evidence gaps: {shown.evidence.gaps.join("; ")}</p>}</div>}
        {(shown.dependencies ?? []).length > 0 && <div><p className="font-semibold mb-2">Required changes</p>{shown.dependencies?.map((a, i) =>
          <p key={a.id}><Link className="text-blue-600 underline" to={`/workspace?approval_id=${encodeURIComponent(a.id)}`}>Review change {i + 1}</Link> · {a.status} / {a.application_status}</p>)}</div>}
        {shown.completion_approval_id && <Link className="text-blue-600 underline" to={`/workspace?approval_id=${encodeURIComponent(shown.completion_approval_id)}`}>Review completion proposal</Link>}
        {["needs_input", "failed", "cancelled"].includes(shown.status) && <div>
          <label className="block">Additional information or requested corrections
            <textarea className="mt-2 block w-full rounded-lg border border-app bg-transparent p-3" maxLength={4000} rows={3} value={instructions} onChange={e => setInstructions(e.target.value)} />
          </label>
          <button type="button" className={button} disabled={mutation.isPending || !instructions.trim()} onClick={() => mutation.mutate("revise")}>Research again with this information</button>
        </div>}
        <div className="flex flex-wrap gap-2">
          {active(shown) && <button type="button" className={button} disabled={mutation.isPending} onClick={() => mutation.mutate("cancel")}>Cancel research</button>}
          {["failed", "cancelled"].includes(shown.status) && <button type="button" className={button} disabled={mutation.isPending} onClick={() => mutation.mutate("retry")}>Retry retained work</button>}
          {["ready_for_review", "awaiting_approvals"].includes(shown.status) && <button type="button" className={button} disabled={mutation.isPending || !shown.can_propose_completion} onClick={() => mutation.mutate("complete")}>I reviewed the results · Propose Complete</button>}
        </div>
        {shown.status === "awaiting_approvals" && !shown.can_propose_completion && <p className="text-xs text-muted">Apply the required changes before proposing completion.</p>}
        {mutation.error && <p role="alert" className="text-red-600">{mutation.error.message}</p>}
      </div>}
    </Dialog>
  </>
}

export function ActionItemExecutionToolbar() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ActionExecutionSettings | null>(null)
  const config = useQuery({ queryKey: settingsKey, queryFn: fetchActionExecutionSettings })
  const runs = useExecutions()
  const save = useMutation({ mutationFn: saveActionExecutionSettings, onSuccess: value => {
    qc.setQueryData(settingsKey, value); setOpen(false)
  } })
  const batch = useMutation({ mutationFn: runActionItemBatch, onSuccess: () => void qc.invalidateQueries({ queryKey: runsKey }) })
  const attention = runs.data?.runs.filter(r => ["needs_input", "failed", "ready_for_review", "awaiting_approvals", "completion_proposed"].includes(r.status)).length ?? 0
  if (!config.data?.enabled) return null
  return <>
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">
      <button type="button" className={button} onClick={() => {
        const { automatic, enabled_kinds, max_cost_usd, daily_budget_usd, max_concurrent } = config.data
        setDraft({ automatic, enabled_kinds, max_cost_usd, daily_budget_usd, max_concurrent }); setOpen(true)
      }}>Research settings</button>
      <button type="button" className={button} disabled={batch.isPending} onClick={() => batch.mutate()}>Run eligible backlog</button>
      {config.data.automatic && <span>Automatic research enabled</span>}
      {attention > 0 && <span role="status">{attention} research {attention === 1 ? "item needs" : "items need"} review</span>}
      {(batch.error || batch.data?.message) && <p role="status">{batch.error?.message ?? batch.data?.message}</p>}
    </div>
    <Dialog open={open} onOpenChange={setOpen} title="Action-item research settings" description="Stan prepares research and proposed changes. You approve changes and completion.">
      {draft && <form className="space-y-4" onSubmit={e => { e.preventDefault(); save.mutate(draft) }}>
        <label className="flex items-center gap-2"><input type="checkbox" checked={draft.automatic} onChange={e => setDraft({ ...draft, automatic: e.target.checked })} />Automatically research newly approved eligible items</label>
        <p className="text-sm text-muted">Existing items run only when you start them. Research uses your company research model and connection.</p>
        {([ ["thesis", "Thesis research"], ["kill_conditions", "Measurable kill conditions"], ["valuation", "Valuation research"] ] as const).map(([kind, label]) => <label key={kind} className="flex items-center gap-2"><input type="checkbox" checked={draft.enabled_kinds.includes(kind)} onChange={e => setDraft({ ...draft, enabled_kinds: e.target.checked ? [...draft.enabled_kinds, kind] : draft.enabled_kinds.filter(k => k !== kind) })} />{label}</label>)}
        {([ ["max_cost_usd", "Per-run budget ($)", 1, 25], ["daily_budget_usd", "Daily budget ($)", 1, 100], ["max_concurrent", "Concurrent runs", 1, 3] ] as const).map(([key, label, min, max]) => <label key={key} className="block text-sm">{label}<input className="ml-3 rounded border border-app bg-transparent p-2 w-24" type="number" min={min} max={max} step={key === "max_concurrent" ? 1 : 0.5} required value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.valueAsNumber })} /></label>)}
        <p className="text-xs text-muted">Each start reserves its full run budget against the daily limit. Retries retain their original total allowance.</p>
        {save.error && <p role="alert" className="text-red-600">{save.error.message}</p>}
        <button type="submit" className={button} disabled={save.isPending}>Save research settings</button>
      </form>}
    </Dialog>
  </>
}
