import { existsSync, readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { DEMO, DEMO_LINKS, matchesTourRoute, readCheckpoint, saveCheckpoint, stepIndex, TOUR_STEPS, TOUR_STORAGE_NAME, tourReducer, type TourCheckpoint, type TourState } from "./tour"

const initial: TourState = { mode: "closed", index: 0, checkpoint: null }
const checkpoint: TourCheckpoint = { version: 1, stepId: "comparison", completed: false }
const storage = (value: string | null = null) => {
  const values = new Map<string, string>()
  if (value) values.set(TOUR_STORAGE_NAME, value)
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, text: string) => { values.set(key, text) } }
}

describe("tour checkpoints and transitions", () => {
  it("opens a choice without advancing; exit preserves the last checkpoint", () => {
    const active = tourReducer(initial, { type: "start", index: 3 })
    const closed = tourReducer(active, { type: "exit" })
    expect(closed).toEqual({ mode: "closed", index: 3, checkpoint })
    expect(tourReducer(closed, { type: "launch" })).toEqual({ ...closed, mode: "choose" })
    expect(tourReducer(closed, { type: "start", index: stepIndex(checkpoint.stepId) }).index).toBe(3)
    expect(tourReducer(closed, { type: "start", index: 0 }).checkpoint?.stepId).toBe("starting-point")
  })
  it("only finishes the final active step and rejects invalid destinations", () => {
    expect(tourReducer(initial, { type: "finish" })).toBe(initial)
    const first = tourReducer(initial, { type: "start", index: 0 })
    expect(tourReducer(first, { type: "finish" })).toBe(first)
    for (const index of [-1, 8, 0.5, NaN]) expect(tourReducer(first, { type: "start", index })).toBe(first)
    const last = tourReducer(first, { type: "start", index: 7 })
    const finished = tourReducer(last, { type: "finish" })
    expect(finished.mode).toBe("complete")
    expect(finished.checkpoint?.completed).toBe(true)
    expect(tourReducer(finished, { type: "start", index: 0 }).checkpoint?.completed).toBe(false)
  })
  it("round-trips a checkpoint without automatically opening after reload", () => {
    const local = storage()
    expect(saveCheckpoint(local, checkpoint)).toBe(true)
    expect(readCheckpoint(local)).toEqual(checkpoint)
    expect({ ...initial, checkpoint: readCheckpoint(local) }.mode).toBe("closed")
  })
  it("handles corrupt, obsolete, unknown, and disabled storage", () => {
    for (const value of ["broken", "null", "{}", JSON.stringify({ ...checkpoint, version: 2 }), JSON.stringify({ ...checkpoint, stepId: "deleted" }), JSON.stringify({ ...checkpoint, completed: "false" })]) expect(readCheckpoint(storage(value))).toBeNull()
    const denied = { getItem: () => { throw new Error("disabled") }, setItem: () => { throw new Error("disabled") } }
    expect(readCheckpoint(denied)).toBeNull()
    expect(saveCheckpoint(denied, checkpoint)).toBe(false)
  })
})

describe("tour route context", () => {
  it("matches every canonical destination and keeps paths relative", () => {
    expect(new Set(TOUR_STEPS.map((step) => step.id)).size).toBe(8)
    expect(new Set(TOUR_STEPS.map((step) => step.target)).size).toBe(8)
    for (const step of TOUR_STEPS) {
      const url = new URL(step.to, "http://longaeva.local")
      expect(matchesTourRoute(step, url.pathname, url.search)).toBe(true)
      expect(matchesTourRoute(step, "/guide", url.search)).toBe(false)
    }
    for (const path of Object.values(DEMO_LINKS)) expect(path.startsWith("/")).toBe(true)
  })
  it("allows exploring observations and selectors without losing the step", () => {
    expect(matchesTourRoute(TOUR_STEPS[1], "/state", `?origin=${DEMO.origin}&tab=evidence&observation=test&review_company=booking`)).toBe(true)
    expect(matchesTourRoute(TOUR_STEPS[5], "/evaluation", "?section=forecasts&target=service_revenue&horizon=4q")).toBe(true)
    expect(matchesTourRoute(TOUR_STEPS[0], "/state", "")).toBe(true)
  })
  it("pauses when the origin, view, section, or selected saved run changes", () => {
    expect(matchesTourRoute(TOUR_STEPS[0], "/state", "?origin=2025-10-28")).toBe(false)
    expect(matchesTourRoute(TOUR_STEPS[0], "/state", "?tab=evidence")).toBe(false)
    expect(matchesTourRoute(TOUR_STEPS[2], "/scenarios", "?run_id=new&baseline_run_id=other")).toBe(false)
    expect(matchesTourRoute(TOUR_STEPS[3], "/scenarios", `?origin=${DEMO.origin}&baseline_run_id=${DEMO.baselineId}&run_id=other`)).toBe(false)
    expect(matchesTourRoute(TOUR_STEPS[5], "/evaluation", "?section=ablations")).toBe(false)
    expect(matchesTourRoute(TOUR_STEPS[7], "/replay", "?run_id=other")).toBe(false)
  })
})

// A frontend-only Docker build has no package data directory. The complete
// package and standalone-export checks run this assertion with the actual seed.
const manifestPath = new URL("../../../data/demo/manifest.json", import.meta.url)
it.skipIf(!existsSync(manifestPath))("guide links select the packaged, succeeded, paired mix-shift runs", () => {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  expect(manifest.origins).toContain(DEMO.origin)
  expect(manifest.links.some((link: { path: string }) => link.path === DEMO_LINKS.comparison)).toBe(true)
  const baseline = manifest.tables.run.find((run: { id: string }) => run.id === DEMO.baselineId)
  const variant = manifest.tables.run.find((run: { id: string }) => run.id === DEMO.mixShiftId)
  expect(baseline.status).toBe("succeeded")
  expect(variant.status).toBe("succeeded")
  expect(variant.baseline_run_id).toBe(DEMO.baselineId)
  expect(variant.interventions[0]).toMatchObject({ type: "mix_shift_conserving_total", cross_border_change: -0.1 })
  const observation = manifest.tables.observation.find((row: { id: string }) => row.id === DEMO.bookingObservationId)
  expect(observation).toMatchObject({ company: "booking", source_id: DEMO.bookingSourceId, activity_type: "room_nights" })
  const source = manifest.tables.source.find((row: { id: string }) => row.id === DEMO.bookingSourceId)
  expect(source.publication_ts.slice(0, 10) <= DEMO.origin).toBe(true)
})
