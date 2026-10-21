import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

type ModuleInfoLookup = (id: string) => { isEntry: boolean; importers: readonly string[] } | null

const eagerModules = new Set<string>()
const lazyModules = new Set<string>()

// True when an entry reaches the module through static imports alone, i.e.
// every page downloads it before rendering.
function isEagerModule(id: string, getModuleInfo: ModuleInfoLookup) {
  if (eagerModules.has(id)) return true
  if (lazyModules.has(id)) return false
  const visited = new Set<string>()
  const reachesEntry = (current: string): boolean => {
    if (eagerModules.has(current)) return true
    if (lazyModules.has(current) || visited.has(current)) return false
    visited.add(current)
    const info = getModuleInfo(current)
    if (!info) return false
    if (info.isEntry || info.importers.some(reachesEntry)) {
      eagerModules.add(current)
      return true
    }
    return false
  }
  const eager = reachesEntry(id)
  if (!eager) lazyModules.add(id)
  return eager
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id, { getModuleInfo }) {
          if (!id.includes('node_modules')) return
          if (
            // Not '/react/', which also matches the lazily loaded @sentry/react.
            id.includes('/node_modules/react/') ||
            id.includes('/react-dom/') ||
            id.includes('/react-router/') ||
            id.includes('/react-router-dom/') ||
            id.includes('/scheduler/') ||
            id.includes('/use-sync-external-store/')
          ) {
            return 'vendor-react'
          }
          if (id.includes('/@tanstack/')) return 'vendor-query'
          if (id.includes('/axios/')) return 'vendor-http'
          if (
            id.includes('/recharts/') ||
            id.includes('/d3-') ||
            id.includes('/victory-vendor/')
          ) {
            return 'vendor-charts'
          }
          if (
            id.includes('/react-markdown/') ||
            id.includes('/remark-') ||
            id.includes('/unified/') ||
            id.includes('/hast-') ||
            id.includes('/mdast-') ||
            id.includes('/micromark') ||
            id.includes('/unist-') ||
            id.includes('/vfile') ||
            id.includes('/property-information/') ||
            id.includes('/space-separated-tokens/') ||
            id.includes('/comma-separated-tokens/') ||
            id.includes('/character-entities') ||
            id.includes('/decode-named-character-reference/') ||
            id.includes('/trim-lines/') ||
            id.includes('/zwitch/')
          ) {
            return 'vendor-markdown'
          }
          // lucide's barrel re-exports every icon, so each one looks eager
          // below. Leave icons to the bundler, which places them by use.
          if (id.includes('/lucide-react/')) return
          // Each group above also takes its unassigned dependencies, so the
          // catch-all claims only what the entry needs. Lazy-only packages
          // (recharts' Redux/immer, markdown helpers, Sentry) stay with the
          // group or chunk that imports them.
          if (isEagerModule(id, getModuleInfo)) return 'vendor'
        },
      },
    },
  },
})
