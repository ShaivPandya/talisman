import { AlertCircle, FileText, Image as ImageIcon, Loader2, Table, X } from "lucide-react"
import { attachmentUrl, formatAttachmentSize, type AgentAttachment, type AttachmentKind } from "@/lib/chatAttachments"
import { cn } from "@/lib/utils"

const KIND_ICON = { pdf: FileText, image: ImageIcon, csv: Table } satisfies Record<AttachmentKind, typeof FileText>

/** A file that is still uploading, or failed to. Ready files are `AgentAttachment`s. */
export interface PendingAttachment {
  key: string
  name: string
  size: number
  status: "uploading" | "error"
  error?: string
}

const chipClass = "inline-flex max-w-full items-center gap-1.5 rounded-lg border border-app bg-card px-2 py-1 text-xs text-app"

function AttachmentThumb({ attachment }: { attachment: AgentAttachment }) {
  const Icon = KIND_ICON[attachment.kind] ?? FileText
  if (attachment.kind === "image") {
    return <img src={attachmentUrl(attachment.id)} alt="" className="h-7 w-7 shrink-0 rounded object-cover" loading="lazy" />
  }
  return <Icon size={14} className="shrink-0 text-muted" aria-hidden="true" />
}

/** The files a sent message carried. Each opens in a new tab. */
export function AttachmentChips({ attachments, className }: { attachments: AgentAttachment[]; className?: string }) {
  if (!attachments.length) return null
  return (
    <ul className={cn("flex flex-wrap gap-1.5", className)} aria-label="Attachments">
      {attachments.map(attachment => (
        <li key={attachment.id} className="min-w-0 max-w-full">
          <a
            href={attachmentUrl(attachment.id)}
            target="_blank"
            rel="noreferrer"
            className={cn(chipClass, "transition-colors hover:bg-card-muted")}
            title={`${attachment.name} · ${formatAttachmentSize(attachment.size)}`}
          >
            <AttachmentThumb attachment={attachment} />
            <span className="min-w-0 truncate">{attachment.name}</span>
            {attachment.size > 0 && <span className="shrink-0 text-subtle">{formatAttachmentSize(attachment.size)}</span>}
          </a>
        </li>
      ))}
    </ul>
  )
}

/** The files waiting in the composer: uploaded ones, and ones still uploading or failed. */
export function ComposerAttachmentChips({
  ready,
  pending,
  onRemoveReady,
  onRemovePending,
}: {
  ready: AgentAttachment[]
  pending: PendingAttachment[]
  onRemoveReady: (id: string) => void
  onRemovePending: (key: string) => void
}) {
  if (!ready.length && !pending.length) return null
  return (
    <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Files to attach">
      {ready.map(attachment => (
        <li key={attachment.id} className={chipClass} title={`${attachment.name} · ${formatAttachmentSize(attachment.size)}`}>
          <AttachmentThumb attachment={attachment} />
          <span className="min-w-0 truncate">{attachment.name}</span>
          <button
            type="button"
            onClick={() => onRemoveReady(attachment.id)}
            className="shrink-0 rounded p-0.5 text-muted transition-colors hover:text-app"
            aria-label={`Remove ${attachment.name}`}
          >
            <X size={12} aria-hidden="true" />
          </button>
        </li>
      ))}
      {pending.map(item => (
        <li
          key={item.key}
          className={cn(chipClass, item.status === "error" && "border-[hsl(var(--destructive)/0.3)] text-negative")}
          role={item.status === "error" ? "alert" : "status"}
        >
          {item.status === "uploading"
            ? <Loader2 size={14} className="shrink-0 animate-spin text-muted" aria-hidden="true" />
            : <AlertCircle size={14} className="shrink-0" aria-hidden="true" />}
          <span className="min-w-0 truncate">
            {item.status === "uploading" ? `Uploading ${item.name}…` : `${item.name}: ${item.error ?? "Upload failed"}`}
          </span>
          <button
            type="button"
            onClick={() => onRemovePending(item.key)}
            className="shrink-0 rounded p-0.5 text-muted transition-colors hover:text-app"
            aria-label={item.status === "uploading" ? `Cancel upload of ${item.name}` : `Dismiss ${item.name}`}
          >
            <X size={12} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  )
}
