import { TRANSFORMS } from "@/lib/graphFundamentals"
import type { ChartSeries, FundamentalField } from "@/lib/graphFundamentals"

const selectClass = "w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs"
export function SeriesEditor({
  series,
  fields,
  onChange,
  onRemove,
  onMove,
  panes,
  paneId,
}: {
  series: ChartSeries
  fields: FundamentalField[]
  onChange: (patch: Partial<ChartSeries>) => void
  onRemove: () => void
  onMove: (paneId: string) => void
  panes: { id: string; label: string }[]
  paneId: string
}) {
  const field = fields.find((f) => f.id === series.field)
  const estimateReason = !field?.estimates
    ? "Only EPS and revenue have yfinance consensus coverage."
    : "Consensus covers supplied quarters/years only."
  return (
    <details className="rounded-lg border border-border bg-surface/50">
      <summary className="flex cursor-pointer items-center gap-2 p-2 text-xs">
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: series.color }} />
        <span className="min-w-0 flex-1 truncate">
          {series.label ||
            (series.operation ? "Calculated series" : `${series.ticker} · ${field?.label ?? series.field}`)}
        </span>
        <span aria-hidden="true" className="text-muted">
          Edit
        </span>
      </summary>
      <div className="space-y-2 border-t border-border p-2">
        <label className="block text-xs text-muted">
          Label
          <input
            className={selectClass}
            value={series.label}
            maxLength={160}
            placeholder={series.ticker ?? "Calculated series"}
            onChange={(e) => onChange({ label: e.target.value })}
          />
        </label>
        {!series.operation ? (
          <label className="block text-xs text-muted">
            Field
            <select
              className={selectClass}
              value={series.field}
              onChange={(e) => onChange({ field: e.target.value, estimates: false })}
            >
              {fields.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-muted">
            Colour
            <input
              aria-label={`Colour ${series.ticker ?? "series"}`}
              className="block h-8 w-full"
              type="color"
              value={series.color}
              onChange={(e) => onChange({ color: e.target.value })}
            />
          </label>
          <label className="text-xs text-muted">
            Width
            <select
              className={selectClass}
              value={series.width}
              onChange={(e) => onChange({ width: Number(e.target.value) })}
            >
              {[1, 2, 3, 4, 5].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-muted">
            Visualization
            <select
              className={selectClass}
              value={series.visualization}
              onChange={(e) => onChange({ visualization: e.target.value as ChartSeries["visualization"] })}
            >
              <option value="line">Line</option>
              <option value="bar">Bar</option>
            </select>
          </label>
          <label className="text-xs text-muted">
            Style
            <select
              className={selectClass}
              value={series.style}
              onChange={(e) => onChange({ style: e.target.value as ChartSeries["style"] })}
            >
              <option value="solid">Solid</option>
              <option value="dashed">Dashed</option>
            </select>
          </label>
        </div>
        <label className="block text-xs text-muted">
          Transform
          <select
            className={selectClass}
            value={series.transform}
            onChange={(e) => onChange({ transform: e.target.value as ChartSeries["transform"] })}
          >
            {TRANSFORMS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          Pane
          <select className={selectClass} value={paneId} onChange={(e) => onMove(e.target.value)}>
            {panes.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
            <option value="new">New pane</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs" title={estimateReason}>
          <input
            type="checkbox"
            checked={series.estimates}
            disabled={!field?.estimates || !!series.operation}
            onChange={(e) => onChange({ estimates: e.target.checked })}
          />
          Include consensus estimates
        </label>
        <p className="text-[10px] text-muted">{estimateReason}</p>
        {field ? <p className="text-[10px] text-muted">{field.formula}</p> : null}
        <button className="text-xs text-red-400 hover:underline" onClick={onRemove}>
          Remove series
        </button>
      </div>
    </details>
  )
}
