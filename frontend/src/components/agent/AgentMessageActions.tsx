import { useEffect, useRef, useState, type ReactNode } from "react"
import { Check, ChevronLeft, ChevronRight, Copy } from "lucide-react"
import { cn } from "@/lib/utils"
import { copyText } from "@/lib/clipboard"

const BUTTON_CLASS =
  "inline-flex h-6 min-w-6 items-center justify-center gap-1 rounded-md px-1.5 text-xs text-muted hover:bg-muted-surface hover:text-app focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 disabled:pointer-events-none disabled:opacity-40"

export function ActionButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled} className={BUTTON_CLASS}>
      {children}
    </button>
  )
}

export function CopyButton({ label, getText, className }: { label: string; getText: () => string; className?: string }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const copy = async () => {
    if (!(await copyText(getText()))) return
    setCopied(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <button
      type="button"
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      onClick={() => void copy()}
      className={cn(BUTTON_CLASS, className)}
    >
      {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
    </button>
  )
}

export function VersionSwitcher({
  index,
  count,
  disabled,
  onSwitch,
}: {
  index: number
  count: number
  disabled?: boolean
  onSwitch: (direction: -1 | 1) => void
}) {
  return (
    <div className="inline-flex items-center text-xs text-muted" role="group" aria-label="Versions">
      <button
        type="button"
        aria-label="Previous version"
        title="Previous version"
        onClick={() => onSwitch(-1)}
        disabled={disabled || index === 0}
        className={BUTTON_CLASS}
      >
        <ChevronLeft size={13} aria-hidden="true" />
      </button>
      <span className="min-w-8 text-center tabular-nums" aria-live="polite">
        {index + 1}/{count}
      </span>
      <button
        type="button"
        aria-label="Next version"
        title="Next version"
        onClick={() => onSwitch(1)}
        disabled={disabled || index === count - 1}
        className={BUTTON_CLASS}
      >
        <ChevronRight size={13} aria-hidden="true" />
      </button>
    </div>
  )
}

/** The row under a message: versions always show, the actions on hover or keyboard focus. */
export function MessageActionRow({
  align,
  version,
  disabled,
  onSwitchVersion,
  children,
}: {
  align: "start" | "end"
  version?: { index: number; count: number }
  disabled?: boolean
  onSwitchVersion?: (direction: -1 | 1) => void
  children: ReactNode
}) {
  return (
    <div className={cn("mt-1 flex h-6 items-center gap-1", align === "end" ? "justify-end" : "justify-start")}>
      {version && onSwitchVersion && (
        <VersionSwitcher index={version.index} count={version.count} disabled={disabled} onSwitch={onSwitchVersion} />
      )}
      <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        {children}
      </div>
    </div>
  )
}

export function EditMessageForm({
  initialValue,
  onCancel,
  onSubmit,
}: {
  initialValue: string
  onCancel: () => void
  onSubmit: (value: string) => void
}) {
  const [value, setValue] = useState(initialValue)
  const field = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    field.current?.focus()
    field.current?.setSelectionRange(initialValue.length, initialValue.length)
  }, [initialValue])
  const canSend = value.trim().length > 0 && value.trim() !== initialValue.trim()

  return (
    <form
      className="w-[min(86%,42rem)] rounded-2xl border border-app bg-card p-2 shadow-sm"
      onSubmit={event => {
        event.preventDefault()
        if (canSend) onSubmit(value)
      }}
    >
      <textarea
        ref={field}
        aria-label="Edit message"
        value={value}
        rows={Math.min(8, Math.max(2, value.split("\n").length))}
        onChange={event => setValue(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Escape") onCancel()
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && canSend) onSubmit(value)
        }}
        className="w-full resize-none bg-transparent px-2 py-1 text-sm leading-6 text-app outline-none"
      />
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onCancel} className="theme-button-secondary px-3 py-1 text-xs">
          Cancel
        </button>
        <button type="submit" disabled={!canSend} className="theme-button-primary px-3 py-1 text-xs disabled:opacity-50">
          Send
        </button>
      </div>
    </form>
  )
}
