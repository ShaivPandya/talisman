import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { HIDEABLE_PATHS } from "@/components/layout/navSections"
import { DEFAULT_ACCENT, isAccentId, type AccentId } from "@/lib/accentPresets"

// index.html reads ACCENT_STORAGE_KEY before first paint; keep the key in sync there.
const ACCENT_STORAGE_KEY = "talisman-accent"
const HIDDEN_PAGES_STORAGE_KEY = "talisman-hidden-pages"
const SIDEBAR_COLLAPSED_STORAGE_KEY = "talisman-sidebar-collapsed"

function readStorage(key: string) {
  if (typeof window === "undefined") return null

  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string | null) {
  try {
    if (value === null) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, value)
    }
  } catch {
    // Ignore storage failures and keep the preference in memory.
  }
}

function getStoredAccent(): AccentId {
  const stored = readStorage(ACCENT_STORAGE_KEY)
  return isAccentId(stored) ? stored : DEFAULT_ACCENT
}

function getStoredHiddenPaths(): string[] {
  const stored = readStorage(HIDDEN_PAGES_STORAGE_KEY)
  if (!stored) return []

  try {
    const parsed: unknown = JSON.parse(stored)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((path): path is string => typeof path === "string" && HIDEABLE_PATHS.has(path))
  } catch {
    return []
  }
}

function getStoredSidebarCollapsed() {
  return readStorage(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true"
}

interface PersonalizationContextValue {
  accent: AccentId
  setAccent: (accent: AccentId) => void
  hiddenPaths: ReadonlySet<string>
  togglePageHidden: (path: string) => void
  showAllPages: () => void
  sidebarCollapsed: boolean
  setSidebarCollapsed: (collapsed: boolean) => void
  toggleSidebarCollapsed: () => void
}

const PersonalizationContext = createContext<PersonalizationContextValue | null>(null)

export function PersonalizationProvider({ children }: { children: ReactNode }) {
  const [accent, setAccent] = useState<AccentId>(getStoredAccent)
  const [hiddenPathList, setHiddenPathList] = useState<string[]>(getStoredHiddenPaths)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(getStoredSidebarCollapsed)

  const hiddenPaths = useMemo(() => new Set(hiddenPathList), [hiddenPathList])

  useEffect(() => {
    const root = document.documentElement
    if (accent === DEFAULT_ACCENT) {
      delete root.dataset.accent
      writeStorage(ACCENT_STORAGE_KEY, null)
    } else {
      root.dataset.accent = accent
      writeStorage(ACCENT_STORAGE_KEY, accent)
    }
  }, [accent])

  useEffect(() => {
    writeStorage(HIDDEN_PAGES_STORAGE_KEY, hiddenPathList.length > 0 ? JSON.stringify(hiddenPathList) : null)
  }, [hiddenPathList])

  useEffect(() => {
    writeStorage(SIDEBAR_COLLAPSED_STORAGE_KEY, sidebarCollapsed ? "true" : null)
  }, [sidebarCollapsed])

  const togglePageHidden = useCallback((path: string) => {
    if (!HIDEABLE_PATHS.has(path)) return
    setHiddenPathList(current =>
      current.includes(path) ? current.filter(hiddenPath => hiddenPath !== path) : [...current, path],
    )
  }, [])

  const showAllPages = useCallback(() => setHiddenPathList([]), [])
  const toggleSidebarCollapsed = useCallback(() => setSidebarCollapsed(collapsed => !collapsed), [])

  return (
    <PersonalizationContext.Provider
      value={{
        accent,
        setAccent,
        hiddenPaths,
        togglePageHidden,
        showAllPages,
        sidebarCollapsed,
        setSidebarCollapsed,
        toggleSidebarCollapsed,
      }}
    >
      {children}
    </PersonalizationContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePersonalization() {
  const context = useContext(PersonalizationContext)
  if (!context) throw new Error("usePersonalization must be used inside PersonalizationProvider")
  return context
}
