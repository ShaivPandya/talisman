import { useEffect, useState } from "react"
import { NavLink, Outlet } from "react-router-dom"

import { getHealth, type HealthResponse } from "@/lib/api"
import { cx } from "@/lib/cx"

const NAV = [
  { to: "/runs", label: "Runs" },
  { to: "/state", label: "State & Evidence" },
  { to: "/scenarios", label: "Scenarios" },
  { to: "/valuation", label: "Valuation & Actions" },
  { to: "/evaluation", label: "Evaluation" },
  { to: "/replay", label: "Replay" },
] as const

export function AppShell() {
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
    <div className="flex min-h-dvh">
      <aside className="theme-sidebar hidden w-60 shrink-0 flex-col border-r border-strong p-4 sm:flex">
        <p className="theme-eyebrow">Longaeva</p>
        <h1 className="mb-6 text-lg font-semibold tracking-tight">Visa simulation</h1>
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
        <header className="flex items-center justify-between gap-3 border-b border-app px-4 py-3 sm:hidden">
          <span className="font-semibold">Longaeva</span>
          <span className="caption">{apiOk ? "API ok" : healthError ? "API down" : "…"}</span>
        </header>
        <nav className="flex gap-2 overflow-x-auto border-b border-app px-3 py-2 sm:hidden">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cx(
                  "theme-badge whitespace-nowrap",
                  isActive ? "theme-badge-info" : "theme-badge-neutral",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="theme-page flex-1 overflow-auto">
          <div className="theme-page-content">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
