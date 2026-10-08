import { useCallback, useEffect, useMemo, useReducer, useRef, type ReactNode } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { readCheckpoint, saveCheckpoint, TOUR_STEPS, tourReducer, type TourState } from "@/lib/tour"
import { TourContext } from "@/lib/tourContext"

export function TourProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [state, dispatch] = useReducer(tourReducer, null, (): TourState => {
    let checkpoint = null
    try { checkpoint = readCheckpoint(window.localStorage) } catch { /* storage can be disabled */ }
    return { mode: "closed", index: 0, checkpoint }
  })
  const drafts = useRef(new Map<string, string>())
  const retries = useRef(new Map<string, () => void>())
  const registerDraft = useCallback((id: string, label: string | null) => {
    if (label) drafts.current.set(id, label)
    else drafts.current.delete(id)
  }, [])
  const registerRetry = useCallback((id: string, retry: (() => void) | null) => {
    if (retry) retries.current.set(id, retry)
    else retries.current.delete(id)
  }, [])
  const go = useCallback((index: number) => {
    const step = TOUR_STEPS[index]
    if (!step) return
    const changingPage = location.pathname + location.search !== step.to
    const labels = [...new Set(drafts.current.values())]
    if (changingPage && labels.length && !window.confirm(`You have unsaved ${labels.join(" and ")}. Leave this page and discard those edits? Choose Cancel to keep editing.`)) return
    dispatch({ type: "start", index })
    if (changingPage) navigate(step.to)
  }, [navigate, location.pathname, location.search])
  const launch = useCallback(() => dispatch({ type: "launch" }), [])
  const exit = useCallback(() => {
    dispatch({ type: "exit" })
    // Never change the route or focus an element underneath an open modal.
    if (!document.querySelector("dialog[open]")) {
      window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>("[data-tour-launcher]")?.focus())
    }
  }, [])
  const finish = useCallback(() => dispatch({ type: "finish" }), [])
  const retry = useCallback((id: string) => retries.current.get(id)?.(), [])
  useEffect(() => {
    if (!state.checkpoint) return
    try { saveCheckpoint(window.localStorage, state.checkpoint) } catch { /* use in-memory checkpoint */ }
  }, [state.checkpoint])
  const value = useMemo(() => ({ state, launch, go, exit, finish, registerDraft, registerRetry, retry }), [state, launch, go, exit, finish, registerDraft, registerRetry, retry])
  return <TourContext.Provider value={value}>{children}</TourContext.Provider>
}
