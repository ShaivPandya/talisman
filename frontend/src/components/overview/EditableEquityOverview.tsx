import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { EquityOverviewReadView } from "@/components/overview/EquityOverviewReadView"
import { ActionButton } from "@/components/shared/FormControls"
import { StagedProposalNotice } from "@/components/shared/StagedProposalNotice"
import { saveOverviewContent } from "@/lib/api"
import { invalidateApprovalSummaries } from "@/lib/approvalQueries"
import type { ParsedOverview } from "@/lib/overviewTypes"

const SECONDARY = "rounded-lg border border-app px-3 py-1.5 text-sm font-medium text-muted hover:text-app transition-colors disabled:opacity-50"

export function EditableEquityOverview({ content, parsed, ticker, editLabel = "Edit overview" }: {
  content: string | null
  parsed: ParsedOverview | null
  ticker: string
  editLabel?: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const qc = useQueryClient()
  const saveMutation = useMutation({
    mutationFn: () => saveOverviewContent(ticker, draft),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["dossier", ticker] }),
        qc.invalidateQueries({ queryKey: ["idea"] }),
        qc.invalidateQueries({ queryKey: ["ideas"] }),
        invalidateApprovalSummaries(qc),
      ])
      setEditing(false)
    },
  })
  const proposal = saveMutation.data?.application_status !== "applied" ? saveMutation.data : null

  function startEdit() {
    setDraft(content ?? "")
    saveMutation.reset()
    setEditing(true)
  }

  return (
    <div>
      <StagedProposalNotice proposal={proposal} showReviewLink className="mb-3">
        contains your overview changes. Review it before the stored overview changes.
      </StagedProposalNotice>
      {editing ? (
        <div>
          <label htmlFor={`overview-editor-${ticker}`} className="mb-2 block text-sm font-medium text-app">Overview</label>
          <textarea
            id={`overview-editor-${ticker}`}
            value={draft}
            onChange={event => setDraft(event.target.value)}
            disabled={saveMutation.isPending}
            className="w-full min-h-[400px] rounded-lg border border-app bg-transparent p-3 text-sm text-app font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder={`# ${ticker} Overview\n## Financials\n## Sensitivity to Extrinsic Factors\n## Industry`}
          />
          {saveMutation.isError && <p role="alert" className="mt-1 text-sm text-red-600">{saveMutation.error.message}</p>}
          <div className="mt-2 flex gap-2">
            <ActionButton onClick={() => saveMutation.mutate()} disabled={!draft.trim()} loading={saveMutation.isPending} loadingText="Saving..." className="w-auto">
              Save Overview
            </ActionButton>
            <button type="button" onClick={() => setEditing(false)} disabled={saveMutation.isPending} className={SECONDARY}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <div className="mb-4 flex justify-end">
            <button type="button" onClick={startEdit} className={SECONDARY}>{content ? editLabel : "Write Overview"}</button>
          </div>
          {content ? <EquityOverviewReadView content={content} parsed={parsed} ticker={ticker} />
            : <p className="rounded-lg border border-app bg-card-muted px-3 py-4 text-sm text-muted">No overview stored.</p>}
        </>
      )}
    </div>
  )
}
