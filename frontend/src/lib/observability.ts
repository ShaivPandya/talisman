// Loaded lazily through observabilityShim; import that module instead.
import * as Sentry from "@sentry/react"
import { useEffect, type FC, type ReactNode } from "react"
import { createRoutesFromChildren, matchRoutes, useLocation, useNavigationType } from "react-router-dom"
import { envBool } from "@/lib/observabilityShim"

export type RouteTracking = FC<{ children?: ReactNode }>

// Renders nothing. Wrapped by Sentry and mounted beside the app's <Routes>
// with the same children, it names the pageload span and starts navigation
// spans, as Sentry's Routes wrapper would.
const RouteTrackingTarget: RouteTracking = () => null

const DROP_KEYS = new Set([
  "authorization",
  "cookie",
  "cookies",
  "password",
  "prompt",
  "prompts",
  "messages",
  "payload",
  "result",
  "body",
  "csrf",
  "csrfToken",
  "x-csrf-token",
  "x-api-proxy-secret",
  "holdings",
  "positions",
  "portfolio",
  "thesis",
])

function envFloat(name: keyof ImportMetaEnv, defaultValue: number): number {
  const raw = import.meta.env[name]
  if (raw === undefined || raw === "") return defaultValue
  const parsed = Number(raw)
  if (!Number.isFinite(parsed)) return defaultValue
  return Math.max(0, Math.min(1, parsed))
}

function stripQuery(url: string): string {
  try {
    const parsed = new URL(url, window.location.origin)
    parsed.search = ""
    parsed.hash = ""
    return parsed.toString()
  } catch {
    return url.split("?")[0] ?? url
  }
}

function scrubValue(value: unknown): unknown {
  if (typeof value === "string") {
    return value.length > 500 ? `${value.slice(0, 500)}…` : value
  }
  if (Array.isArray(value)) {
    return value.slice(0, 5).map(scrubValue)
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value)) {
      const lowered = key.toLowerCase()
      if (DROP_KEYS.has(lowered) || [...DROP_KEYS].some(part => lowered.includes(part))) {
        out[key] = "[REDACTED]"
      } else if (typeof item === "object" && item !== null) {
        out[key] = scrubValue(item)
      } else {
        out[key] = item
      }
    }
    return out
  }
  return value
}

function scrubContexts(contexts: Sentry.ErrorEvent["contexts"]): Sentry.ErrorEvent["contexts"] {
  if (!contexts) return contexts
  return Object.fromEntries(
    Object.entries(contexts).map(([key, value]) => [key, scrubValue(value) as Record<string, unknown>]),
  )
}

function scrubEvent(event: Sentry.ErrorEvent): Sentry.ErrorEvent | null {
  const next = { ...event }
  if (next.request) {
    next.request = {
      ...next.request,
      url: next.request.url ? stripQuery(next.request.url) : next.request.url,
      headers: undefined,
      data: undefined,
      cookies: undefined,
    }
  }
  if (next.extra) {
    next.extra = scrubValue(next.extra) as Record<string, unknown>
  }
  if (next.contexts) {
    next.contexts = scrubContexts(next.contexts)
  }
  return next
}

function scrubBreadcrumb(breadcrumb: Sentry.Breadcrumb): Sentry.Breadcrumb | null {
  if (breadcrumb.category === "navigation" && breadcrumb.data) {
    return {
      ...breadcrumb,
      data: Object.fromEntries(Object.entries(breadcrumb.data).map(([key, value]) =>
        [key, typeof value === "string" ? stripQuery(value) : value],
      )),
    }
  }
  if (breadcrumb.category === "xhr" || breadcrumb.category === "fetch") {
    return {
      ...breadcrumb,
      data: breadcrumb.data
        ? (scrubValue({
            ...breadcrumb.data,
            url: typeof breadcrumb.data.url === "string" ? stripQuery(breadcrumb.data.url) : breadcrumb.data.url,
            body: undefined,
            request_body: undefined,
            response_body: undefined,
          }) as Record<string, unknown>)
        : undefined,
    }
  }
  return breadcrumb
}

function scrubPerformanceSpan<T extends { op?: string; description?: string; data?: Record<string, unknown> }>(span: T): T {
  let description = span.description
  if (span.op?.startsWith("ui")) description = span.op
  else if (description && (span.op?.startsWith("http") || span.op?.startsWith("resource") || /^https?:\/\//.test(description))) {
    const prefix = description.match(/^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /)?.[0] ?? ""
    description = prefix + stripQuery(description.slice(prefix.length))
  }
  return {
    ...span,
    description,
    data: span.data ? Object.fromEntries(Object.entries(span.data).filter(([key, value]) =>
      typeof value === "number" || typeof value === "boolean"
      || ["sentry.origin", "sentry.op", "sentry.source", "http.request.method", "release", "environment",
        "transaction", "user_agent.original", "sentry.pageload.span_id", "sentry.report_event"].includes(key),
    )) : undefined,
  }
}

// The shim calls this only when sentryFrontendEnabled() holds.
export function initFrontendObservability(): RouteTracking {
  const dsn = (import.meta.env.VITE_SENTRY_DSN ?? "").trim()
  const environment =
    (import.meta.env.VITE_SENTRY_ENVIRONMENT ?? "").trim() || import.meta.env.MODE || "development"
  const release =
    (import.meta.env.VITE_SENTRY_RELEASE ?? "").trim() ||
    (import.meta.env.VITE_TALISMAN_RELEASE_GIT_SHA_SHORT ?? "").trim() ||
    undefined

  Sentry.init({
    dsn,
    environment,
    release,
    enabled: import.meta.env.PROD || envBool("VITE_SENTRY_FORCE_DEV", false),
    sendDefaultPii: false,
    tracesSampleRate: envFloat("VITE_SENTRY_TRACES_SAMPLE_RATE", 0.05),
    beforeSend: scrubEvent,
    beforeSendTransaction: event => ({
      ...event,
      request: event.request ? { url: event.request.url ? stripQuery(event.request.url) : undefined } : undefined,
      extra: event.extra ? scrubValue(event.extra) as Record<string, unknown> : undefined,
      // Performance context includes DOM/resource details; retain metric values,
      // not content or arbitrary application contexts.
      contexts: event.contexts?.trace ? { trace: scrubPerformanceSpan(event.contexts.trace) } : undefined,
      spans: event.spans?.map(scrubPerformanceSpan),
    }),
    beforeSendSpan: scrubPerformanceSpan,
    beforeBreadcrumb: scrubBreadcrumb,
    integrations: [Sentry.reactRouterV7BrowserTracingIntegration({
      useEffect,
      useLocation,
      useNavigationType,
      createRoutesFromChildren,
      matchRoutes,
      enableInp: true,
      // Keep LCP on pageload. SDK 9's lifecycle hooks conflict when both
      // standalone vital observers are enabled. Standalone CLS retains zeroes.
      _experiments: { enableStandaloneClsSpans: true },
    })],
  })
  return Sentry.withSentryReactRouterV7Routing(RouteTrackingTarget)
}

// Replays an error the shim queued before Sentry's global handlers existed.
export function captureUncaughtError(error: unknown, type: "onerror" | "onunhandledrejection"): void {
  Sentry.captureException(error, { mechanism: { type, handled: false } })
}

export function captureRouteError(
  error: unknown,
  info: { componentStack?: string | null; route?: string },
): void {
  Sentry.captureException(error, {
    contexts: {
      react: {
        componentStack: info.componentStack ?? undefined,
      },
      route: {
        path: info.route,
      },
    },
  })
}
