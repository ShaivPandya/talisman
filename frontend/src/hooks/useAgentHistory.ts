import { useEffect, useRef, useState } from "react"
import { useInfiniteQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query"
import type { SessionSummary } from "./useAgentChat"
import { fetchHistoryPage, pinSession, removeHistorySession, type SessionHistoryPage } from "./agentSessionHistory"

export const AGENT_HISTORY_QUERY_KEY = ["agent-history"] as const

interface PendingDeletion {
  session: SessionSummary
  timer: number | null
}

export function useAgentHistory(enabled: boolean, onDeleted: (sessionId: string) => void) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const [pendingDeletions, setPendingDeletions] = useState<SessionSummary[]>([])
  const [hiddenSessionIds, setHiddenSessionIds] = useState<Set<string>>(() => new Set())
  const deletionsRef = useRef(new Map<string, PendingDeletion>())
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    const deletions = deletionsRef.current
    return () => {
      // Leaving the app before the Undo window closes cancels pending deletions.
      for (const deletion of deletions.values()) {
        if (deletion.timer !== null) window.clearTimeout(deletion.timer)
      }
      deletions.clear()
    }
  }, [])

  const historyQuery = useInfiniteQuery({
    queryKey: [...AGENT_HISTORY_QUERY_KEY, query],
    queryFn: ({ pageParam, signal }) => fetchHistoryPage(query, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: page => page.next_cursor ?? undefined,
    enabled,
    retry: 1,
  })

  function updatePendingDeletions() {
    setPendingDeletions([...deletionsRef.current.values()].filter(item => item.timer !== null).map(item => item.session))
    setHiddenSessionIds(new Set(deletionsRef.current.keys()))
  }

  function scheduleDelete(session: SessionSummary) {
    if (deletionsRef.current.has(session.session_id)) return
    setDeleteError(null)
    const timer = window.setTimeout(() => {
      // Keep the row hidden while the DELETE is in flight, but end the Undo window.
      const deletion = deletionsRef.current.get(session.session_id)
      if (!deletion) return
      deletion.timer = null
      updatePendingDeletions()
      void removeHistorySession(session.session_id).then(() => {
        queryClient.setQueriesData<InfiniteData<SessionHistoryPage>>({ queryKey: AGENT_HISTORY_QUERY_KEY }, data => data && ({
          ...data,
          pages: data.pages.map(page => ({ ...page, sessions: page.sessions.filter(item => item.session_id !== session.session_id) })),
        }))
        onDeleted(session.session_id)
      }).catch((error: unknown) => {
        setDeleteError(error instanceof Error ? error.message : "Could not delete the conversation.")
      }).finally(() => {
        deletionsRef.current.delete(session.session_id)
        updatePendingDeletions()
        void queryClient.invalidateQueries({ queryKey: AGENT_HISTORY_QUERY_KEY })
      })
    }, 10_000)
    deletionsRef.current.set(session.session_id, { session, timer })
    updatePendingDeletions()
  }

  function undoDelete(sessionId: string) {
    const deletion = deletionsRef.current.get(sessionId)
    if (!deletion || deletion.timer === null) return
    window.clearTimeout(deletion.timer)
    deletionsRef.current.delete(sessionId)
    updatePendingDeletions()
  }

  async function togglePin(session: SessionSummary) {
    await pinSession(session.session_id, !session.pinned_at)
    await queryClient.invalidateQueries({ queryKey: AGENT_HISTORY_QUERY_KEY })
  }

  const seen = new Set<string>()
  const history = (historyQuery.data?.pages.flatMap(page => page.sessions) ?? []).filter(session => {
    if (session.message_count <= 0 || hiddenSessionIds.has(session.session_id) || seen.has(session.session_id)) return false
    seen.add(session.session_id)
    return true
  })

  return {
    history, search, setSearch, pendingDeletions, deleteError,
    dismissDeleteError: () => setDeleteError(null),
    scheduleDelete, undoDelete, togglePin,
    loading: historyQuery.isPending || search.trim() !== query,
    loadingMore: historyQuery.isFetchingNextPage,
    hasMore: historyQuery.hasNextPage,
    error: historyQuery.error?.message ?? null,
    loadMore: () => { if (!historyQuery.isFetching) void historyQuery.fetchNextPage() },
    retry: () => { void historyQuery.refetch() },
  }
}
