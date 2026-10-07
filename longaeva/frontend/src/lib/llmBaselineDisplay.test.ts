import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"
import { ForecastPanel } from "@/components/evaluation/ReportPanels"
import type { SavedReport } from "./reportApi"

it("renders quantile scoring, unavailable targets and failed captures distinctly", () => {
  const saved = {
    key: "llm_baseline",
    title: "LLM same-document baseline",
    forecast: {
      config: {
        model_variant: "llm_baseline",
        baseline: {
          provider: "openai",
          model: "gpt-5.4",
          limitation: "Pretrained-model knowledge can include historical outcomes.",
          capture_counts: { succeeded: 2, provider_error: 1 },
        },
      },
      config_hash: "fixture",
      n_scored: 1,
      n_excluded: 0,
      exclusions: [],
      aggregates: {},
      four_quarter: {},
      origins: [
        {
          origin_date: "2024-01-25",
          label: "FY2024Q1",
          window: "primary",
          scores: { "q1.net_revenue.abs_error": 2, "q1.net_revenue.median": 100 },
          error: null,
          skipped_drivers: {},
        },
        {
          origin_date: "2024-04-23",
          label: "FY2024Q2",
          window: "primary",
          scores: {},
          error: null,
          skipped_drivers: { net_revenue: "No comparable evidence" },
        },
        {
          origin_date: "2024-07-23",
          label: "FY2024Q3",
          window: "primary",
          scores: {},
          error: "provider_error: bounded transport failure",
          skipped_drivers: {},
        },
      ],
    },
  } as unknown as SavedReport
  const html = renderToStaticMarkup(
    createElement(ForecastPanel, {
      reports: [saved],
      selected: "llm_baseline",
      target: "net_revenue",
      horizon: "q1",
      window: "overall",
    }),
  )
  expect(html).toContain("gpt-5.4")
  expect(html).toContain("CRPS unavailable")
  expect(html).toContain("Four-quarter forecasts not run")
  expect(html).toContain("Pretrained-model knowledge")
  expect(html).toContain("Excerpt selection")
  expect(html).toContain("2 succeeded · 1 provider error")
  expect(html).toContain("No comparable evidence")
  expect(html).toContain("provider_error: bounded transport failure")
  expect(html).toContain("Scored")
})
