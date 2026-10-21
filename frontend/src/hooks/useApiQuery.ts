import { useQuery, type QueryKey, type UseQueryOptions } from "@tanstack/react-query"
import { queryGcTime } from "@/lib/queryCache"

/**
 * Thin wrapper around useQuery with a default staleTime matching
 * the FastAPI TTL caches (5 min for market data).
 */
export function useApiQuery<T>(
  key: QueryKey,
  fn: () => Promise<T>,
  staleTime = 5 * 60 * 1000,
  options: Pick<UseQueryOptions<T>, "placeholderData"> = {},
) {
  return useQuery<T>({
    queryKey: key as QueryKey,
    queryFn: fn,
    staleTime,
    gcTime: queryGcTime(staleTime),
    placeholderData: options.placeholderData,
    retry: 1,
  })
}
