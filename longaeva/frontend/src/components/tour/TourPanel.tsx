import { useEffect, useRef, useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { DEMO_LINKS, matchesTourRoute, stepIndex, TOUR_STEPS } from "@/lib/tour"
import { useTour } from "@/lib/tourContext"

export function TourPanel() {
  const { state, go, exit, finish, retry } = useTour()
  const location = useLocation()
  const panel = useRef<HTMLElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const [attempt, setAttempt] = useState(0)
  const [target, setTarget] = useState({ key: "", status: "loading", message: "" })
  const step = TOUR_STEPS[state.index]
  const onRoute = matchesTourRoute(step, location.pathname, location.search)
  const key = `${state.mode}:${state.index}:${location.pathname}:${location.search}:${attempt}`
  useEffect(() => {
    if (state.mode === "closed") return
    panel.current?.querySelector<HTMLElement>(".tour-panel-body")?.scrollTo({ top: 0, behavior: "instant" })
    heading.current?.focus({ preventScroll: true })
  }, [state.mode, state.index])
  useEffect(() => {
    const node = panel.current
    if (!node) return
    const measure = () => document.documentElement.style.setProperty("--tour-panel-height", `${node.getBoundingClientRect().height}px`)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => { observer.disconnect(); document.documentElement.style.removeProperty("--tour-panel-height") }
  }, [state.mode])
  useEffect(() => {
    if (state.mode !== "active" || !onRoute) return
    let highlighted: HTMLElement | null = null
    let timedOut = false
    const inspect = () => {
      const node = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`)
      const status = node?.dataset.tourStatus ?? "loading"
      const message = node?.dataset.tourMessage ?? ""
      if (highlighted && (highlighted !== node || status !== "ready")) {
        highlighted.classList.remove("tour-highlight")
        highlighted = null
      }
      if (node && status === "ready" && highlighted !== node) {
        highlighted = node
        node.classList.add("tour-highlight")
        node.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" })
      }
      const next = { key, status: timedOut && status === "loading" ? "delayed" : status, message }
      setTarget((previous) => previous.key === next.key && previous.status === next.status && previous.message === next.message ? previous : next)
    }
    inspect()
    const observer = new MutationObserver(inspect)
    const main = document.querySelector("main")
    if (main) observer.observe(main, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-tour-status", "data-tour-message"] })
    const timer = window.setTimeout(() => { timedOut = true; inspect() }, 12000)
    return () => { observer.disconnect(); window.clearTimeout(timer); highlighted?.classList.remove("tour-highlight") }
  }, [state.mode, step, onRoute, key])
  useEffect(() => {
    if (state.mode === "closed") return
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) exit()
    }
    window.addEventListener("keydown", escape)
    return () => window.removeEventListener("keydown", escape)
  }, [state.mode, exit])

  if (state.mode === "closed") return null
  const current = target.key === key ? target : { status: "loading", message: "" }
  const unavailable = ["error", "empty", "delayed"].includes(current.status)
  const choose = state.mode === "choose"
  const complete = state.mode === "complete"
  return (
    <aside ref={panel} className="tour-panel" aria-label="Product tour">
      <header className="tour-panel-header">
        <div className="tour-panel-label">
          <span className="font-semibold">Product tour</span>
          <span className="caption" aria-live="polite" aria-atomic="true">{choose ? "5–7 min" : complete ? "Complete" : <><span className="sr-only">Step </span>{state.index + 1}<span aria-hidden="true"> / </span><span className="sr-only"> of </span>{TOUR_STEPS.length}</>}</span>
        </div>
        <button className="theme-button-base theme-button-secondary" onClick={exit}>Exit tour</button>
      </header>
      <div className="tour-panel-body">
        <h2 ref={heading} tabIndex={-1} className="text-lg font-semibold mb-3">{choose ? "Explore Longaeva" : complete ? "You’ve explored the workflow" : step.title}</h2>
        {choose ? <>
          <p className="body-copy">Follow a saved Visa example from evidence to reproducible results. You can use the real page controls, skip steps, and exit whenever you like.</p>
          {state.checkpoint && <p className="body-copy mt-3">{state.checkpoint.completed ? "You previously completed this tour." : `Continue from step ${stepIndex(state.checkpoint.stepId) + 1}: ${TOUR_STEPS[stepIndex(state.checkpoint.stepId)].title}.`}</p>}
        </> : complete ? <>
          <p className="body-copy">You’ve inspected evidence, assumptions, paired outcomes, valuation, evaluation, and reproducibility.</p>
          <p className="body-copy mt-3">Try your own scenario or return to the guide for methodology and limitations.</p>
          <Link className="text-link inline-block mt-3" to={DEMO_LINKS.scenario} onClick={exit}>Build a scenario →</Link><br />
          <Link className="text-link inline-block mt-3" to="/guide" onClick={exit}>How to use →</Link>
        </> : <>
          <p className="body-copy">{step.explanation}</p>
          <h3 className="font-semibold mt-4 mb-2">What to inspect</h3>
          <p className="body-copy">{step.inspect}</p>
          {step.optional && <p className="caption mt-4">{step.optional}</p>}
          {!onRoute ? <div className="theme-notice mt-4" role="status">Tour paused while you explore. Return to this step when you’re ready.</div> : current.status === "loading" ? <p role="status" className="caption mt-4">Waiting for this page’s content… You can skip or exit.</p> : unavailable ? <div className="theme-notice theme-notice-warning mt-4" role="status">
            <p>{current.message || (current.status === "empty" ? "This example’s content is unavailable in the current dataset." : current.status === "delayed" ? "This section is taking longer to load or its tour target is unavailable." : "This section could not load.")}</p>
            <p className="caption mt-2">The packaged demo is loaded by make up. Retry this step, skip it, or exit.</p>
          </div> : null}
        </>}
      </div>
      <footer className="tour-panel-footer">
        {choose ? <>
          {state.checkpoint && !state.checkpoint.completed && <button className="theme-button-base theme-button-primary" onClick={() => go(stepIndex(state.checkpoint!.stepId))}>Resume tour</button>}
          <button className={`theme-button-base ${state.checkpoint && !state.checkpoint.completed ? "theme-button-secondary" : "theme-button-primary"}`} onClick={() => go(0)}>{state.checkpoint ? "Restart tour" : "Start tour"}</button>
        </> : complete ? <button className="theme-button-base theme-button-secondary" onClick={() => go(0)}>Restart tour</button> : <>
          <button className="theme-button-base theme-button-secondary" disabled={state.index === 0} onClick={() => go(state.index - 1)}>Back</button>
          {!onRoute && <button className="theme-button-base theme-button-secondary" onClick={() => go(state.index)}>Return to tour step</button>}
          {onRoute && unavailable && <button className="theme-button-base theme-button-secondary" onClick={() => { retry(step.target); setAttempt((value) => value + 1) }}>Retry step</button>}
          <button className="theme-button-base theme-button-primary" onClick={() => state.index === TOUR_STEPS.length - 1 ? finish() : go(state.index + 1)}>{state.index === TOUR_STEPS.length - 1 ? "Finish tour" : unavailable || current.status === "loading" ? "Skip step" : "Next"}</button>
        </>}
      </footer>
    </aside>
  )
}
