// Accent colors live in index.css as [data-accent="<id>"] rules for light and dark mode.
// Keep this list and those rules in sync.
export const ACCENT_PRESETS = [
  { id: "blue", label: "Blue" },
  { id: "indigo", label: "Indigo" },
  { id: "violet", label: "Violet" },
  { id: "teal", label: "Teal" },
  { id: "green", label: "Green" },
  { id: "orange", label: "Orange" },
  { id: "rose", label: "Rose" },
  { id: "graphite", label: "Graphite" },
] as const

export type AccentId = (typeof ACCENT_PRESETS)[number]["id"]

export const DEFAULT_ACCENT: AccentId = "blue"

export function isAccentId(value: unknown): value is AccentId {
  return ACCENT_PRESETS.some(preset => preset.id === value)
}
