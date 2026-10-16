import { NavLink, useNavigate } from "react-router-dom"
import { LogOut, Moon, PanelLeftClose, PanelLeftOpen, Search, Sun } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth } from "@/contexts/AuthContext"
import { usePersonalization } from "@/contexts/PersonalizationContext"
import { useTheme } from "@/contexts/ThemeContext"
import { MOBILE_MAX_WIDTH_QUERY, useMediaQuery } from "@/hooks/useMediaQuery"
import { BoundedTooltip } from "@/components/shared/BoundedTooltip"
import { NAV_SECTIONS } from "./navSections"

interface SidebarProps {
  isOpen: boolean
  onClose: () => void
  onOpenSearch: () => void
}

export function Sidebar({ isOpen, onClose, onOpenSearch }: SidebarProps) {
  const { logout, mode } = useAuth()
  const { resolvedTheme, toggleTheme } = useTheme()
  const { hiddenPaths, sidebarCollapsed, toggleSidebarCollapsed } = usePersonalization()
  const isMobile = useMediaQuery(MOBILE_MAX_WIDTH_QUERY)
  const navigate = useNavigate()

  // The phone drawer always shows the full labeled list; only the desktop sidebar collapses.
  const rail = sidebarCollapsed && !isMobile
  const isDark = resolvedTheme === "dark"
  const visibleSections = NAV_SECTIONS
    .map(section => ({ ...section, pages: section.pages.filter(page => !hiddenPaths.has(page.path)) }))
    .filter(section => section.pages.length > 0)

  async function handleLogout() {
    if (mode === "cloudflare") {
      await logout()
      return
    }
    try {
      await logout()
    } finally {
      navigate("/login", { replace: true })
    }
  }

  const collapseButton = isMobile ? null : (
    <BoundedTooltip tooltip={rail ? "Expand sidebar" : undefined} placement="right" className="inline-flex shrink-0">
      <button
        type="button"
        onClick={toggleSidebarCollapsed}
        aria-label={rail ? "Expand sidebar" : "Collapse sidebar"}
        title={rail ? undefined : "Collapse sidebar"}
        className="theme-icon-button h-9 w-9"
      >
        {rail ? <PanelLeftOpen size={17} aria-hidden="true" /> : <PanelLeftClose size={17} aria-hidden="true" />}
      </button>
    </BoundedTooltip>
  )

  return (
    <nav
      className={[
        rail ? "md:w-[4.25rem]" : "md:w-[17.5rem]",
        "md:shrink-0 md:static md:translate-x-0 md:h-screen md:sticky md:top-0",
        "fixed top-0 left-0 z-30 h-full w-[min(21rem,calc(100vw-1rem))]",
        "transition-[transform,width] duration-300",
        isOpen ? "translate-x-0" : "-translate-x-full",
        "theme-sidebar border-r border-strong flex flex-col",
      ].join(" ")}
      aria-label="Primary navigation"
      data-collapsed={rail ? "true" : undefined}
    >
      {rail ? (
        <div className="flex flex-col items-center gap-2 border-b border-app px-2 pb-3 pt-[max(1rem,var(--safe-top))]">
          {collapseButton}
          <BoundedTooltip tooltip="Search pages (Cmd J)" placement="right" className="inline-flex">
            <button
              type="button"
              onClick={onOpenSearch}
              aria-label="Search pages"
              aria-keyshortcuts="Meta+J"
              className="theme-icon-button h-10 w-10 border border-app bg-input"
            >
              <Search size={16} aria-hidden="true" />
            </button>
          </BoundedTooltip>
        </div>
      ) : (
        <div className="border-b border-app px-4 pb-4 pt-[max(1rem,var(--safe-top))]">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="theme-eyebrow mb-2">Workspace</p>
              <p className="text-lg font-semibold tracking-[-0.03em] text-app">Talisman</p>
            </div>
            {collapseButton}
          </div>
          <button
            type="button"
            onClick={onOpenSearch}
            aria-label="Search pages"
            aria-keyshortcuts="Meta+J"
            className="mt-4 flex h-11 w-full items-center gap-2 rounded-[var(--radius-md)] border border-app bg-input px-3 text-left text-sm text-muted transition-colors hover:border-strong hover:bg-hover hover:text-app"
          >
            <Search size={15} className="shrink-0 text-subtle" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">Search pages</span>
            <kbd className="shrink-0 rounded-md border border-app bg-card-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-subtle">
              Cmd J
            </kbd>
          </button>
        </div>
      )}

      <div className={cn("flex-1 overflow-y-auto py-4", rail ? "px-2" : "px-3")}>
        {visibleSections.map((section, si) => (
          <div key={section.label}>
            {!rail && (
              <p className="mb-1 mt-4 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-subtle">
                {section.label}
              </p>
            )}
            {section.pages.map(page => {
              const Icon = page.icon
              const link = (
                <NavLink
                  key={page.path}
                  to={page.path}
                  end={page.path === "/"}
                  onClick={onClose}
                  aria-label={rail ? page.label : undefined}
                  className={({ isActive }) =>
                    cn(
                      "theme-sidebar-link flex w-full text-left text-sm",
                      rail ? "justify-center px-0" : "mb-1 gap-3",
                      isActive && "theme-sidebar-link-active font-medium",
                    )
                  }
                >
                  <Icon size={rail ? 18 : 16} className="shrink-0" aria-hidden="true" />
                  {!rail && <span className="min-w-0 truncate">{page.label}</span>}
                </NavLink>
              )

              return rail ? (
                <BoundedTooltip key={page.path} tooltip={page.label} placement="right" className="mb-1 block">
                  {link}
                </BoundedTooltip>
              ) : link
            })}
            {si < visibleSections.length - 1 && (
              <hr className="my-2 border-app" />
            )}
          </div>
        ))}
      </div>

      {rail ? (
        <div className="flex flex-col items-center gap-2 border-t border-app px-2 py-3 pb-[max(0.75rem,var(--safe-bottom))]">
          <BoundedTooltip tooltip={isDark ? "Switch to light mode" : "Switch to dark mode"} placement="right" className="inline-flex">
            <button
              type="button"
              role="switch"
              aria-checked={isDark}
              aria-label="Toggle dark mode"
              onClick={toggleTheme}
              className="theme-icon-button h-10 w-10 border border-app bg-card-muted"
            >
              {isDark
                ? <Moon size={16} className="text-link" aria-hidden="true" />
                : <Sun size={16} className="text-link" aria-hidden="true" />}
            </button>
          </BoundedTooltip>
          <BoundedTooltip tooltip="Sign out" placement="right" className="inline-flex">
            <button
              type="button"
              onClick={handleLogout}
              aria-label="Sign out"
              className="theme-icon-button h-10 w-10"
            >
              <LogOut size={16} aria-hidden="true" />
            </button>
          </BoundedTooltip>
        </div>
      ) : (
        <div className="border-t border-app px-3 py-3 pb-[max(0.75rem,var(--safe-bottom))]">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleLogout}
              className="theme-button-base theme-button-secondary flex-1 justify-start px-4"
            >
              Sign out
            </button>
            <button
              type="button"
              role="switch"
              aria-checked={isDark}
              aria-label="Toggle dark mode"
              onClick={toggleTheme}
              className="inline-flex h-11 shrink-0 items-center gap-2 rounded-full border border-app bg-card-muted px-3 transition-colors hover:bg-hover"
            >
              <Sun
                size={14}
                className={isDark ? "text-subtle" : "text-link"}
                aria-hidden="true"
              />
              <span
                className="relative inline-flex h-5 w-9 rounded-full transition-colors duration-200"
                style={{
                  backgroundColor: isDark
                    ? "hsl(var(--accent))"
                    : "hsl(var(--border-strong))",
                }}
              >
                <span
                  className={cn(
                    "mt-[2px] inline-block h-4 w-4 rounded-full bg-elevated shadow-sm transition-transform duration-200",
                    isDark ? "translate-x-[18px]" : "translate-x-[2px]",
                  )}
                />
              </span>
              <Moon
                size={14}
                className={isDark ? "text-link" : "text-subtle"}
                aria-hidden="true"
              />
            </button>
          </div>
        </div>
      )}
    </nav>
  )
}
