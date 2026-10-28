import { useEffect, useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Play, SlidersHorizontal } from "lucide-react"

import { DigestCard } from "@/components/ideaDigest/DigestCard"
import { MacroViewPanel } from "@/components/ideaDigest/MacroViewPanel"
import { PresetSettingsDialog } from "@/components/ideaDigest/PresetSettingsDialog"
import { Dialog } from "@/components/shared/Dialog"
import { TextInput } from "@/components/shared/FormControls"
import { ErrorMessage, LoadingSpinner } from "@/components/shared/LoadingSpinner"
import { Notice } from "@/components/shared/Notice"
import { PageHeader } from "@/components/shared/PageHeader"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { useRegisterScreenContext } from "@/contexts/ScreenContext"
import {
  dismissIdeaScanCandidate,
  fetchIdeaScanJob,
  fetchIdeaScanRun,
  fetchIdeaScanRuns,
  fetchIdeaScanSettings,
  promoteIdeaScanCandidate,
  startIdeaScanRun,
  type IdeaScanCandidate,
  type IdeaScanDirection,
  type IdeaScanRun,
  type IdeaScanRunSummary,
  type IdeaScanUniverse,
} from "@/lib/api"
import { stanDraftForCard } from "@/lib/ideaDigest"
import { jobStatusQueryOptions } from "@/lib/jobQueries"
import { openStanWithDraft } from "@/lib/stanLauncher"

const ACTIVE_JOB_KEY = "idea-digest-active-job"
const UNIVERSES: { value: IdeaScanUniverse; label: string }[] = [
  { value: "sp500", label: "S&P 500" },
  { value: "sp400", label: "S&P 400" },
  { value: "sp600", label: "S&P 600" },
  { value: "russell2000", label: "Russell 2000" },
]
const PHASE_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Starting",
  universe: "Loading universes",
  data: "Fetching prices and fundamentals",
  prices: "Fetching prices",
  fundamentals: "Fetching fundamentals",
  screens: "Screening and ranking",
  macro: "Writing the macro view",
  reviews: "Reviewing names",
  publish: "Publishing the digest",
}

function readActiveJob(): string | null {
  try {
    return localStorage.getItem(ACTIVE_JOB_KEY)
  } catch {
    return null
  }
}

function writeActiveJob(jobId: string | null) {
  try {
    if (jobId) localStorage.setItem(ACTIVE_JOB_KEY, jobId)
    else localStorage.removeItem(ACTIVE_JOB_KEY)
  } catch {
    // Storage is a convenience; the run still shows up in the history.
  }
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
}

function runLabel(run: IdeaScanRunSummary): string {
  const parts = [run.week ?? run.run_id, formatWhen(run.created_at)]
  if (run.status !== "completed") parts.push(run.status)
  if (run.limited) parts.push("test")
  return parts.join(" · ")
}

function defaultRunId(runs: IdeaScanRunSummary[]): string | null {
  return (runs.find(r => r.status === "completed") ?? runs[0])?.run_id ?? null
}

function CandidateGroup({
  title,
  direction,
  run,
  pendingKey,
  onPromote,
  onDismiss,
}: {
  title: string
  direction: IdeaScanDirection
  run: IdeaScanRun
  pendingKey: string | null
  onPromote: (card: IdeaScanCandidate) => void
  onDismiss: (card: IdeaScanCandidate) => void
}) {
  const all = (run.candidates ?? []).filter(c => c.direction === direction)
  const visible = all.filter(c => c.card_state !== "dismissed")
  const dismissed = all.length - visible.length
  return (
    <section aria-labelledby={`digest-${direction}`} className="min-w-0">
      <h2 id={`digest-${direction}`} className="mb-3 flex items-baseline gap-2 text-sm font-semibold text-app">
        {title}
        <span className="text-xs font-normal text-subtle">
          {visible.length} shown{dismissed ? ` · ${dismissed} dismissed` : ""}
        </span>
      </h2>
      {visible.length === 0 ? (
        <p className="rounded-xl border border-dashed border-app/70 p-4 text-sm text-muted">
          No {direction} names to show.
        </p>
      ) : (
        <div className="space-y-3">
          {visible.map(card => {
            const key = `${card.direction}:${card.ticker}`
            return (
              <DigestCard
                key={key}
                card={card}
                busy={pendingKey === key}
                onPromote={() => onPromote(card)}
                onDiscuss={() => openStanWithDraft(stanDraftForCard(card, run.week))}
                onDismiss={() => onDismiss(card)}
              />
            )
          })}
        </div>
      )}
    </section>
  )
}

