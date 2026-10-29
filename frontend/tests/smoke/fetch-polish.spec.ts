import { test, expect, dossierResponse } from "./fixtures"
import type { PositionValuation } from "@/lib/api"

const baseline = process.env.TL203_BASELINE === "1"

function report(name: string, metrics: Record<string, number>) {
  console.log(`TL203 ${JSON.stringify({ name, baseline, ...metrics })}`)
}

test("ratio windows share one request and calculate statistics for the selected window", async ({ page }) => {
  const requests: string[] = []
  await page.clock.setFixedTime(new Date("2026-10-22T12:00:00Z"))
  await page.route("**/api/chart/ratio", async route => {
    const body = route.request().postDataJSON()
    requests.push(body.start_date)
    await new Promise(resolve => setTimeout(resolve, 200))
    await route.fulfill({ json: {
      symbol_a: "HD", symbol_b: "LOW", ratio_data: [
        { Date: "2018-01-01", "Price A": 100, "Price B": 10, Ratio: 10 },
        { Date: "2024-01-01", "Price A": 20, "Price B": 10, Ratio: 2 },
        { Date: "2026-01-01", "Price A": 40, "Price B": 10, Ratio: 4 },
      ].filter(row => row.Date >= body.start_date),
    } })
  })
  await page.goto("/chart")
  await page.getByRole("button", { name: "Ratio", exact: true }).click()
  const started = Date.now()
  await page.getByRole("button", { name: "HD / LOW", exact: true }).click()
  await expect(page.getByText("Fetching ratio data...", { exact: true })).toHaveCount(0)
  await expect(page.locator("main .recharts-wrapper")).toHaveCount(1)
  await expect(page.getByText("3.0000", { exact: true }).first()).toBeVisible()
  const readyMs = Date.now() - started
  await page.getByRole("button", { name: "10Y", exact: true }).click()
  await expect(page.getByText("5.3333", { exact: true }).first()).toBeVisible()
  expect(requests).toHaveLength(baseline ? 2 : 1)
  report("ratio", { requests: requests.length, readyMs })
})

test("macro refresh reuses the forced response", async ({ page, apiMocks }) => {
  apiMocks.approvalsDismissed = true
  const requests: boolean[] = []
  await page.route("**/api/liquidity*", async route => {
    requests.push(new URL(route.request().url()).searchParams.get("force_refresh") === "true")
    await new Promise(resolve => setTimeout(resolve, 200))
    await route.fallback()
  })
  await page.goto("/liquidity")
  await expect(page.getByRole("heading", { name: "Liquidity Dashboard", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Refresh Data", exact: true })).toBeVisible()
  const before = requests.length
  const started = Date.now()
  await page.getByRole("button", { name: "Refresh Data", exact: true }).click()
  await expect(page.getByRole("button", { name: "Refresh Data", exact: true })).toBeEnabled()
  const refreshRequests = requests.slice(before)
  expect(refreshRequests).toEqual(baseline ? [true, false] : [true])
  report("macro", { requests: refreshRequests.length, readyMs: Date.now() - started })
})

test("valuation starts while dossier is still loading", async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let valuationStarted = false
  await page.route("**/api/dossier/MSFT", async route => {
    await gate
    await route.fulfill({ json: dossierResponse })
  })
  await page.route("**/api/valuation/MSFT", async route => {
    valuationStarted = true
    await route.fallback()
  })
  await page.goto("/dossier/MSFT")
  try {
    await expect(page.getByText("Loading...", { exact: true })).toBeVisible()
    if (!baseline) await expect.poll(() => valuationStarted).toBe(true)
    else await new Promise(resolve => setTimeout(resolve, 300))
    report("dossier", { valuationBeforeDossier: Number(valuationStarted) })
    expect(valuationStarted).toBe(!baseline)
  } finally { release() }
})

test("slow idea polling never overlaps requests and pauses in hidden tabs", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("idea-watchlist-active-jobs-current", JSON.stringify({ test: "poll-test" })))
  await page.route("**/api/ideas/test", route => route.fulfill({ json: {
    idea: { id: "test", ticker: "MSFT", asset: "equity", instrument_type: "security", status: "watching", tags: [], metadata: {} },
    documents: {}, evaluations: [], lifecycle_events: [], record_timeline: [],
  } }))
  let requests = 0
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route("**/api/ideas/evaluate/async/poll-test", async route => {
    requests++
    await gate
    await route.fulfill({ json: { job_id: "poll-test", status: "running" } })
  })
  await page.goto("/ideas/test")
  await expect.poll(() => requests).toBeGreaterThan(0)
  await new Promise(resolve => setTimeout(resolve, 3000))
  report("poll-overlap", { requests })
  expect(requests).toBe(baseline ? 2 : 1)
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" })
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }))
  })
  release()
  await new Promise(resolve => setTimeout(resolve, 100))
  const before = requests
  await new Promise(resolve => setTimeout(resolve, 3000))
  report("poll-hidden", { requests: requests - before })
  if (!baseline) expect(requests).toBe(before)
})

