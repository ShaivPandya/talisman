import * as RadixDialog from "@radix-ui/react-dialog"
import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { cn } from "@/lib/utils"
import {
  fetchAgentResponsePreferences,
  fetchAgentWorkflows,
  updateAgentResponsePreferences,
  type AgentResponsePreferences,
  type AgentWorkflow,
} from "@/lib/api"
import { renameSessionTitle, useAgentChat, type AgentJobCompletion, type AgentMessage } from "@/hooks/useAgentChat"
import { AGENT_HISTORY_QUERY_KEY, useAgentHistory } from "@/hooks/useAgentHistory"
import { exportHistorySession } from "@/hooks/agentSessionHistory"
import type { ScreenContext } from "@/contexts/ScreenContext"
import type { StanOpenDetail } from "@/lib/stanLauncher"
import { AgentChatComposer, type AgentChatComposerHandle, type AgentChatDraft } from "./AgentChatComposer"
import { AgentChatQueuePanel } from "./AgentChatQueuePanel"
import { AgentChatHeader } from "./AgentChatHeader"
import { AgentCompletionToast } from "./AgentCompletionToast"
import { AgentContextPane } from "./AgentContextPane"
import { AgentHistoryPanel } from "./AgentHistoryPanel"
import { AgentMessageStream } from "./AgentMessageStream"
import { AgentPreferencesPanel } from "./AgentPreferencesPanel"
import { AgentWorkflowLauncher } from "./AgentWorkflowLauncher"
import { QUICK_PROMPT_GROUPS } from "./agentChatPrompts"
import { resizeChatTextarea } from "./agentChatTextarea"
import { useMediaQuery } from "./useMediaQuery"
import { useDecisionTrace } from "@/contexts/DecisionTraceContext"
import type { AgentPanel, AgentViewMode } from "./AgentChatTypes"

const PREFERENCES_STORAGE_KEY = "agent-response-preferences"
const RESPONSE_PREFERENCES_QUERY_KEY = ["agent-response-preferences"] as const

const DEFAULT_RESPONSE_PREFERENCES: AgentResponsePreferences = {
  personality: "pragmatic",
  warmth: "less",
  enthusiasm: "less",
  headers_lists: "less",
  emoji: "less",
  fast_answers: true,
  thinking_enabled: false,
  custom_instructions: "",
}

interface AgentChatProps {
  open: boolean
  onClose: () => void
  screenContext?: ScreenContext
  pendingCommand?: StanOpenDetail | null
  onPendingCommandConsumed?: () => void
  desktopViewMode?: AgentViewMode
  onViewModeChange?: (mode: AgentViewMode) => void
}

interface WorkflowInvalidationTarget {
  workflowName: string
  ticker: string | null
}

function loadResponsePreferences(): AgentResponsePreferences {
  try {
    const raw = localStorage.getItem(PREFERENCES_STORAGE_KEY)
    if (!raw) return DEFAULT_RESPONSE_PREFERENCES
    const parsed = JSON.parse(raw) as Partial<AgentResponsePreferences>
    return {
      ...DEFAULT_RESPONSE_PREFERENCES,
      ...parsed,
    }
  } catch {
    return DEFAULT_RESPONSE_PREFERENCES
  }
}

function normalizePreferences(prefs: AgentResponsePreferences): AgentResponsePreferences {
  return {
    ...prefs,
    custom_instructions: prefs.custom_instructions?.trim() || "",
  }
}

function workflowTargetFromCommand(value: string): WorkflowInvalidationTarget | null {
  const match = value.trim().match(/^\/workflow:([A-Za-z0-9_]+)(?::([A-Za-z0-9._-]+))?(?:\s|$)/)
  if (!match) return null
  return {
    workflowName: match[1],
    ticker: match[2] ? match[2].toUpperCase() : null,
  }
}

function invalidateWorkflowRunQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  target: WorkflowInvalidationTarget,
) {
  void queryClient.invalidateQueries({ queryKey: ["workspace"] })
  void queryClient.invalidateQueries({ queryKey: ["workflow-runs"] })
  if (target.ticker) {
    void queryClient.invalidateQueries({ queryKey: ["dossier", target.ticker] })
  }
}

