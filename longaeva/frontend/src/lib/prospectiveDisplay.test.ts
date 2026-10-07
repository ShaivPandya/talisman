import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { expect, it } from "vitest"
import type { ProspectiveReport } from "./reportApi"
import { prospectiveValue } from "./prospectiveDisplay"
import { ProspectivePanel } from "../components/evaluation/ProspectivePanel"

it("displays timestamps and growth bases while keeping the prospective forecast unscored", () => {
  const report: ProspectiveReport = {
    kind: "prospective", target: "FY2026Q4", scoring_status: "Not yet scored",
    cutoff_ts: "2026-07-28T20:05:26Z", registered_at: "2026-10-07T19:24:14Z",
    run_id: "saved-run", n_paths: 5000, n_quarters: 4, seed: 32,
    content_hash: "registration-hash", outputs_hash: "outputs-hash",
    parameter_set_hash: "parameters-hash", source_manifest_hash: "sources-hash",
    code_version: "saved-version", lib_versions: { numpy: "saved-version" },
    replay_status: "exact_match",
    publication_check_url: "https://investor.visa.com/financial-information/quarterly-earnings/default.aspx",
    publication_checked_at: "2026-10-07T19:20:00Z",
    forecasts: [
      { metric: "net_revenue", period_label: "FY2026Q4", target_period_start: "2026-07-01", target_period_end: "2026-09-30",
        quantiles: { "0.1": 10000, "0.5": 11000, "0.9": 12000 }, unit: "usd_millions", basis: "gaap", growth_convention: "quarterly_level" },
      { metric: "payments_volume_growth_constant", period_label: "FY2026Q4", target_period_start: "2026-07-01", target_period_end: "2026-09-30",
        quantiles: { "0.1": 0, "0.5": 0.08, "0.9": 0.12 }, unit: "ratio", basis: "constant_dollar", growth_convention: "annualized_qoq" },
      { metric: "net_revenue", period_label: "FY2027Q1", target_period_start: "2026-10-01", target_period_end: "2026-12-31",
        quantiles: { "0.1": 10000, "0.5": 11000, "0.9": 12000 }, unit: "usd_millions", basis: "gaap", growth_convention: "quarterly_level" },
    ],
  }
  const html = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(ProspectivePanel, { report })))
  expect(html).toContain("FY2026Q4")
  expect(html).toContain("Not yet scored")
  expect(html).toContain(report.registered_at)
  expect(html).toContain(report.cutoff_ts)
  expect(html).toContain("11,000")
  expect(html).toContain("8.00%")
  expect(html).toContain("Annualized quarter-over-quarter %")
  expect(html).toContain("USD millions")
  expect(html).toContain("exact match")
  expect(html).toContain("LLM disabled")
  expect(html).toContain("supporting horizon")
  expect(html).not.toContain("MAE")
  expect(html).not.toContain("Coverage")
})

it("preserves zero ratios and missing quantiles", () => {
  const row = { unit: "ratio", quantiles: { "0.5": 0 } }
  expect(prospectiveValue(row, "0.5")).toBe("0.00%")
  expect(prospectiveValue(row, "0.9")).toBe("Unavailable")
})
