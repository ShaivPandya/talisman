import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import {
  AblationPanel,
  ForecastPanel,
  PortfolioPanel,
} from "@/components/evaluation/ReportPanels"
import { SavedDocument } from "@/components/evaluation/SavedDocument"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import {
  getReportCatalog,
  getSavedReport,
  type ReportCatalog,
  type SavedReport,
} from "@/lib/reportApi"
import { EVALUATION_TARGETS, TARGET_LABELS } from "@/lib/reportDisplay"

const FORECAST_KEYS = [
  "full_model",
  "seasonal_trend",
  "financial_only",
  "guidance",
  "no_external_commentary",
  "pooled_spending",
  "no_service_lag",
]
const SECTIONS = {
  forecasts: "Forecasts & baselines",
  ablations: "Ablations",
  portfolio: "Benchmarks",
  documents: "Report & model",
  pending: "Pending content",
}

export function EvaluationPage() {
  const [params, setParams] = useSearchParams()
  const rawSection = params.get("section") ?? "forecasts"
  const section = rawSection in SECTIONS ? rawSection : "forecasts"
  const target = EVALUATION_TARGETS.includes(
    params.get("target") as (typeof EVALUATION_TARGETS)[number],
  )
    ? params.get("target")!
    : "net_revenue"
  const horizon = params.get("horizon") === "4q" ? "4q" : "q1"
  const rawWindow = params.get("window") ?? "overall"
  const window =
    horizon === "4q" && section === "forecasts"
      ? "overall"
      : ["primary", "extension"].includes(rawWindow)
        ? rawWindow
        : "overall"
  const variant = FORECAST_KEYS.includes(params.get("variant") ?? "")
    ? params.get("variant")!
    : "full_model"
  const profile = params.get("profile") ?? "central"
  const documentKey = params.get("document") ?? "evaluation-notes"
  const [revision, setRevision] = useState(0)
  const [catalog, setCatalog] = useState<ReportCatalog | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const signature =
    section === "forecasts"
      ? FORECAST_KEYS.join(",")
      : ["ablations", "portfolio"].includes(section)
        ? section
        : ""
  const [state, setState] = useState<{
    signature: string
    reports: SavedReport[]
    errors: string[]
  } | null>(null)
  useEffect(() => {
    let cancelled = false
    getReportCatalog()
      .then((c) => {
        if (!cancelled) {
          setCatalog(c)
          setCatalogError(null)
        }
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setCatalogError(
            e instanceof Error ? e.message : "Unable to load report catalog",
          )
      })
    return () => {
      cancelled = true
    }
  }, [revision])
  useEffect(() => {
    if (!signature) return
    let cancelled = false
    const keys = signature.split(",")
    Promise.allSettled(keys.map(getSavedReport)).then((results) => {
      if (cancelled) return
      const reports: SavedReport[] = [],
        errors: string[] = []
      results.forEach((r, i) => {
        if (r.status === "fulfilled") reports.push(r.value)
        else
          errors.push(
            `${keys[i]}: ${r.reason instanceof Error ? r.reason.message : "Unable to load saved report"}`,
          )
      })
      setState({ signature, reports, errors })
    })
    return () => {
      cancelled = true
    }
  }, [signature, revision])
  const current = state?.signature === signature ? state : null
  const ablation = current?.reports[0]?.ablations
  const portfolio = current?.reports[0]?.portfolio
  const selectedProfile =
    ablation && profile in ablation.summaries ? profile : "central"
  function change(key: string, value: string) {
    const next = new URLSearchParams(params)
    next.set(key, value)
    if (key === "horizon" && value === "4q" && section === "forecasts")
      next.set("window", "overall")
    setParams(next)
  }
  return (
    <div>
      <header className="theme-page-header">
        <div>
          <p className="theme-eyebrow">Saved results</p>
          <h1 className="theme-page-title">Evaluation</h1>
          <p className="theme-page-subtitle">
            Inspect packaged evaluation artifacts, counts and limitations. No
            scoring is run from this page.
          </p>
        </div>
      </header>
      <nav
        aria-label="Evaluation sections"
        className="flex flex-wrap gap-2 mb-5"
      >
        {Object.entries(SECTIONS).map(([key, label]) => (
          <button
            key={key}
            aria-current={section === key ? "page" : undefined}
            className={`theme-button-base ${section === key ? "theme-button-primary" : "theme-button-secondary"}`}
            onClick={() => change("section", key)}
          >
            {label}
          </button>
        ))}
      </nav>
      {catalogError || current?.errors.length ? (
        <div className="theme-notice theme-notice-error mb-5">
          {catalogError && <p>{catalogError}</p>}
          {current?.errors.map((e) => (
            <p key={e}>{e}</p>
          ))}
          <button
            className="theme-button-base theme-button-secondary mt-2"
            onClick={() => {
              setState(null)
              setRevision((n) => n + 1)
            }}
          >
            Retry saved reports
          </button>
        </div>
      ) : null}
      {["forecasts", "ablations"].includes(section) && (
        <SurfaceCard className="p-4 mb-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm">
              Target
              <select
                className="theme-input block w-full mt-1"
                value={target}
                onChange={(e) => change("target", e.target.value)}
              >
                {EVALUATION_TARGETS.map((k) => (
                  <option key={k} value={k}>
                    {TARGET_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Horizon
              <select
                className="theme-input block w-full mt-1"
                value={horizon}
                onChange={(e) => change("horizon", e.target.value)}
              >
                <option value="q1">Next quarter</option>
                <option value="4q">Four quarters</option>
              </select>
            </label>
            <label className="text-sm">
              Window
              <select
                className="theme-input block w-full mt-1"
                value={window}
                disabled={horizon === "4q" && section === "forecasts"}
                onChange={(e) => change("window", e.target.value)}
              >
                <option value="overall">All windows</option>
                <option value="primary">Primary</option>
                <option value="extension">Extension</option>
              </select>
            </label>
          </div>
          {section === "forecasts" ? (
            <label className="text-sm block mt-3">
              Origin detail model
              <select
                className="theme-input block w-full mt-1"
                value={variant}
                onChange={(e) => change("variant", e.target.value)}
              >
                {FORECAST_KEYS.map((k) => (
                  <option key={k} value={k}>
                    {catalog?.reports.find((r) => r.key === k)?.title ??
                      k.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="text-sm block mt-3">
              Saved profile
              <select
                className="theme-input block w-full mt-1"
                value={selectedProfile}
                onChange={(e) => change("profile", e.target.value)}
              >
                {Object.keys(ablation?.summaries ?? { central: {} }).map(
                  (k) => (
                    <option key={k} value={k}>
                      {k.replaceAll("_", " ")}
                    </option>
                  ),
                )}
              </select>
            </label>
          )}
        </SurfaceCard>
      )}
      {signature && !current && <p role="status">Loading saved reports…</p>}
      {section === "forecasts" && current && (
        <ForecastPanel
          reports={current.reports}
          selected={variant}
          target={target}
          horizon={horizon}
          window={window}
        />
      )}
      {section === "ablations" && ablation && (
        <AblationPanel
          report={ablation}
          target={target}
          horizon={horizon}
          window={window}
          profile={selectedProfile}
        />
      )}
      {section === "portfolio" && portfolio && (
        <PortfolioPanel report={portfolio} />
      )}
      {signature &&
        current?.reports[0]?.status === "pending" &&
        section !== "forecasts" && (
          <p className="theme-notice">{current.reports[0].reason}</p>
        )}
      {section === "documents" && (
        <>
          <label className="text-sm block mb-5">
            Saved document
            <select
              className="theme-input block w-full mt-1"
              value={documentKey}
              onChange={(e) => change("document", e.target.value)}
            >
              {!catalog?.documents.some((d) => d.key === documentKey) && (
                <option value={documentKey}>{documentKey}</option>
              )}
              {catalog?.documents.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.title}
                  {d.status === "pending" ? " · pending" : ""}
                </option>
              ))}
            </select>
          </label>
          <SavedDocument documentKey={documentKey} />
        </>
      )}
      {section === "pending" && (
        <div className="space-y-4">
          {catalog?.reports
            .filter((r) => r.kind === "pending")
            .map((r) => (
              <SurfaceCard key={r.key} className="p-5">
                <h2 className="font-semibold">{r.title}</h2>
                <p className="body-copy mt-2">{r.reason}</p>
                <p className="caption mt-2">Owned by {r.owner_issue}</p>
                {r.key === "failure_case" && (
                  <button
                    className="theme-button-base theme-button-secondary mt-3"
                    onClick={() => {
                      const next = new URLSearchParams(params)
                      next.set("section", "documents")
                      next.set("document", "evaluation-report")
                      setParams(next)
                    }}
                  >
                    Open final report availability
                  </button>
                )}
              </SurfaceCard>
            ))}
        </div>
      )}
      {section === "pending" && !catalog && !catalogError && (
        <p role="status">Loading availability…</p>
      )}
    </div>
  )
}
