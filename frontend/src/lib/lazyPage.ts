import { lazy, type ComponentType } from "react"

const RETRY_DELAYS_MS = [300, 1_000, 2_000] as const

export function lazyPage<T extends ComponentType>(loader: () => Promise<Record<string, T>>, exportName: string) {
  let pending: Promise<{ default: T }> | undefined

  async function load() {
    for (let attempt = 0; ; attempt += 1) {
      try {
        const mod = await loader()
        if (!mod || typeof mod !== "object") throw new TypeError("Failed to fetch dynamically imported module")
        if (!mod[exportName]) throw new Error(`Lazy page export "${exportName}" was not found.`)
        return { default: mod[exportName] }
      } catch (error) {
        if (attempt === RETRY_DELAYS_MS.length) throw error
        await new Promise(resolve => setTimeout(resolve, RETRY_DELAYS_MS[attempt]))
      }
    }
  }

  function preload() {
    pending ??= load().catch(error => {
      // Failed speculative loads must not poison a later navigation.
      pending = undefined
      throw error
    })
    return pending
  }

  return Object.assign(lazy(preload), { preload })
}
