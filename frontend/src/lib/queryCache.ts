export const DEFAULT_QUERY_GC_TIME_MS = 60 * 60 * 1000

export function queryGcTime(staleTime: number): number {
  // Never-stale queries still have bounded retention once they become inactive.
  return Math.max(DEFAULT_QUERY_GC_TIME_MS, Number.isFinite(staleTime) ? staleTime : 0)
}
