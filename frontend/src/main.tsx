import './instrumentation'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { bootstrapAuth } from '@/lib/authBootstrap'
import { preloadRoute } from '@/lib/pageRoutes'
import { preloadRouteData } from '@/lib/routeData'
import { reloadOnceForStaleAssetLoad } from '@/lib/chunkRecovery'

type VitePreloadErrorEvent = Event & { payload?: unknown }

window.addEventListener('vite:preloadError', (event: VitePreloadErrorEvent) => {
  event.preventDefault()
  reloadOnceForStaleAssetLoad('vite-preload', event.payload)
})

// Start session, route, and route-data loads before React mounts. Route loaders
// and AuthProvider reuse these promises, including during Strict Mode's remount.
void bootstrapAuth()
void preloadRoute(window.location.pathname).catch(() => {})
// Home renders the landing page only after /auth/me redirects. Load that chunk
// during the check so it is not a third serial request.
if (window.location.pathname === "/") {
  void preloadRoute("/login").catch(() => {})
}
preloadRouteData(window.location.href)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
