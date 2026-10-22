import { queryOptions, type QueryKey } from "@tanstack/react-query"

export class JobPollingTimeout extends Error {}

export function jobStatusQueryOptions<T extends { status: string }>(
  queryKey: QueryKey,
  queryFn: () => Promise<T>,
  enabled: boolean,
  interval = 2500,
) {
  return queryOptions({
    queryKey,
    queryFn,
    enabled,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: false,
    refetchInterval: query => {
      const status = query.state.data?.status
      return !status || status === "queued" || status === "running" ? interval : false
    },
    // Ignore fetch-status transitions and structurally equal job snapshots.
    notifyOnChangeProps: ["data", "error", "errorUpdateCount"] as const,
  })
}
