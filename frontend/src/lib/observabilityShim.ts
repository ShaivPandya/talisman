// Keeps @sentry/react (in ./observability) out of the entry bundle. Sentry
// loads once the first page has rendered, so it doesn't compete with that
// page's chunks; until then this queues uncaught errors and route errors so
// startup failures are still reported.
import { useEffect, useSyncExternalStore } from "react"
import type { RouteTracking } from "@/lib/observability"

type ObservabilityClient = typeof import("@/lib/observability")
type Report = (client: ObservabilityClient) => void

const MAX_QUEUED_REPORTS = 20
// For screens that never render <LoadObservabilityAfterRender />.
const FALLBACK_LOAD_DELAY_MS = 5_000

let loadStarted = false
let client: ObservabilityClient | null = null
let routeTracking: RouteTracking | null = null
// Null once Sentry has loaded, or failed to load.
let queuedReports: Report[] | null = []
const routeTrackingListeners = new Set<() => void>()

export function envBool(name: keyof ImportMetaEnv, defaultValue: boolean): boolean {
  const raw = import.meta.env[name]
  if (raw === undefined || raw === "") return defaultValue
  const normalized = String(raw).trim().toLowerCase()
  if (["1", "true", "yes", "on", "enabled"].includes(normalized)) return true
  if (["0", "false", "no", "off", "disabled"].includes(normalized)) return false
  return defaultValue
}

export function sentryFrontendEnabled(): boolean {
  const dsn = (import.meta.env.VITE_SENTRY_DSN ?? "").trim()
  if (!envBool("VITE_SENTRY_ENABLED", true)) return false
  return Boolean(dsn)
}

function report(task: Report) {
  if (client) {
    task(client)
  } else if (queuedReports && queuedReports.length < MAX_QUEUED_REPORTS) {
    queuedReports.push(task)
    // Something needs sending, so stop waiting for the page.
    loadClient()
  }
}

function queueUncaughtError(event: ErrorEvent) {
  const error = event.error ?? event.message
  report(loaded => loaded.captureUncaughtError(error, "onerror"))
}

function queueUnhandledRejection(event: PromiseRejectionEvent) {
  const reason = event.reason
  report(loaded => loaded.captureUncaughtError(reason, "onunhandledrejection"))
}

function loadClient() {
  if (loadStarted) return
  loadStarted = true
  void importClient()
}

async function importClient() {
  try {
    const mod = await import("@/lib/observability")
    // Undefined when main.tsx's stale-asset handler swallowed a failed load.
    if (mod) {
      routeTracking = mod.initFrontendObservability()
      client = mod
    }
  } catch (error) {
    console.warn("Frontend monitoring failed to load.", error)
  }

  // Sentry's global handlers own uncaught errors from here on.
  window.removeEventListener("error", queueUncaughtError)
  window.removeEventListener("unhandledrejection", queueUnhandledRejection)
  const reports = queuedReports ?? []
  queuedReports = null
  const loaded = client
  if (loaded) reports.forEach(task => task(loaded))
  routeTrackingListeners.forEach(listener => listener())
}

export function startFrontendObservability(): void {
  if (!sentryFrontendEnabled()) return

  window.addEventListener("error", queueUncaughtError)
  window.addEventListener("unhandledrejection", queueUnhandledRejection)
  window.setTimeout(loadWhenIdle, FALLBACK_LOAD_DELAY_MS)
}

function loadWhenIdle() {
  if (loadStarted || !sentryFrontendEnabled()) return
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(loadClient, { timeout: 2_000 })
  } else {
    window.setTimeout(loadClient, 1000)
  }
}

// Render beside a page inside its Suspense boundary: it mounts once the page
// has loaded, then Sentry loads on the next idle period.
export function LoadObservabilityAfterRender(): null {
  useEffect(loadWhenIdle, [])
  return null
}

export function captureRouteError(
  error: unknown,
  info: { componentStack?: string | null; route?: string },
): void {
  if (!sentryFrontendEnabled()) return
  report(loaded => loaded.captureRouteError(error, info))
}

function subscribeRouteTracking(listener: () => void) {
  routeTrackingListeners.add(listener)
  return () => {
    routeTrackingListeners.delete(listener)
  }
}

// Sentry's route tracker once loaded, else null.
export function useRouteTracking(): RouteTracking | null {
  return useSyncExternalStore(subscribeRouteTracking, () => routeTracking, () => null)
}
