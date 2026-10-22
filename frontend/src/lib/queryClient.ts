import { QueryClient } from "@tanstack/react-query"
import { DEFAULT_QUERY_GC_TIME_MS } from "@/lib/queryCache"

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000,
      gcTime: DEFAULT_QUERY_GC_TIME_MS,
    },
  },
})
