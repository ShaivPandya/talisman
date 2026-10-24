import { AlertCircle, ArrowDown, MessageCircle, RotateCw } from "lucide-react"
import { AgentMessage } from "./AgentMessage"
import { EMPTY_STATE_PROMPTS } from "./agentChatPrompts"
import type { AgentMessage as AgentMessageType } from "@/hooks/useAgentChat"
import type { BranchVersion } from "@/hooks/agentChatShared"
import type { AgentAttachment } from "@/lib/chatAttachments"
import type { RefObject, UIEventHandler } from "react"

interface AgentMessageStreamProps {
  messages: AgentMessageType[]
  sessionId?: string | null
  isStreaming: boolean
  error: string | null
  onPrompt: (prompt: string) => void
  onRetry: (prompt: string, attachments: AgentAttachment[]) => void
  retryDisabled: boolean
  onOpenTrace?: (message: AgentMessageType) => void
  onScroll: UIEventHandler<HTMLDivElement>
  showJumpToLatest: boolean
  onJumpToLatest: () => void
  messageVersions?: ReadonlyMap<string, BranchVersion>
  actionsDisabled?: boolean
  onRegenerate?: (messageId: string) => void
  onEdit?: (messageId: string, content: string) => void
  onSwitchBranch?: (messageId: string, direction: -1 | 1) => void
  scrollContainerRef: RefObject<HTMLDivElement | null>
  messagesEndRef: RefObject<HTMLDivElement | null>
}

export function AgentMessageStream({
  messages,
  sessionId,
  isStreaming,
  error,
  onPrompt,
  onRetry,
  retryDisabled,
  onOpenTrace,
  onScroll,
  showJumpToLatest,
  onJumpToLatest,
  messageVersions,
  actionsDisabled,
  onRegenerate,
  onEdit,
  onSwitchBranch,
  scrollContainerRef,
  messagesEndRef,
}: AgentMessageStreamProps) {
  const isEmpty = messages.length === 0 && !isStreaming
  let retryPrompt: string | undefined
  let retryAttachments: AgentAttachment[] = []
  if (error) {
    for (let index = messages.length - 1; index >= 0; index--) {
      if (messages[index].role === "user") {
        retryPrompt = messages[index].content
        retryAttachments = messages[index].attachments ?? []
        break
      }
    }
  }

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scrollContainerRef} onScroll={onScroll} className="h-full overflow-y-auto bg-app px-4 py-4">
        {isEmpty ? (
          <div className="flex min-h-full flex-col items-center justify-center text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-app bg-card text-link shadow-sm">
              <MessageCircle size={22} aria-hidden="true" />
            </div>
            <p className="text-base font-semibold text-app">Stan is ready</p>
            <p className="mt-1 max-w-[28rem] text-sm leading-6 text-muted">
              Ask for a portfolio read, market regime check, or risk review.
            </p>
            <div className="mt-5 grid w-full max-w-[34rem] grid-cols-1 gap-2 sm:grid-cols-2">
              {EMPTY_STATE_PROMPTS.map(prompt => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => onPrompt(prompt)}
                  className="theme-button-secondary min-h-12 justify-start rounded-xl px-3 py-2 text-left text-xs font-medium leading-5 text-muted hover:text-app"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-[54rem] flex-col">
            {messages.map((message, index) => {
              const version = messageVersions?.get(message.id)
              return (
                <AgentMessage
                  key={message.id}
                  message={message}
                  sessionId={sessionId}
                  onOpenTrace={onOpenTrace}
                  versionIndex={version?.index}
                  versionCount={version?.count}
                  canRegenerate={index === messages.length - 1 && message.role === "assistant"}
                  actionsDisabled={actionsDisabled}
                  onRegenerate={onRegenerate}
                  onEdit={onEdit}
                  onSwitchBranch={onSwitchBranch}
                />
              )
            })}
            {error && (
              <div
                className="mb-3 flex items-start gap-2 rounded-xl border border-[hsl(var(--destructive)/0.22)] bg-[hsl(var(--destructive-muted))] px-3 py-2 text-sm text-negative"
                role="alert"
              >
                <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
                <div>
                  <p className="font-semibold">Request interrupted</p>
                  <p className="mt-0.5 text-xs leading-5">{error}</p>
                  {retryPrompt && (
                    <button
                      type="button"
                      onClick={() => onRetry(retryPrompt, retryAttachments)}
                      disabled={retryDisabled}
                      className="theme-button-secondary mt-2 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                    >
                      <RotateCw size={13} aria-hidden="true" />
                      Retry
                    </button>
                  )}
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>
      {showJumpToLatest && !isEmpty && (
        <button
          type="button"
          onClick={onJumpToLatest}
          className="theme-button-secondary absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-full border border-app px-3 py-2 text-xs font-semibold shadow-sm"
        >
          <ArrowDown size={14} aria-hidden="true" />
          Jump to latest
        </button>
      )}
    </div>
  )
}
