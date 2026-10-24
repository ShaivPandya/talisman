import { memo, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { GitPullRequest } from "lucide-react"
import { ApprovalChangeSummary } from "@/components/shared/ApprovalChangeSummary"
import { BaseStateBadge, DecisionStateBadge } from "@/components/shared/DecisionStateBadge"
import { ActionButton } from "@/components/shared/FormControls"
import type { AgentProposalPart } from "@/hooks/agentChatShared"
import { approveItem, fetchApproval, rejectItem, type ApprovalRecord } from "@/lib/api"
import {
  formatApprovalResolutionError,
  invalidateAfterApprovalResolution,
  invalidateApprovalSummaries,
  patchResolvedApprovalSummaries,
  shouldRefetchApprovalSummariesAfterError,
} from "@/lib/approvalQueries"
import { approvalDecisionState } from "@/lib/decisionState"
import { TOOL_LABELS, humanizeToolName } from "./agentToolDisplay"

const APPROVAL_NOTE_REQUIRED = "Approval note is required before applying an internal state change."

type Resolution = "approve" | "reject"

function applicationText(approval: ApprovalRecord): string | null {
  if (approval.status !== "approved") return null
  if (approval.application_status === "applied") return "Approved and applied."
  if (approval.application_status === "failed") return approval.application_error || "Approved, but applying the change failed."
  return "Approved."
}

/**
 * A pending approval a `propose_*` tool created. It reads the approval itself, so the card shows what the
 * approval is now, and approving or rejecting here goes through the same calls and cache updates as the Workspace.
 */
export const AgentProposalCard = memo(function AgentProposalCard({ proposal }: { proposal: AgentProposalPart }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["approval", proposal.approvalId],
    queryFn: () => fetchApproval(proposal.approvalId),
    staleTime: 15_000,
  })
  const [note, setNote] = useState("")
  const [submitting, setSubmitting] = useState<Resolution | null>(null)
  const [error, setError] = useState<string | null>(null)
  const approval = query.data
  const label = TOOL_LABELS[proposal.tool] ?? humanizeToolName(proposal.tool)
  const pending = approval ? (approval.status ?? "pending") === "pending" : false

  async function resolve(action: Resolution) {
    if (!approval || submitting) return
    const trimmed = note.trim()
    if (action === "approve" && !trimmed) {
      setError(APPROVAL_NOTE_REQUIRED)
      return
    }
    setError(null)
    setSubmitting(action)
    try {
      const resolved = action === "approve" ? await approveItem(approval.id, trimmed) : await rejectItem(approval.id, trimmed || undefined)
      queryClient.setQueryData(["approval", proposal.approvalId], resolved)
      patchResolvedApprovalSummaries(queryClient, resolved, approval)
      invalidateAfterApprovalResolution(queryClient, approval)
    } catch (err) {
      setError(formatApprovalResolutionError(err))
      if (shouldRefetchApprovalSummariesAfterError(err)) {
        void invalidateApprovalSummaries(queryClient)
        void query.refetch()
      }
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <section
      className="my-3 rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40"
      data-testid="agent-proposal-card"
      aria-label={`Proposal: ${label}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <GitPullRequest size={14} className="text-amber-700 dark:text-amber-300" aria-hidden="true" />
        <span className="font-semibold text-app">{label}</span>
        {(approval?.ticker ?? proposal.ticker) && (
          <span className="text-xs text-muted">{approval?.ticker ?? proposal.ticker}</span>
        )}
        {approval && <DecisionStateBadge state={approvalDecisionState(approval)} className="ml-auto" />}
        {approval?.base_state_status === "stale" && (
          <BaseStateBadge state={approval.base_state_status} message={approval.base_state_message} />
        )}
      </div>

      {query.isPending && <p className="mt-2 text-xs text-muted">Loading proposal…</p>}
      {query.isError && (
        <p className="mt-2 text-xs text-red-700 dark:text-red-300" role="alert">
          Could not load this proposal.{" "}
          <button type="button" className="underline" onClick={() => void query.refetch()}>
            Retry
          </button>{" "}
          or{" "}
          <Link to="/workspace" className="underline">
            review it in the Workspace
          </Link>
          .
        </p>
      )}

      {approval && (
        <>
          {approval.reason && <p className="mt-2 text-xs text-muted">{approval.reason}</p>}
          <details className="mt-2 text-xs text-muted">
            <summary className="cursor-pointer text-subtle hover:text-app">What changes</summary>
            <div className="mt-1.5">
              <ApprovalChangeSummary approval={approval} />
            </div>
          </details>

          {pending ? (
            <div className="mt-3 space-y-2">
              <label className="theme-field-label" htmlFor={`proposal-note-${proposal.approvalId}`}>
                Decision note
              </label>
              <textarea
                id={`proposal-note-${proposal.approvalId}`}
                value={note}
                onChange={event => setNote(event.target.value)}
                rows={2}
                className="theme-input w-full"
                placeholder="Required to approve. Optional to reject."
              />
              {error && (
                <p className="text-xs text-red-700 dark:text-red-300" role="alert">
                  {error}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <ActionButton
                  onClick={() => void resolve("approve")}
                  loading={submitting === "approve"}
                  loadingText="Applying..."
                  disabled={Boolean(submitting) || !note.trim() || approval.can_approve === false}
                  className="theme-button-success w-auto px-4"
                >
                  Approve
                </ActionButton>
                <ActionButton
                  onClick={() => void resolve("reject")}
                  loading={submitting === "reject"}
                  loadingText="Rejecting..."
                  disabled={Boolean(submitting) || approval.can_reject === false}
                  className="theme-button-destructive w-auto px-4"
                >
                  Reject
                </ActionButton>
                <Link to={approval.review_route ?? "/workspace"} className="text-xs underline text-muted hover:text-app">
                  Review in Workspace
                </Link>
              </div>
            </div>
          ) : (
            <p className="mt-2 text-xs text-muted">
              {applicationText(approval) ?? (approval.status === "rejected" ? "Rejected." : `Status: ${approval.status}`)}{" "}
              <Link to={approval.review_route ?? "/workspace"} className="underline hover:text-app">
                View
              </Link>
            </p>
          )}
        </>
      )}
    </section>
  )
})
