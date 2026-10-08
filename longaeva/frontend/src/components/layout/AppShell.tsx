import { useEffect, useState } from "react"
import { Link, NavLink, Outlet } from "react-router-dom"

import { getHealth, type HealthResponse } from "@/lib/api"
import { cx } from "@/lib/cx"
import { useTour } from "@/lib/tourContext"
import { TourProvider } from "@/components/tour/TourProvider"
import { TourPanel } from "@/components/tour/TourPanel"

const NAV = [
  { to: "/guide", label: "How to use" },
  { to: "/runs", label: "Runs" },
  { to: "/state", label: "State & Evidence" },
  { to: "/scenarios", label: "Scenarios" },
  { to: "/valuation", label: "Valuation & Actions" },
  { to: "/evaluation", label: "Evaluation" },
  { to: "/replay", label: "Replay" },
] as const

export function AppShell() {
  return <TourProvider><ShellContent /></TourProvider>
}

function ShellContent() {
  const { state, launch } = useTour()
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      getHealth()
        .then((payload) => {
          if (!cancelled) {
            setHealth(payload)
            setHealthError(null)
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setHealth(null)
            setHealthError(err instanceof Error ? err.message : "API unreachable")
          }
        })
    }
    load()
    const id = window.setInterval(load, 15000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const apiOk = health?.status === "ok"

  return (
    <div className={`flex min-h-dvh ${state.mode !== "closed" ? "tour-open" : ""}`}>
      <aside className="theme-sidebar hidden w-60 shrink-0 flex-col border-r border-strong p-4 sm:flex">
        <Link to="/guide" className="app-wordmark">Longaeva<span aria-hidden="true">.</span></Link>
        <nav className="flex flex-col">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cx("theme-sidebar-link mb-1 text-sm", isActive && "theme-sidebar-link-active font-medium")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto pt-6 caption">
          {healthError ? (
            <span className="text-negative">API {healthError}</span>
          ) : apiOk ? (
            <span className="text-positive">API ok · {health?.alembic_revision ?? "—"}</span>
          ) : (
            <span className="text-subtle">Checking API…</span>
          )}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="tour-toolbar">
          <div className="app-context">
            <Link to="/guide" className="app-wordmark sm:hidden">Longaeva<span aria-hidden="true">.</span></Link>
            <span className="app-context-company">Visa</span>
            <span className="caption hidden sm:inline">Business simulation</span>
          </div>
          <button data-tour-launcher className="theme-button-base theme-button-secondary" onClick={launch}>Product tour</button>
        </div>
        <nav className="app-mobile-nav sm:hidden">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cx(
                  "app-mobile-link",
                  isActive && "app-mobile-link-active",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="tour-main-row">
          <main className="theme-page flex-1 min-w-0">
            <div className="theme-page-content">
              <Outlet />
            </div>
          </main>
          <TourPanel />
        </div>
      </div>
    </div>
  )
}
