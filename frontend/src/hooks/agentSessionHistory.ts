import type { SessionSummary } from "./useAgentChat"
import { csrfHeaders } from "@/lib/csrfToken"

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/+$/, "")

function mutationHeaders(method: string, url: string) {
  return {
    ...csrfHeaders(),
    "X-Request-Schema-Name": `${method.toLowerCase()}:${new URL(url, window.location.origin).pathname}`,
    "X-Request-Schema-Version": "1",
  }
}

export interface SessionHistoryPage {
  sessions: SessionSummary[]
  next_cursor: string | null
}

async function checkResponse(response: Response) {
  if (response.ok) return response
  const body = await response.json().catch(() => null) as { detail?: string } | null
  throw new Error(body?.detail || "Could not update conversation history. Please try again.")
}

export async function fetchHistoryPage(query: string, cursor: string | null, signal?: AbortSignal): Promise<SessionHistoryPage> {
  const params = new URLSearchParams({ limit: "30", paginated: "true" })
  if (query) params.set("q", query)
  if (cursor) params.set("cursor", cursor)
  const response = await checkResponse(await fetch(`${BASE_URL}/memory/sessions?${params}`, {
    credentials: "include", signal,
  }))
  const data = await response.json() as SessionHistoryPage | SessionSummary[]
  // Also accept the original list response during a rolling server deployment.
  return Array.isArray(data) ? { sessions: data, next_cursor: null } : data
}

export async function pinSession(sessionId: string, pinned: boolean): Promise<SessionSummary> {
  const url = `${BASE_URL}/memory/sessions/${encodeURIComponent(sessionId)}`
  const response = await checkResponse(await fetch(url, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...mutationHeaders("PATCH", url) },
    body: JSON.stringify({ pinned }),
  }))
  return response.json() as Promise<SessionSummary>
}

export async function removeHistorySession(sessionId: string) {
  const url = `${BASE_URL}/memory/sessions/${encodeURIComponent(sessionId)}`
  await checkResponse(await fetch(url, {
    method: "DELETE", credentials: "include", headers: mutationHeaders("DELETE", url),
  }))
}

export async function exportHistorySession(session: SessionSummary) {
  const response = await checkResponse(await fetch(`${BASE_URL}/memory/sessions/${encodeURIComponent(session.session_id)}/export`, {
    credentials: "include",
  }))
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  const filename = Array.from(session.title || "Conversation", character => character.charCodeAt(0) < 32 ? "_" : character)
    .join("").replace(/[<>:"/\\|?*]/g, "_").slice(0, 120)
  anchor.download = `${filename}.md`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
