import { useEffect, useState } from "react"
import { getRun, type RunRead } from "./api"

export function useSelectedRun(runId: string, revision = 0) {
  const [state, setState] = useState<{
    id: string
    revision: number
    run: RunRead | null
    error: string | null
  }>({ id: "", revision: 0, run: null, error: null })
  useEffect(() => {
    if (!runId) return
    let cancelled = false
    getRun(runId)
      .then((run) => {
        if (!cancelled) setState({ id: runId, revision, run, error: null })
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setState({
            id: runId,
            revision,
            run: null,
            error: e instanceof Error ? e.message : "Unable to load run",
          })
      })
    return () => {
      cancelled = true
    }
  }, [runId, revision])
  return state.id === runId && state.revision === revision
    ? state
    : { id: runId, run: null, error: null }
}
