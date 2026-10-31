import Markdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { memo, useRef, useState, type ReactNode } from "react"
import type { EgressRecord, AgentMessage as AgentMessageType } from "@/hooks/useAgentChat"
import { Pencil, RefreshCw, ShieldAlert } from "lucide-react"
import { DecisionStateBadge, EffectScopeBadge } from "@/components/shared/DecisionStateBadge"
import { TraceTriggerButton } from "@/components/shared/TraceTriggerButton"
import { AgentActivity } from "./AgentActivity"
import { AttachmentChips } from "./AgentAttachmentChips"
import { AgentChart } from "./AgentChart"
import { AgentFeedbackControls } from "./AgentFeedbackControls"
import { ActionButton, CopyButton, EditMessageForm, MessageActionRow } from "./AgentMessageActions"
import { AgentProposalCard } from "./AgentProposalCard"
import { AgentSources } from "./AgentSources"
import { toolEffectScope } from "./agentToolDisplay"
import { messageCostDetail, messageCostLabel } from "@/hooks/agentMessageCost"

const MARKDOWN_COMPONENTS: Components = {
  table({ children, ...props }) {
    return (
      <div className="my-3 max-w-full overflow-x-auto rounded-lg border border-app bg-card-muted">
        <table {...props} className="min-w-full border-collapse text-sm">
          {children}
        </table>
      </div>
    )
  },
  th({ children, ...props }) {
    return (
      <th {...props} className="border-b border-app px-3 py-2 text-left text-xs font-semibold uppercase tracking-[0.12em] text-subtle">
        {children}
      </th>
    )
  },
  td({ children, ...props }) {
    return (
      <td {...props} className="border-t border-app px-3 py-2 align-top text-sm text-app">
        {children}
      </td>
    )
  },
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>
  },
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const block = useRef<HTMLPreElement>(null)
  return (
    <div className="group/code relative my-3 max-w-full">
      <CopyButton
        label="Copy code"
        getText={() => (block.current?.textContent ?? "").replace(/\n$/, "")}
        className="absolute right-1.5 top-1.5 bg-card opacity-0 focus-visible:opacity-100 group-hover/code:opacity-100 [@media(hover:none)]:opacity-100"
      />
      <pre ref={block} className="max-w-full overflow-x-auto rounded-lg border border-app bg-card-muted p-3 text-xs leading-5">
        {children}
      </pre>
    </div>
  )
}

const ARTIFACT_JSON_KEYS = [
  "evaluation_draft",
  "action_items",
  "watch_triggers",
]

function containsArtifactJsonKey(value: string): boolean {
  return ARTIFACT_JSON_KEYS.some(key => value.includes(`"${key}"`))
}

