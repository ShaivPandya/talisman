import { useEffect, useRef, type ReactNode } from "react"
import { useTour } from "@/lib/tourContext"

export type TourTargetStatus = "loading" | "ready" | "error" | "empty"

export function TourTarget({ id, status, message, onRetry, children, className }: {
  id?: string
  status: TourTargetStatus
  message?: string | null
  onRetry?: () => void
  children: ReactNode
  className?: string
}) {
  const { registerRetry } = useTour()
  const retry = useRef(onRetry)
  useEffect(() => { retry.current = onRetry }, [onRetry])
  const canRetry = !!onRetry
  useEffect(() => {
    if (!id || !canRetry) return
    registerRetry(id, () => retry.current?.())
    return () => registerRetry(id, null)
  }, [id, canRetry, registerRetry])
  return <div data-tour={id} data-tour-status={status} data-tour-message={message || undefined} className={className}>{children}</div>
}
