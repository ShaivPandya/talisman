import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { clearCache } from "@/lib/api"

interface RefreshButtonProps {
  queryKeys: unknown[][]
  beforeRefetch?: () => Promise<unknown>
  onRefresh?: () => Promise<unknown>
  onError?: (error: unknown) => void
  onSuccess?: () => void
  // Clears the shared backend cache for every user; prefer a force_refresh fetch in onRefresh or beforeRefetch.
  clearBackendCache?: boolean
}

export function RefreshButton({
  queryKeys,
  beforeRefetch,
  onRefresh,
  onError,
  onSuccess,
  clearBackendCache = false,
}: RefreshButtonProps) {
  const qc = useQueryClient()
  const [isRefreshing, setIsRefreshing] = useState(false)

  async function handleRefresh() {
    setIsRefreshing(true)
    if (clearBackendCache) {
      try {
        await clearCache()
      } catch {
        // ignore cache clear errors — still refetch
      }
    }
    try {
      if (beforeRefetch) await beforeRefetch()
      if (onRefresh) {
        await onRefresh()
      } else {
        // An empty key matches every cached query, so skip it rather than refetch other pages.
        await Promise.all(queryKeys.filter(key => key.length > 0).map(key => qc.refetchQueries({ queryKey: key })))
      }
      onSuccess?.()
    } catch (err) {
      onError?.(err)
    } finally {
      setIsRefreshing(false)
    }
  }

  return (
    <button
      type="button"
      onClick={handleRefresh}
      disabled={isRefreshing}
      className="theme-button-base theme-button-secondary px-4 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {isRefreshing ? "Refreshing..." : "Refresh Data"}
    </button>
  )
}
