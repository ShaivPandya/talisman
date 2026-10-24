import { useCallback, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { csrfHeaders } from "@/lib/csrfToken"

export interface MemoryEntry {
  session_id: string
  title: string | null
  started_at: string | null
  ended_at: string | null
  summary: string
}
export interface MemoryContext {
  enabled: boolean
  memories: MemoryEntry[]
  prompt: string
  error?: string
}
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/+$/, "")
const DRAFT_KEY = "agent-memory-draft:v1"
export const MEMORY_ENTRIES_KEY = ["agent-memory-entries"] as const

async function memoryRequest<T>(path: string, method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  const url = `${BASE_URL}/memory/${path}`
  const response = await fetch(url, {
    method, credentials: "include", signal,
    headers: method === "GET" ? undefined : {
      "Content-Type": "application/json", ...csrfHeaders(),
      "X-Request-Schema-Name": `${method.toLowerCase()}:${new URL(url, window.location.origin).pathname}`,
      "X-Request-Schema-Version": "1",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof payload?.detail === "string" ? payload.detail : "Could not update memory. Please try again.")
  }
  return response.json() as Promise<T>
}
export function fetchMemoryEntries(query: string, offset: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ q: query, offset: String(offset), limit: "30" })
  return memoryRequest<{ entries: MemoryEntry[]; has_more: boolean }>(`entries?${params}`, "GET", undefined, signal)
}
export function updateMemory(entry: { sessionId: string; summary?: string }) {
  return memoryRequest(`entries/${encodeURIComponent(entry.sessionId)}`, entry.summary === undefined ? "DELETE" : "PATCH",
    entry.summary === undefined ? undefined : { summary: entry.summary })
}
export function useAgentMemory(sessionId: string | null, visible: boolean, lastContext?: MemoryContext) {
  const client = useQueryClient()
  const [draftEnabled, setDraftEnabled] = useState(() => {
    try { return localStorage.getItem(DRAFT_KEY) !== "false" } catch { return true }
  })
  const [optimistic, setOptimistic] = useState<{ sessionId: string; enabled: boolean } | null>(null)
  const queryKey = ["agent-memory-settings", sessionId]
  const settings = useQuery({
    queryKey,
    queryFn: ({ signal }) => memoryRequest<{ enabled: boolean }>(`sessions/${encodeURIComponent(sessionId!)}/memory`, "GET", undefined, signal),
    enabled: visible && Boolean(sessionId), staleTime: 0, retry: 1,
  })
  const mutation = useMutation({
    mutationFn: (input: { sessionId: string; enabled: boolean }) => memoryRequest<{ enabled: boolean }>(`sessions/${encodeURIComponent(input.sessionId)}/memory`, "PATCH", { enabled: input.enabled }),
    onMutate: async input => {
      const key = ["agent-memory-settings", input.sessionId]
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<{ enabled: boolean }>(key)
      client.setQueryData(key, { enabled: input.enabled })
      return { key, previous }
    },
    onSuccess: (data, input) => {
      client.setQueryData(["agent-memory-settings", input.sessionId], data)
      setOptimistic(current => current?.sessionId === input.sessionId ? null : current)
    },
    onError: (_error, input, context) => {
      if (context) client.setQueryData(context.key, context.previous)
      setOptimistic(current => current?.sessionId === input.sessionId ? null : current)
    },
  })
  const resetDraft = useCallback(() => {
    setDraftEnabled(true)
    try { localStorage.removeItem(DRAFT_KEY) } catch { /* storage may be unavailable */ }
  }, [])
  function setEnabled(enabled: boolean) {
    if (sessionId) {
      setOptimistic({ sessionId, enabled })
      mutation.mutate({ sessionId, enabled })
    }
    else {
      setDraftEnabled(enabled)
      try { localStorage.setItem(DRAFT_KEY, String(enabled)) } catch { /* storage may be unavailable */ }
    }
  }
  return {
    enabled: sessionId ? (optimistic?.sessionId === sessionId ? optimistic.enabled : settings.data?.enabled ?? lastContext?.enabled ?? true) : draftEnabled,
    draftEnabled, setEnabled, resetDraft, saving: mutation.isPending || optimistic?.sessionId === sessionId,
    loading: Boolean(sessionId) && settings.isPending,
    error: (mutation.variables?.sessionId === sessionId ? mutation.error?.message : undefined) ?? settings.error?.message,
    retry: () => { mutation.reset(); void settings.refetch() },
  }
}
