import type { Page } from "@playwright/test"
import { expect, test } from "./fixtures"
import type { IdeaScanCandidate, IdeaScanPreset, IdeaScanRun, IdeaScanScreenResult, IdeaScanSettings } from "@/lib/api"

const RUN_ID = "20261031T120000000000Z-abc123"

function card(overrides: Partial<IdeaScanCandidate>): IdeaScanCandidate {
  return {
    ticker: "AAA",
    direction: "long",
    company: "Alpha Industries",
    sector: "Technology",
    industry: "Semiconductors",
    universes: ["sp500"],
    presets: [{ id: "long-momentum-quality", name: "Long · Momentum + quality" }],
    signals: [{ preset_id: "long-momentum-quality", label: "Composite percentile 96 (≥ 90)" }],
    preset_count: 1,
    agreement_score: 1.96,
    macro_boost: 0.5,
    final_score: 2.46,
    macro_fit: { sector: "Technology", score: 2, confidence: "high", reason: "AI capex keeps rising", fit: "tailwind", boost: 0.5 },
    factor_ranks: { composite_pct: 0.96, quality_pct: 0.9, price_momentum_pct: 0.95, eps_momentum_pct: 0.7, revenue_momentum_pct: 0.8 },
    metrics: { market_cap: 42e9, price_to_book: 6.1, rev_yoy_avg: 24.5, eps_yoy_avg: 31.2, return_52w: 48.0, return_3m: 12.1, enterpriseToEbitda: 28.4 },
    revision_30d: null,
    days_to_earnings: 12,
    review: {
      status: "ok",
      trigger: "Top-decile composite with accelerating revenue.",
      why_now: "Guidance raised on data-center demand.",
      variant_view: "Market underestimates the services mix.",
      macro_fit: "Sector tailwind supports the setup.",
      headlines: [{ title: "Alpha raises outlook", url: "https://news.example.com/alpha", date: "2026-10-28" }],
      missing_inputs: ["Customer concentration"],
      next_action: "research",
    },
    review_status: "reviewed",
    scout_status: "published",
    card_state: "open",
    idea_id: null,
    ...overrides,
  }
}

function fullRun(): IdeaScanRun {
  return {
    run_id: RUN_ID,
    week: "2026-W44",
    status: "completed",
    source: "scheduler",
    limited: false,
    created_at: "2026-10-31T12:00:00Z",
    completed_at: "2026-10-31T13:02:00Z",
    summary: { text: "Quality tech leads the long side; energy names dominate the shorts.", origin: "llm" },
    macro_view: {
      status: "ok",
      as_of: "2026-10-31T12:40:00Z",
      model: "claude-opus-5-5",
      summary: "Growth is steady, liquidity is easing.",
      rows: [
        {
          sector: "Technology", score: 2, previous_score: 1, confidence: "high", reason: "AI capex keeps rising",
          evidence: [{ type: "search", ref: "https://news.example.com/capex", detail: "Hyperscaler capex up 40%" }],
          change_explanation: "Two more hyperscalers raised capex guidance.", origin: "llm",
        },
        {
          sector: "Energy", score: -2, previous_score: -2, confidence: "medium", reason: "Oil inventories building",
          evidence: [{ type: "snapshot", ref: "economic_backdrop:current:v1", detail: "Industrial production flat" }],
          change_explanation: "", origin: "llm",
        },
      ],
      dropped: [{ sector: "Utilities", reason: "no verifiable evidence" }],
      sources: [{ title: "Capex story", url: "https://news.example.com/capex" }],
      snapshots: [],
      error: null,
    },
    candidates: [
      card({}),
      card({ ticker: "BBB", company: "Beta Robotics", agreement_score: 1.8, macro_boost: 0, final_score: 1.8, review: null, review_status: "not_reviewed_budget", macro_fit: null }),
      card({
        ticker: "EEE", direction: "short", company: "Echo Petroleum", sector: "Energy", industry: "Oil & Gas E&P",
        presets: [{ id: "short-breaking-down", name: "Short · Breaking down" }],
        signals: [{ preset_id: "short-breaking-down", label: "30-day EPS revisions -6.0% (negative)" }],
        macro_fit: { sector: "Energy", score: -2, confidence: "medium", reason: "Oil inventories building", fit: "tailwind", boost: 0.38 },
        short_data: { short_percent_of_float: 0.142, short_ratio: 5.1, shares_short: 1e7, borrow: null },
        days_to_earnings: 9,
        review: {
          status: "ok",
          why_now: "Estimates cut three times this month.",
          headlines: [],
          missing_inputs: ["Borrow cost and availability (no broker feed connected)"],
          next_action: "watch",
        },
      }),
    ],
    already_tracked: [{ ticker: "MSFT", direction: "long", company: "Microsoft", tracked_as: "position", presets: [{ id: "long-momentum-quality", name: "Long · Momentum + quality" }] }],
    near_misses: [{ ticker: "CCC", direction: "long", company: "Gamma Foods", sector: "Consumer Defensive", preset_id: "long-cheap-improving", preset_name: "Long · Cheap & improving", failed_check: "P/B 1.71 (< 1.5)", signals: [] }],
    changes: { new: [{ ticker: "AAA", direction: "long", company: "Alpha Industries" }], still: [{ ticker: "EEE", direction: "short", company: "Echo Petroleum" }], dropped: [{ ticker: "ZZZ", direction: "long", company: "Zeta" }] },
    compared_with_run_id: "20261024T120000000000Z-old",
    presets: [{ id: "long-momentum-quality", name: "Long · Momentum + quality", direction: "long", evaluated: 3480, hits: 348, kept: 10, near_misses: 10 }],
    stats: { universe: 3512, with_data: 3401, candidates: 4, already_tracked: 1, review_slots: 15, reviewed: 2, not_reviewed_budget: 1, not_reviewed_cap: 0, published: 2, near_misses: 1 },
    cost: { limit_usd: 2, spent_usd: 1.62, web_searches: 11, by_step: { macro: 0.38, review: 1.14, digest: 0.1 }, skipped: [{ step: "review", label: "BBB (long)", reason: "budget" }] },
  }
}

