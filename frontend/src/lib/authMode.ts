export type AuthMode = "cloudflare" | "password"

const requested = (import.meta.env.VITE_AUTH_MODE ?? "password").toLowerCase()

let currentAuthMode: AuthMode = requested === "cloudflare" ? "cloudflare" : "password"
let authenticatedSession = false

export function hasAuthenticatedSession() {
  return authenticatedSession
}

export function setAuthenticatedSession(authenticated: boolean) {
  authenticatedSession = authenticated
}

export function getAuthMode(): AuthMode {
  return currentAuthMode
}

export function setAuthMode(mode: AuthMode) {
  currentAuthMode = mode
}

