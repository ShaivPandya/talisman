import { memo } from "react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { formatValue, mixedCurrencies, paneIssue, panePlotData } from "@/lib/graphFundamentals"
import type { DisplaySeries, Period } from "@/lib/graphFundamentals"

function FundamentalTooltip({ active, label, series }: { active?: boolean; label: string; series: DisplaySeries[] }) {
  if (!active) return null
  return (
    <div className="max-w-sm rounded-lg border border-border bg-surface p-3 text-xs shadow-xl">
      <p className="mb-2 font-semibold">{label}</p>
      {series.map((s) => {
        const point = s.points.find((p) => p.date === label)
        if (!point) return null
        return (
          <div key={s.config.id} className="mb-2 last:mb-0">
            <p style={{ color: s.config.color }}>
              {s.label}: <strong>{formatValue(point.value, s.unit, s.currency)}</strong>
              {point.estimate ? " · Estimate" : ""}
            </p>
            <p className="text-muted">
              {point.period_label} · {point.source ?? s.source ?? "Unavailable"}
            </p>
            {point.estimate ? (
              <p className="text-muted">
                {point.analysts ?? "Unknown"} analysts · Observed {point.as_of?.slice(0, 10) ?? "unknown"}
                <br />
                {point.basis}
              </p>
            ) : (
              <p className="text-muted">
                {point.filed ? `Filed ${point.filed}` : "Filing date unavailable"} · Fetched{" "}
                {s.as_of?.slice(0, 10) ?? "unknown"}
              </p>
            )}
            {point.source_period_end && point.source_period_end !== point.date ? (
              <p className="text-muted">
                Provider period end {point.source_period_end}; aligned to this fiscal period.
              </p>
            ) : null}
            {point.reason ? <p className="text-amber-500">{point.reason}</p> : null}
          </div>
        )
      })}
    </div>
  )
}

export const FundamentalPane = memo(function FundamentalPane({
  title,
  series,
  dates,
  syncId,
  bottom,
  period,
}: {
  title: string
  series: DisplaySeries[]
  dates: string[]
  syncId: string
  bottom: boolean
  period: Period
}) {
  const issue = paneIssue(series)
  if (issue)
    return (
      <section className="rounded-xl border border-border bg-surface p-4">
        <h2 className="font-semibold">{title}</h2>
        <p role="alert" className="mt-2 text-sm text-amber-500">
          {issue}
        </p>
      </section>
    )
  const { rows, lines } = panePlotData(series, dates, period)
  const visible = new Set(dates)
  const unavailable = series.filter((s) => !s.points.some((p) => p.value !== null && visible.has(p.date)))
  const unit = series[0]?.unit ?? "ratio"
  const currencies = [...new Set(series.map((s) => s.currency).filter(Boolean))]
  return (
    <section className="min-w-0 rounded-xl border border-border bg-surface p-4" aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-muted">
          {currencies.join(" / ") ||
            (unit === "percent" ? "%" : unit === "ratio" ? "Ratio" : unit === "index" ? "Index" : unit)}
        </span>
      </div>
      {mixedCurrencies(series) ? (
        <p role="status" className="mb-2 text-xs text-amber-500">
          Mixed reported currencies: {currencies.join(", ")}. Values have not been converted.
        </p>
      ) : null}
      {unavailable.length ? (
        <div className="mb-2 text-xs text-amber-500">
          {unavailable.map((s) => (
            <p key={s.config.id}>
              {s.label}: {s.reason ?? "No comparable data in this range."}
            </p>
          ))}
        </div>
      ) : null}
      {rows.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted">No observations in this range.</p>
      ) : (
        <ResponsiveContainer width="100%" height={bottom ? 265 : 240}>
          <ComposedChart
            data={rows}
            syncId={syncId}
            syncMethod="value"
            margin={{ top: 8, right: 12, left: 14, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" vertical={false} />
            <XAxis
              dataKey="date"
              hide={!bottom}
              minTickGap={55}
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              tickFormatter={(v) => `${String(v).slice(0, 4)} Q${Math.ceil(Number(String(v).slice(5, 7)) / 3)}`}
            />
            <YAxis
              width={68}
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              tickFormatter={(v) => formatValue(Number(v), unit)}
              domain={["auto", "auto"]}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              content={(props) => (
                <FundamentalTooltip active={props.active} label={String(props.label ?? "")} series={series} />
              )}
            />
            <ReferenceLine y={0} stroke="hsl(var(--chart-axis))" strokeDasharray="3 3" />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {series
              .filter((s) => s.config.visualization === "bar")
              .map((s) => (
                <Bar
                  key={s.config.id}
                  dataKey={s.config.id}
                  name={s.label}
                  fill={s.config.color}
                  maxBarSize={20}
                  isAnimationActive={false}
                />
              ))}
            {lines.map((line) => (
              <Line
                key={line.key}
                type="linear"
                dataKey={line.key}
                name={line.estimate ? `${line.series.label} consensus` : line.series.label}
                stroke={line.series.config.color}
                strokeWidth={line.series.config.width}
                strokeDasharray={line.estimate ? "3 4" : line.series.config.style === "dashed" ? "6 4" : undefined}
                dot={line.estimate ? { r: 2 } : line.points.length === 1 ? { r: 3 } : false}
                legendType={line.showLegend ? "line" : "none"}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      )}
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted">
        {series.map((s) => (
          <span key={s.config.id} title={s.formula}>
            {s.label}: {s.source ?? "Unavailable"}
            {s.formula ? " · calculated/defined in field details" : ""}
          </span>
        ))}
      </div>
    </section>
  )
})