const SETTINGS: IdeaScanSettings = {
  presets: [
    {
      id: "long-cheap-improving", name: "Long · Cheap & improving", direction: "long", universes: ["sp500", "sp400", "sp600", "russell2000"],
      screen: "long_screen", params: { pb_threshold: 1.5 }, weights: { quality: 0.33, price_momentum: 0.33, revenue_momentum: 0.2, eps_momentum: 0.14 },
      max_names: 10, enabled: true, liquidity_coverage: null,
    },
    {
      id: "long-liquid-covered", name: "Long · Liquid & well covered", direction: "long", universes: ["sp500", "sp400", "sp600", "russell2000"],
      screen: "liquid_covered", params: { min_dollar_volume_industry_pct: 0.75, require_above_median_coverage: true, min_composite_pct: null },
      weights: { quality: 0.33, price_momentum: 0.33, revenue_momentum: 0.2, eps_momentum: 0.14 }, max_names: 10, enabled: true, liquidity_coverage: null,
    },
  ],
  config: { max_reviews: 15, max_cost_usd: 2, review_web_searches: 2, macro_web_searches: 5, near_miss_limit: 10 },
  known_defaults: ["long-cheap-improving", "long-liquid-covered"],
}

const SCREEN_RESULT: IdeaScanScreenResult = {
  run_id: RUN_ID,
  week: "2026-W44",
  data_fetched_at: "2026-10-31T10:00:00+00:00",
  evaluated: 3401,
  hits_total: 1,
  hits: [{
    ticker: "AAA", company: "Alpha Industries", sector: "Technology", industry: "Semiconductors", market_cap: 4.2e10,
    dollar_volume: 8.4e8, analyst_count: 31, composite_pct: 0.93, preset_score: 0.93,
    signals: ["P/B 1.20 (< 1.5)", "Dollar volume $840.0M/day, 96 pct of Semiconductors (≥ 80)", "31 analysts (> Semiconductors median 12.0)"], failed: [],
  }],
  near_misses: [{
    ticker: "BBB", company: "Beta Devices", sector: "Technology", industry: "Semiconductors", market_cap: 3e9,
    dollar_volume: 2e7, analyst_count: 14, composite_pct: 0.71, preset_score: 0.71,
    signals: ["P/B 1.10 (< 1.5)"], failed: ["Dollar volume $20.0M/day, 41 pct of Semiconductors (≥ 80)"],
  }],
}

