import * as RadioGroup from "@radix-ui/react-radio-group"
import { Check, Eye } from "lucide-react"

import { NAV_SECTIONS } from "@/components/layout/navSections"
import { SegmentedControl, Toggle } from "@/components/shared/FormControls"
import { PageHeader } from "@/components/shared/PageHeader"
import { SurfaceCard } from "@/components/shared/SurfaceCard"
import { usePersonalization } from "@/contexts/PersonalizationContext"
import { useTheme, type ThemePreference } from "@/contexts/ThemeContext"
import { ACCENT_PRESETS, isAccentId } from "@/lib/accentPresets"

const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
]

export function PersonalizationSettings() {
  const { theme, setTheme } = useTheme()
  const {
    accent,
    setAccent,
    hiddenPaths,
    togglePageHidden,
    showAllPages,
    sidebarCollapsed,
    setSidebarCollapsed,
  } = usePersonalization()

  return (
    <div className="max-w-4xl space-y-4">
      <PageHeader
        title="Personalization"
        subtitle="Appearance and navigation preferences. Saved on this device only."
      />

      <SurfaceCard className="p-5">
        <h2 className="section-title">Theme</h2>
        <p className="mt-1 text-xs text-muted">System follows your device's light or dark setting.</p>
        <div className="mt-4">
          <SegmentedControl options={THEME_OPTIONS} value={theme} onChange={setTheme} />
        </div>
      </SurfaceCard>

      <SurfaceCard className="p-5">
        <h2 id="accent-color-heading" className="section-title">Accent color</h2>
        <p className="mt-1 text-xs text-muted">
          Used for primary buttons, links, focus rings, and the active page in the sidebar.
        </p>
        <RadioGroup.Root
          value={accent}
          onValueChange={value => {
            if (isAccentId(value)) setAccent(value)
          }}
          aria-labelledby="accent-color-heading"
          className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4"
        >
          {ACCENT_PRESETS.map(preset => (
            // data-accent scopes the preset's tokens to this swatch (see index.css).
            <RadioGroup.Item
              key={preset.id}
              value={preset.id}
              data-accent={preset.id}
              className="flex min-h-11 items-center gap-3 rounded-[var(--radius-md)] border border-app bg-card-muted px-3 py-2 text-left text-sm font-medium text-app transition-colors hover:bg-hover data-[state=checked]:border-[hsl(var(--accent))] data-[state=checked]:bg-[hsl(var(--accent-muted))]"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]">
                <RadioGroup.Indicator>
                  <Check size={14} strokeWidth={3} aria-hidden="true" />
                </RadioGroup.Indicator>
              </span>
              {preset.label}
            </RadioGroup.Item>
          ))}
        </RadioGroup.Root>
      </SurfaceCard>

      <SurfaceCard className="p-5">
        <h2 className="section-title">Sidebar</h2>
        <div className="mt-3">
          <Toggle
            label="Collapse sidebar to icons"
            description="Shows an icon rail with tooltips on desktop. The phone menu always shows labels."
            checked={sidebarCollapsed}
            onChange={setSidebarCollapsed}
          />
        </div>
      </SurfaceCard>

      <SurfaceCard className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="section-title">Sidebar pages</h2>
            <p className="mt-1 text-xs text-muted">
              Hidden pages stay available from page search (Cmd J). Personalization is always shown.
            </p>
          </div>
          <button
            type="button"
            onClick={showAllPages}
            disabled={hiddenPaths.size === 0}
            className="theme-button-base theme-button-secondary px-3 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Eye size={15} aria-hidden="true" />
            Show all
          </button>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {NAV_SECTIONS.map(section => (
            <div key={section.label} className="theme-surface-muted px-3 py-3">
              <p className="label-text mb-1">{section.label}</p>
              {section.pages.map(page => (
                <Toggle
                  key={page.path}
                  label={page.label}
                  description={page.locked ? "Always shown" : undefined}
                  checked={!hiddenPaths.has(page.path)}
                  disabled={page.locked}
                  onChange={() => togglePageHidden(page.path)}
                />
              ))}
            </div>
          ))}
        </div>
      </SurfaceCard>
    </div>
  )
}
