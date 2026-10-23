import type { ScreenContext } from "@/contexts/ScreenContext"
import type { AgentResponseFeedbackRecord, AgentResponsePreferences } from "@/lib/api"

import type { AgentTraceSnapshot } from "@/lib/decisionTrace"

export interface ToolCall {
  name: string
  id: string
  status: "pending" | "running" | "ok" | "error" | "blocked" | "timeout" | "retrying" | "partial" | "cancelled"
  message?: string
  policyDecisionId?: string
  elapsedMs?: number
  arguments?: unknown
  /** Set when `arguments` was cut to a preview of its JSON text. */
  argumentsTruncated?: boolean
  /** Messages saved before result previews hold the whole result here instead. */
  result?: unknown
  resultPreview?: string
  resultBytes?: number
  resultTruncated?: boolean
  /** A date (YYYY-MM-DD) or an ISO timestamp: when the data the tool returned is from. */
  asOf?: string
  cache?: string
}

/** One narration or thinking-summary entry in a message's activity list. */
export interface AgentNote {
  id: string
  text: string
}

export interface EgressRecord {
  id: string
  decision: "allowed" | "allowed_with_warning" | "blocked" | string
  decisionReason?: string
  dataSensitivity?: string
  provider?: string
  model?: string
  policyDecisionId?: string
}

export interface AgentMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: number
  clientTurnId?: string
  parentId?: string | null
  messageStatus?: "streaming" | "complete" | "stopped" | "failed"
  contentParts?: Record<string, unknown>[]
  sources?: Record<string, unknown>[]
  attachments?: Record<string, unknown>[]
  toolCalls?: ToolCall[]
  /** Text the model wrote ahead of its tool calls. It is not part of the answer. */
  narration?: AgentNote[]
  /** Thinking summaries, one per thinking block, when Thinking is on. */
  thinking?: AgentNote[]
  isStreaming?: boolean
  statusText?: string
  egressRecords?: EgressRecord[]
  traceSnapshot?: AgentTraceSnapshot | null
  feedback?: AgentResponseFeedbackRecord | null
}

export interface ActiveAgentJob {
  jobId: string
  assistantId: string
  afterSeq: number
  clientTurnId: string
  sessionId: string
}

export type AgentMessageDelivery = "enqueue" | "immediate"

export interface AgentSendOptions {
  durable?: boolean
  mode?: AgentMessageDelivery
}

export interface QueuedAgentMessage {
  id: string
  content: string
  createdAt: number
  screenContext?: ScreenContext | null
  responsePreferences?: AgentResponsePreferences | null
  options?: AgentSendOptions
}

const ACTIVE_TOOL_STATUSES: ReadonlySet<ToolCall["status"]> = new Set([
  "pending",
  "running",
  "retrying",
])

/**
 * True when an assistant turn is still in flight. Only a streaming message counts: status text or
 * running tool chips left on a settled message (saved mid tool-run, then restored) do not.
 */
export function assistantTurnInProgress(messages: AgentMessage[]): boolean {
  return messages.some(message => message.role === "assistant" && message.isStreaming)
}

/**
 * Settle assistant messages restored without a live turn behind them: clear streaming state and
 * status text, and mark tool chips that were still running as cancelled. `liveAssistantId` (the
 * message an active job is still writing) is left as it is.
 */
export function settleInterruptedMessages(
  messages: AgentMessage[],
  liveAssistantId?: string | null,
): AgentMessage[] {
  return messages.map(message => {
    if (message.role !== "assistant" || message.id === liveAssistantId) return message
    const hasActiveTool = message.toolCalls?.some(tool => ACTIVE_TOOL_STATUSES.has(tool.status))
    if (!message.isStreaming && !message.statusText && !hasActiveTool) return message
    return {
      ...message,
      isStreaming: false,
      statusText: undefined,
      toolCalls: message.toolCalls?.map(tool =>
        ACTIVE_TOOL_STATUSES.has(tool.status) ? { ...tool, status: "cancelled" as const } : tool,
      ),
    }
  })
}

/** Position of a message among its alternatives: regenerated answers, or edited versions of a question. */
export interface BranchVersion {
  index: number
  count: number
  previousId: string | null
  nextId: string | null
}

export interface BranchView {
  /** The branch being shown, root first. */
  messages: AgentMessage[]
  /** Alternatives for each shown message that has any. */
  versions: ReadonlyMap<string, BranchVersion>
}

const NO_VERSIONS: ReadonlyMap<string, BranchVersion> = new Map()

// Messages saved before parent ids existed continue the message before them.
function parentOf(messages: AgentMessage[], index: number): string | null {
  const parentId = messages[index].parentId
  return parentId === undefined ? (messages[index - 1]?.id ?? null) : parentId
}

function isChain(messages: AgentMessage[]): boolean {
  return messages.every((_, index) => parentOf(messages, index) === (messages[index - 1]?.id ?? null))
}

function indexTree(messages: AgentMessage[]) {
  const byId = new Map(messages.map(message => [message.id, message]))
  const children = new Map<string | null, AgentMessage[]>()
  const parents = new Map<string, string | null>()
  messages.forEach((message, index) => {
    const parentId = parentOf(messages, index)
    const key = parentId !== null && byId.has(parentId) ? parentId : null
    parents.set(message.id, key)
    const siblings = children.get(key)
    if (siblings) siblings.push(message)
    else children.set(key, [message])
  })
  return { byId, children, parents }
}

/**
 * The branch of a conversation to show. A conversation without alternatives is returned as it is,
 * so the usual chat costs one pass over its messages. `leafId` picks the branch; without it, or
 * when it names no message, the newest one is shown.
 */
export function resolveBranch(messages: AgentMessage[], leafId?: string | null): BranchView {
  if (isChain(messages)) return { messages, versions: NO_VERSIONS }
  const { byId, children, parents } = indexTree(messages)
  let leaf = leafId && byId.has(leafId) ? leafId : null
  for (let index = messages.length - 1; leaf === null && index >= 0; index--) {
    if (!children.has(messages[index].id)) leaf = messages[index].id
  }
  const path: AgentMessage[] = []
  const seen = new Set<string>()
  for (let id = leaf; id !== null && byId.has(id) && !seen.has(id); id = parents.get(id) ?? null) {
    seen.add(id)
    path.push(byId.get(id)!)
  }
  path.reverse()
  const versions = new Map<string, BranchVersion>()
  for (const message of path) {
    const siblings = (children.get(parents.get(message.id) ?? null) ?? []).filter(item => item.role === message.role)
    if (siblings.length < 2) continue
    const index = siblings.indexOf(message)
    versions.set(message.id, {
      index,
      count: siblings.length,
      previousId: siblings[index - 1]?.id ?? null,
      nextId: siblings[index + 1]?.id ?? null,
    })
  }
  return { messages: path, versions }
}

/** The newest leaf at or below a message: where the conversation resumes after switching to it. */
export function leafBelow(messages: AgentMessage[], id: string): string {
  const { children } = indexTree(messages)
  let leaf = id
  for (let next = children.get(leaf); next?.length; next = children.get(leaf)) leaf = next[next.length - 1].id
  return leaf
}

/** The id a message hangs from, or null at the top of the conversation. */
export function parentIdOf(messages: AgentMessage[], id: string): string | null {
  const index = messages.findIndex(message => message.id === id)
  return index < 0 ? null : parentOf(messages, index)
}
