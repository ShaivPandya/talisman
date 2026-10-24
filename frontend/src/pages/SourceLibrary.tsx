import { useEffect, useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"

import { ErrorMessage, LoadingSpinner } from "@/components/shared/LoadingSpinner"
import { PageHeader } from "@/components/shared/PageHeader"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { useApiQuery } from "@/hooks/useApiQuery"
import { deleteSourceFile, fetchSourceLibrary, type SourceLibraryFile } from "@/lib/api"

const QUERY_KEY = ["source-library"]

function formatSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.ceil(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function LibraryRow({ file }: { file: SourceLibraryFile }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const removeRef = useRef<HTMLButtonElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const names = file.tickers.join(", ")
  const remove = useMutation({
    mutationFn: () => deleteSourceFile(file.sha256),
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: QUERY_KEY }),
      qc.invalidateQueries({ queryKey: ["name-documents"] }),
    ]),
  })

  useEffect(() => { if (confirming) cancelRef.current?.focus() }, [confirming])

  return (
    <li className="space-y-2 border-t border-app py-3 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <a href={file.url} className="break-words text-sm text-link underline underline-offset-2">{file.name}</a>
          <p className="text-xs text-subtle">
            {formatSize(file.size)} · Uploaded {new Date(file.created_at).toLocaleDateString()}
          </p>
          {file.other_names.length > 0 && (
            <p className="text-xs text-subtle">Also uploaded as {file.other_names.join(", ")}</p>
          )}
          <ul aria-label={`Names ${file.name} is attached to`} className="mt-2 flex flex-wrap gap-1.5">
            {file.tickers.map(ticker => (
              <li key={ticker} className="rounded border border-app px-2 py-0.5 text-xs text-app">{ticker}</li>
            ))}
          </ul>
        </div>
        {!confirming && (
          <button type="button" ref={removeRef} onClick={() => setConfirming(true)}
            aria-label={`Delete ${file.name} from every name`} title="Delete from every name"
            className="shrink-0 rounded p-2 text-muted hover:text-app">
            <Trash2 size={16} aria-hidden="true" />
          </button>
        )}
      </div>
      {confirming && (
        <div role="group" aria-label={`Confirm deleting ${file.name}`} className="flex flex-wrap items-center gap-2 rounded border border-app p-3">
          <p className="mr-auto text-sm text-app">
            Delete {file.name} from {names}? Research and Stan will stop using it. This cannot be undone.
          </p>
          <button type="button" disabled={remove.isPending} onClick={() => remove.mutate()}
            className="rounded border border-app px-3 py-1 text-sm text-red-600 disabled:opacity-50">
            {remove.isPending ? "Deleting…" : "Delete file"}
          </button>
          <button type="button" ref={cancelRef} disabled={remove.isPending}
            onClick={() => { setConfirming(false); remove.reset(); requestAnimationFrame(() => removeRef.current?.focus()) }}
            className="rounded border border-app px-3 py-1 text-sm text-app disabled:opacity-50">
            Cancel
          </button>
        </div>
      )}
      {remove.error && <p role="alert" className="text-sm text-red-600">{remove.error.message}</p>}
    </li>
  )
}

export function SourceLibrary() {
  // Files are added on name pages, so always re-read the workspace when this page opens.
  const library = useApiQuery(QUERY_KEY, fetchSourceLibrary, 0)

  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Source Library"
        subtitle="Every private source file uploaded to any name. Deleting a file removes it from every name it is attached to."
      />
      {library.isPending && <LoadingSpinner message="Loading source files…" />}
      {library.error && <ErrorMessage message={library.error.message} />}
      {library.data && (
        <SurfaceCard className="p-4">
          <h2 className="text-sm font-semibold text-app">
            {library.data.count === 1 ? "1 source file" : `${library.data.count} source files`}
          </h2>
          {library.data.count === 0 ? (
            <p className="mt-3 text-sm text-subtle">
              No source files have been uploaded yet. Add them from the Source files section of a name's page.
            </p>
          ) : (
            <ul className="mt-2">
              {library.data.files.map(file => <LibraryRow key={file.sha256} file={file} />)}
            </ul>
          )}
        </SurfaceCard>
      )}
    </div>
  )
}