test("profile save updates the displayed valuation without a follow-up GET", async ({ page, apiMocks }) => {
  apiMocks.approvalsDismissed = true
  let reads = 0
  const valuation: PositionValuation = {
    ticker: "MSFT", company_name: "Original valuation", market_data: {},
    profile: { id: "general", label: "General", selection_mode: "auto", weights: {}, effective_weights: {}, options: [{ id: "bank", label: "Bank" }] },
    metrics: {}, peer_context: { source: "test", peer_count: 0, peers: [], metric_stats: {} },
    composite_score: { value: null, status: "missing", components: {} },
    data_quality: { status: "ok", usable_metric_count: 0, warnings: [], metric_statuses: {} },
  }
  await page.route("**/api/valuation/MSFT", route => {
    reads++
    return route.fulfill({ json: valuation })
  })
  await page.route("**/api/valuation/MSFT/profile-override", route => route.fulfill({ json: { valuation: {
    ...valuation, company_name: "Recomputed valuation", profile: { ...valuation.profile, override_profile_id: "bank", selection_mode: "override" },
  } } }))
  await page.goto("/dossier/MSFT?tab=valuation")
  await expect(page.getByText("Original valuation", { exact: true })).toBeVisible()
  const before = reads
  await page.locator("select").filter({ has: page.locator('option[value="bank"]') }).selectOption("bank")
  await expect(page.getByText("Recomputed valuation", { exact: true })).toBeVisible()
  expect(reads).toBe(before)
})

test("approval polling shares Workspace data, uses sixty seconds, and pauses while hidden", async ({ page, apiMocks }) => {
  apiMocks.approvalsDismissed = true
  await page.clock.install()
  let reads = 0
  await page.route("**/api/approvals/summary*", route => { reads++; return route.fallback() })
  await page.goto("/workspace")
  await expect(page.getByText("Here's where your book stands and the few things worth your attention.")).toBeVisible()
  expect(reads).toBe(1)
  await page.clock.runFor(31_000)
  expect(reads).toBe(1)
  await page.clock.runFor(30_000)
  await expect.poll(() => reads).toBe(2)
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" })
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }))
  })
  await page.clock.runFor(120_000)
  expect(reads).toBe(2)
})

test("editor and sizer reuse fresh defaults on navigation", async ({ page, apiMocks }) => {
  apiMocks.approvalsDismissed = true
  const reads = { positions: 0, hedges: 0, settings: 0, prefill: 0 }
  await page.route("**/api/portfolio-positions", route => { reads.positions++; return route.fulfill({ json: { positions: [] } }) })
  await page.route("**/api/hedge-positions", route => { reads.hedges++; return route.fulfill({ json: { positions: [] } }) })
  await page.route("**/api/portfolio-settings", route => { reads.settings++; return route.fulfill({ json: { book_size: 123456 } }) })
  await page.route("**/api/portfolio-sizer/prefill", route => { reads.prefill++; return route.fulfill({ json: { book_size: 123456, positions: [] } }) })
  await page.goto("/portfolio/edit")
  await expect(page.getByText("Loading portfolio and hedge positions...")).toHaveCount(0)
  await expect.poll(() => reads).toEqual({ positions: 1, hedges: 1, settings: 1, prefill: 0 })
  await page.getByRole("link", { name: "Portfolio Sizer", exact: true }).click()
  await expect.poll(() => reads.prefill).toBe(1)
  await expect(page.locator('input[placeholder="100000"]')).toHaveValue("123456")
  await page.locator('input[placeholder="100000"]').fill("234567")
  await page.getByRole("link", { name: "Edit Portfolio", exact: true }).first().click()
  await expect(page.getByText("Loading portfolio and hedge positions...")).toHaveCount(0)
  await page.getByRole("link", { name: "Portfolio Sizer", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Portfolio Sizer", exact: true })).toBeVisible()
  await expect(page.locator('input[placeholder="100000"]')).toHaveValue("234567")
  expect(reads).toEqual({ positions: 1, hedges: 1, settings: 1, prefill: 1 })
})

test("context provider avoids consumer renders when its parent updates", async ({ page }) => {
  await page.goto("/chart")
  const renders = await page.evaluate(async baseline => {
    const path = "/tests/smoke/screen-context-harness.ts"
    const { measureContext } = await import(/* @vite-ignore */ path)
    return measureContext(baseline)
  }, baseline)
  report("context", { renders })
  expect(renders).toBe(baseline ? 11 : 1)
})

test("resumed document generation completes once and clears its stored job", async ({ page, apiMocks }) => {
  apiMocks.approvalsDismissed = true
  await page.addInitScript(() => localStorage.setItem("document-generation-active-jobs:v1", JSON.stringify({
    "overview:MSFT": { kind: "overview", ticker: "MSFT", jobId: "upload-test", status: "running", startedAt: new Date().toISOString() },
  })))
  let reads = 0
  let dossierReads = 0
  await page.route("**/api/dossier/MSFT", route => { dossierReads++; return route.fallback() })
  await page.route("**/api/document-generation/async/upload-test", route => {
    reads++
    return route.fulfill({ json: { job_id: "upload-test", status: "done", result: { status: "ok", ticker: "MSFT", content: "Completed overview" } } })
  })
  await page.goto("/dossier/MSFT")
  await expect(page.getByText("Saved", { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem("document-generation-active-jobs:v1"))).toBe(null)
  expect(reads).toBe(1)
  expect(dossierReads).toBe(2)
})

test("resumed analyzer stops polling after cancellation", async ({ page, apiMocks }) => {
  apiMocks.approvalsDismissed = true
  await page.addInitScript(() => localStorage.setItem("portfolio-analyzer:active-job:portfolio", JSON.stringify({
    jobId: "analyzer-test", status: "running", startedAt: new Date().toISOString(),
  })))
  let reads = 0
  await page.route("**/api/portfolio-analyzer/async/analyzer-test", route => {
    reads++
    return route.fulfill({ json: { job_id: "analyzer-test", status: "cancelled", error: "Test mission stopped" } })
  })
  await page.goto("/analyzer")
  await expect(page.getByText("Test mission stopped", { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem("portfolio-analyzer:active-job:portfolio"))).toBe(null)
  expect(reads).toBe(1)
})
