import { afterEach, describe, expect, it, vi } from "vitest"
import type { ComparisonRow, ParameterSetRead, ParameterSpec } from "./api"
import {
  buildScenarioDraft,
  comparisonRows,
  defaultDraft,
  inputValue,
  intervalBand,
  modelValue,
  submitWorkspacePair,
} from "./scenarios"

const spec: ParameterSpec = {
  name: "payments_volume_growth",
  unit: "ratio",
  lower: -0.4,
  upper: 0.4,
  default: 0.08,
  role: "free",
  description: "Growth",
}
const base: ParameterSetRead = {
  id: "params",
  company: "visa",
  cutoff_ts: "2024-07-23T20:05:38Z",
  values: { payments_volume_growth: 0.08 },
  ranges: { payments_volume_growth: [0.02, 0.12] },
  evidence_links: {
    payments_volume_growth: {
      observation_ids: ["obs"],
      assumption: false,
      rationale: null,
    },
  },
  assumption_flags: {},
  content_hash: "hash",
  parent_id: null,
}
afterEach(() => vi.unstubAllGlobals())
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })

describe("scenario inputs", () => {
  it("converts percent controls without changing ratio controls", () => {
    expect(inputValue(spec.name, 0.08)).toBe("8")
    expect(modelValue(spec.name, "9.5")).toBe(0.095)
    expect(inputValue("activity_seasonal_q1", 1.04)).toBe("1.04")
    expect(modelValue("corr_demand_fx", "-0.2")).toBe(-0.2)
  })
  it("requires a rationale and preserves calibrated values for untouched fields", () => {
    const draft = { ...defaultDraft(), values: { [spec.name]: "10" } }
    expect(() => buildScenarioDraft(draft, base, [spec])).toThrow(
      "Explain the assumption",
    )
    draft.rationales[spec.name] = "Higher consumer spending"
    expect(buildScenarioDraft(draft, base, [spec]).overrides).toEqual({
      [spec.name]: { value: 0.1, rationale: "Higher consumer spending" },
    })
    expect(buildScenarioDraft(defaultDraft(), base, [spec]).overrides).toEqual(
      {},
    )
  })
  it.each(["", "NaN", "41"])("rejects invalid override %s", (value) => {
    expect(() =>
      buildScenarioDraft(
        { ...defaultDraft(), values: { [spec.name]: value } },
        base,
        [spec],
      ),
    ).toThrow("model bounds")
  })
  it("validates interventions and run bounds", () => {
    expect(() =>
      buildScenarioDraft({ ...defaultDraft(), mixChange: "-100" }, base, [
        spec,
      ]),
    ).toThrow("Mix change")
    expect(() =>
      buildScenarioDraft(
        { ...defaultDraft(), spend: true, reduction: "100" },
        base,
        [spec],
      ),
    ).toThrow("Spending reduction")
    expect(() =>
      buildScenarioDraft({ ...defaultDraft(), mixQuarter: "5" }, base, [spec]),
    ).toThrow("quarter")
    expect(() =>
      buildScenarioDraft({ ...defaultDraft(), paths: "1.5" }, base, [spec]),
    ).toThrow("integer")
    const built = buildScenarioDraft({ ...defaultDraft(), spend: true }, base, [
      spec,
    ])
    expect(built.interventions).toHaveLength(2)
    expect(built.seed).toBe(22)
    expect(built.n_paths).toBe(5000)
  })
})

describe("paired submission", () => {
  it("creates fresh grouped scenarios then submits shared run settings", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ id: "baseline" }))
      .mockResolvedValueOnce(response({ id: "variant" }))
      .mockResolvedValueOnce(response([{ id: "run-a" }, { id: "run-b" }], 202))
    vi.stubGlobal("fetch", fetchMock)
    await expect(
      submitWorkspacePair(defaultDraft(), base, [spec]),
    ).resolves.toHaveLength(2)
    const bodies = fetchMock.mock.calls.map((call) => JSON.parse(call[1].body))
    expect(bodies[0].pair_group_id).toBe(bodies[1].pair_group_id)
    expect(bodies[0].interventions).toEqual([])
    expect(bodies[1].interventions[0].cross_border_change).toBe(-0.1)
    expect(bodies[2]).toMatchObject({
      baseline_scenario_id: "baseline",
      scenario_ids: ["baseline", "variant"],
      seed: 22,
      n_paths: 5000,
      n_quarters: 4,
      cutoff_ts: base.cutoff_ts,
    })
  })
  it("does not submit runs after a scenario validation failure", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ id: "baseline" }))
      .mockResolvedValueOnce(response({ detail: "invalid correlation" }, 422))
    vi.stubGlobal("fetch", fetchMock)
    const draft = defaultDraft()
    await expect(submitWorkspacePair(draft, base, [spec])).rejects.toThrow(
      "invalid correlation",
    )
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(draft).toEqual(defaultDraft())
  })
})

it("uses saved difference quantiles and signed interval bounds", () => {
  const row: ComparisonRow = {
    metric: "net_revenue",
    quarter_index: 0,
    period_label: "FY2024Q4",
    baseline_mean: 100,
    variant_mean: 90,
    difference_mean: -10,
    difference_std: 5,
    difference_std_error: 1,
    quantiles: {
      "0.05": -30,
      "0.1": -20,
      "0.25": -15,
      "0.5": -10,
      "0.75": -5,
      "0.9": 0,
      "0.95": 4,
    },
    quantile_std_errors: {},
  }
  const fan = comparisonRows([row], row.metric)[0]
  expect(intervalBand(fan.p05, fan.p95)).toEqual([-30, 4])
  expect(intervalBand(fan.p25, fan.p75)).toEqual([-15, -5])
  expect(fan.mean).toBe(-10)
  expect(fan.p50).toBe(-10)
})
