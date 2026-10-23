import {
  AlertCircle,
  Ban,
  Brain,
  CheckCircle2,
  ChevronRight,
  Clock,
  GitPullRequest,
  Loader2,
  MessageSquareText,
  RotateCw,
} from "lucide-react"
import type { AgentMessage, AgentNote, ToolCall } from "@/hooks/agentChatShared"
import { TOOL_LABELS, formatAsOf, formatDuration, humanizeToolName, toolEffectScope, toolStateLabel } from "./agentToolDisplay"

const CACHE_HITS = new Set(["hit", "turn_hit"])
const BUSY_STATUSES: ReadonlySet<ToolCall["status"]> = new Set(["pending", "running", "retrying"])
const FAILED_STATUSES: ReadonlySet<ToolCall["status"]> = new Set(["error", "blocked", "timeout", "cancelled"])

function isBusy(tool: ToolCall): boolean {
  return BUSY_STATUSES.has(tool.status)
}

function isFailed(tool: ToolCall): boolean {
  return FAILED_STATUSES.has(tool.status)
}

function clip(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`
}

function argumentEntries(tool: ToolCall): [string, string][] {
  const args = tool.arguments
  if (args == null) return []
  if (typeof args !== "object" || Array.isArray(args)) {
    return [["arguments", typeof args === "string" ? args : JSON.stringify(args)]]
  }
  return Object.entries(args as Record<string, unknown>).map(([key, value]) => [
    key,
    typeof value === "string" ? value : JSON.stringify(value),
  ])
}

/** The arguments in one line, for the row: what was searched, which ticker. */
function argumentSummary(tool: ToolCall): string {
  return argumentEntries(tool)
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${clip(value, 48)}`)
    .join(", ")
}

