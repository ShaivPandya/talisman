import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, FileUp, Trash2 } from "lucide-react"
import { attachNameDocument, deleteNameDocument, fetchNameDocuments, uploadNameDocument, type NameDocument } from "@/lib/api"
import { cn } from "@/lib/utils"

// One preference for every name's page, so a long file list stays out of the way once collapsed.
const COLLAPSED_KEY = "talisman.sourceFiles.collapsed"

function storedCollapsed() {
  try { return localStorage.getItem(COLLAPSED_KEY) === "true" } catch { return false }
}

function DocumentRow({ document, ticker }: { document: NameDocument; ticker: string }) {
  const qc = useQueryClient()
  const fieldId = useId()
  const [names, setNames] = useState("")
  const [attached, setAttached] = useState(false)
  const remove = useMutation({
    mutationFn: () => deleteNameDocument(ticker, document.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["name-documents", ticker] }),
  })
  const attach = useMutation({
    mutationFn: () => attachNameDocument(ticker, document.id, names.split(/[,\s]+/).filter(Boolean)),
    onSuccess: () => { setNames(""); setAttached(true); void qc.invalidateQueries({ queryKey: ["name-documents"] }) },
  })
  return (
    <li className="space-y-2 border-t border-app py-3 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <a href={document.url} className="break-words text-sm text-link underline underline-offset-2">{document.name}</a>
          <p className="text-xs text-subtle">Private upload · {Math.max(1, Math.ceil(document.size / 1024))} KB · {new Date(document.created_at).toLocaleDateString()}</p>
        </div>
        <button type="button" disabled={remove.isPending} onClick={() => remove.mutate()}
          aria-label={`Remove ${document.name} from ${ticker}`} title={`Remove from ${ticker}`}
          className="shrink-0 rounded p-2 text-muted hover:text-app disabled:opacity-50">
          <Trash2 size={16} aria-hidden="true" />
        </button>
      </div>
      <details>
        <summary className="cursor-pointer text-xs text-muted">Attach to other names</summary>
        <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); setAttached(false); attach.mutate() }}>
          <div>
            <label htmlFor={fieldId} className="block text-xs text-muted">Symbols, separated by commas</label>
            <input id={fieldId} value={names} onChange={event => setNames(event.target.value)} placeholder="MU, EURUSD=X, GC=F"
              className="mt-1 rounded border border-app bg-card px-2 py-1 text-sm text-app" />
          </div>
          <button type="submit" disabled={!names.trim() || attach.isPending} className="rounded border border-app px-3 py-1 text-sm text-app disabled:opacity-50">
            {attach.isPending ? "Attaching…" : "Attach file"}
          </button>
        </form>
        {attached && <p role="status" className="mt-1 text-xs text-muted">File attached to the selected names.</p>}
      </details>
      {(remove.error || attach.error) && <p role="alert" className="text-sm text-red-600">{(remove.error || attach.error)?.message}</p>}
    </li>
  )
}

export function NameDocumentsPanel({ ticker }: { ticker: string }) {
  const qc = useQueryClient()
  const inputId = useId()
  const contentId = useId()
  const [collapsed, setCollapsed] = useState(storedCollapsed)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState("")
  const files = useQuery({ queryKey: ["name-documents", ticker], queryFn: () => fetchNameDocuments(ticker) })

  function toggle() {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem(COLLAPSED_KEY, String(next)) } catch { /* storage may be unavailable */ }
  }

  async function upload(selected: File[]) {
    setCollapsed(false)
    setUploading(true)
    setError("")
    const errors: string[] = []
    try {
      for (const file of selected) {
        try {
          await uploadNameDocument(ticker, file)
        } catch (reason) {
          errors.push(`${file.name}: ${reason instanceof Error ? reason.message : "Upload failed."}`)
        }
      }
      await qc.invalidateQueries({ queryKey: ["name-documents", ticker] })
      setError(errors.join(" "))
    } finally {
      setUploading(false)
    }
  }

  return (
    <section aria-label={`Source files for ${ticker}`} className="theme-surface mb-4 rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-app">
          <button type="button" onClick={toggle} aria-expanded={!collapsed} aria-controls={contentId}
            className="flex items-center gap-2 text-left">
            <ChevronDown size={16} aria-hidden="true" className={cn("shrink-0 text-subtle transition-transform", collapsed && "-rotate-90")} />
            Source files
            {files.data != null && files.data.count > 0 && <span className="text-xs font-normal text-subtle">{files.data.count}</span>}
          </button>
        </h2>
        <label htmlFor={inputId} className={`inline-flex items-center gap-2 rounded border border-app px-3 py-2 text-sm text-app ${uploading ? "opacity-50" : "cursor-pointer"}`}>
          <FileUp size={15} aria-hidden="true" /> {uploading ? "Uploading…" : "Add source files"}
          <input id={inputId} type="file" multiple disabled={uploading} aria-label="Add source files"
            accept=".pdf,.txt,.md,.markdown,.csv,application/pdf,text/plain,text/markdown,text/csv"
            className="sr-only" onChange={event => {
              const selected = Array.from(event.target.files ?? [])
              event.target.value = ""
              if (selected.length) void upload(selected)
            }} />
        </label>
      </div>
      {uploading && <p role="status" className="mt-2 text-xs text-muted">Reading and saving source files…</p>}
      {(error || files.error) && <p role="alert" className="mt-2 text-sm text-red-600">{error || files.error?.message}</p>}
      <div id={contentId} hidden={collapsed}>
        <p className="mt-1 text-xs text-muted">Private workspace sources for research and Stan. PDF, text, Markdown or CSV, up to 20 MiB each.</p>
        {files.isPending && <p role="status" className="mt-2 text-xs text-muted">Loading source files…</p>}
        {files.data?.count === 0 && <p className="mt-3 text-sm text-subtle">No source files attached to {ticker}.</p>}
        <ul className="mt-2">
          {files.data?.documents.map(document => <DocumentRow key={document.id} document={document} ticker={ticker} />)}
        </ul>
      </div>
    </section>
  )
}
