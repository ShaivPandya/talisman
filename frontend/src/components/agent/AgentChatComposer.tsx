import { AtSign, Brain, ChevronDown, Monitor, Paperclip, Plus, Send, Square, X, Zap } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { fetchPortfolioPositions, fetchThesisMeta, uploadAgentAttachment, type AgentWorkflow } from "@/lib/api"
import type { ScreenContext } from "@/contexts/ScreenContext"
import {
  ATTACHMENT_ACCEPT,
  DEFAULT_ATTACHMENT_PROMPT,
  MAX_ATTACHMENTS,
  attachmentFileProblem,
  type AgentAttachment,
} from "@/lib/chatAttachments"
import { cn } from "@/lib/utils"
import { ComposerAttachmentChips, type PendingAttachment } from "./AgentAttachmentChips"
import { resizeChatTextarea } from "./agentChatTextarea"
import { composerTrigger, filterComposerSuggestions, mentionSuggestions, type ComposerSuggestion } from "./agentComposerSuggestions"
import {
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  type RefObject,
} from "react"

export interface AgentChatDraft {
  value: string
  selection: { start: number; end: number } | null
}

export interface AgentChatComposerHandle {
  setInput: (value: string, attachments?: AgentAttachment[]) => void
  dismissSuggestions: () => boolean
}

interface AgentChatComposerProps {
  ref?: Ref<AgentChatComposerHandle>
  loadDraft: () => AgentChatDraft
  onDraftChange: (draft: AgentChatDraft) => void
  onSend: (content: string, attachments: AgentAttachment[]) => void
  /** Files uploaded but not yet sent, kept like the draft text while the composer is unmounted. */
  loadAttachments?: () => AgentAttachment[]
  onAttachmentsChange?: (attachments: AgentAttachment[]) => void
  onStop: () => void
  /** True while the current turn is in progress (stream, job poll, or active tools). */
  isBusy: boolean
  queuedCount?: number
  textareaRef: RefObject<HTMLTextAreaElement | null>
  compactWorkflowSlot?: ReactNode
  workflowsOpen?: boolean
  onToggleWorkflows?: () => void
  workflows: AgentWorkflow[]
  workflowsLoading: boolean
  workflowsError: boolean
  screenContext?: ScreenContext
  includeScreenContext: boolean
  onToggleScreenContext: () => void
  thinkingEnabled: boolean
  onToggleThinking: () => void
}

