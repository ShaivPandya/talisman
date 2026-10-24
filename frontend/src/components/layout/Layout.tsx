import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react"
import { Link, Outlet, useLocation, useNavigation } from "react-router-dom"
import { Bell, Menu, MessageCircle, PanelRightOpen, X } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Sidebar } from "./Sidebar"
import { getRouteLabel } from "./navSections"
import { SidebarSearchDialog } from "./SidebarSearchDialog"
import { ScreenContextProvider, useScreenContext, useAutoScreenContext } from "@/contexts/ScreenContext"
import { DecisionTraceProvider } from "@/contexts/DecisionTraceContext"
import { DecisionTraceDrawer } from "@/components/shared/DecisionTraceDrawer"
import { fetchApprovalSummary, type ApprovalRecord } from "@/lib/api"
import { approvalSummaryQueryKey } from "@/lib/approvalQueries"
import { STAN_OPEN_EVENT, type StanOpenDetail } from "@/lib/stanLauncher"
import { hasResumableActiveJob } from "@/hooks/agentChatSessionStore"
import { LoadObservabilityAfterRender } from "@/lib/observabilityShim"
import { cn } from "@/lib/utils"
import { useAuth } from "@/contexts/AuthContext"
import { preloadRoute } from "@/lib/pageRoutes"
import type { AgentViewMode } from "@/components/agent/AgentChatTypes"

const ACTION_ITEM_ALERT_LIMIT = 50

// The chat (and react-markdown) stays out of the entry bundle.
const loadAgentChat = () => import("../agent/AgentChat")
const AgentChat = lazy(async () => {
  const mod = await loadAgentChat()
  if (!mod) throw new TypeError("Failed to fetch dynamically imported module")
  return { default: mod.AgentChat }
})

export function Layout({ bootstrapping = false }: { bootstrapping?: boolean }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [agentOpen, setAgentOpen] = useState(false)
  const [pageSearchOpen, setPageSearchOpen] = useState(false)

  return (
    <ScreenContextProvider>
      <DecisionTraceProvider>
        <LayoutInner
          bootstrapping={bootstrapping}
          sidebarOpen={sidebarOpen}
          setSidebarOpen={setSidebarOpen}
          agentOpen={agentOpen}
          setAgentOpen={setAgentOpen}
          pageSearchOpen={pageSearchOpen}
          setPageSearchOpen={setPageSearchOpen}
        />
        <DecisionTraceDrawer />
      </DecisionTraceProvider>
    </ScreenContextProvider>
  )
}

interface LayoutInnerProps {
  bootstrapping: boolean
  sidebarOpen: boolean
  setSidebarOpen: (v: boolean) => void
  agentOpen: boolean
  setAgentOpen: Dispatch<SetStateAction<boolean>>
  pageSearchOpen: boolean
  setPageSearchOpen: (v: boolean) => void
}

