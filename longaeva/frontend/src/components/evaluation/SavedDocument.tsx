import { useEffect, useState } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Link } from "react-router-dom"
import {
  getSavedDocument,
  type SavedDocument as DocumentRead,
} from "@/lib/reportApi"
import { documentHref } from "@/lib/reportDisplay"
import { SurfaceCard } from "@/components/shared/SurfaceCard"

export function SavedDocument({ documentKey }: { documentKey: string }) {
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<{
    key: string
    document: DocumentRead | null
    error: string | null
  } | null>(null)
  useEffect(() => {
    let cancelled = false
    getSavedDocument(documentKey)
      .then((document) => {
        if (!cancelled) setState({ key: documentKey, document, error: null })
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setState({
            key: documentKey,
            document: null,
            error:
              e instanceof Error ? e.message : "Unable to load saved document",
          })
      })
    return () => {
      cancelled = true
    }
  }, [documentKey, revision])
  const current = state?.key === documentKey ? state : null
  if (!current) return <p role="status">Loading saved document…</p>
  if (current.error)
    return (
      <p className="theme-notice theme-notice-error">
        {current.error}{" "}
        <button
          className="theme-button-base theme-button-secondary"
          onClick={() => {
            setState(null)
            setRevision((n) => n + 1)
          }}
        >
          Retry document
        </button>
      </p>
    )
  const document = current.document
  if (!document) return null
  if (document.status === "pending")
    return <p className="theme-notice">{document.reason}</p>
  return (
    <SurfaceCard className="p-5">
      <article className="saved-markdown">
        <Markdown
          remarkPlugins={[remarkGfm]}
          skipHtml
          components={{
            a: ({ href, children }) => {
              const safe = documentHref(href, document.document_links)
              if (!safe) return <span>{children}</span>
              return safe.startsWith("/evaluation") ? (
                <Link className="text-link" to={safe}>
                  {children}
                </Link>
              ) : (
                <a
                  className="text-link"
                  href={safe}
                  target={safe.startsWith("http") ? "_blank" : undefined}
                  rel="noreferrer"
                >
                  {children}
                </a>
              )
            },
            img: ({ alt }) => <span>{alt}</span>,
            table: ({ children }) => (
              <div className="overflow-x-auto my-4">
                <table className="report-table">{children}</table>
              </div>
            ),
            pre: ({ children }) => <pre className="report-pre">{children}</pre>,
          }}
        >
          {document.markdown}
        </Markdown>
      </article>
    </SurfaceCard>
  )
}
