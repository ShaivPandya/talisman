import { useState } from "react"
import { skipToken, useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  deleteScreenerRun, fetchScreenerRun, fetchScreenerRuns, saveScreenerRun,
  type ScreenerSnapshot, type ScreenerTab,
} from "@/lib/api"
import { ActionButton, TextInput } from "@/components/shared/FormControls"
import { ErrorMessage } from "@/components/shared/LoadingSpinner"

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function settingLabel(key: string): string {
  const labels: Record<string, string> = {
    input_mode: "Input", pb_threshold: "P/B threshold", profit_type: "Profitability", loss_type: "Loss filter",
    rel_momentum_benchmark: "Relative benchmark", liquidity_coverage: "Liquid and well covered",
    min_dollar_volume_industry_pct: "Minimum industry dollar-volume percentile",
    require_above_median_coverage: "Analyst coverage above industry median",
    check_issuance: "Net equity issuance filter",
  }
  return labels[key] ?? key.replace(/^check_/, "").replaceAll("_", " ")
    .replace(/\beps\b/g, "EPS").replace(/\bebit\b/g, "EBIT").replace(/\byoy\b/g, "YoY")
    .replace(/\bpos\b/g, "positive").replace(/\bneg\b/g, "negative").replace(/\brel\b/g, "relative")
}

function settingValue(key: string, value: unknown): string {
  if (value == null || value === false) return "Off"
  if (value === true) return "On"
  if (typeof value === "number" && (key.endsWith("_pct") || key === "min_dollar_volume_industry_pct")) {
    return key === "min_dollar_volume_industry_pct" ? `${Math.round(value * 100)}` : `${value}%`
  }
  if (Array.isArray(value)) return value.map(item => settingValue("", item)).join(", ")
  if (typeof value === "object") return Object.entries(value)
    .map(([label, item]) => `${settingLabel(label)}: ${settingValue(label, item)}`).join(" · ")
  return String(value).replaceAll("_", " ") || "—"
}

