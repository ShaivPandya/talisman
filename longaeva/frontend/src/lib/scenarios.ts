import {
  createPairRuns,
  createScenario,
  type ComparisonRow,
  type Intervention,
  type ParameterSetRead,
  type ParameterSpec,
  type RunRead,
  type ScenarioCreate,
} from "./api"
import { toFanRows } from "./runs"

export interface ScenarioDraft {
  name: string
  values: Record<string, string>
  rationales: Record<string, string>
  mix: boolean
  mixChange: string
  mixQuarter: string
  spend: boolean
  reduction: string
  spendQuarter: string
  seed: string
  paths: string
}

export const defaultDraft = (): ScenarioDraft => ({
  name: "Mix shift",
  values: {},
  rationales: {},
  mix: true,
  mixChange: "-10",
  mixQuarter: "1",
  spend: false,
  reduction: "5",
  spendQuarter: "1",
  seed: "22",
  paths: "5000",
})

export function isPercentParameter(name: string): boolean {
  return (
    !name.startsWith("corr_") &&
    !name.includes("seasonal") &&
    name !== "international_fx_sensitivity"
  )
}
export const inputValue = (name: string, value: number): string =>
  String(Number((value * (isPercentParameter(name) ? 100 : 1)).toPrecision(12)))
export const modelValue = (name: string, value: string): number =>
  Number(value) / (isPercentParameter(name) ? 100 : 1)

export function buildScenarioDraft(
  draft: ScenarioDraft,
  base: ParameterSetRead,
  specs: ParameterSpec[],
) {
  if (!draft.name.trim()) throw new Error("Enter a scenario name.")
  const seed = integer(draft.seed, 0, 2 ** 31 - 1, "Seed")
  const n_paths = integer(draft.paths, 1, 50000, "Paths")
  const overrides: ScenarioCreate["parameter_overrides"] = {}
  for (const spec of specs) {
    const raw = draft.values[spec.name]
    if (
      raw === undefined ||
      raw === inputValue(spec.name, base.values[spec.name])
    )
      continue
    const value = modelValue(spec.name, raw)
    if (
      !raw.trim() ||
      !Number.isFinite(value) ||
      value < spec.lower ||
      value > spec.upper
    ) {
      throw new Error(
        `${spec.name.replaceAll("_", " ")}: enter a value within the model bounds.`,
      )
    }
    if (value === base.values[spec.name]) continue
    const rationale = draft.rationales[spec.name]?.trim()
    if (!rationale)
      throw new Error(
        `Explain the assumption for ${spec.name.replaceAll("_", " ")}.`,
      )
    overrides[spec.name] = { value, rationale }
  }
  const interventions: Intervention[] = []
  if (draft.mix) {
    const change = Number(draft.mixChange) / 100
    if (
      !draft.mixChange.trim() ||
      !Number.isFinite(change) ||
      change <= -1 ||
      change > 3
    )
      throw new Error("Mix change must be greater than −100% and at most 300%.")
    interventions.push({
      type: "mix_shift_conserving_total",
      cross_border_change: change,
      start_quarter: integer(draft.mixQuarter, 1, 4, "Mix start quarter"),
    })
  }
  if (draft.spend) {
    const reduction = Number(draft.reduction) / 100
    if (
      !draft.reduction.trim() ||
      !Number.isFinite(reduction) ||
      reduction <= 0 ||
      reduction >= 1
    )
      throw new Error(
        "Spending reduction must be greater than 0% and less than 100%.",
      )
    interventions.push({
      type: "total_spend_reduction",
      reduction,
      start_quarter: integer(
        draft.spendQuarter,
        1,
        4,
        "Spending start quarter",
      ),
    })
  }
  return { overrides, interventions, seed, n_paths }
}

function integer(
  raw: string,
  low: number,
  high: number,
  label: string,
): number {
  const value = Number(raw)
  if (!raw.trim() || !Number.isInteger(value) || value < low || value > high)
    throw new Error(`${label} must be an integer from ${low} to ${high}.`)
  return value
}

export async function submitWorkspacePair(
  draft: ScenarioDraft,
  base: ParameterSetRead,
  specs: ParameterSpec[],
): Promise<RunRead[]> {
  const parsed = buildScenarioDraft(draft, base, specs)
  const common = {
    company: base.company,
    parameter_set_id: base.id,
    pair_group_id: crypto.randomUUID(),
  }
  const baseline = await createScenario({
    ...common,
    name: "Calibrated baseline",
    interventions: [],
    parameter_overrides: {},
  })
  const variant = await createScenario({
    ...common,
    name: draft.name.trim(),
    interventions: parsed.interventions,
    parameter_overrides: parsed.overrides,
  })
  return createPairRuns({
    scenario_ids: [baseline.id, variant.id],
    baseline_scenario_id: baseline.id,
    cutoff_ts: base.cutoff_ts,
    seed: parsed.seed,
    n_paths: parsed.n_paths,
    n_quarters: 4,
  })
}

export function comparisonRows(rows: ComparisonRow[], metric: string) {
  return toFanRows(
    rows.map((row) => ({
      ...row,
      mean: row.difference_mean,
      std: row.difference_std,
      std_error: row.difference_std_error,
    })),
    metric,
  )
}

export function intervalBand(low: number, high: number): [number, number] {
  return [low, high]
}
export const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "Request failed"
