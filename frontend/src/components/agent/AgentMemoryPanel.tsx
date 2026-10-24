import { useDeferredValue, useState } from "react"
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { fetchMemoryEntries, MEMORY_ENTRIES_KEY, updateMemory, type MemoryContext, type MemoryEntry, type useAgentMemory } from "@/hooks/agentMemory"

interface Props {
  memory: ReturnType<typeof useAgentMemory>
  lastContext?: MemoryContext
}
export function AgentMemoryPanel({ memory, lastContext }: Props) {
  const client = useQueryClient()
  const [search, setSearch] = useState("")
  const query = useDeferredValue(search)
  const [editing, setEditing] = useState<{ sessionId: string; text: string } | null>(null)
  const entries = useInfiniteQuery({
    queryKey: [...MEMORY_ENTRIES_KEY, query],
    queryFn: ({ pageParam, signal }) => fetchMemoryEntries(query, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => last.has_more ? pages.reduce((count, page) => count + page.entries.length, 0) : undefined,
    retry: 1,
  })
  const mutation = useMutation({
    mutationFn: updateMemory,
    onSuccess: () => { setEditing(null); void client.invalidateQueries({ queryKey: MEMORY_ENTRIES_KEY }) },
  })
  function beginEdit(entry: MemoryEntry) {
    mutation.reset()
    setEditing({ sessionId: entry.session_id, text: entry.summary })
  }
  return (
    <div className="flex-1 overflow-y-auto bg-app px-4 py-4">
      <div className="mx-auto w-full max-w-[42rem] space-y-4">
        <section className="rounded-xl border border-app bg-card p-4">
          <label className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium text-app">
            Don’t use memory in this chat
            <input type="checkbox" checked={!memory.enabled} disabled={memory.saving || memory.loading}
              onChange={event => memory.setEnabled(!event.target.checked)} aria-label="Don’t use memory in this chat" />
          </label>
          <p className="mt-2 text-xs leading-5 text-muted">Applies to future replies. This chat’s history and document research remain available.</p>
          {memory.saving && <p role="status" className="mt-2 text-xs text-muted">Saving memory preference…</p>}
          {memory.error && <div role="alert" className="mt-2 text-xs text-negative">{memory.error} <button type="button" className="underline" onClick={memory.retry}>Retry settings</button></div>}
        </section>
        <section aria-label="Memory used for latest reply" className="rounded-xl border border-app bg-card p-4">
          <h3 className="text-sm font-semibold text-app">Memory used for latest reply</h3>
          <p className="mt-1 text-xs leading-5 text-muted">This snapshot shows what was sent. Saved edits and deletions apply to future replies.</p>
          {!lastContext ? <p className="mt-3 text-sm text-muted">Send a message to see which memories are used.</p> : <>
            {lastContext.error && <p role="alert" className="mt-3 text-xs text-negative">{lastContext.error}</p>}
            {lastContext.memories.length === 0 ? <p className="mt-3 text-sm text-muted">{lastContext.enabled ? "No conversation memory was used." : "Memory was off for this reply."}</p>
              : lastContext.memories.map(entry => <article key={entry.session_id} className="mt-3 border-t border-app pt-3">
                <p className="text-xs font-medium text-muted">{entry.title || "Past conversation"} · {(entry.ended_at || entry.started_at || "").slice(0, 10)}</p>
                <p className="mt-1 whitespace-pre-wrap break-words text-sm text-app">{entry.summary}</p>
              </article>)}
            {lastContext.prompt && <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer">Exact memory sent</summary><pre className="mt-2 whitespace-pre-wrap break-words">{lastContext.prompt}</pre></details>}
          </>}
        </section>
        <section aria-label="Saved conversation memory" className="rounded-xl border border-app bg-card p-4">
          <h3 className="text-sm font-semibold text-app">Saved conversation memory</h3>
          <p className="mt-1 text-xs leading-5 text-muted">Relevant summaries may be used in any chat. Edits and deletions apply everywhere; original conversations stay in History.</p>
          <input type="search" aria-label="Search saved memory" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} placeholder="Search memory" className="theme-input mt-3 w-full rounded-lg px-3 py-2 text-sm" />
          {mutation.error && <p role="alert" className="mt-3 text-xs text-negative">{mutation.error.message}</p>}
          {entries.isPending ? <p role="status" className="mt-3 text-sm text-muted">Loading memory…</p>
            : entries.isError ? <div role="alert" className="mt-3 text-sm text-negative">{entries.error.message} <button type="button" className="underline" onClick={() => void entries.refetch()}>Retry memory</button></div>
            : <>
              {entries.data.pages.every(page => page.entries.length === 0) && <p className="mt-3 text-sm text-muted">{search ? "No matching memories." : "No saved conversation memory yet."}</p>}
              {entries.data.pages.flatMap(page => page.entries).map(entry => <article key={entry.session_id} className="mt-3 border-t border-app pt-3">
                <p className="text-xs font-medium text-muted">{entry.title || "Past conversation"} · {(entry.ended_at || entry.started_at || "").slice(0, 10)}</p>
                {editing?.sessionId === entry.session_id ? <form onSubmit={event => {
                  event.preventDefault()
                  if (editing.text.trim()) mutation.mutate({ sessionId: entry.session_id, summary: editing.text.trim() })
                }}>
                  <textarea aria-label="Edit memory summary" value={editing.text} onChange={event => setEditing({ sessionId: entry.session_id, text: event.target.value })} maxLength={12000} rows={5} className="theme-input mt-2 w-full rounded-lg px-3 py-2 text-sm" />
                  <div className="mt-2 flex gap-3 text-xs"><button type="submit" disabled={mutation.isPending || !editing.text.trim()} className="text-link disabled:opacity-50">Save memory</button><button type="button" disabled={mutation.isPending} onClick={() => setEditing(null)}>Cancel</button></div>
                </form> : <>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm text-app">{entry.summary}</p>
                  <div className="mt-2 flex gap-3 text-xs"><button type="button" disabled={mutation.isPending} onClick={() => beginEdit(entry)} className="text-link">Edit memory</button><button type="button" disabled={mutation.isPending} onClick={() => mutation.mutate({ sessionId: entry.session_id })} className="text-negative">Delete memory</button></div>
                </>}
              </article>)}
              {entries.hasNextPage && <button type="button" disabled={entries.isFetchingNextPage} onClick={() => void entries.fetchNextPage()} className="mt-4 text-sm text-link">{entries.isFetchingNextPage ? "Loading…" : "Load more memory"}</button>}
            </>}
        </section>
      </div>
    </div>
  )
}
