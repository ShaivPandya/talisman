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

// Start all three before React mounts. Route loaders and AuthProvider reuse
// these promises, including during Strict Mode's repeated mount.
void bootstrapAuth()
void preloadRoute(window.location.pathname).catch(() => {})
preloadRouteData(window.location.href)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