function LayoutInner({
  bootstrapping,
  sidebarOpen,
  setSidebarOpen,
  agentOpen,
  setAgentOpen,
  pageSearchOpen,
  setPageSearchOpen,
}: LayoutInnerProps) {
  const { screenContext } = useScreenContext()
  const autoContext = useAutoScreenContext()
  const effectiveContext = screenContext ?? autoContext
  const location = useLocation()
  const navigation = useNavigation()
  const { isAuthenticated, isLoading } = useAuth()
  const pending = bootstrapping || navigation.state !== "idle"
  const canUseActions = isAuthenticated && !isLoading && !bootstrapping
  const routeLabel = getRouteLabel(location.pathname)
  const [pendingStanCommand, setPendingStanCommand] = useState<StanOpenDetail | null>(null)
  const [agentViewMode, setAgentViewMode] = useState<AgentViewMode>("compact")
  // Mount the chat on first open, or right away when a saved job needs
  // useAgentChat to resume it. It stays mounted once opened.
  const [agentChatMounted, setAgentChatMounted] = useState(hasResumableActiveJob)
  if (agentOpen && !agentChatMounted) setAgentChatMounted(true)

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<StanOpenDetail>).detail
      if (!detail?.command?.trim()) return
      setPendingStanCommand(detail)
      setAgentOpen(true)
    }
    window.addEventListener(STAN_OPEN_EVENT, handler)
    return () => window.removeEventListener(STAN_OPEN_EVENT, handler)
  }, [setAgentOpen])

  const openPageSearch = useCallback(() => {
    setPageSearchOpen(true)
    setSidebarOpen(false)
  }, [setPageSearchOpen, setSidebarOpen])

  useEffect(() => {
    function handleGlobalKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.isComposing || event.repeat) return
      if (!event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return

      const key = event.key.toLowerCase()
      if (key === "j") {
        event.preventDefault()
        openPageSearch()
        return
      }

      if (key === "k") {
        event.preventDefault()
        setAgentOpen(open => !open)
        setPageSearchOpen(false)
      }
    }

    window.addEventListener("keydown", handleGlobalKeyDown, true)
    return () => window.removeEventListener("keydown", handleGlobalKeyDown, true)
  }, [openPageSearch, setAgentOpen, setPageSearchOpen])

  return (
    <div className="flex min-h-screen bg-app text-app">
      {pending && (
        <div role="progressbar" aria-label="Loading page" className="fixed inset-x-0 top-0 z-[70] h-1 overflow-hidden bg-selected">
          <div className="h-full w-1/3 animate-pulse bg-[hsl(var(--accent))] motion-reduce:animate-none" />
        </div>
      )}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onOpenSearch={openPageSearch}
      />

      <main aria-busy={pending} className={cn("theme-page flex-1 overflow-auto min-w-0", canUseActions && agentOpen && agentViewMode === "compact" && "lg:mr-[28rem] xl:mr-[32rem]")}>
        <div className="theme-page-content">
          <div className="theme-floating mb-4 flex items-center justify-between gap-3 px-3 py-3 md:hidden">
            <button
              type="button"
              className="theme-icon-button"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={18} />
            </button>
            <div className="min-w-0 text-center">
              <p className="text-xs uppercase tracking-[0.14em] text-subtle">Talisman</p>
              <p className="truncate text-sm font-semibold text-app">{routeLabel}</p>
            </div>
            <button
              type="button"
              className="theme-icon-button"
              onClick={() => setAgentOpen(true)}
              disabled={!canUseActions}
              aria-label="Open Stan"
            >
              <PanelRightOpen size={18} />
            </button>
          </div>

          <Suspense fallback={<PageLoading />}>
            {bootstrapping ? <PageLoading /> : <Outlet />}
            {/* Mount once the page has loaded, so background downloads don't compete with it. */}
            {canUseActions && <>
              <PrefetchRoutes />
              <PrefetchAgentChat />
              <LoadObservabilityAfterRender />
            </>}
          </Suspense>
        </div>
      </main>

      {canUseActions && <ActionItemApprovalAlert agentOpen={agentOpen} />}

      <button
        type="button"
        onClick={() => setAgentOpen(true)}
        disabled={!canUseActions}
        className={cn(
          "theme-floating fixed bottom-[max(1.25rem,calc(1.25rem+var(--safe-bottom)))] right-[max(1rem,calc(1rem+var(--safe-right)))] z-40 flex h-14 w-14 items-center justify-center text-link transition-colors hover:bg-selected md:flex",
          agentOpen && "max-md:hidden",
        )}
        aria-label="Open Stan"
      >
        <MessageCircle size={20} />
      </button>

      {canUseActions && agentChatMounted && (
        <Suspense fallback={null}>
          <AgentChat
            open={agentOpen}
            onClose={() => setAgentOpen(false)}
            screenContext={effectiveContext}
            pendingCommand={pendingStanCommand}
            onPendingCommandConsumed={() => setPendingStanCommand(null)}
            desktopViewMode={agentViewMode}
            onViewModeChange={setAgentViewMode}
          />
        </Suspense>
      )}
      <SidebarSearchDialog
        open={pageSearchOpen}
        onOpenChange={setPageSearchOpen}
        onNavigate={() => setSidebarOpen(false)}
      />
    </div>
  )
}

function actionItemTicker(approval: ApprovalRecord) {
  const proposed = approval.proposed_change
  const raw = approval.ticker || proposed?.ticker
  const ticker = String(raw || "").trim().toUpperCase()
  return ticker || null
}