function SavedCriteria({ request }: { request: Record<string, unknown> }) {
  return (
    <details className="mt-2 text-xs text-muted">
      <summary className="cursor-pointer">Criteria used for these results</summary>
      <dl className="mt-2 grid gap-1 sm:grid-cols-2">
        {Object.entries(request).map(([key, value]) => (
          <div key={key} className="min-w-0 break-words">
            <dt className="font-medium capitalize">{settingLabel(key)}</dt>
            <dd>{settingValue(key, value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

function SaveRun({ screen, snapshot }: { screen: ScreenerTab; snapshot: ScreenerSnapshot }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(() => `${screen} · ${new Date(snapshot.captured_at).toLocaleString()}`)
  const save = useMutation({
    mutationFn: () => saveScreenerRun({
      screen, name: name.trim(), request: snapshot.request, result: snapshot.result,
      captured_at: snapshot.captured_at, benchmark: snapshot.benchmark,
    }),
    onMutate: () => queryClient.getQueryCache().find({ queryKey: ["screeners", screen] }),
    onSuccess: (saved, _variables, query) => {
      if (!query || query !== queryClient.getQueryCache().find({ queryKey: ["screeners", screen] })) return
      queryClient.setQueryData<ScreenerSnapshot>(["screeners", screen], current =>
        current?.captured_at === snapshot.captured_at ? saved : current)
      void queryClient.invalidateQueries({ queryKey: ["saved-screeners", screen] })
    },
  })
  return (
    <div className="space-y-2">
      {snapshot.run_id ? (
        <div className="space-y-1">
          <p className="text-sm text-muted">Viewing saved run: <strong>{snapshot.name}</strong></p>
          <p className="text-xs text-muted">The results below are from this saved run. Use the form to start a new screen.</p>
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-48 flex-1">
            <TextInput id="screener-run-name" label="Run name" value={name} onChange={setName} />
          </div>
          <ActionButton onClick={() => save.mutate()} loading={save.isPending} disabled={!name.trim() || name.trim().length > 160}>
            Save run
          </ActionButton>
        </div>
      )}
      <p className="text-xs text-muted">Results captured {new Date(snapshot.captured_at).toLocaleString()}. Saved runs stay available until you delete them.</p>
      <SavedCriteria request={snapshot.request} />
      {save.isError && <ErrorMessage message={message(save.error)} />}
    </div>
  )
}

export function ScreenerRunHistory({ screen }: { screen: ScreenerTab }) {
  const queryClient = useQueryClient()
  const [offset, setOffset] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const running = useIsMutating({ mutationKey: ["screener-run", screen] }) > 0
  const { data: snapshot } = useQuery<ScreenerSnapshot>({
    queryKey: ["screeners", screen], queryFn: skipToken, staleTime: Infinity,
  })
  const history = useQuery({
    queryKey: ["saved-screeners", screen, offset], queryFn: () => fetchScreenerRuns(screen, offset),
  })
  const open = useMutation({
    mutationFn: fetchScreenerRun,
    onMutate: () => queryClient.getQueryCache().find({ queryKey: ["screeners", screen] }),
    onSuccess: (run, _variables, query) => {
      if (!query || query !== queryClient.getQueryCache().find({ queryKey: ["screeners", screen] })) return
      if (queryClient.isMutating({ mutationKey: ["screener-run", screen] })) return
      queryClient.setQueryData(["screeners", screen], run)
    },
  })
  const remove = useMutation({
    mutationFn: deleteScreenerRun,
    onMutate: () => queryClient.getQueryCache().find({ queryKey: ["screeners", screen] }),
    onSuccess: (_result, runId, query) => {
      if (!query || query !== queryClient.getQueryCache().find({ queryKey: ["screeners", screen] })) return
      setConfirmDelete(null)
      queryClient.setQueryData<ScreenerSnapshot>(["screeners", screen], current =>
        current?.run_id === runId ? { ...current, run_id: undefined, name: undefined } : current)
      if (history.data?.length === 1 && offset > 0) setOffset(offset - 50)
      void queryClient.invalidateQueries({ queryKey: ["saved-screeners", screen] })
    },
  })
  return (
    <section aria-label="Saved screener runs" className="theme-surface mb-6 max-w-3xl p-4 space-y-4">
      <h2 className="font-semibold text-app">Saved runs</h2>
      {snapshot && <SaveRun key={snapshot.captured_at + (snapshot.run_id ?? "")} screen={screen} snapshot={snapshot} />}
      {history.isPending && <p className="text-sm text-muted">Loading saved runs…</p>}
      {history.isError && <ErrorMessage message={message(history.error)} />}
      {history.data?.length === 0 && <p className="text-sm text-muted">No saved {screen.toLowerCase()} runs. Run a screen, then save its results here.</p>}
      <ul className="space-y-2">
        {history.data?.map(run => (
          <li key={run.run_id} className="flex flex-wrap items-center justify-between gap-2 border-t border-app pt-2">
            <div className="min-w-0 break-words">
              <p className="text-sm font-medium text-app">{run.name}</p>
              <p className="text-xs text-muted">Saved {new Date(run.created_at).toLocaleString()}</p>
            </div>
            <div className="flex gap-3 text-sm">
              <button type="button" className="text-blue-600 disabled:opacity-50" disabled={running || open.isPending || remove.isPending}
                aria-label={`Open ${run.name}`} onClick={() => open.mutate(run.run_id)}>Open</button>
              {confirmDelete === run.run_id ? <>
                <button type="button" className="text-red-600 disabled:opacity-50" disabled={remove.isPending}
                  onClick={() => remove.mutate(run.run_id)}>Delete permanently</button>
                <button type="button" disabled={remove.isPending} onClick={() => setConfirmDelete(null)}>Cancel</button>
              </> : (
                <button type="button" className="text-red-600 disabled:opacity-50" disabled={open.isPending || remove.isPending}
                  aria-label={`Delete ${run.name}`} onClick={() => setConfirmDelete(run.run_id)}>Delete</button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {(offset > 0 || history.data?.length === 50) && (
        <div className="flex gap-4 text-sm">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(offset - 50)}>Newer</button>
          <button type="button" disabled={history.data?.length !== 50} onClick={() => setOffset(offset + 50)}>Older</button>
        </div>
      )}
      {open.isPending && <p role="status" className="text-sm text-muted">Opening saved results…</p>}
      {open.isError && <ErrorMessage message={message(open.error)} />}
      {remove.isError && <ErrorMessage message={message(remove.error)} />}
    </section>
  )
}