function stripTrailingArtifactJson(value: string): string {
  const trimmedStart = value.trimStart()
  if (trimmedStart.startsWith("{") && containsArtifactJsonKey(trimmedStart)) {
    return value.slice(0, value.length - trimmedStart.length).trimEnd()
  }

  const candidates = [...value.matchAll(/\n\s*\{/g)].reverse()
  for (const match of candidates) {
    const start = match.index ?? -1
    if (start < 0) continue
    const suffix = value.slice(start)
    if (!containsArtifactJsonKey(suffix)) continue
    return value.slice(0, start).trimEnd()
  }
  return value
}

function stripArtifactBlocks(value: string): string {
  const withoutClosedBlocks = value.replace(
    /(^|\n)```([^\n]*)\n([\s\S]*?)```[ \t]*(?=\n|$)/g,
    (match, prefix: string, info: string, body: string) => {
      const isArtifactBlock = info.trim().toLowerCase() === "artifacts" || containsArtifactJsonKey(body)
      return isArtifactBlock ? prefix : match
    },
  )

  const lastFence = withoutClosedBlocks.lastIndexOf("```")
  if (lastFence >= 0) {
    const trailingBlock = withoutClosedBlocks.slice(lastFence)
    const firstLine = trailingBlock.split("\n", 1)[0]?.replace(/^```/, "").trim().toLowerCase()
    if (firstLine === "artifacts" || containsArtifactJsonKey(trailingBlock)) {
      return withoutClosedBlocks.slice(0, lastFence).trimEnd()
    }
  }

  return stripTrailingArtifactJson(withoutClosedBlocks)
}

interface EgressRecordGroup {
  id: string
  decision: "allowed_with_warning" | "blocked"
  records: EgressRecord[]
}

function visibleEgressGroups(records: EgressRecord[] | undefined): EgressRecordGroup[] {
  const groups = new Map<EgressRecordGroup["decision"], EgressRecordGroup>()
  for (const record of records ?? []) {
    if (record.decision !== "allowed_with_warning" && record.decision !== "blocked") continue
    const decision = record.decision
    const group = groups.get(decision)
    if (group) {
      group.records.push(record)
    } else {
      groups.set(decision, { id: decision, decision, records: [record] })
    }
  }
  return [...groups.values()]
}

function egressRecordTitle(record: EgressRecord): string {
  return [
    record.decisionReason,
    record.dataSensitivity ? `Sensitivity: ${record.dataSensitivity}` : null,
    record.provider ? `Provider: ${record.provider}` : null,
    record.model ? `Model: ${record.model}` : null,
    record.policyDecisionId ? `Policy decision: ${record.policyDecisionId}` : null,
  ].filter(Boolean).join("\n")
}

function EgressChip({ group }: { group: EgressRecordGroup }) {
  const blocked = group.decision === "blocked"
  const label = blocked ? "Model egress blocked" : "Private context sent"
  const title = [
    group.records.length > 1 ? `${group.records.length} model calls recorded.` : null,
    ...group.records.map((record, index) => {
      const detail = egressRecordTitle(record)
      if (!detail) return null
      return group.records.length > 1 ? `Call ${index + 1}\n${detail}` : detail
    }),
  ].filter(Boolean).join("\n\n")
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs mr-1.5 mb-1.5 ${
        blocked
          ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
          : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
      }`}
      title={title}
    >
      <ShieldAlert size={10} aria-hidden="true" />
      {label}
      {group.records.length > 1 && <span className="opacity-75">· {group.records.length} calls</span>}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Message component
// ---------------------------------------------------------------------------

export const AgentMessage = memo(function AgentMessage({
  message,
  sessionId,
  onOpenTrace,
  versionIndex,
  versionCount,
  canRegenerate,
  actionsDisabled,
  onRegenerate,
  onEdit,
  onSwitchBranch,
}: {
  message: AgentMessageType
  sessionId?: string | null
  onOpenTrace?: (message: AgentMessageType) => void
  /** Which version of the message this is, when it has alternatives. */
  versionIndex?: number
  versionCount?: number
  /** True for the latest answer of the branch, the only one that can be regenerated. */
  canRegenerate?: boolean
  /** True while a turn is running: versions and edits wait for it. */
  actionsDisabled?: boolean
  onRegenerate?: (messageId: string) => void
  onEdit?: (messageId: string, content: string) => void
  onSwitchBranch?: (messageId: string, direction: -1 | 1) => void
}) {
  const [editing, setEditing] = useState(false)
  const version = versionIndex !== undefined && versionCount ? { index: versionIndex, count: versionCount } : undefined
  const switchVersion = onSwitchBranch ? (direction: -1 | 1) => onSwitchBranch(message.id, direction) : undefined

  if (message.role === "user") {
    return (
      <div className="group mb-4 flex flex-col items-end">
        {/* An edited message is sent with the same files, so they stay in view while editing. */}
        {message.attachments?.length ? (
          <AttachmentChips attachments={message.attachments} className="mb-1.5 max-w-[min(86%,42rem)] justify-end" />
        ) : null}
        {editing ? (
          <EditMessageForm
            initialValue={message.content}
            onCancel={() => setEditing(false)}
            onSubmit={content => {
              setEditing(false)
              onEdit?.(message.id, content)
            }}
          />
        ) : (
          <div className="max-w-[min(86%,42rem)] rounded-2xl rounded-br-md bg-[hsl(var(--accent))] px-4 py-2.5 text-sm leading-6 text-[hsl(var(--accent-foreground))] shadow-sm whitespace-pre-wrap">
            {message.content}
          </div>
        )}
        {!editing && (
          <MessageActionRow align="end" version={version} disabled={actionsDisabled} onSwitchVersion={switchVersion}>
            <CopyButton label="Copy message" getText={() => message.content} />
            {onEdit && (
              <ActionButton label="Edit message" onClick={() => setEditing(true)} disabled={actionsDisabled}>
                <Pencil size={13} aria-hidden="true" />
              </ActionButton>
            )}
          </MessageActionRow>
        )}
      </div>
    )
  }

  const displayContent = stripArtifactBlocks(message.content)
  const messageScope = message.toolCalls?.some(tc => toolEffectScope(tc.name) === "internal_state")
    ? "internal_state"
    : "read_only"
  const messageDecisionState = messageScope === "internal_state" ? "proposal" : "analysis"
  const egressGroups = visibleEgressGroups(message.egressRecords)

  // Assistant message
  return (
    <div className="group mb-4 flex flex-col items-start">
      <div className="max-w-[min(92%,48rem)] rounded-2xl rounded-bl-md border border-app bg-card px-4 py-3 text-sm leading-6 text-app shadow-sm">
        {messageDecisionState === "proposal" && (
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <DecisionStateBadge state={messageDecisionState} />
            <EffectScopeBadge scope={messageScope} />
          </div>
        )}
        <AgentActivity message={message} />
        {egressGroups.length > 0 && (
          <div className="flex flex-wrap mb-2">
            {egressGroups.map(group => (
              <EgressChip key={group.id} group={group} />
            ))}
          </div>
        )}

        {/* Markdown content */}
        {displayContent && (
          <div className="prose prose-sm max-w-none break-words dark:prose-invert prose-p:my-1.5 prose-p:leading-6 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-li:my-0.5 prose-code:break-words">
            <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>{displayContent}</Markdown>
          </div>
        )}

        {!displayContent && message.statusText && (
          <span className="text-xs text-muted">{message.statusText}</span>
        )}

        {message.charts?.map(chart => (
          <AgentChart key={chart.id} chart={chart} />
        ))}
        {message.proposals?.map(proposal => (
          <AgentProposalCard key={proposal.id} proposal={proposal} />
        ))}

        {/* Streaming cursor */}
        {message.isStreaming && (
          <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle rounded-sm" />
        )}

        <AgentSources sources={message.sources} />
        {!message.isStreaming && message.cost && (
          <div className="mt-2 flex justify-end">
            <span
              className="cursor-help rounded text-[10px] leading-4 tabular-nums text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              tabIndex={0}
              title={messageCostDetail(message.cost)}
              aria-label={`${messageCostLabel(message.cost)}. ${messageCostDetail(message.cost)}`}
              data-testid="agent-message-cost"
            >
              {messageCostLabel(message.cost)}
            </span>
          </div>
        )}
      </div>
      {!message.isStreaming && (
        <MessageActionRow align="start" version={version} disabled={actionsDisabled} onSwitchVersion={switchVersion}>
          {displayContent && <CopyButton label="Copy response" getText={() => displayContent} />}
          {onOpenTrace && (
            <TraceTriggerButton compact label="Trace Stan response" className="h-6 w-6" onClick={() => onOpenTrace(message)} />
          )}
          <AgentFeedbackControls message={message} sessionId={sessionId ?? null} />
          {canRegenerate && onRegenerate && (
            <ActionButton label="Regenerate response" onClick={() => onRegenerate(message.id)} disabled={actionsDisabled}>
              <RefreshCw size={13} aria-hidden="true" />
            </ActionButton>
          )}
        </MessageActionRow>
      )}
    </div>
  )
})
