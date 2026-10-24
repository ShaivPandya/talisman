export type AttachmentKind = "pdf" | "image" | "csv"

/** What the server stores for an uploaded file and keeps on the message that cites it. */
export interface AgentAttachment {
  id: string
  name: string
  mime_type: string
  kind: AttachmentKind
  size: number
}

const MIB = 1024 * 1024

export const MAX_ATTACHMENTS = 5
export const MAX_UPLOAD_BYTES: Record<AttachmentKind, number> = { pdf: 20 * MIB, image: 5 * MIB, csv: 2 * MIB }
export const ATTACHMENT_ACCEPT = "application/pdf,image/png,image/jpeg,image/webp,text/csv,.pdf,.png,.jpg,.jpeg,.webp,.csv"
/** Sent when files are attached with no text, so a screenshot alone is a valid message. */
export const DEFAULT_ATTACHMENT_PROMPT = "Please review the attached file(s)."

const KIND_LABEL: Record<AttachmentKind, string> = { pdf: "PDF", image: "image", csv: "CSV file" }

export function attachmentKindOf(file: Pick<File, "name" | "type">): AttachmentKind | null {
  const type = file.type.toLowerCase()
  const name = file.name.toLowerCase()
  if (type === "application/pdf" || name.endsWith(".pdf")) return "pdf"
  if (["image/png", "image/jpeg", "image/webp"].includes(type) || /\.(png|jpe?g|webp)$/.test(name)) return "image"
  if (type === "text/csv" || type === "application/csv" || name.endsWith(".csv")) return "csv"
  return null
}

/** A reason the file cannot be attached, or null. The server checks again; this saves the upload. */
export function attachmentFileProblem(file: File): string | null {
  const kind = attachmentKindOf(file)
  if (!kind) return `${file.name || "That file"} is not supported. Attach a PDF, a PNG, JPEG or WebP image, or a CSV file.`
  if (file.size === 0) return `${file.name || "That file"} is empty.`
  const limit = MAX_UPLOAD_BYTES[kind]
  if (file.size > limit) return `${file.name || "That file"} is larger than the ${limit / MIB} MiB limit for a ${KIND_LABEL[kind]}.`
  return null
}

export function formatAttachmentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < MIB) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / MIB).toFixed(bytes < 10 * MIB ? 1 : 0)} MB`
}

export function attachmentUrl(id: string): string {
  const base = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/+$/, "")
  return `${base}/agent/attachments/${encodeURIComponent(id)}`
}

function kindFromMime(mime: string): AttachmentKind {
  if (mime.startsWith("image/")) return "image"
  return mime === "text/csv" ? "csv" : "pdf"
}

/** Attachments as the server sends them back on a message. Anything with an id is kept. */
export function normalizeAttachments(value: unknown): AgentAttachment[] {
  if (!Array.isArray(value)) return []
  const found: AgentAttachment[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const record = item as Record<string, unknown>
    if (typeof record.id !== "string" || !record.id) continue
    const mime = typeof record.mime_type === "string" ? record.mime_type : ""
    found.push({
      ...record,
      id: record.id,
      name: typeof record.name === "string" && record.name ? record.name : "Attachment",
      mime_type: mime,
      kind: record.kind === "pdf" || record.kind === "image" || record.kind === "csv" ? record.kind : kindFromMime(mime),
      size: typeof record.size === "number" ? record.size : 0,
    })
  }
  return found
}
