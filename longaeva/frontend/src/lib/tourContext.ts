import { createContext, useContext, useEffect, useId } from "react"
import type { TourState } from "./tour"

export interface TourContextValue {
  state: TourState
  launch: () => void
  go: (index: number) => void
  exit: () => void
  finish: () => void
  registerDraft: (id: string, label: string | null) => void
  registerRetry: (id: string, retry: (() => void) | null) => void
  retry: (id: string) => void
}
export const TourContext = createContext<TourContextValue | null>(null)
export function useTour() {
  const context = useContext(TourContext)
  if (!context) throw new Error("Tour controls require the application shell")
  return context
}

export function useTourDraftGuard(dirty: boolean, label: string) {
  const { registerDraft } = useTour()
  const id = useId()
  useEffect(() => {
    registerDraft(id, dirty ? label : null)
    return () => registerDraft(id, null)
  }, [id, dirty, label, registerDraft])
}
