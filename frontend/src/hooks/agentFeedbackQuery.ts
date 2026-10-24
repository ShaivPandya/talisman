import { queryOptions } from "@tanstack/react-query"
import { fetchAgentResponseFeedback, type AgentResponseFeedbackRecord } from "@/lib/api"

export type SessionFeedback = Record<string, AgentResponseFeedbackRecord>

export const agentFeedbackQueryKey = (sessionId: string | null) => ["agent-response-feedback", sessionId] as const

/** One fetch per conversation load; message controls only subscribe to the cache. */
export function agentFeedbackQueryOptions(sessionId: string | null) {
  return queryOptions({
    queryKey: agentFeedbackQueryKey(sessionId),
    queryFn: async (): Promise<SessionFeedback> => {
      if (!sessionId) return {}
      const response = await fetchAgentResponseFeedback({ session_id: sessionId })
      const byTurn: SessionFeedback = {}
      // The API returns newest first. Preserve the latest label for each turn.
      for (const feedback of response.feedback ?? []) {
        const turnId = feedback.client_turn_id
        if (turnId && !byTurn[turnId]) byTurn[turnId] = feedback
      }
      return byTurn
    },
    enabled: Boolean(sessionId),
    staleTime: 5 * 60 * 1000,
    retry: false,
    retryOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}
