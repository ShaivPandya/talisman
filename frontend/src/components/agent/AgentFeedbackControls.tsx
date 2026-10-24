import { useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { MessageSquare, PencilLine, ThumbsDown, ThumbsUp } from "lucide-react"
import type { AgentMessage } from "@/hooks/agentChatShared"
import { agentFeedbackQueryKey, agentFeedbackQueryOptions, type SessionFeedback } from "@/hooks/agentFeedbackQuery"
import {
  submitAgentResponseFeedback,
  type AgentFeedbackDecision,
  type SubmitAgentResponseFeedbackRequest,
} from "@/lib/api"
import { AgentResponseFeedbackDialog } from "./AgentResponseFeedbackDialog"

interface AgentFeedbackControlsProps {
  message: AgentMessage
  sessionId: string | null
}

const BUTTON_CLASS = "inline-flex h-6 min-w-6 items-center justify-center gap-1 rounded-md px-1.5 text-xs text-muted hover:bg-muted-surface hover:text-app focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 disabled:opacity-40 aria-pressed:text-link"

export function AgentFeedbackControls({ message, sessionId }: AgentFeedbackControlsProps) {
  const queryClient = useQueryClient()
  // The chat hook owns the fetch. This observer selects just this turn's rating,
  // so mounting messages or switching branches never starts another request.
  const feedbackQuery = useQuery({
    ...agentFeedbackQueryOptions(sessionId),
    enabled: false,
    select: data => data[message.clientTurnId ?? ""] ?? null,
  })
  const feedback = feedbackQuery.data ?? message.feedback ?? null
  const [dialogDecision, setDialogDecision] = useState<AgentFeedbackDecision | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const canSubmit = Boolean(sessionId && message.clientTurnId && !message.isStreaming
    && message.messageStatus !== "stopped" && message.messageStatus !== "failed")

  const handleSubmit = async (payload: SubmitAgentResponseFeedbackRequest) => {
    if (!sessionId || !message.clientTurnId || submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    setError(null)
    try {
      const response = await submitAgentResponseFeedback({
        ...payload,
        session_id: sessionId,
        client_turn_id: message.clientTurnId,
      })
      queryClient.setQueryData<SessionFeedback>(agentFeedbackQueryKey(sessionId), current => ({
        ...current,
        [message.clientTurnId!]: response.feedback,
      }))
      setDialogDecision(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save feedback")
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  if (!canSubmit) return null
  const disabled = submitting || feedbackQuery.isFetching

  return (
    <>
      <div className="flex items-center gap-0.5" role="group" aria-label="Response feedback">
        <button
          type="button"
          aria-label="Good response"
          title="Good response"
          aria-pressed={feedback?.decision === "approve"}
          disabled={disabled}
          onClick={() => void handleSubmit({ decision: "approve", eligible_for_training: false })}
          className={BUTTON_CLASS}
        >
          <ThumbsUp size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Bad response"
          title="Bad response"
          aria-pressed={feedback?.decision === "reject"}
          disabled={disabled}
          onClick={() => void handleSubmit({ decision: "reject", eligible_for_training: false })}
          className={BUTTON_CLASS}
        >
          <ThumbsDown size={13} aria-hidden="true" />
        </button>
        {feedback && (
          <button
            type="button"
            aria-label="Feedback details"
            title="Feedback details"
            disabled={disabled}
            onClick={() => { setError(null); setDialogDecision(feedback.decision) }}
            className={BUTTON_CLASS}
          >
            <MessageSquare size={13} aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          aria-label="Correct response"
          title="Correct response"
          aria-pressed={feedback?.decision === "correct"}
          disabled={disabled}
          onClick={() => { setError(null); setDialogDecision("correct") }}
          className={BUTTON_CLASS}
        >
          <PencilLine size={13} aria-hidden="true" />
        </button>
        {error && dialogDecision === null && <span role="alert" className="ml-1 text-xs text-negative">{error}</span>}
      </div>
      {dialogDecision !== null && (
        <AgentResponseFeedbackDialog
          open
          onOpenChange={open => { if (!open) setDialogDecision(null) }}
          decision={dialogDecision}
          initialContent={message.content}
          initialFeedback={feedback}
          submitting={submitting}
          error={error}
          onSubmit={payload => void handleSubmit(payload)}
        />
      )}
    </>
  )
}
