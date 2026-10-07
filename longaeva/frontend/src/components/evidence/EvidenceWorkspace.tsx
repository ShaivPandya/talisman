import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import type { WorkspaceState } from "@/lib/api"
import { PassageSearch } from "./PassageSearch"
import { ObservationQueue } from "./ObservationQueue"
import { ObservationReview } from "@/components/review/ObservationReview"

export function EvidenceWorkspace({ state }: { state: WorkspaceState }) {
  const [params, setParams] = useSearchParams()
  const [revision, setRevision] = useState(0)
  const observation = params.get("observation")
  const update = (changes: Record<string, string | null>) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      for (const [key, value] of Object.entries(changes)) {
        if (value === null) next.delete(key)
        else next.set(key, value)
      }
      return next
    })
  const searchKey = JSON.stringify(
    ["q", "company", "period_start", "period_end", "cutoff_ts"].map((key) =>
      params.get(key),
    ),
  )
  const queueKey = JSON.stringify(
    ["review_company", "review_status", "source_id", "queue_offset"].map(
      (key) => params.get(key),
    ),
  )
  return (
    <>
      <PassageSearch
        key={searchKey}
        params={params}
        cutoff={state.cutoff_ts}
        update={update}
      />
      <ObservationQueue
        key={`${queueKey}:${revision}`}
        params={params}
        update={update}
      />
      {observation && (
        <ObservationReview
          key={`${state.origin_date}:${observation}`}
          id={observation}
          origin={state.origin_date}
          cutoff={state.cutoff_ts}
          params={params}
          update={update}
          onSaved={() => setRevision((value) => value + 1)}
        />
      )}
    </>
  )
}