export function AgentChat({
  open,
  onClose,
  screenContext,
  pendingCommand,
  onPendingCommandConsumed,
  desktopViewMode = "compact",
  onViewModeChange,
}: AgentChatProps) {
  const [completions, setCompletions] = useState<AgentJobCompletion[]>([])
  const handleDurableComplete = useCallback((completion: AgentJobCompletion) => {
    setCompletions(current => [...current, completion])
  }, [])
  const dismissCompletion = useCallback((jobId: string) => {
    setCompletions(current => current.filter(completion => completion.jobId !== jobId))
  }, [])
  const {
    messages,
    messageVersions,
    isStreaming,
    isComposerBusy,
    error,
    sessionId,
    sessionTitle,
    queuedMessages,
    sendMessage,
    regenerate,
    editAndResend,
    switchBranch,
    stopStreaming,
    clearChat,
    forgetSession,
    loadSession,
    applySessionTitle,
    removeQueuedMessage,
    editQueuedMessage,
    clearQueuedMessages,
    sendQueuedMessageNow,
  } = useAgentChat(handleDurableComplete)
  const { openDecisionTrace } = useDecisionTrace()
  const queryClient = useQueryClient()
  const isDesktop = useMediaQuery("(min-width: 1024px)")
  const viewMode: AgentViewMode = isDesktop ? desktopViewMode : "compact"
  const docked = isDesktop && viewMode === "compact"
  const [activePanel, setActivePanel] = useState<AgentPanel>("chat")
  const history = useAgentHistory(open && activePanel === "history", forgetSession)
  const [workflowTicker, setWorkflowTicker] = useState("")
  const [showCompactWorkflows, setShowCompactWorkflows] = useState(false)
  const [cachedPreferences] = useState<AgentResponsePreferences>(loadResponsePreferences)
  const [draftPreferences, setDraftPreferences] = useState<AgentResponsePreferences>(cachedPreferences)
  const [preferenceSaveError, setPreferenceSaveError] = useState<string | null>(null)
  const [includeScreenContext, setIncludeScreenContext] = useState(true)
  const [thinkingOverride, setThinkingOverride] = useState<boolean | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesScrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const composerRef = useRef<AgentChatComposerHandle>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const draftRef = useRef<AgentChatDraft>({ value: "", selection: null })
  const followingLatestRef = useRef(true)
  const lastScrollTopRef = useRef(0)
  const scrollViewRef = useRef<{ container: HTMLDivElement | null; firstMessageId?: string }>({ container: null })
  const [showJumpToLatest, setShowJumpToLatest] = useState(false)
  const wasStreamingRef = useRef(isStreaming)
  const pendingWorkflowInvalidationRef = useRef<WorkflowInvalidationTarget | null>(null)
  const lastConsumedCommandRef = useRef<string | null>(null)

  const loadComposerDraft = useCallback(() => draftRef.current, [])
  const saveComposerDraft = useCallback((draft: AgentChatDraft) => {
    draftRef.current = draft
  }, [])

  const workflowsQuery = useQuery({
    queryKey: ["agent-workflows"],
    queryFn: fetchAgentWorkflows,
    enabled: open,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const preferencesQuery = useQuery({
    queryKey: RESPONSE_PREFERENCES_QUERY_KEY,
    queryFn: fetchAgentResponsePreferences,
    enabled: open,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const preferencesMutation = useMutation({
    mutationFn: updateAgentResponsePreferences,
    onSuccess: savedPreferences => {
      const next = normalizePreferences(savedPreferences)
      queryClient.setQueryData(RESPONSE_PREFERENCES_QUERY_KEY, next)
      setDraftPreferences(next)
      localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(next))
      setPreferenceSaveError(null)
      setActivePanel("chat")
    },
    onError: err => {
      setPreferenceSaveError(err instanceof Error ? err.message : "Failed to save preferences")
    },
  })

  const workflows = workflowsQuery.data ?? []
  const activePreferences = useMemo(() => preferencesQuery.data
    ? normalizePreferences(preferencesQuery.data)
    : cachedPreferences, [preferencesQuery.data, cachedPreferences])

  const sendTurn = useCallback((content: string, options?: Parameters<typeof sendMessage>[3]) => {
    void sendMessage(content, includeScreenContext ? screenContext : null, {
      ...activePreferences,
      thinking_enabled: thinkingOverride ?? activePreferences.thinking_enabled,
    }, options)
    setIncludeScreenContext(true)
    setThinkingOverride(null)
  }, [sendMessage, includeScreenContext, screenContext, activePreferences, thinkingOverride])

  const handleOpenTrace = useCallback((message: AgentMessage) => {
    openDecisionTrace({ kind: "agent_message", record: {}, sessionId, message })
  }, [openDecisionTrace, sessionId])

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior) => {
    const container = messagesScrollRef.current
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior })
      lastScrollTopRef.current = container.scrollTop
      return
    }
    messagesEndRef.current?.scrollIntoView({ behavior, block: "end" })
  }, [])

  const handleMessagesScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const container = event.currentTarget
    // A delayed scroll event can arrive after new text changes the height.
    // Only a changed reading position should change whether we follow.
    if (container.scrollTop === lastScrollTopRef.current) return
    lastScrollTopRef.current = container.scrollTop
    const nearBottom = container.scrollHeight - container.clientHeight - container.scrollTop <= 80
    followingLatestRef.current = nearBottom
    setShowJumpToLatest(!nearBottom)
  }, [])

  const handleJumpToLatest = useCallback(() => {
    followingLatestRef.current = true
    setShowJumpToLatest(false)
    scrollMessagesToBottom("auto")
  }, [scrollMessagesToBottom])

  const focusComposerTextarea = useCallback(() => {
    const textarea = textareaRef.current
    if (!textarea) return

    const inputValue = draftRef.current.value
    const selection = draftRef.current.selection ?? { start: inputValue.length, end: inputValue.length }
    textarea.focus()
    const start = Math.min(selection.start, inputValue.length)
    const end = Math.min(selection.end, inputValue.length)
    textarea.setSelectionRange(start, end)
  }, [])

  useEffect(() => {
    if (!open || activePanel !== "chat") {
      scrollViewRef.current = { container: null }
      return
    }

    const container = messagesScrollRef.current
    const firstMessageId = messages[0]?.id
    // A newly opened view or a different conversation starts at the latest turn.
    if (scrollViewRef.current.container !== container || scrollViewRef.current.firstMessageId !== firstMessageId) {
      followingLatestRef.current = true
    }
    scrollViewRef.current = { container, firstMessageId }
    // Coalesce token commits into one layout read and scroll per frame.
    const animationFrame = window.requestAnimationFrame(() => {
      // Check again here: the user may scroll after this frame was scheduled.
      if (!followingLatestRef.current) return
      setShowJumpToLatest(false)
      scrollMessagesToBottom("auto")
    })
    return () => window.cancelAnimationFrame(animationFrame)
  }, [messages, isStreaming, activePanel, open, scrollMessagesToBottom])

  useEffect(() => {
    if (wasStreamingRef.current && !isStreaming && pendingWorkflowInvalidationRef.current) {
      invalidateWorkflowRunQueries(queryClient, pendingWorkflowInvalidationRef.current)
      pendingWorkflowInvalidationRef.current = null
    }
    wasStreamingRef.current = isStreaming
  }, [isStreaming, queryClient])

  useEffect(() => {
    if (open && activePanel === "chat") {
      const focused = document.activeElement
      if (!focused || focused === document.body || panelRef.current?.contains(focused)) focusComposerTextarea()
    }
  }, [open, activePanel, focusComposerTextarea])

  useEffect(() => {
    if (textareaRef.current) resizeChatTextarea(textareaRef.current)
  }, [open, viewMode])

  useEffect(() => {
    if (preferencesQuery.data) {
      localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(normalizePreferences(preferencesQuery.data)))
    }
  }, [preferencesQuery.data])

  useEffect(() => {
    if (!pendingCommand) {
      lastConsumedCommandRef.current = null
    }
  }, [pendingCommand])

  useEffect(() => {
    if (!open || !pendingCommand?.command?.trim()) return
    const command = pendingCommand.command.trim()
    if (lastConsumedCommandRef.current === command) return
    lastConsumedCommandRef.current = command
    pendingWorkflowInvalidationRef.current = workflowTargetFromCommand(command)
    window.setTimeout(() => {
      setActivePanel("chat")
      sendTurn(command, {
        durable: pendingCommand.durable ?? true,
        mode: isStreaming ? "enqueue" : undefined,
      })
    }, 0)
    onPendingCommandConsumed?.()
  }, [
    open,
    pendingCommand,
    isStreaming,
    sendTurn,
    onPendingCommandConsumed,
  ])

  function updateDraftPreferences(updater: (prev: AgentResponsePreferences) => AgentResponsePreferences) {
    setDraftPreferences(updater)
    setPreferenceSaveError(null)
  }

  const handleSend = useCallback((content: string) => {
    followingLatestRef.current = true
    setShowJumpToLatest(false)
    const workflow = workflowTargetFromCommand(content)
    pendingWorkflowInvalidationRef.current = workflow
    setActivePanel("chat")
    sendTurn(content, { durable: Boolean(workflow), mode: isComposerBusy ? "enqueue" : undefined })
  }, [isComposerBusy, sendTurn])

  const handleRegenerate = useCallback((messageId: string) => {
    pendingWorkflowInvalidationRef.current = null
    void regenerate(messageId, screenContext, activePreferences)
  }, [screenContext, activePreferences, regenerate])

  const handleEditMessage = useCallback((messageId: string, content: string) => {
    pendingWorkflowInvalidationRef.current = workflowTargetFromCommand(content)
    void editAndResend(messageId, content, screenContext, activePreferences)
  }, [screenContext, activePreferences, editAndResend])

  const handleQuickPrompt = useCallback((prompt: string) => {
    followingLatestRef.current = true
    setShowJumpToLatest(false)
    pendingWorkflowInvalidationRef.current = null
    setActivePanel("chat")
    sendTurn(prompt, isStreaming ? { mode: "enqueue" } : undefined)
  }, [isStreaming, sendTurn])

  function handleWorkflow(workflow: AgentWorkflow) {
    const ticker = workflowTicker.trim().toUpperCase()
    if (workflow.requiresTicker && !ticker) return
    followingLatestRef.current = true
    setShowJumpToLatest(false)
    const command = workflow.requiresTicker
      ? `/workflow:${workflow.name}:${ticker}`
      : `/workflow:${workflow.name}`
    pendingWorkflowInvalidationRef.current = { workflowName: workflow.name, ticker: ticker || null }
    setActivePanel("chat")
    sendTurn(command, {
      durable: true,
      mode: isStreaming ? "enqueue" : undefined,
    })
    setWorkflowTicker("")
    setShowCompactWorkflows(false)
  }

  function handleShowHistory() {
    setActivePanel("history")
  }

  function handleShowPreferences() {
    setDraftPreferences(activePreferences)
    setPreferenceSaveError(null)
    setActivePanel("preferences")
  }

  function handleSavePreferences() {
    if (preferencesMutation.isPending) return
    preferencesMutation.mutate(normalizePreferences(draftPreferences))
  }

  async function handleLoadSession(sessionId: string) {
    await loadSession(sessionId)
    setActivePanel("chat")
  }

  async function handleRenameSession(targetSessionId: string, title: string) {
    const previous = history.history.find(session => session.session_id === targetSessionId)
    const previousActiveTitle = sessionId === targetSessionId ? sessionTitle : null
    if (sessionId === targetSessionId) {
      applySessionTitle(targetSessionId, title, "manual")
    }

    try {
      const updated = await renameSessionTitle(targetSessionId, title)
      void queryClient.invalidateQueries({ queryKey: AGENT_HISTORY_QUERY_KEY })
      if (sessionId === targetSessionId) {
        applySessionTitle(targetSessionId, updated.title ?? title, updated.title_source ?? "manual")
      }
    } catch (err) {
      if (sessionId === targetSessionId) {
        applySessionTitle(targetSessionId, previousActiveTitle, previous?.title_source ?? null)
      }
      throw err
    }
  }

  function handleClearChat() {
    clearChat()
    setActivePanel("chat")
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) onClose()
  }

  const compactWorkflowSlot = viewMode === "compact" ? (
    <AgentWorkflowLauncher
      workflows={workflows}
      isLoading={workflowsQuery.isLoading}
      isError={workflowsQuery.isError}
      isStreaming={isStreaming}
      workflowTicker={workflowTicker}
      onTickerChange={setWorkflowTicker}
      onWorkflow={handleWorkflow}
      variant="compact"
    />
  ) : null

  const historyNotices = (
    <>
      {history.pendingDeletions.map(session => (
        <div key={session.session_id} role="status" className="flex items-center justify-between gap-3 border-b border-app bg-card px-4 py-3 text-xs text-app">
          <span className="min-w-0">Deleting <span className="font-semibold">{session.title || "conversation"}</span> in 10 seconds.</span>
          <button type="button" onClick={() => history.undoDelete(session.session_id)} className="shrink-0 font-semibold text-link" aria-label={`Undo delete ${session.title || "conversation"}`}>Undo</button>
        </div>
      ))}
      {history.deleteError && (
        <div role="alert" className="flex items-center justify-between gap-3 border-b border-app bg-card px-4 py-3 text-xs text-negative">
          <span>{history.deleteError}</span>
          <button type="button" onClick={history.dismissDeleteError} className="text-link">Dismiss</button>
        </div>
      )}
    </>
  )

  return (
    <RadixDialog.Root open={open} onOpenChange={handleOpenChange} modal={!docked}>
      <AgentCompletionToast completions={completions} onDismiss={dismissCompletion} />
      <RadixDialog.Portal>
        {!docked && <RadixDialog.Overlay className="fixed inset-0 z-40 bg-[hsl(var(--background-overlay))]/45 backdrop-blur-[2px]" />}
        <RadixDialog.Content
          ref={panelRef}
          aria-modal={!docked}
          onInteractOutside={event => { if (docked) event.preventDefault() }}
          onEscapeKeyDown={event => {
            if (docked && event.target instanceof Node && !panelRef.current?.contains(event.target)) {
              event.preventDefault()
              return
            }
            if (isComposerBusy) {
              event.preventDefault()
              stopStreaming()
            } else if (composerRef.current?.dismissSuggestions()) {
              event.preventDefault()
            }
          }}
          className={cn(
            "fixed z-50 flex flex-col overflow-hidden bg-app focus:outline-none",
            viewMode === "console"
              ? "bottom-[max(1rem,var(--safe-bottom))] left-[max(1rem,var(--safe-left))] right-[max(1rem,var(--safe-right))] top-[max(1rem,var(--safe-top))] rounded-[1.25rem] border border-app shadow-[var(--shadow-floating)]"
              : "right-0 top-0 h-[100dvh] w-full border-l border-app shadow-[var(--shadow-floating)] sm:w-[32rem] lg:w-[28rem] xl:w-[32rem]",
          )}
          onOpenAutoFocus={event => {
            event.preventDefault()
            if (activePanel === "chat") {
              focusComposerTextarea()
            }
          }}
        >
          <RadixDialog.Title className="sr-only">Stan assistant</RadixDialog.Title>
          <RadixDialog.Description className="sr-only">
            Market intelligence assistant with chat, workflow controls, history, and preferences.
          </RadixDialog.Description>

          <AgentChatHeader
            activePanel={activePanel}
            viewMode={viewMode}
            isDesktop={isDesktop}
            canClear={messages.length > 0}
            sessionId={sessionId}
            sessionTitle={sessionTitle}
            onRenameTitle={title => {
              if (!sessionId) return Promise.resolve()
              return handleRenameSession(sessionId, title)
            }}
            onBack={() => setActivePanel("chat")}
            onShowHistory={handleShowHistory}
            onShowPreferences={handleShowPreferences}
            onToggleViewMode={() => onViewModeChange?.(viewMode === "console" ? "compact" : "console")}
            onClearChat={handleClearChat}
            onClose={onClose}
          />
          {historyNotices}

          <div className="flex min-h-0 flex-1">
            <section className="flex min-w-0 flex-1 flex-col">
              {activePanel === "history" ? (
                <AgentHistoryPanel
                  history={history.history}
                  loading={history.loading}
                  search={history.search}
                  onSearch={history.setSearch}
                  loadingMore={history.loadingMore}
                  hasMore={history.hasMore}
                  onLoadMore={history.loadMore}
                  error={history.error}
                  onRetry={history.retry}
                  onLoadSession={handleLoadSession}
                  onDeleteSession={history.scheduleDelete}
                  onPinSession={history.togglePin}
                  onExportSession={exportHistorySession}
                  onRenameSession={handleRenameSession}
                />
              ) : activePanel === "preferences" ? (
                <AgentPreferencesPanel
                  draftPreferences={draftPreferences}
                  onChange={updateDraftPreferences}
                  onSave={handleSavePreferences}
                  isSaving={preferencesMutation.isPending}
                  saveError={preferenceSaveError}
                  preferencesUnavailable={preferencesQuery.isError && !preferenceSaveError}
                />
              ) : (
                <>
                  <AgentMessageStream
                    messages={messages}
                    sessionId={sessionId}
                    isStreaming={isStreaming}
                    error={error}
                    onPrompt={handleQuickPrompt}
                    onRetry={handleSend}
                    retryDisabled={isComposerBusy}
                    onOpenTrace={handleOpenTrace}
                    onScroll={handleMessagesScroll}
                    showJumpToLatest={showJumpToLatest}
                    onJumpToLatest={handleJumpToLatest}
                    messageVersions={messageVersions}
                    actionsDisabled={isComposerBusy}
                    onRegenerate={handleRegenerate}
                    onEdit={handleEditMessage}
                    onSwitchBranch={switchBranch}
                    scrollContainerRef={messagesScrollRef}
                    messagesEndRef={messagesEndRef}
                  />
                  <AgentChatQueuePanel
                    queuedMessages={queuedMessages}
                    onSendNow={id => { void sendQueuedMessageNow(id) }}
                    onEdit={id => {
                      const text = editQueuedMessage(id)
                      if (text != null) composerRef.current?.setInput(text)
                    }}
                    onRemove={removeQueuedMessage}
                    onClear={clearQueuedMessages}
                  />
                  <AgentChatComposer
                    ref={composerRef}
                    loadDraft={loadComposerDraft}
                    onDraftChange={saveComposerDraft}
                    onSend={handleSend}
                    onStop={stopStreaming}
                    isBusy={isComposerBusy}
                    queuedCount={queuedMessages.length}
                    textareaRef={textareaRef}
                    compactWorkflowSlot={compactWorkflowSlot}
                    workflowsOpen={showCompactWorkflows}
                    onToggleWorkflows={() => setShowCompactWorkflows(value => !value)}
                    workflows={workflows}
                    workflowsLoading={workflowsQuery.isLoading}
                    workflowsError={workflowsQuery.isError}
                    screenContext={screenContext}
                    includeScreenContext={includeScreenContext}
                    onToggleScreenContext={() => setIncludeScreenContext(value => !value)}
                    thinkingEnabled={thinkingOverride ?? activePreferences.thinking_enabled}
                    onToggleThinking={() => setThinkingOverride(value => !(value ?? activePreferences.thinking_enabled))}
                  />
                </>
              )}
            </section>

            {activePanel === "chat" && viewMode === "console" && (
              <AgentContextPane
                screenContext={screenContext}
                contextIncluded={includeScreenContext}
                workflows={workflows}
                workflowsLoading={workflowsQuery.isLoading}
                workflowsError={workflowsQuery.isError}
                isStreaming={isStreaming}
                workflowTicker={workflowTicker}
                onTickerChange={setWorkflowTicker}
                onWorkflow={handleWorkflow}
                promptGroups={QUICK_PROMPT_GROUPS}
                onPrompt={handleQuickPrompt}
              />
            )}
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
      {!open && (history.pendingDeletions.length > 0 || history.deleteError) && (
        <div className="fixed bottom-4 right-4 z-[60] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-app shadow-[var(--shadow-floating)]">
          {historyNotices}
        </div>
      )}
    </RadixDialog.Root>
  )
}
