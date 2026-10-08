// The small, stable demo reference set. The full seed manifest stays server-side.
export const DEMO = {
  origin: "2024-07-23",
  baselineId: "cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d",
  mixShiftId: "3752b7df-c114-5fa4-b312-efe5a5908c38",
  bookingSourceId: "85889f26-ced9-48a4-9c7b-e61af4ad41d9",
  bookingObservationId: "b2fda0e2-cdfe-4018-b9f8-f4baefc73fa8",
} as const

export const DEMO_LINKS = {
  state: `/state?origin=${DEMO.origin}`,
  evidence: `/state?origin=${DEMO.origin}&tab=evidence&source_id=${DEMO.bookingSourceId}&observation=${DEMO.bookingObservationId}`,
  scenario: `/scenarios?origin=${DEMO.origin}`,
  comparison: `/scenarios?origin=${DEMO.origin}&baseline_run_id=${DEMO.baselineId}&run_id=${DEMO.mixShiftId}`,
  valuation: `/valuation?run_id=${DEMO.baselineId}`,
  evaluation: "/evaluation?section=forecasts",
  prospective: "/evaluation?section=prospective",
  replay: `/replay?run_id=${DEMO.baselineId}`,
  methodology: "/evaluation?section=documents&document=evaluation-report",
  model: "/evaluation?section=documents&document=model-spec",
  limitations: "/evaluation?section=documents&document=limitations",
  failure: "/evaluation?section=documents&document=evaluation-report#failure-case",
} as const

export interface TourStep {
  id: string
  title: string
  to: string
  target: string
  explanation: string
  inspect: string
  optional?: string
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: "starting-point", title: "Inspect the starting point", to: DEMO_LINKS.state, target: "starting-state",
    explanation: "Start with what was known on July 23, 2024. The information cutoff determines which published sources can support the starting state and assumptions.",
    inspect: "Check the cutoff, units, fiscal period, and measured or derived status. Open a source for net revenue to inspect the retained passage and original document.",
    optional: "View source opens an evidence dialog. Close it to continue, or exit the tour from inside the dialog.",
  },
  {
    id: "evidence", title: "Trace evidence into assumptions", to: DEMO_LINKS.evidence, target: "evidence-review",
    explanation: "Disclosures become structured observations. Review history retains the original extraction and effective reviewed values; supported mapping rules connect accepted evidence to parameters.",
    inspect: "Inspect the selected Booking room-nights observation from May 2024: its retained quote, review history, and mapping rationale. The queue is filtered to that eligible source; clear the filter to explore others.",
    optional: "You can inspect without saving. Saving a review or applying a rule is an explicit action; unsupported observations remain context.",
  },
  {
    id: "scenario", title: "Define a scenario", to: DEMO_LINKS.scenario, target: "scenario-definition",
    explanation: "Compare a calibrated baseline with an analyst-defined variant. Interventions change the business scenario; driver overrides are recorded assumptions and require a rationale.",
    inspect: "Inspect the default −10% cross-border mix shift, which conserves total payments volume. Check the driver ranges and Advanced settings: four quarters, 5,000 paths, and seed 22.",
    optional: "Run paired scenarios if you want to try your own assumptions. Next opens an existing comparison, so a new simulation is optional.",
  },
  {
    id: "comparison", title: "Compare the saved outcome", to: DEMO_LINKS.comparison, target: "saved-comparison",
    explanation: "These saved baseline and mix-shift runs use the same random draws. Differences are computed path by path, so the comparison isolates the scenario change under the model.",
    inspect: "Compare net-revenue fan charts and the variant-minus-baseline interval. Switch to payments volume to inspect conservation, then examine conditional attribution below.",
    optional: "Attribution is conditional on the model and its assumptions. It is not an empirical causal estimate.",
  },
  {
    id: "valuation", title: "Inspect valuation implications", to: DEMO_LINKS.valuation, target: "valuation-results",
    explanation: "The saved baseline feeds an earnings-and-multiple valuation bridge. The page separates operating uncertainty from valuation-multiple assumptions and shows illustrative action costs.",
    inspect: "Compare the earnings-driven and multiple-driven spreads, then inspect the action rule and each cost component. The outer envelope is not a probability interval.",
    optional: "The reference price is a quarterly buyback average. Interpret the action examples with that limitation in view.",
  },
  {
    id: "evaluation", title: "Assess performance", to: DEMO_LINKS.evaluation, target: "evaluation-results",
    explanation: "Saved evaluation artifacts compare forecasts with matched baselines across historical origins. These scores are separate from the six illustrative demonstration runs.",
    inspect: "Check the target, horizon, sample counts, errors, and interval coverage. Explore Ablations and Report & model for the failure case and methodological limits.",
    optional: "Changing selectors inspects saved reports; it does not run a new evaluation.",
  },
  {
    id: "prospective", title: "Inspect the prospective forecast", to: DEMO_LINKS.prospective, target: "prospective-results",
    explanation: "The frozen Q4 FY2026 registration was made before results were published. It remains unscored and is excluded from retrospective scores and sample counts.",
    inspect: "Check the evidence cutoff, actual registration time, forecast distributions, and frozen provenance. Distinguish the registered target from supporting quarters.",
    optional: "The registration is immutable. The report explains the procedure for scoring it when outcomes are available.",
  },
  {
    id: "replay", title: "Reproduce a result", to: DEMO_LINKS.replay, target: "replay-run",
    explanation: "Replay recomputes the selected demo baseline from pinned inputs without an LLM. Recorded hashes and runtime details make reproduction inspectable.",
    inspect: "Optionally click Replay saved run. An exact match has matching hashes; numerical equivalence means differences are within the existing 1e-9 tolerance despite different hashes.",
    optional: "Replay runs only when you click its button. Finishing the tour does not trigger computation.",
  },
]

