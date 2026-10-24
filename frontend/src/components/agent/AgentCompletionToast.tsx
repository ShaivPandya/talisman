import * as Toast from "@radix-ui/react-toast"
import { createPortal } from "react-dom"
import { CheckCircle2, X } from "lucide-react"
import type { AgentJobCompletion } from "@/hooks/useAgentChat"

export function AgentCompletionToast({
  completions,
  onDismiss,
}: {
  completions: AgentJobCompletion[]
  onDismiss: (jobId: string) => void
}) {
  // Outside the dialog portal so closing chat does not hide the notification.
  return createPortal(
    <Toast.Provider duration={6000}>
      {completions.map(completion => (
        <Toast.Root
          key={completion.jobId}
          open
          onOpenChange={open => { if (!open) onDismiss(completion.jobId) }}
          type="background"
          className="theme-floating flex items-start gap-3 rounded-xl border border-app bg-card p-4 text-app shadow-lg"
        >
          <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-positive" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <Toast.Title className="text-sm font-medium">Stan finished responding</Toast.Title>
            <Toast.Description className="mt-1 truncate text-xs text-muted">
              {completion.title ?? "Your background response is ready."}
            </Toast.Description>
          </div>
          <Toast.Close aria-label="Dismiss completion notification" className="theme-icon-button h-6 w-6 shrink-0">
            <X size={14} aria-hidden="true" />
          </Toast.Close>
        </Toast.Root>
      ))}
      <Toast.Viewport className="fixed bottom-[max(5.5rem,var(--safe-bottom))] right-[max(1rem,var(--safe-right))] z-[70] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 outline-none" />
    </Toast.Provider>,
    document.body,
  )
}
