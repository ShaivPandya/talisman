import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { Dialog } from "@/components/shared/Dialog"
import { TextInput, Toggle } from "@/components/shared/FormControls"
import { Notice } from "@/components/shared/Notice"
import {
  resetIdeaScanSettings,
  saveIdeaScanSettings,
  type IdeaScanPreset,
  type IdeaScanSettings,
  type IdeaScanUniverse,
} from "@/lib/api"
import { DEFAULT_LIQUIDITY_COVERAGE } from "@/lib/ideaDigest"

const UNIVERSES: { value: IdeaScanUniverse; label: string }[] = [
  { value: "sp500", label: "S&P 500" },
  { value: "sp400", label: "S&P 400" },
  { value: "sp600", label: "S&P 600" },
  { value: "russell2000", label: "Russell 2000" },
]

const SCREEN_LABELS: Record<IdeaScanPreset["screen"], string> = {
  long_screen: "Long screen",
  short_screen: "Short screen",
  quality_value: "Quality + valuation",
  value_momentum: "Value + momentum + quality",
  composite_top: "Composite ranker, top",
  breakdown: "Price momentum + revisions, bottom",
  liquid_covered: "Liquidity + analyst coverage",
}

type ConfigKey = keyof IdeaScanSettings["config"]
const CONFIG_FIELDS: { key: ConfigKey; label: string; helper: string }[] = [
  { key: "max_reviews", label: "Names reviewed per run", helper: "Across all presets" },
  { key: "max_cost_usd", label: "Budget per run (USD)", helper: "Reviews stop before this is exceeded" },
  { key: "review_web_searches", label: "Web searches per review", helper: "" },
  { key: "macro_web_searches", label: "Web searches for the macro view", helper: "" },
]

interface Draft {
  settings: IdeaScanSettings
  advanced: Record<string, string>
}

function toDraft(settings: IdeaScanSettings): Draft {
  return {
    settings: structuredClone(settings),
    advanced: Object.fromEntries(
      settings.presets.map(p => [p.id, JSON.stringify({ params: p.params, weights: p.weights }, null, 2)]),
    ),
  }
}

interface PresetSettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  settings: IdeaScanSettings
}