async function mockDigest(page: Page, run: IdeaScanRun) {
  const calls = { dismissed: [] as string[], promoted: [] as string[], saved: [] as IdeaScanSettings[], screened: [] as IdeaScanPreset[] }
  let current = structuredClone(run)
  await page.route("**/api/idea-scan/**", async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (method === "GET" && path === "/api/idea-scan/runs") {
      return route.fulfill({ json: { runs: [{ run_id: run.run_id, week: run.week, status: run.status, source: run.source, created_at: run.created_at, completed_at: run.completed_at ?? null, candidates: run.candidates?.length ?? 0, reviewed: 2, spent_usd: 1.62, limited: false }] } })
    }
    if (method === "GET" && path === `/api/idea-scan/runs/${RUN_ID}`) return route.fulfill({ json: current })
    if (method === "GET" && path === "/api/idea-scan/settings") return route.fulfill({ json: { settings: SETTINGS, defaults: SETTINGS } })
    if (method === "PUT" && path === "/api/idea-scan/settings") {
      calls.saved.push(request.postDataJSON())
      return route.fulfill({ json: { settings: request.postDataJSON() } })
    }
    if (method === "POST" && path === "/api/idea-scan/screen") {
      calls.screened.push(request.postDataJSON().preset)
      return route.fulfill({ json: SCREEN_RESULT })
    }
    const match = path.match(/\/candidates\/(long|short)\/([^/]+)\/(dismiss|promote)$/)
    if (method === "POST" && match) {
      const [, direction, ticker, action] = match
      const target = current.candidates?.find(c => c.ticker === ticker && c.direction === direction)
      if (!target) return route.fulfill({ status: 404, json: { detail: "Unknown candidate" } })
      const updated = action === "dismiss"
        ? { ...target, card_state: "dismissed" as const }
        : { ...target, card_state: "promoted" as const, idea_id: `investment_idea:${ticker.toLowerCase()}` }
      current = { ...current, candidates: current.candidates?.map(c => (c === target ? updated : c)) }
      calls[action === "dismiss" ? "dismissed" : "promoted"].push(`${direction}:${ticker}`)
      return route.fulfill({ json: action === "dismiss" ? { candidate: updated } : { candidate: updated, idea_id: updated.idea_id, created: true } })
    }
    return route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } })
  })
  return calls
}

test("the digest shows the macro view, both sides, and run stats", async ({ page }) => {
  await mockDigest(page, fullRun())
  await page.goto("/idea-digest")
  await expect(page.getByRole("heading", { name: "Idea Digest" })).toBeVisible()
  await expect(page.getByText("Quality tech leads the long side")).toBeVisible()

  const macro = page.getByRole("region", { name: "Macro view by sector" })
  await expect(macro.getByText("AI capex keeps rising")).toBeVisible()
  await expect(macro.getByText("was +1")).toBeVisible()
  await macro.getByRole("button", { name: /Technology/ }).click()
  await expect(macro.getByText("Two more hyperscalers raised capex guidance.")).toBeVisible()
  await expect(macro.getByRole("link", { name: "Hyperscaler capex up 40%" })).toHaveAttribute("href", "https://news.example.com/capex")
  await expect(macro.getByText("Dropped: Utilities (no verifiable evidence)")).toBeVisible()

  const longs = page.getByRole("region", { name: /Long ideas/ })
  const shorts = page.getByRole("region", { name: /Short ideas/ })
  await expect(longs.getByTestId("digest-card-long-AAA")).toContainText("Guidance raised on data-center demand.")
  await expect(longs.getByTestId("digest-card-long-AAA")).toContainText("Macro supports this long (Technology +2, high)")
  await expect(longs.getByTestId("digest-card-long-BBB")).toContainText("Not reviewed (budget)")
  await expect(shorts.getByTestId("digest-card-short-EEE")).toContainText("14.2% of float")
  await expect(shorts.getByTestId("digest-card-short-EEE")).toContainText("9 days to earnings")
  await expect(shorts.getByTestId("digest-card-short-EEE")).toContainText("borrow data not available")

  await expect(page.getByRole("region", { name: "Near-misses" })).toContainText("P/B 1.71 (< 1.5)")
  await expect(page.getByRole("region", { name: "Already tracked" })).toContainText("MSFT")
  await expect(page.getByRole("region", { name: "Compared with last week" })).toContainText("ZZZ")
  const stats = page.getByRole("region", { name: "Run stats" })
  await expect(stats).toContainText("$1.62")
  await expect(stats).toContainText("Skipped for budget: BBB (long)")
  await page.screenshot({ path: test.info().outputPath("idea-digest.png"), fullPage: true })
})