export const TOUR_STORAGE_NAME = "longaeva.product-tour.v1"
export interface TourCheckpoint { version: 1; stepId: string; completed: boolean }
export interface TourState {
  mode: "closed" | "choose" | "active" | "complete"
  index: number
  checkpoint: TourCheckpoint | null
}
export type TourAction =
  | { type: "launch" }
  | { type: "start"; index: number }
  | { type: "exit" }
  | { type: "finish" }

export const stepIndex = (id: string) => TOUR_STEPS.findIndex((step) => step.id === id)

export function tourReducer(state: TourState, action: TourAction): TourState {
  if (action.type === "launch") return { ...state, mode: "choose" }
  if (action.type === "exit") return { ...state, mode: "closed" }
  if (action.type === "finish") {
    if (state.mode !== "active" || state.index !== TOUR_STEPS.length - 1) return state
    return { ...state, mode: "complete", checkpoint: { version: 1, stepId: TOUR_STEPS[state.index].id, completed: true } }
  }
  if (!Number.isInteger(action.index) || action.index < 0 || action.index >= TOUR_STEPS.length) return state
  return { mode: "active", index: action.index, checkpoint: { version: 1, stepId: TOUR_STEPS[action.index].id, completed: false } }
}

type TourStorage = Pick<Storage, "getItem" | "setItem">
export function readCheckpoint(storage: TourStorage): TourCheckpoint | null {
  try {
    const raw = storage.getItem(TOUR_STORAGE_NAME)
    if (!raw) return null
    const item = JSON.parse(raw) as Partial<TourCheckpoint>
    if (item?.version !== 1 || typeof item.stepId !== "string" || stepIndex(item.stepId) < 0 || typeof item.completed !== "boolean") return null
    return item as TourCheckpoint
  } catch { return null }
}
export function saveCheckpoint(storage: TourStorage, checkpoint: TourCheckpoint): boolean {
  try { storage.setItem(TOUR_STORAGE_NAME, JSON.stringify(checkpoint)); return true }
  catch { return false }
}

// Compare only the context a step needs. Observation selections and report
// filters remain usable; switching origin, saved pair, or section pauses guidance.
export function matchesTourRoute(step: TourStep, pathname: string, search: string): boolean {
  const destination = new URL(step.to, "http://longaeva.local")
  if (destination.pathname !== pathname) return false
  const params = new URLSearchParams(search)
  const defaults: Record<string, string> = { origin: DEMO.origin, tab: "state", section: "forecasts" }
  for (const [key, value] of destination.searchParams) {
    if (!["origin", "tab", "section", "run_id", "baseline_run_id"].includes(key)) continue
    if ((params.get(key) ?? defaults[key]) !== value) return false
  }
  if (pathname === "/state" && (params.get("tab") ?? "state") !== (destination.searchParams.get("tab") ?? "state")) return false
  if (step.id === "scenario" && (params.has("run_id") || params.has("baseline_run_id"))) return false
  return true
}