export function PresetSettingsDialog({ open, onOpenChange, settings }: PresetSettingsDialogProps) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(() => toDraft(settings))
  const [jsonError, setJsonError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: saveIdeaScanSettings,
    onSuccess: data => {
      queryClient.setQueryData(["idea-scan", "settings"], (current: { defaults: IdeaScanSettings } | undefined) => ({
        ...current,
        settings: data.settings,
      }))
      onOpenChange(false)
    },
  })
  const reset = useMutation({
    mutationFn: resetIdeaScanSettings,
    onSuccess: data => {
      queryClient.setQueryData(["idea-scan", "settings"], (current: { defaults: IdeaScanSettings } | undefined) => ({
        ...current,
        settings: data.settings,
      }))
      setDraft(toDraft(data.settings))
    },
  })

  function updatePreset(id: string, change: Partial<IdeaScanPreset>) {
    setDraft(current => ({
      ...current,
      settings: {
        ...current.settings,
        presets: current.settings.presets.map(p => (p.id === id ? { ...p, ...change } : p)),
      },
    }))
  }

  function submit() {
    setJsonError(null)
    const presets: IdeaScanPreset[] = []
    for (const preset of draft.settings.presets) {
      try {
        const parsed = JSON.parse(draft.advanced[preset.id] ?? "{}") as Partial<IdeaScanPreset>
        presets.push({ ...preset, params: parsed.params ?? preset.params, weights: parsed.weights ?? preset.weights })
      } catch {
        setJsonError(`${preset.name}: the advanced settings aren't valid JSON.`)
        return
      }
    }
    save.mutate({ ...draft.settings, presets })
  }

  const error = jsonError ?? (save.error as Error | null)?.message ?? (reset.error as Error | null)?.message ?? null

  return (
    <Dialog
      open={open}
      onOpenChange={next => {
        if (next) setDraft(toDraft(settings))
        onOpenChange(next)
      }}
      title="Idea scan presets"
      description="Changes apply from the next run. Each preset is screened against the same weekly data set."
    >
      <div className="space-y-6">
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {CONFIG_FIELDS.map(field => (
            <TextInput
              key={field.key}
              id={`idea-scan-${field.key}`}
              label={field.label}
              type="number"
              helperText={field.helper || undefined}
              value={String(draft.settings.config[field.key])}
              onChange={value =>
                setDraft(current => ({
                  ...current,
                  settings: { ...current.settings, config: { ...current.settings.config, [field.key]: Number(value) } },
                }))
              }
            />
          ))}
        </section>

        <section className="space-y-4">
          {draft.settings.presets.map(preset => (
            <div key={preset.id} className="rounded-xl border border-app/70 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-app">{preset.name}</p>
                  <p className="text-xs text-subtle">
                    {preset.direction === "long" ? "Long" : "Short"} · {SCREEN_LABELS[preset.screen]}
                  </p>
                </div>
                <Toggle label="Enabled" checked={preset.enabled} onChange={enabled => updatePreset(preset.id, { enabled })} />
              </div>
              <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <TextInput
                  id={`preset-name-${preset.id}`}
                  label="Name"
                  value={preset.name}
                  onChange={name => updatePreset(preset.id, { name })}
                />
                <TextInput
                  id={`preset-max-${preset.id}`}
                  label="Maximum names"
                  type="number"
                  value={String(preset.max_names)}
                  onChange={value => updatePreset(preset.id, { max_names: Number(value) })}
                />
              </div>
              {preset.screen !== "liquid_covered" && (
                <div className="mt-3 grid grid-cols-1 items-end gap-4 sm:grid-cols-2">
                  <Toggle
                    label="Only liquid, well-covered names"
                    checked={preset.liquidity_coverage != null}
                    onChange={on => updatePreset(preset.id, { liquidity_coverage: on ? DEFAULT_LIQUIDITY_COVERAGE : null })}
                  />
                  {preset.liquidity_coverage && (
                    <TextInput
                      id={`preset-liquidity-${preset.id}`}
                      label="Dollar volume, min. percentile in industry"
                      type="number"
                      helperText="Analyst count must also be above the industry median"
                      value={String(Math.round(preset.liquidity_coverage.min_dollar_volume_industry_pct * 100))}
                      onChange={value =>
                        updatePreset(preset.id, {
                          liquidity_coverage: {
                            ...DEFAULT_LIQUIDITY_COVERAGE,
                            ...preset.liquidity_coverage,
                            min_dollar_volume_industry_pct: Number(value) / 100,
                          },
                        })
                      }
                    />
                  )}
                </div>
              )}
              <fieldset className="mt-3">
                <legend className="theme-field-label">Universes</legend>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-2">
                  {UNIVERSES.map(universe => (
                    <label key={universe.value} className="flex min-h-9 items-center gap-2 text-sm text-app">
                      <input
                        type="checkbox"
                        checked={preset.universes.includes(universe.value)}
                        onChange={event =>
                          updatePreset(preset.id, {
                            universes: event.target.checked
                              ? [...preset.universes, universe.value]
                              : preset.universes.filter(u => u !== universe.value),
                          })
                        }
                      />
                      {universe.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-muted">Screen parameters and ranking weights</summary>
                <textarea
                  aria-label={`${preset.name} advanced settings`}
                  className="theme-input mt-2 h-48 w-full font-mono text-xs"
                  spellCheck={false}
                  value={draft.advanced[preset.id] ?? ""}
                  onChange={event =>
                    setDraft(current => ({ ...current, advanced: { ...current.advanced, [preset.id]: event.target.value } }))
                  }
                />
              </details>
            </div>
          ))}
        </section>

        {error && <Notice tone="error">{error}</Notice>}

        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            className="theme-button-base theme-button-ghost px-4"
            onClick={() => reset.mutate()}
            disabled={reset.isPending || save.isPending}
          >
            Reset to defaults
          </button>
          <button
            type="button"
            className="theme-button-base theme-button-primary px-4"
            onClick={submit}
            disabled={save.isPending || reset.isPending}
          >
            {save.isPending ? "Saving…" : "Save presets"}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
