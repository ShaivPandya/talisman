import { useQuery } from "@tanstack/react-query"
import { fetchIbkrFlexStatus } from "@/lib/api"

function money(value: number | null | undefined, currency = "USD") {
  if (value == null) return "—"
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value)
  } catch {
    return `${value.toLocaleString()} ${currency}`
  }
}

export function IbkrFlexStatusPanel() {
  const query = useQuery({ queryKey: ["ibkr-flex-status"], queryFn: fetchIbkrFlexStatus, staleTime: 30_000, refetchInterval: 60_000 })
  if (query.isPending) return <p className="text-sm text-muted mb-4">Loading broker sync status…</p>
  if (query.error) return <p role="status" className="theme-notice theme-notice-error mb-4">Broker sync status unavailable. {String(query.error)}</p>
  const data = query.data
  if (!data) return null
  const warning = data.status !== "ok"
  return (
    <section aria-label="IBKR Flex sync" className={`theme-notice ${warning ? "theme-notice-warning" : "theme-notice-info"} mb-4`}>
      <div className="min-w-0 w-full">
        <div className="flex flex-wrap justify-between gap-2">
          <strong>IBKR Flex · {data.status === "never_synced" ? "Awaiting first sync" : data.status === "ok" ? "Synced" : data.status === "stale" ? "Statement is stale" : "Sync failed"}</strong>
          {data.as_of && <span>Statement as of {data.as_of}</span>}
        </div>
        <p className="text-sm mt-1">Latest available daily statement. Portfolio and NAV changes require approval.</p>
        {!data.configured && <p className="text-sm mt-1">Scheduled sync is not configured.</p>}
        {data.error && <p role="status" className="text-sm mt-1">{data.error} {data.last_success_at ? "The last successful statement remains below." : "The approved book is unchanged."}</p>}
        {data.last_success_at && <p className="text-xs mt-1">Last successful pull: {new Date(data.last_success_at).toLocaleString()}</p>}
        {data.as_of && (
          <details className="mt-3">
            <summary className="cursor-pointer">Broker holdings and balances</summary>
            <p className="text-sm my-2">Net liquidation: {money(data.net_liquidation, data.base_currency ?? "USD")}. These are statement values; proposals may still be pending.</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <caption className="sr-only">IBKR statement holdings, marks, unrealized profit and loss, and open lots</caption>
                <thead><tr><th className="py-2 pr-4">Instrument</th><th className="pr-4">Quantity</th><th className="pr-4">Broker mark</th><th className="pr-4">Unrealized P&amp;L ({data.base_currency ?? "base"})</th><th>Lot open dates</th></tr></thead>
                <tbody>{data.positions?.map(row => (
                  <tr key={row.position_id ?? row.ticker}>
                    <td className="py-2 pr-4">{row.option_contract_symbol ?? row.ticker}</td>
                    <td className="pr-4">{row.direction === "short" ? "−" : ""}{row.quantity ?? row.shares ?? "—"}</td>
                    <td className="pr-4">{money(row.broker_mark_price, row.currency ?? "USD")}</td>
                    <td className="pr-4">{money(row.broker_unrealized_pnl_base, row.base_currency ?? data.base_currency ?? "USD")}</td>
                    <td>{row.ibkr_lots?.map(lot => lot.open_date).filter(Boolean).join(", ") || "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            {!!data.cash_balances?.length && <p className="text-sm mt-3">Cash: {data.cash_balances.map(row => money(row.balance, row.currency)).join(" · ")}</p>}
          </details>
        )}
      </div>
    </section>
  )
}