function actionItemDescription(approval: ApprovalRecord) {
  const raw = approval.proposed_change?.description
  const description = String(raw || "").trim()
  if (!description) return "A new action item proposal is waiting for approval."
  return description.length > 140 ? `${description.slice(0, 139)}...` : description
}

function actionItemReviewRoute(approval: ApprovalRecord) {
  return approval.review_route ?? `/workspace?approval_id=${encodeURIComponent(approval.id)}`
}

function ActionItemApprovalAlert({ agentOpen }: { agentOpen: boolean }) {
  const location = useLocation()
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set())
  const summaryQuery = useQuery({
    queryKey: approvalSummaryQueryKey({ status: "pending", limit: ACTION_ITEM_ALERT_LIMIT }),
    queryFn: () => fetchApprovalSummary({ status: "pending", limit: ACTION_ITEM_ALERT_LIMIT }),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const approval = useMemo(() => {
    const items = summaryQuery.data?.items ?? []
    return items.find(item => item.action_id === "create_action_item" && !dismissedIds.has(item.id)) ?? null
  }, [dismissedIds, summaryQuery.data?.items])

  if (!approval || location.pathname === "/workspace" || agentOpen) return null

  const ticker = actionItemTicker(approval)

  return (
    <aside
      className="theme-floating fixed right-[max(1rem,calc(1rem+var(--safe-right)))] top-[max(4.75rem,calc(4.75rem+var(--safe-top)))] z-50 w-[min(27rem,calc(100vw-2rem))] p-4 md:top-[max(1rem,calc(1rem+var(--safe-top)))]"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          <Bell size={16} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-app">
                Action item staged{ticker ? ` for ${ticker}` : ""}
              </p>
              <p className="mt-1 break-words text-sm leading-5 text-muted">
                {actionItemDescription(approval)}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setDismissedIds(prev => new Set(prev).add(approval.id))}
              className="theme-icon-button h-8 w-8 shrink-0"
              aria-label="Dismiss action item alert"
              title="Dismiss"
            >
              <X size={14} />
            </button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Link
              to={actionItemReviewRoute(approval)}
              className="theme-button-base theme-button-primary min-h-9 px-3 text-xs"
            >
              Review in Workspace
            </Link>
            <span className="text-xs text-subtle">Approval required before it becomes an open action item.</span>
          </div>
        </div>
      </div>
    </aside>
  )
}

function PrefetchRoutes() {
  const location = useLocation()
  useEffect(() => {
    let cancelled = false
    let idleId: number | undefined
    let timer: number | undefined
    const routes = ["/", "/workspace", "/risk"].filter(path => path !== location.pathname)
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection
    if (connection?.saveData || connection?.effectiveType?.includes("2g")) return

    async function next() {
      const path = routes.shift()
      if (cancelled || !path) return
      await preloadRoute(path).catch(() => {})
      if (!cancelled) schedule()
    }
    function schedule() {
      if (typeof window.requestIdleCallback === "function") {
        idleId = window.requestIdleCallback(() => { void next() })
      } else {
        timer = window.setTimeout(() => { void next() }, 1_000)
      }
    }
    schedule()
    return () => {
      cancelled = true
      if (idleId !== undefined) window.cancelIdleCallback(idleId)
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [location.pathname])
  return null
}

function PrefetchAgentChat() {
  useEffect(() => {
    let idleId: number | null = null
    let timeoutId: number | null = null

    const prefetchAgentChat = () => {
      loadAgentChat().catch(() => {
        // Opportunistic; opening the chat loads it again and surfaces errors.
      })
    }

    if (typeof window.requestIdleCallback === "function") {
      idleId = window.requestIdleCallback(prefetchAgentChat)
    } else {
      timeoutId = window.setTimeout(prefetchAgentChat, 1000)
    }

    return () => {
      if (idleId !== null && typeof window.cancelIdleCallback === "function") {
        window.cancelIdleCallback(idleId)
      }
      if (timeoutId !== null) window.clearTimeout(timeoutId)
    }
  }, [])

  return null
}

function PageLoading() {
  return (
    <div className="flex min-h-[240px] items-center justify-center text-sm text-muted">
      Loading...
    </div>
  )
}
