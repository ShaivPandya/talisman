import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useApiQuery } from "@/hooks/useApiQuery"
import { fetchEconomicBackdrop, type EconomicReading } from "@/lib/api"
import { ErrorMessage, LoadingSpinner } from "@/components/shared/LoadingSpinner"
import { RefreshButton } from "@/components/shared/RefreshButton"

function ReadingTable({ readings }: { readings: EconomicReading[] }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-xs">
    <thead><tr className="border-b border-app text-muted"><th className="p-3">Indicator</th><th className="p-3">Value / unit</th><th className="p-3">As of</th><th className="p-3">Period / vintage</th><th className="p-3">Source</th></tr></thead>
    <tbody>{readings.map(row => <tr key={row.key} className="border-b border-app align-top">
      <td className="max-w-sm p-3"><span className="font-medium">{row.label}</span>
        {row.note ? <p className="mt-1 text-muted">{row.note}</p> : null}
        {row.next_release_note ? <p className="mt-1 text-muted">Next release: {row.next_release_note}</p> : null}</td>
      <td className="p-3"><span className="font-medium tabular-nums">{row.value == null ? "Missing" : row.value.toLocaleString(undefined, { maximumFractionDigits: 3 })}</span>
        <p className="mt-1 text-muted">{row.unit}</p>{row.status !== "ok" ? <p className="mt-1 text-muted">{row.status.replace(/_/g, " ")}</p> : null}</td>
      <td className="whitespace-nowrap p-3">{row.as_of ?? "Not reported"}</td>
      <td className="p-3">{row.forecast_period ?? "Observation"}
        {row.vintage ? <p className="mt-1">{row.vintage}</p> : null}
        {row.vintage_date ? <p className="mt-1 text-muted">{row.vintage_date_kind ?? "Publisher vintage"}: {row.vintage_date}</p> : null}</td>
      <td className="p-3"><a className="text-accent underline" target="_blank" rel="noreferrer" href={row.source_url}>Official source</a></td>
    </tr>)}</tbody>
  </table></div>
}

export function EconomicBackdrop() {
  const queryClient = useQueryClient()
  const [country, setCountry] = useState("US")
  const { data, isLoading, error } = useApiQuery(["economic-backdrop"], fetchEconomicBackdrop)
  const rows = data?.readings ?? []
  const activity = rows.filter(row => row.kind === "observation")
  const forecasts = rows.filter(row => row.kind !== "observation" && (!row.country || row.country === country))
  const countries = [...new Set(rows.flatMap(row => row.country ? [row.country] : []))]
  return <section className="mb-6 rounded-xl border border-app bg-card p-4" aria-label="Economic activity and published forecasts">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">Economic activity and published forecasts</h2>
      <p className="mt-1 text-sm text-muted">Publisher forecasts and US activity alongside market returns. The market-stress regime is calculated separately.</p></div>
      <RefreshButton onRefresh={async () => { queryClient.setQueryData(["economic-backdrop"], await fetchEconomicBackdrop({ force_refresh: true })) }} queryKeys={[["economic-backdrop"]]} /></div>
    {isLoading ? <LoadingSpinner message="Fetching economic backdrop..." /> : null}
    {error ? <ErrorMessage message={String(error)} /> : null}
    {data ? <>
      <h3 className="mb-2 text-sm font-semibold">US activity, housing and credit</h3><ReadingTable readings={activity} />
      <div className="mb-2 mt-6 flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-semibold">Published nowcasts and IMF forecasts</h3>
        {countries.length ? <label className="text-sm">IMF country<select aria-label="IMF forecast country" className="ml-2 rounded border border-app bg-card p-2" value={country} onChange={event => setCountry(event.target.value)}>
          {countries.map(name => <option key={name} value={name}>{name}</option>)}</select></label> : null}</div>
      <ReadingTable readings={forecasts} />
      <p className="mt-3 text-xs text-muted">{data.note} Retrieved: {data.fetched_at}</p>
    </> : null}
  </section>
}
