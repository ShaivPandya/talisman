import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2, Plus, Sparkles } from "lucide-react"

import { SelectInput, TextInput } from "@/components/shared/FormControls"
import { StagedProposalNotice } from "@/components/shared/StagedProposalNotice"
import { StatusBadge, type StatusTone } from "@/components/shared/StatusBadge"
import {
  createCatalyst,
  extractIdeaCatalysts,
  updateCatalystStatus,
  type StagedMutationResponse,
  type TrackedCatalyst,
} from "@/lib/api"
import { invalidateApprovalSummaries } from "@/lib/approvalQueries"
import { formatLabel } from "@/lib/ideaUtils"

const STATUS_TONES: Record<string, StatusTone> = {
  pending: "info", played_out: "success", failed: "error", superseded: "neutral",
}
const STATUSES = ["pending", "played_out", "failed", "superseded"]
const CATEGORIES = ["fundamental", "technical", "macro", "event", "regulatory"]
const BUTTON = "theme-button-base theme-button-secondary min-h-10 px-3 text-sm disabled:opacity-50"

export function IdeaCatalysts({ ideaId, ticker, catalysts, overviewPresent }: {
  ideaId: string
  ticker: string
  catalysts: TrackedCatalyst[]
  overviewPresent: boolean
}) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [description, setDescription] = useState("")
  const [category, setCategory] = useState("fundamental")
  const [targetDate, setTargetDate] = useState("")
  const [proposal, setProposal] = useState<StagedMutationResponse | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function refresh() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["idea"] }),
      qc.invalidateQueries({ queryKey: ["dossier", ticker] }),
      qc.invalidateQueries({ queryKey: ["catalysts", ticker] }),
      invalidateApprovalSummaries(qc),
    ])
  }

  const extraction = useMutation({
    mutationFn: () => extractIdeaCatalysts(ideaId),
    onSuccess: async result => {
      if (result.approval_id && result.application_status !== "applied") {
        setProposal(result as StagedMutationResponse)
        setMessage(null)
      } else {
        setProposal(null)
        setMessage(result.extracted_count
          ? `Catalysts saved from overview research. ${result.catalysts.length} tracked; existing statuses preserved.`
          : "No source-backed catalysts found in the overview research.")
      }
      await refresh()
    },
  })
  const creation = useMutation({
    mutationFn: () => createCatalyst({
      ticker, description: description.trim(), category, ...(targetDate ? { target_date: targetDate } : {}),
    }),
    onSuccess: async result => {
      setProposal(result)
      setMessage(null)
      setDescription("")
      setTargetDate("")
      setAdding(false)
      await refresh()
    },
  })
  const statusChange = useMutation({
    mutationFn: ({ catalyst, status }: { catalyst: TrackedCatalyst; status: string }) =>
      updateCatalystStatus(catalyst.object_uid || catalyst.id, status),
    onSuccess: async result => {
      setProposal(result)
      setMessage(null)
      await refresh()
    },
  })
  const busy = extraction.isPending || creation.isPending || statusChange.isPending
  const error = extraction.error || creation.error || statusChange.error

  return (
    <section className="space-y-4" aria-label="Idea catalysts">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="section-title text-sm">Catalysts</h3>
          <p className="mt-1 text-xs text-subtle">Track upcoming events and drivers from overview research.</p>
          {!overviewPresent && <p className="mt-1 text-xs text-subtle">Store an overview to extract catalysts.</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={BUTTON} disabled={!overviewPresent || busy} onClick={() => extraction.mutate()}>
            {extraction.isPending ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Sparkles size={16} aria-hidden="true" />}
            {extraction.isPending ? "Extracting" : "Extract from overview"}
          </button>
          <button type="button" className={BUTTON} disabled={busy} onClick={() => setAdding(!adding)} aria-expanded={adding}>
            <Plus size={16} aria-hidden="true" /> Add catalyst
          </button>
        </div>
      </div>
      {message && <p role="status" className="text-sm text-muted">{message}</p>}
      <StagedProposalNotice proposal={proposal} showReviewLink />
      {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error.message}</p>}
      {adding && (
        <form className="space-y-3 rounded-lg border border-app p-4" onSubmit={event => {
          event.preventDefault()
          if (description.trim()) creation.mutate()
        }}>
          <TextInput id="idea-catalyst-description" label="Catalyst description" value={description} onChange={setDescription} disabled={busy} />
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectInput id="idea-catalyst-category" label="Category" value={category} onChange={setCategory}
              options={CATEGORIES.map(value => ({ value, label: formatLabel(value) }))} disabled={busy} />
            <TextInput id="idea-catalyst-target" label="Target date (optional)" type="date" value={targetDate} onChange={setTargetDate} disabled={busy} />
          </div>
          <div className="flex gap-2">
            <button type="submit" className={BUTTON} disabled={!description.trim() || busy}>Propose catalyst</button>
            <button type="button" className={BUTTON} disabled={busy} onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </form>
      )}
      {catalysts.length === 0 && <p className="text-sm text-muted">No catalysts tracked.</p>}
      {catalysts.map(catalyst => {
        const status = catalyst.status || "pending"
        return (
          <article key={catalyst.object_uid || catalyst.id} className="space-y-2 rounded-lg border border-app px-4 py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="text-sm font-medium text-app">{catalyst.description || "Untitled catalyst"}</p>
              <StatusBadge tone={STATUS_TONES[status] ?? "neutral"}>{formatLabel(status)}</StatusBadge>
            </div>
            <div className="flex flex-wrap gap-3 text-xs text-subtle">
              <span>{formatLabel(catalyst.category || "uncategorized")}</span>
              {catalyst.target_date && <span>Target: {catalyst.target_date}</span>}
            </div>
            {catalyst.evidence && <p className="text-xs text-muted whitespace-pre-wrap">{catalyst.evidence}</p>}
            <div className="flex flex-wrap gap-2">
              {STATUSES.filter(value => value !== status).map(value => (
                <button key={value} type="button" disabled={busy}
                  onClick={() => statusChange.mutate({ catalyst, status: value })}
                  className="rounded border border-app px-2 py-1 text-xs text-muted hover:text-app disabled:opacity-50">
                  Propose {formatLabel(value).toLowerCase()}
                </button>
              ))}
            </div>
          </article>
        )
      })}
    </section>
  )
}
