import { authApi } from "@/lib/api"
import { getAuthMode, setAuthenticatedSession, setAuthMode, type AuthMode } from "@/lib/authMode"
import { setCsrfToken } from "@/lib/csrfToken"

export interface Session {
  mode: AuthMode
  isAuthenticated: boolean
  username: string | null
}

let pending: Promise<Session> | undefined
let session: Session | undefined

async function probeCloudflareAccess() {
  try {
    const response = await fetch("/cdn-cgi/access/get-identity", {
      method: "GET", redirect: "manual", credentials: "include", cache: "no-store",
    })
    return { available: response.status !== 404, authenticated: response.ok }
  } catch {
    return { available: false, authenticated: false }
  }
}

export function getBootstrapSession() {
  return session
}

export function bootstrapAuth(): Promise<Session> {
  pending ??= (async () => {
    const requestedMode = getAuthMode()
    // These requests are independent. A missing Access proxy still falls back
    // to password sessions, without delaying /auth/me behind its probe.
    const me = authApi.me().catch(() => null)
    const access = requestedMode === "cloudflare" ? await probeCloudflareAccess() : null
    const identity = await me
    const mode = access?.available ? "cloudflare" : "password"
    setAuthMode(mode)
    session = {
      mode,
      isAuthenticated: mode === "cloudflare" ? Boolean(access?.authenticated) : Boolean(identity),
      username: identity?.username ?? null,
    }
    if (!session.isAuthenticated) setCsrfToken(null)
    setAuthenticatedSession(session.isAuthenticated)
    return session
  })()
  return pending
}