export function AgentChatComposer({
  ref,
  loadDraft,
  onDraftChange,
  onSend,
  loadAttachments,
  onAttachmentsChange,
  onStop,
  isBusy,
  queuedCount = 0,
  textareaRef,
  compactWorkflowSlot,
  workflowsOpen,
  onToggleWorkflows,
  workflows,
  workflowsLoading,
  workflowsError,
  screenContext,
  includeScreenContext,
  onToggleScreenContext,
  thinkingEnabled,
  onToggleThinking,
}: AgentChatComposerProps) {
  // The ref preserves drafts while the dialog or another panel unmounts this
  // composer; keystrokes only update local state, never the message list.
  const [input, setInput] = useState(() => loadDraft().value)
  const [selection, setSelection] = useState(() => {
    const draft = loadDraft()
    return draft.selection ?? { start: draft.value.length, end: draft.value.length }
  })
  const [focused, setFocused] = useState(false)
  const [ready, setReady] = useState<AgentAttachment[]>(() => loadAttachments?.() ?? [])
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const [attachProblem, setAttachProblem] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const uploadsRef = useRef(new Map<string, AbortController>())
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [menuState, setMenuState] = useState({ key: "", index: 0, dismissed: false })
  const menuId = useId()
  const trigger = focused ? composerTrigger(input, selection.start, selection.end) : null
  const triggerKey = trigger ? `${trigger.kind}:${trigger.start}:${trigger.end}:${input}` : ""
  const menuOpen = Boolean(trigger && !(menuState.key === triggerKey && menuState.dismissed))
  const needsMentions = menuOpen && trigger?.kind !== "workflow"
  const positionsQuery = useQuery({
    queryKey: ["portfolio", "positions"], queryFn: () => fetchPortfolioPositions(),
    enabled: needsMentions, staleTime: 5 * 60 * 1000, retry: 1,
  })
  const thesesQuery = useQuery({
    queryKey: ["thesis", "meta"], queryFn: fetchThesisMeta,
    enabled: needsMentions, staleTime: 5 * 60 * 1000, retry: 1,
  })
  const mentions = useMemo(() => mentionSuggestions(
    positionsQuery.data?.positions ?? [], thesesQuery.data ?? [], screenContext?.ticker,
  ), [positionsQuery.data, thesesQuery.data, screenContext?.ticker])
  const suggestions = trigger ? filterComposerSuggestions(trigger, workflows, mentions) : []
  const selectedIndex = Math.min(menuState.key === triggerKey ? menuState.index : 0, Math.max(0, suggestions.length - 1))
  const commandMatch = input.trim().match(/^\/workflow:([A-Za-z0-9_]+)(?::(.*))?$/)
  const needsWorkflowTicker = Boolean(commandMatch
    && workflows.some(workflow => workflow.name === commandMatch[1] && workflow.requiresTicker)
    && !commandMatch[2]?.trim())
  const hasInput = Boolean(input.trim())
  const uploading = pending.some(item => item.status === "uploading")
  const canSend = (hasInput || ready.length > 0) && !uploading && !needsWorkflowTicker

  useImperativeHandle(ref, () => ({
    setInput(value, attachments) {
      onDraftChange({ value, selection: { start: value.length, end: value.length } })
      setInput(value)
      setSelection({ start: value.length, end: value.length })
      if (attachments) setReady(attachments)
    },
    dismissSuggestions() {
      if (!menuOpen) return false
      setMenuState({ key: triggerKey, index: 0, dismissed: true })
      return true
    },
  }), [onDraftChange, menuOpen, triggerKey])

  useEffect(() => {
    if (textareaRef.current) resizeChatTextarea(textareaRef.current)
  }, [input, textareaRef])

  useEffect(() => {
    onAttachmentsChange?.(ready)
  }, [ready, onAttachmentsChange])

  useEffect(() => {
    const uploads = uploadsRef.current
    return () => uploads.forEach(controller => controller.abort())
  }, [])

  useEffect(() => {
    if (menuOpen) document.getElementById(`${menuId}-${selectedIndex}`)?.scrollIntoView({ block: "nearest" })
  }, [menuOpen, menuId, selectedIndex])

  function addFiles(files: File[]) {
    if (!files.length) return
    const room = MAX_ATTACHMENTS - ready.length - pending.length
    const problems: string[] = []
    if (files.length > Math.max(room, 0)) problems.push(`You can attach up to ${MAX_ATTACHMENTS} files to a message.`)
    for (const file of files.slice(0, Math.max(room, 0))) {
      const problem = attachmentFileProblem(file)
      if (problem) {
        problems.push(problem)
        continue
      }
      const key = crypto.randomUUID()
      const controller = new AbortController()
      uploadsRef.current.set(key, controller)
      setPending(previous => [...previous, { key, name: file.name, size: file.size, status: "uploading" }])
      uploadAgentAttachment(file, controller.signal)
        .then(attachment => {
          setPending(previous => previous.filter(item => item.key !== key))
          setReady(previous => [...previous, attachment])
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          const reason = error instanceof Error && error.message ? error.message : "Upload failed"
          setPending(previous => previous.map(item => item.key === key ? { ...item, status: "error", error: reason } : item))
        })
        .finally(() => uploadsRef.current.delete(key))
    }
    setAttachProblem(problems.length ? problems.join(" ") : null)
  }

  function removePending(key: string) {
    uploadsRef.current.get(key)?.abort()
    setPending(previous => previous.filter(item => item.key !== key))
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    // A screenshot pastes as a file. Text copied from a spreadsheet also carries an image, so leave that alone.
    const files = Array.from(event.clipboardData.files)
    if (!files.length || event.clipboardData.getData("text/plain")) return
    event.preventDefault()
    addFiles(files)
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    if (!event.dataTransfer.types.includes("Files")) return
    event.preventDefault()
    setDragging(true)
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    if (!event.dataTransfer.files.length) return
    event.preventDefault()
    setDragging(false)
    addFiles(Array.from(event.dataTransfer.files))
  }

  function handleSend() {
    if (!canSend) return
    const content = input.trim()
    const attachments = ready
    onDraftChange({ value: "", selection: { start: 0, end: 0 } })
    setInput("")
    setSelection({ start: 0, end: 0 })
    setReady([])
    setAttachProblem(null)
    onSend(content || DEFAULT_ATTACHMENT_PROMPT, attachments)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    if (menuOpen && suggestions.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault()
        const step = event.key === "ArrowDown" ? 1 : -1
        setMenuState({ key: triggerKey, index: (selectedIndex + step + suggestions.length) % suggestions.length, dismissed: false })
        return
      }
      if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
        event.preventDefault()
        chooseSuggestion(suggestions[selectedIndex])
        return
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      handleSend()
    }
  }

  function rememberSelection(element: HTMLTextAreaElement) {
    const next = { start: element.selectionStart, end: element.selectionEnd }
    setSelection(previous => previous.start === next.start && previous.end === next.end ? previous : next)
    onDraftChange({ value: element.value, selection: next })
  }

  function replaceInput(value: string, caret: number) {
    setInput(value)
    setSelection({ start: caret, end: caret })
    setMenuState({ key: "", index: 0, dismissed: false })
    onDraftChange({ value, selection: { start: caret, end: caret } })
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current
      if (textarea?.value === value) {
        textarea.focus()
        textarea.setSelectionRange(caret, caret)
      }
    })
  }

  function chooseSuggestion(suggestion: ComposerSuggestion) {
    if (!trigger) return
    const insertion = trigger.kind === "mention" ? `@${suggestion.insertion}` : suggestion.insertion
    const suffix = input.slice(trigger.end)
    const separator = suggestion.workflow?.requiresTicker || /^\s/.test(suffix) ? "" : " "
    const next = input.slice(0, trigger.start) + insertion + separator + suffix
    const caret = trigger.start + insertion.length + separator.length
    replaceInput(next, caret)
    // A workflow requiring a ticker moves directly into ticker completion.
    if (!suggestion.workflow?.requiresTicker) {
      const nextTrigger = composerTrigger(next, caret, caret)
      if (nextTrigger) setMenuState({ key: `${nextTrigger.kind}:${nextTrigger.start}:${nextTrigger.end}:${next}`, index: 0, dismissed: true })
    }
  }

  function insertMention() {
    const prefix = input.slice(0, selection.start)
    const insertion = `${prefix && !/\s$/.test(prefix) ? " " : ""}@`
    replaceInput(prefix + insertion + input.slice(selection.end), prefix.length + insertion.length)
  }

  const sendLabel = isBusy ? "Queue follow-up" : "Send message"
  const sendTitle = isBusy ? "Queue follow-up" : "Send message"

  return (
    <div
      className={cn("safe-bottom relative shrink-0 border-t border-app bg-card px-4 py-3", dragging && "ring-2 ring-inset ring-[hsl(var(--accent))]")}
      onDragOver={handleDragOver}
      onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
      onDrop={handleDrop}
    >
      {compactWorkflowSlot && onToggleWorkflows && (
        <div className="mb-3">
          <button
            type="button"
            onClick={onToggleWorkflows}
            className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-app"
            aria-expanded={workflowsOpen}
          >
            <Zap size={13} aria-hidden="true" />
            <span>Workflows</span>
            <ChevronDown size={12} className={cn("transition-transform", workflowsOpen && "rotate-180")} aria-hidden="true" />
          </button>
          {workflowsOpen && compactWorkflowSlot}
        </div>
      )}

      {isBusy && (
        <div className="mb-2 flex items-center justify-between gap-3 rounded-lg border border-app bg-card-muted px-3 py-2 text-xs text-muted" aria-live="polite">
          <span>
            Generating response
            {queuedCount > 0 ? ` · ${queuedCount} queued` : " · Enter queues follow-up"}
          </span>
          <span className="h-2 w-2 rounded-full bg-[hsl(var(--accent))] animate-pulse" aria-hidden="true" />
        </div>
      )}

      <ComposerAttachmentChips
        ready={ready}
        pending={pending}
        onRemoveReady={id => setReady(previous => previous.filter(item => item.id !== id))}
        onRemovePending={removePending}
      />
      {attachProblem && <p className="mb-2 text-xs text-negative" role="alert">{attachProblem}</p>}

      <div className="relative">
        {menuOpen && trigger && (
          <div className="absolute bottom-full z-10 mb-2 max-h-[min(18rem,40dvh)] w-full overflow-y-auto rounded-xl border border-app bg-card p-2 shadow-[var(--shadow-floating)]">
            <p className="px-2 py-1 text-xs text-subtle">
              {trigger.kind === "workflow" ? "Workflows" : trigger.kind === "ticker" ? "Choose or type a ticker" : "Tickers, positions and theses"}
            </p>
            <div id={menuId} role="listbox" aria-label={trigger.kind === "workflow" ? "Workflow suggestions" : "Mention suggestions"}>
              {suggestions.map((suggestion, index) => (
                <button
                  key={suggestion.id}
                  id={`${menuId}-${index}`}
                  type="button"
                  role="option"
                  aria-selected={index === selectedIndex}
                  tabIndex={-1}
                  onMouseDown={event => event.preventDefault()}
                  onClick={() => chooseSuggestion(suggestion)}
                  className={cn("flex w-full flex-col rounded-lg px-3 py-2 text-left text-sm", index === selectedIndex ? "bg-card-muted text-app" : "text-muted hover:bg-card-muted")}
                >
                  <span className="font-medium">{suggestion.label}</span>
                  <span className="text-xs text-subtle">{suggestion.description}</span>
                </button>
              ))}
            </div>
            {trigger.kind === "workflow" ? (
              (workflowsLoading || workflowsError || !suggestions.length) && <p className="px-2 py-2 text-xs text-muted" role="status">
                {workflowsLoading ? "Loading workflows…" : workflowsError ? "Workflows are unavailable right now." : "No matching workflows."}
              </p>
            ) : (
              <>
                {(positionsQuery.isFetching || thesesQuery.isFetching) && <p className="px-2 py-1 text-xs text-muted" role="status">Loading saved positions and theses…</p>}
                {(positionsQuery.isError || thesesQuery.isError) && <p className="px-2 py-1 text-xs text-muted" role="status">Some saved suggestions are unavailable. You can still enter a ticker.</p>}
                {!suggestions.length && <p className="px-2 py-2 text-xs text-muted">Type a ticker to use it.</p>}
              </>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={event => {
              const value = event.currentTarget.value
              setInput(value)
              rememberSelection(event.currentTarget)
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocused(true)}
            onKeyUp={event => rememberSelection(event.currentTarget)}
            onMouseUp={event => rememberSelection(event.currentTarget)}
            onSelect={event => rememberSelection(event.currentTarget)}
            onBlur={event => {
              rememberSelection(event.currentTarget)
              setFocused(false)
            }}
            onInput={event => resizeChatTextarea(event.currentTarget)}
            onPaste={handlePaste}
            placeholder="Ask about markets, portfolio, macro..."
            aria-label="Message Stan"
            aria-autocomplete="list"
            aria-controls={menuOpen ? menuId : undefined}
            aria-activedescendant={menuOpen && suggestions.length ? `${menuId}-${selectedIndex}` : undefined}
            rows={1}
            className="theme-input min-h-[44px] min-w-0 max-h-[120px] flex-1 resize-none overflow-x-hidden rounded-xl text-sm leading-5"
            style={{ height: "44px", overflowX: "hidden", overflowY: "hidden" }}
          />
          {isBusy && (
            <button
              type="button"
              onClick={onStop}
              className="theme-button-destructive flex h-11 w-11 flex-none items-center justify-center rounded-full"
              aria-label="Stop generating"
              title="Stop generating (Esc)"
            >
              <Square size={14} aria-hidden="true" />
            </button>
          )}
          {(!isBusy || hasInput || ready.length > 0) && (
            <button
              type="button"
              onClick={handleSend}
              disabled={!canSend}
              className="theme-button-primary flex h-11 w-11 flex-none items-center justify-center rounded-full text-[hsl(var(--accent-foreground))] disabled:cursor-not-allowed disabled:opacity-40"
              aria-label={sendLabel}
              title={sendTitle}
            >
              <Send size={14} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      {needsWorkflowTicker && <p className="mt-2 text-xs text-muted" role="status">Choose or enter a ticker to run this workflow.</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => replaceInput("/", 1)} disabled={hasInput} aria-label="Choose workflow" title="Choose workflow (/)" className="theme-button-secondary flex h-9 items-center gap-1 rounded-lg px-2 text-xs disabled:opacity-40">
          <Zap size={13} aria-hidden="true" /> /
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Attach files"
          title="Attach PDFs, images or CSVs. You can also paste or drop them."
          className="theme-button-secondary flex h-9 items-center rounded-lg px-2 text-xs"
        >
          <Paperclip size={13} aria-hidden="true" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ATTACHMENT_ACCEPT}
          tabIndex={-1}
          aria-hidden="true"
          className="hidden"
          onChange={event => {
            addFiles(Array.from(event.currentTarget.files ?? []))
            event.currentTarget.value = ""
          }}
        />
        <button type="button" onClick={insertMention} aria-label="Mention ticker, position or thesis" title="Mention ticker, position or thesis (@)" className="theme-button-secondary flex h-9 items-center rounded-lg px-2 text-xs">
          <AtSign size={13} aria-hidden="true" />
        </button>
        <button type="button" onClick={onToggleThinking} aria-pressed={thinkingEnabled} title="Applies to the next message only" className={cn("theme-button-secondary flex h-9 items-center gap-1.5 rounded-lg px-2 text-xs", thinkingEnabled && "text-link")}>
          <Brain size={13} aria-hidden="true" /> Thinking
        </button>
        {screenContext && (
          <button type="button" onClick={onToggleScreenContext} aria-label={includeScreenContext ? "Remove screen context" : "Attach screen context"} title={includeScreenContext ? "Remove screen context from the next message" : "Attach screen context to the next message"} className="theme-button-secondary flex min-h-9 min-w-0 max-w-full items-center gap-1.5 rounded-lg px-2 text-xs">
            <Monitor size={13} className="shrink-0" aria-hidden="true" />
            <span className="truncate">{includeScreenContext ? screenContext.pageName : "Add screen context"}{includeScreenContext && screenContext.ticker ? ` · ${screenContext.ticker}` : ""}</span>
            {includeScreenContext ? <X size={12} className="shrink-0" aria-hidden="true" /> : <Plus size={12} className="shrink-0" aria-hidden="true" />}
          </button>
        )}
      </div>
    </div>
  )
}