/** The result as text to show. Messages saved before previews hold the whole result in `result`. */
function resultText(tool: ToolCall): string | null {
  const raw = tool.resultPreview ?? (tool.result == null ? null : typeof tool.result === "string" ? tool.result : JSON.stringify(tool.result))
  if (raw == null) return null
  if (tool.resultTruncated) return raw
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function formatBytes(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
}

function ToolStatusIcon({ tool }: { tool: ToolCall }) {
  if (isBusy(tool) && tool.status !== "retrying") {
    return <Loader2 size={12} className="animate-spin text-blue-500" aria-hidden="true" />
  }
  if (tool.status === "retrying") return <RotateCw size={12} className="animate-spin text-blue-500" aria-hidden="true" />
  if (tool.status === "ok") return <CheckCircle2 size={12} className="text-emerald-600" aria-hidden="true" />
  if (tool.status === "blocked") return <Ban size={12} className="text-red-600" aria-hidden="true" />
  if (tool.status === "timeout") return <Clock size={12} className="text-red-600" aria-hidden="true" />
  return <AlertCircle size={12} className={isFailed(tool) ? "text-red-600" : "text-amber-600"} aria-hidden="true" />
}

function ToolRow({ tool }: { tool: ToolCall }) {
  const label = TOOL_LABELS[tool.name] ?? humanizeToolName(tool.name)
  const scope = toolEffectScope(tool.name)
  const args = argumentEntries(tool)
  const result = resultText(tool)
  const summary = argumentSummary(tool)
  const facts = [
    tool.elapsedMs != null && !isBusy(tool) ? formatDuration(tool.elapsedMs) : null,
    tool.cache && CACHE_HITS.has(tool.cache) ? "cached" : null,
    tool.asOf ? `as of ${formatAsOf(tool.asOf)}` : null,
  ].filter(Boolean)
  const hasDetail = args.length > 0 || result != null || Boolean(tool.message) || Boolean(tool.policyDecisionId)

  const header = (
    <>
      <ToolStatusIcon tool={tool} />
      {scope === "internal_state" && <GitPullRequest size={10} aria-hidden="true" />}
      <span className="font-medium text-app">{label}</span>
      {summary && <span className="min-w-0 truncate text-muted">{summary}</span>}
      <span className={`ml-auto shrink-0 ${isFailed(tool) ? "text-red-700 dark:text-red-300" : "text-subtle"}`}>
        {[toolStateLabel(tool.status), ...facts].join(" · ")}
      </span>
    </>
  )

  if (!hasDetail) {
    return <div className="flex items-center gap-1.5 px-2 py-1 text-xs">{header}</div>
  }
  return (
    <details className="group rounded-md">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-muted-surface [&::-webkit-details-marker]:hidden">
        <ChevronRight size={10} className="shrink-0 transition-transform group-open:rotate-90" aria-hidden="true" />
        {header}
      </summary>
      <div className="mb-1 ml-6 space-y-1.5 border-l border-app pl-3 text-xs">
        {tool.message && <p className="text-red-700 dark:text-red-300">{tool.message}</p>}
        {args.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {args.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-subtle">{key}</dt>
                <dd className="min-w-0 break-words font-mono text-app">
                  {clip(value, 400)}
                  {tool.argumentsTruncated && key === "arguments" ? " …" : ""}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {result != null && (
          <details>
            <summary className="cursor-pointer text-subtle hover:text-app">
              Result{tool.resultBytes != null ? ` · ${formatBytes(tool.resultBytes)}` : ""}
            </summary>
            <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md border border-app bg-card-muted p-2 font-mono text-[11px] leading-4">
              {result}
            </pre>
            {tool.resultTruncated && <p className="mt-0.5 text-subtle">Showing the start of the result.</p>}
          </details>
        )}
        {tool.policyDecisionId && <p className="text-subtle">Policy decision: {tool.policyDecisionId}</p>}
      </div>
    </details>
  )
}

function NoteRow({ note, kind }: { note: AgentNote; kind: "thinking" | "narration" }) {
  const Icon = kind === "thinking" ? Brain : MessageSquareText
  return (
    <div className="flex items-start gap-1.5 px-2 py-1 text-xs">
      <Icon size={12} className="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
      <div className="min-w-0">
        <span className="font-medium text-app">{kind === "thinking" ? "Thinking" : "Note"}</span>
        <p className="whitespace-pre-wrap break-words text-muted">{note.text}</p>
      </div>
    </div>
  )
}

/** What the model did for an answer: its thinking summary, what it said ahead of its tools, and each tool call. */
export function AgentActivity({ message }: { message: AgentMessage }) {
  const tools = message.toolCalls ?? []
  const thinking = message.thinking ?? []
  const narration = message.narration ?? []
  if (!tools.length && !thinking.length && !narration.length) return null

  const busyTool = tools.find(isBusy)
  const failures = tools.filter(isFailed).length
  const counts = [
    tools.length ? `${tools.length} ${tools.length === 1 ? "tool" : "tools"}` : null,
    thinking.length ? "thinking" : null,
  ].filter(Boolean)

  return (
    <details className="group mb-2 rounded-lg border border-app bg-card-muted">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted hover:text-app [&::-webkit-details-marker]:hidden">
        <ChevronRight size={12} className="shrink-0 transition-transform group-open:rotate-90" aria-hidden="true" />
        <span className="font-medium">Activity</span>
        {counts.length > 0 && <span>· {counts.join(" · ")}</span>}
        {failures > 0 && (
          <span className="text-red-700 dark:text-red-300">
            · {failures} failed
          </span>
        )}
        {busyTool && (
          <span className="ml-auto flex items-center gap-1 text-blue-600 dark:text-blue-400">
            <Loader2 size={11} className="animate-spin" aria-hidden="true" />
            {TOOL_LABELS[busyTool.name] ?? humanizeToolName(busyTool.name)}
          </span>
        )}
      </summary>
      <div className="space-y-0.5 border-t border-app px-1 py-1.5">
        {thinking.map(note => (
          <NoteRow key={note.id} note={note} kind="thinking" />
        ))}
        {narration.map(note => (
          <NoteRow key={note.id} note={note} kind="narration" />
        ))}
        {tools.map(tool => (
          <ToolRow key={tool.id} tool={tool} />
        ))}
      </div>
    </details>
  )
}
