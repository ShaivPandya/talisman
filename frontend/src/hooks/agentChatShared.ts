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
  toolCalls?: ToolCall[]
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