function NamesList({ items }: { items: { ticker: string; direction: IdeaScanDirection; company: string | null }[] }) {
  if (!items.length) return <span className="text-subtle">none</span>
  return (
    <span className="flex flex-wrap gap-1.5">
      {items.map(item => (
        <span key={`${item.direction}:${item.ticker}`} className="rounded-full bg-card-muted px-2 py-0.5 text-xs text-app" title={item.company ?? undefined}>
          {item.ticker} <span className="text-subtle">{item.direction}</span>
        </span>
      ))}
    </span>
  )
}

function LowerSections({ run }: { run: IdeaScanRun }) {
  const near = run.near_misses ?? []
  const tracked = run.already_tracked ?? []
  const changes = run.changes
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section className="theme-surface rounded-xl p-4 lg:col-span-2" aria-labelledby="near-misses">
        <h2 id="near-misses" className="text-sm font-semibold text-app">Near-misses</h2>
        <p className="mt-0.5 text-xs text-subtle">Missed exactly one check of one preset.</p>
        {near.length === 0 ? (
          <p className="mt-3 text-sm text-muted">None this week.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <thead className="text-xs text-subtle">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Ticker</th>
                  <th className="py-1.5 pr-3 font-medium">Preset</th>
                  <th className="py-1.5 font-medium">Missed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[hsl(var(--border))]">
                {near.map(miss => (
                  <tr key={`${miss.direction}:${miss.ticker}:${miss.preset_id}`}>
                    <td className="py-1.5 pr-3">
                      <Link to={`/explore/${encodeURIComponent(miss.ticker)}`} className="font-medium text-app hover:underline">
                        {miss.ticker}
                      </Link>
                      <span className="ml-2 text-xs text-subtle">{miss.company}</span>
                    </td>
                    <td className="py-1.5 pr-3 text-muted">{miss.preset_name}</td>
                    <td className="py-1.5 text-muted">{miss.failed_check}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="theme-surface rounded-xl p-4" aria-labelledby="already-tracked">
        <h2 id="already-tracked" className="text-sm font-semibold text-app">Already tracked</h2>
        <p className="mt-0.5 text-xs text-subtle">In Ideas or the portfolio, so not reviewed again.</p>
        {tracked.length === 0 ? (
          <p className="mt-3 text-sm text-muted">None this week.</p>
        ) : (
          <ul className="mt-3 space-y-1.5 text-sm">
            {tracked.map(item => (
              <li key={`${item.direction}:${item.ticker}`}>
                <span className="font-medium text-app">{item.ticker}</span>
                <span className="ml-2 text-xs text-subtle">
                  {item.direction} · {item.tracked_as === "position" ? "held" : "on Ideas"} · {item.presets.map(p => p.name).join(", ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="theme-surface rounded-xl p-4" aria-labelledby="week-changes">
        <h2 id="week-changes" className="text-sm font-semibold text-app">Compared with last week</h2>
        {!changes || (!run.compared_with_run_id && run.limited) ? (
          <p className="mt-3 text-sm text-muted">Test runs aren't compared.</p>
        ) : (
          <dl className="mt-3 space-y-2 text-sm">
            {(["new", "still", "dropped"] as const).map(kind => (
              <div key={kind} className="flex gap-3">
                <dt className="w-24 shrink-0 text-muted">{kind === "still" ? "Still listed" : kind === "new" ? "New" : "Dropped"}</dt>
                <dd className="min-w-0"><NamesList items={changes[kind] ?? []} /></dd>
              </div>
            ))}
          </dl>
        )}
      </section>
    </div>
  )
}

function RunStats({ run }: { run: IdeaScanRun }) {
  const stats = run.stats ?? {}
  const cost = run.cost
  const funnel = [
    ["Universe", stats.universe],
    ["With data", stats.with_data],
    ["Candidates", stats.candidates],
    ["Already tracked", stats.already_tracked],
    ["Reviewed", stats.reviewed],
    ["Published to Scout", stats.published],
  ] as const
  const skipped = cost?.skipped ?? []
  return (
    <section className="theme-surface rounded-xl p-4" aria-labelledby="run-stats">
      <h2 id="run-stats" className="text-sm font-semibold text-app">Run stats</h2>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {funnel.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-subtle">{label}</dt>
            <dd className="text-lg font-semibold tabular-nums text-app">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {(run.presets?.length ?? 0) > 0 && (
        <p className="mt-3 text-xs text-muted">
          Preset hits: {run.presets?.map(p => `${p.name} ${p.hits}${p.kept < p.hits ? ` (top ${p.kept} kept)` : ""}`).join(" · ")}
        </p>
      )}
      {cost && (
        <p className="mt-2 text-xs text-muted">
          Cost <span className="font-semibold text-app">${cost.spent_usd.toFixed(2)}</span> of ${cost.limit_usd.toFixed(2)}
          {cost.by_step ? ` (${Object.entries(cost.by_step).map(([step, usd]) => `${step} $${usd.toFixed(2)}`).join(", ")})` : ""}
          {cost.web_searches != null ? ` · ${cost.web_searches} web searches` : ""}
        </p>
      )}
      {skipped.length > 0 && (
        <p className="mt-1 text-xs text-[hsl(var(--warning))]">
          Skipped for budget: {skipped.map(s => s.label).join(", ")}
        </p>
      )}
      {(stats.not_reviewed_cap ?? 0) > 0 && (
        <p className="mt-1 text-xs text-subtle">{stats.not_reviewed_cap} more names were past the review cap.</p>
      )}
    </section>
  )
}

function RunNowDialog({
  open,
  onOpenChange,
  maxReviews,
  maxCost,
  onStart,
  starting,
  error,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  maxReviews: number
  maxCost: number
  onStart: (body: { universes?: IdeaScanUniverse[]; max_reviews?: number }) => void
  starting: boolean
  error: string | null
}) {
  const [universes, setUniverses] = useState<IdeaScanUniverse[]>(UNIVERSES.map(u => u.value))
  const [reviews, setReviews] = useState(String(maxReviews))
  const full = universes.length === UNIVERSES.length && Number(reviews) >= maxReviews
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Run the idea scan now"
      description={`A full run screens about 3,500 names, takes roughly an hour and spends at most $${maxCost.toFixed(2)}.`}
      maxWidth="max-w-lg"
    >
      <div className="space-y-4">
        <fieldset>
          <legend className="theme-field-label">Universes</legend>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-2">
            {UNIVERSES.map(universe => (
              <label key={universe.value} className="flex min-h-9 items-center gap-2 text-sm text-app">
                <input
                  type="checkbox"
                  checked={universes.includes(universe.value)}
                  onChange={event =>
                    setUniverses(current =>
                      event.target.checked ? [...current, universe.value] : current.filter(u => u !== universe.value),
                    )
                  }
                />
                {universe.label}
              </label>
            ))}
          </div>
        </fieldset>
        <TextInput
          id="run-now-reviews"
          label="Names to review"
          type="number"
          value={reviews}
          onChange={setReviews}
          helperText={`Up to ${maxReviews}. Fewer reviews cost less.`}
        />
        {!full && <Notice tone="info">This is a test run: it won't count as last week's baseline.</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        <div className="flex justify-end">
          <button
            type="button"
            className="theme-button-base theme-button-primary px-4"
            disabled={starting || universes.length === 0}
            onClick={() =>
              onStart({
                ...(universes.length < UNIVERSES.length ? { universes } : {}),
                ...(Number(reviews) < maxReviews ? { max_reviews: Math.max(0, Math.floor(Number(reviews))) } : {}),
              })
            }
          >
            {starting ? "Starting…" : "Start run"}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

export function IdeaDigest() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeJobId, setActiveJobId] = useState<string | null>(readActiveJob)
  const [presetsOpen, setPresetsOpen] = useState(false)
  const [runNowOpen, setRunNowOpen] = useState(false)
  const [pendingKey, setPendingKey] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const runsQuery = useQuery({ queryKey: ["idea-scan", "runs"], queryFn: fetchIdeaScanRuns, staleTime: 60_000 })
  const settingsQuery = useQuery({ queryKey: ["idea-scan", "settings"], queryFn: fetchIdeaScanSettings, staleTime: 5 * 60_000 })
  const runs = useMemo(() => runsQuery.data?.runs ?? [], [runsQuery.data])
  const selectedId = searchParams.get("run") ?? defaultRunId(runs)
  const runQuery = useQuery({
    queryKey: ["idea-scan", "run", selectedId],
    queryFn: () => fetchIdeaScanRun(selectedId as string),
    enabled: Boolean(selectedId),
    staleTime: 30_000,
    refetchInterval: query => (query.state.data?.status === "running" ? 15_000 : false),
  })
  const jobQuery = useQuery(
    jobStatusQueryOptions(["idea-scan", "job", activeJobId], () => fetchIdeaScanJob(activeJobId as string), Boolean(activeJobId), 5000),
  )
  const job = jobQuery.data

  useEffect(() => {
    if (!job || job.status === "queued" || job.status === "running") return
    writeActiveJob(null)
    setActiveJobId(null)
    void queryClient.invalidateQueries({ queryKey: ["idea-scan", "runs"] })
    if (job.status === "done" && job.result?.run_id) {
      setSearchParams(params => {
        params.set("run", job.result?.run_id ?? "")
        return params
      })
    } else if (job.status === "error") {
      setActionError(job.error ? `The scan failed: ${job.error}` : "The scan failed.")
    }
  }, [job, queryClient, setSearchParams])

  useEffect(() => {
    // A job id from a previous visit can expire; forget it rather than poll forever.
    if (jobQuery.error) {
      writeActiveJob(null)
      setActiveJobId(null)
    }
  }, [jobQuery.error])

  const start = useMutation({
    mutationFn: startIdeaScanRun,
    onSuccess: response => {
      writeActiveJob(response.job_id)
      setActiveJobId(response.job_id)
      setRunNowOpen(false)
      void queryClient.invalidateQueries({ queryKey: ["idea-scan", "runs"] })
    },
  })

  function updateCard(runId: string, updated: IdeaScanCandidate) {
    queryClient.setQueryData<IdeaScanRun>(["idea-scan", "run", runId], current =>
      current
        ? {
            ...current,
            candidates: (current.candidates ?? []).map(c =>
              c.ticker === updated.ticker && c.direction === updated.direction ? updated : c,
            ),
          }
        : current,
    )
  }

  async function act(card: IdeaScanCandidate, action: "promote" | "dismiss") {
    const run = runQuery.data
    if (!run) return
    const key = `${card.direction}:${card.ticker}`
    setPendingKey(key)
    setActionError(null)
    try {
      const result =
        action === "promote"
          ? await promoteIdeaScanCandidate(run.run_id, card.direction, card.ticker)
          : await dismissIdeaScanCandidate(run.run_id, card.direction, card.ticker)
      updateCard(run.run_id, result.candidate)
      if (action === "promote") void queryClient.invalidateQueries({ queryKey: ["ideas"] })
    } catch (err) {
      setActionError((err as Error).message)
    } finally {
      setPendingKey(null)
    }
  }

  const run = runQuery.data
  const candidates = run?.candidates ?? []
  useRegisterScreenContext(
    run
      ? {
          pageName: "Idea Digest",
          summary: `Weekly idea scan ${run.week}: ${candidates.filter(c => c.direction === "long").length} long and ${candidates.filter(c => c.direction === "short").length} short candidates.`,
          metrics: {
            "Run status": run.status,
            "Names reviewed": String(run.stats?.reviewed ?? 0),
            "Cost (USD)": run.cost ? run.cost.spent_usd.toFixed(2) : "n/a",
          },
        }
      : { pageName: "Idea Digest" },
  )

  const progress = job && (job.status === "queued" || job.status === "running") ? job.progress : undefined
  const config = settingsQuery.data?.settings.config

  return (
    <div className="space-y-6">
      <PageHeader
        title="Idea Digest"
        subtitle="Names worth a closer look from the weekly long and short scan. These are research leads, not trade recommendations."
        actions={
          <>
            {runs.length > 0 && (
              <select
                aria-label="Scan run"
                className="theme-input min-h-10 max-w-[18rem] text-sm"
                value={selectedId ?? ""}
                onChange={event =>
                  setSearchParams(params => {
                    params.set("run", event.target.value)
                    return params
                  })
                }
              >
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>
                    {runLabel(r)}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              className="theme-button-base theme-button-secondary px-3 text-sm"
              onClick={() => setPresetsOpen(true)}
              disabled={!settingsQuery.data}
            >
              <SlidersHorizontal size={14} aria-hidden="true" /> Presets
            </button>
            <button
              type="button"
              className="theme-button-base theme-button-primary px-3 text-sm"
              onClick={() => setRunNowOpen(true)}
              disabled={Boolean(activeJobId) || !config}
            >
              <Play size={14} aria-hidden="true" /> Run now
            </button>
          </>
        }
      />

      {activeJobId && (
        <Notice tone="info">
          Scan running: {PHASE_LABELS[String(progress?.phase ?? job?.status ?? "queued")] ?? progress?.phase}
          {progress?.total ? ` (${progress.done ?? 0} of ${progress.total})` : ""}. You can leave this page; the run keeps going.
        </Notice>
      )}
      {actionError && <Notice tone="error">{actionError}</Notice>}

      {runsQuery.isLoading && <LoadingSpinner message="Loading idea scans…" />}
      {runsQuery.error && <ErrorMessage message={(runsQuery.error as Error).message} />}
      {!runsQuery.isLoading && !runsQuery.error && runs.length === 0 && !activeJobId && (
        <Notice tone="info">
          No scans yet. The weekly scan runs on Saturdays at 8:00 ET once its schedule is switched on, or you can start one now.
        </Notice>
      )}

      {selectedId && runQuery.isLoading && <LoadingSpinner message="Loading the digest…" />}
      {runQuery.error && <ErrorMessage message={(runQuery.error as Error).message} />}

      {run && run.status === "running" && (
        <Notice tone="info">This run is still in progress ({PHASE_LABELS[run.phase ?? ""] ?? run.phase}).</Notice>
      )}
      {run && run.status === "failed" && <Notice tone="error">This run failed: {run.error ?? "unknown error"}</Notice>}

      {run && run.status === "completed" && (
        <>
          <section className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-subtle">
              <span>{run.week}</span>
              <span>· {run.source === "scheduler" ? "Scheduled run" : "Manual run"}</span>
              <span>· finished {formatWhen(run.completed_at)}</span>
              {run.limited && <StatusBadge tone="warning">Test run</StatusBadge>}
            </div>
            {run.summary?.text && <p className="max-w-3xl text-sm leading-6 text-app">{run.summary.text}</p>}
          </section>

          <MacroViewPanel view={run.macro_view} />

          {candidates.length === 0 ? (
            <Notice tone="info">Nothing cleared the bar this week. The near-misses below came closest.</Notice>
          ) : (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <CandidateGroup
                title="Long ideas"
                direction="long"
                run={run}
                pendingKey={pendingKey}
                onPromote={card => void act(card, "promote")}
                onDismiss={card => void act(card, "dismiss")}
              />
              <CandidateGroup
                title="Short ideas"
                direction="short"
                run={run}
                pendingKey={pendingKey}
                onPromote={card => void act(card, "promote")}
                onDismiss={card => void act(card, "dismiss")}
              />
            </div>
          )}

          <LowerSections run={run} />
          <RunStats run={run} />
        </>
      )}

      {settingsQuery.data && (
        <PresetSettingsDialog open={presetsOpen} onOpenChange={setPresetsOpen} settings={settingsQuery.data.settings} />
      )}
      {config && (
        <RunNowDialog
          key={runNowOpen ? "open" : "closed"}
          open={runNowOpen}
          onOpenChange={setRunNowOpen}
          maxReviews={config.max_reviews}
          maxCost={config.max_cost_usd}
          starting={start.isPending}
          error={(start.error as Error | null)?.message ?? null}
          onStart={body => start.mutate(body)}
        />
      )}
    </div>
  )
}
