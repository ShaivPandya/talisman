/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react"
import { authApi } from "@/lib/api"
import { getAuthMode, setAuthenticatedSession, type AuthMode } from "@/lib/authMode"
import { bootstrapAuth, getBootstrapSession } from "@/lib/authBootstrap"
import { setCsrfToken } from "@/lib/csrfToken"
import { useQueryClient } from "@tanstack/react-query"

interface AuthState {
  mode: AuthMode
  isAuthenticated: boolean
  isLoading: boolean
  username: string | null
  login: (password: string, username?: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const initialSession = getBootstrapSession()
  const [mode, setMode] = useState<AuthMode>(initialSession?.mode ?? getAuthMode())
  const [isAuthenticated, setIsAuthenticated] = useState(initialSession?.isAuthenticated ?? false)
  const [isLoading, setIsLoading] = useState(!initialSession)
  const [username, setUsername] = useState<string | null>(initialSession?.username ?? null)

  useEffect(() => {
    let cancelled = false
    void bootstrapAuth().then(session => {
      if (cancelled) return
      if (!session.isAuthenticated) queryClient.clear()
      setMode(session.mode)
      setUsername(session.username)
      setIsAuthenticated(session.isAuthenticated)
      setIsLoading(false)
    })
    return () => { cancelled = true }
  }, [queryClient])

  const login = useCallback(
    async (password: string, loginUsername?: string) => {
      if (mode === "cloudflare") {
        window.location.href = "/"
        return
      }
      const result = await authApi.login(password, loginUsername)
      queryClient.clear()
      setAuthenticatedSession(true)
      setUsername(result.username)
      setIsAuthenticated(true)
    },
    [mode, queryClient],
  )

  const logout = useCallback(async () => {
    if (mode === "cloudflare") {
      queryClient.clear()
      window.location.href = "/cdn-cgi/access/logout"
      return
    }
    await authApi.logout()
    queryClient.clear()
    setAuthenticatedSession(false)
    setCsrfToken(null)
    setUsername(null)
    setIsAuthenticated(false)
  }, [mode, queryClient])

  return (
    <AuthContext.Provider
      value={{ mode, isAuthenticated, isLoading, username, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider")
  return ctx
}