test("cards can be promoted, dismissed and discussed with Stan", async ({ page }) => {
  const calls = await mockDigest(page, fullRun())
  await page.goto("/idea-digest")
  const longs = page.getByRole("region", { name: /Long ideas/ })
  const shorts = page.getByRole("region", { name: /Short ideas/ })

  await longs.getByTestId("digest-card-long-BBB").getByRole("button", { name: "Dismiss" }).click()
  await expect(longs.getByTestId("digest-card-long-BBB")).toHaveCount(0)
  await expect(longs).toContainText("1 dismissed")

  const echo = shorts.getByTestId("digest-card-short-EEE")
  await echo.getByRole("button", { name: "Promote to Idea" }).click()
  await expect(echo.getByRole("link", { name: "Open idea" })).toHaveAttribute("href", "/ideas/investment_idea:eee")
  await expect(echo).toContainText("Promoted")
  expect(calls).toMatchObject({ dismissed: ["long:BBB"], promoted: ["short:EEE"] })

  await longs.getByTestId("digest-card-long-AAA").getByRole("button", { name: "Discuss with Stan" }).click()
  const composer = page.getByLabel("Message Stan")
  await expect(composer).toBeVisible()
  await expect(composer).toHaveValue(/Let's discuss AAA \(Alpha Industries\), a long name from the weekly idea scan \(2026-W44\)/)
  await expect(composer).toHaveValue(/Why now: Guidance raised on data-center demand\./)
})

test("an empty week says nothing cleared the bar and keeps the near-misses", async ({ page }) => {
  await mockDigest(page, { ...fullRun(), candidates: [], summary: { text: "Nothing cleared the bar this week. The near-misses below came closest.", origin: "rule" } })
  await page.goto("/idea-digest")
  await expect(page.getByText("Nothing cleared the bar this week. The near-misses below came closest.").last()).toBeVisible()
  await expect(page.getByRole("region", { name: "Near-misses" })).toContainText("CCC")
})

test("presets can be edited from the digest", async ({ page }) => {
  const calls = await mockDigest(page, fullRun())
  await page.goto("/idea-digest")
  await page.getByRole("button", { name: "Presets" }).click()
  const dialog = page.getByRole("dialog", { name: "Idea scan presets" })
  await dialog.getByLabel("Maximum names").first().fill("4")
  await dialog.getByLabel("Names reviewed per run").fill("8")
  await dialog.getByRole("button", { name: "Save presets" }).click()
  await expect(dialog).toBeHidden()
  expect(calls.saved[0].presets[0].max_names).toBe(4)
  expect(calls.saved[0].config.max_reviews).toBe(8)
})

test("any preset can require liquid, well-covered names", async ({ page }) => {
  const calls = await mockDigest(page, fullRun())
  await page.goto("/idea-digest")
  await page.getByRole("button", { name: "Presets" }).click()
  const dialog = page.getByRole("dialog", { name: "Idea scan presets" })
  // The liquid-covered preset is that screen already, so only the other preset offers the filter.
  await expect(dialog.getByRole("switch", { name: "Only liquid, well-covered names" })).toHaveCount(1)
  await dialog.getByText("Only liquid, well-covered names").click()
  await dialog.getByLabel("Dollar volume, min. percentile in industry").fill("80")
  await dialog.getByRole("button", { name: "Save presets" }).click()
  await expect(dialog).toBeHidden()
  expect(calls.saved[0].presets[0].liquidity_coverage).toEqual({ min_dollar_volume_industry_pct: 0.8, require_above_median_coverage: true })
  expect(calls.saved[0].presets[1].liquidity_coverage).toBeNull()
})

test("the Screeners page runs a digest preset with the filter", async ({ page }) => {
  const calls = await mockDigest(page, fullRun())
  await page.goto("/screeners")
  // A notification toast can slide over the end of the tab bar; retry the click until the panel shows.
  await expect(async () => {
    await page.getByRole("button", { name: "Digest Presets", exact: true }).click()
    await expect(page.getByLabel("Preset")).toBeVisible({ timeout: 1_000 })
  }).toPass()
  await page.getByLabel("Universe").selectOption("sp400")
  await page.getByText("Only liquid, well-covered names").click()
  await page.getByRole("button", { name: "Run Screen" }).click()
  await expect(page.getByText("Matches:")).toBeVisible()
  await expect(page.getByRole("cell", { name: "Alpha Industries" })).toBeVisible()
  await expect(page.getByRole("cell", { name: "$840.0M", exact: true })).toBeVisible()
  await expect(page.getByText("Near misses (one check failed)")).toBeVisible()
  expect(calls.screened[0]).toMatchObject({
    id: "long-cheap-improving",
    universes: ["sp400"],
    liquidity_coverage: { min_dollar_volume_industry_pct: 0.75, require_above_median_coverage: true },
  })
  await page.screenshot({ path: test.info().outputPath("screeners-digest-presets.png"), fullPage: true })
})

test("the digest fits a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await mockDigest(page, fullRun())
  await page.goto("/idea-digest")
  await expect(page.getByTestId("digest-card-long-AAA")).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  await page.screenshot({ path: test.info().outputPath("idea-digest-mobile.png"), fullPage: true })
})
