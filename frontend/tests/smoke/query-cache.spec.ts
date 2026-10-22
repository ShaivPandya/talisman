import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

const baseline = process.env.TL189_BASELINE === "1"

async function measureCharts(page: Page) {
  await page.evaluate(() => {
    const started = performance.now()
    const metrics = { firstChartMs: null as number | null, sawSpinner: false }
    const observer = new MutationObserver(() => {
      if (document.querySelector("main .recharts-wrapper > .recharts-surface") && metrics.firstChartMs === null) {
        metrics.firstChartMs = performance.now() - started
      }
      if (document.querySelector("main .animate-spin")) metrics.sawSpinner = true
    })
    observer.observe(document.body, { childList: true, subtree: true })
    Object.assign(window, { cacheMetrics: metrics, cacheObserver: observer })
  })
}

async function reportCharts(page: Page, name: string) {
  const metrics = await page.evaluate(() => {
    const browser = window as unknown as {
      cacheMetrics: { firstChartMs: number | null; sawSpinner: boolean }
      cacheObserver: MutationObserver
    }
    browser.cacheObserver.disconnect()
    return browser.cacheMetrics
  })
  console.log(JSON.stringify({ name, baseline, ...metrics }))
  await test.info().attach(name, { body: JSON.stringify(metrics), contentType: "application/json" })
  if (!baseline) expect(metrics.sawSpinner).toBe(false)
}

test("portfolio returns after ten minutes with cached charts during background refresh", async ({ page }) => {
  let hold = false
  let release!: () => void
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.route("**/api/portfolio?**", async route => {
    if (hold) await responseGate
    await route.fallback()
  })
  await page.goto("/")
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
  await page.clock.install()
  await page.getByRole("link", { name: "Workspace", exact: true }).click()
  await expect(page.getByText("Here's where your book stands and the few things worth your attention.")).toBeVisible()
  await page.clock.fastForward(10 * 60 * 1000)
  hold = true
  await measureCharts(page)
  const refresh = page.waitForRequest(request => request.url().includes("/api/portfolio?timeframe=This%20Week"))
  await page.getByRole("link", { name: "Portfolio Dashboard", exact: true }).click()
  await refresh
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(baseline ? 0 : 2)
  await expect(page.getByText("Fetching portfolio data...", { exact: true })).toHaveCount(baseline ? 1 : 0)
  // Hold the same response delay in before/after measurements on the shared machine.
  await new Promise(resolve => setTimeout(resolve, 1000))
  release()
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
  await reportCharts(page, "ten-minute-return")
})

test("portfolio timeframe switch keeps charts visible until the response arrives", async ({ page }) => {
  let release!: () => void
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.route("**/api/portfolio?**", async route => {
    if (new URL(route.request().url()).searchParams.get("timeframe") === "Monthly") await responseGate
    await route.fallback()
  })
  await page.goto("/")
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
  await measureCharts(page)
  await page.getByRole("button", { name: "Monthly", exact: true }).click()
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(baseline ? 0 : 2)
  await expect(page.getByText("Fetching portfolio data...", { exact: true })).toHaveCount(baseline ? 1 : 0)
  if (!baseline) await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toContainText("Showing Past Week")
  await new Promise(resolve => setTimeout(resolve, 1000))
  release()
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
  if (!baseline) await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toHaveCount(0)
  await reportCharts(page, "timeframe-switch")
})

const points = [{ date: "2026-05-13", value: 100 }, { date: "2026-05-14", value: 105 }]
const dashboards = [
  { path: "/index-dashboard", endpoint: "/api/index-dashboard", series: "indices", order: "index_order" },
  { path: "/fx-dashboard", endpoint: "/api/fx-dashboard", series: "pairs", order: "pair_order" },
  { path: "/commodities", endpoint: "/api/commodities", series: "commodities", order: "commodity_order" },
  { path: "/sector-metrics", endpoint: "/api/sector-metrics/series", series: "sector_prices", order: "sector_order" },
]

for (const dashboard of dashboards) {
  test(`${dashboard.path} keeps the previous timeframe and labels in unified view`, async ({ page, apiMocks }) => {
    apiMocks.approvalsDismissed = true
    let release!: () => void
    const responseGate = new Promise<void>(resolve => { release = resolve })
    await page.route(url => url.pathname === dashboard.endpoint, async route => {
      const monthly = new URL(route.request().url()).searchParams.get("timeframe") === "Monthly"
      if (monthly) await responseGate
      await route.fulfill({ json: {
        [dashboard.series]: { "Cache test asset": monthly ? points.map(point => ({ ...point, value: point.value + 10 })) : points },
        [dashboard.order]: ["Cache test asset"],
      } })
    })
    if (dashboard.path === "/sector-metrics") {
      await page.route("**/api/sector-metrics", route => route.fulfill({ json: { weights_df: [] } }))
    }
    await page.goto(dashboard.path)
    await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(1)
    await page.getByRole("button", { name: "Unified", exact: true }).click()
    await expect(page.getByText(/Past Week.*normalized to 0%/)).toBeVisible()
    await page.getByRole("button", { name: "Monthly", exact: true }).click()
    await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toContainText("Showing Past Week")
    await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(1)
    await expect(page.getByText(/Past Week.*normalized to 0%/)).toBeVisible()
    release()
    await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toHaveCount(0)
    await expect(page.getByText(/Monthly.*normalized to 0%/)).toBeVisible()
  })
}

function countryData(metric: string) {
  return {
    country_order: ["United States"],
    countries: { "United States": points.map(point => ({ ...point, value: metric === "GDP" ? 2 : 3 })) },
    latest_observation_dates: { "United States": "2026-05-14" },
    series_used: { "United States": "fred" },
    errors: { "United States": [] },
  }
}

test("country metric switches label the last resolved data through rapid changes", async ({ page }) => {
  let releaseGdp!: () => void
  let releaseUnemployment!: () => void
  const gdp = new Promise<void>(resolve => { releaseGdp = resolve })
  const unemployment = new Promise<void>(resolve => { releaseUnemployment = resolve })
  await page.route("**/api/country-dashboard?**", async route => {
    const metric = new URL(route.request().url()).searchParams.get("metric")!
    if (metric === "GDP") await gdp
    if (metric === "Unemployment") await unemployment
    await route.fulfill({ json: countryData(metric) })
  })
  await page.goto("/country-dashboard")
  await expect(page.getByText("Showing: CPI YoY %", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "GDP", exact: true }).click()
  await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toContainText("Showing Inflation")
  await page.getByRole("button", { name: "Unemployment", exact: true }).click()
  await expect(page.getByText("Showing: CPI YoY %", { exact: true })).toBeVisible()
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(1)
  releaseUnemployment()
  await expect(page.getByText("Showing: Rate %", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "GDP", exact: true }).click()
  await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toContainText("Showing Unemployment")
  await expect(page.getByText("Showing: Rate %", { exact: true })).toBeVisible()
  const screenshot = test.info().outputPath("retained-metric.png")
  await page.screenshot({ path: screenshot })
  await test.info().attach("retained-metric", { path: screenshot, contentType: "image/png" })
  releaseGdp()
  await expect(page.getByText("Showing: Real GDP YoY %", { exact: true })).toBeVisible()
})

test("country data and unvisited prefetched metrics survive two hours away", async ({ page }) => {
  const requests: string[] = []
  let hold = false
  let release!: () => void
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.clock.install()
  await page.route("**/api/country-dashboard?**", async route => {
    const metric = new URL(route.request().url()).searchParams.get("metric")!
    requests.push(metric)
    if (hold) await responseGate
    await route.fulfill({ json: countryData(metric) })
  })
  await page.goto("/country-dashboard")
  await expect(page.getByText("Showing: CPI YoY %", { exact: true })).toBeVisible()
  await expect.poll(() => requests.length).toBe(3)
  await page.getByRole("link", { name: "Workspace", exact: true }).click()
  await expect(page.getByText("Here's where your book stands and the few things worth your attention.")).toBeVisible()
  await page.clock.fastForward(2 * 60 * 60 * 1000)
  hold = true
  try {
    await page.getByRole("link", { name: "Country Dashboard", exact: true }).click()
    await expect(page.getByText("Showing: CPI YoY %", { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "GDP", exact: true }).click()
    await expect(page.getByText("Showing: Real GDP YoY %", { exact: true })).toBeVisible()
    expect(requests.sort()).toEqual(["GDP", "Inflation", "Unemployment"])
  } finally {
    release()
  }
})

test("a failed timeframe request surfaces an error and the previous timeframe remains recoverable", async ({ page }) => {
  await page.route("**/api/portfolio?**", route => {
    if (new URL(route.request().url()).searchParams.get("timeframe") === "Monthly") {
      return route.fulfill({ status: 500, json: { detail: "Timeframe unavailable" } })
    }
    return route.fallback()
  })
  await page.goto("/")
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
  await page.getByRole("button", { name: "Monthly", exact: true }).click()
  await expect(page.getByText(/Timeframe unavailable/)).toBeVisible()
  await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toHaveCount(0)
  await page.getByRole("button", { name: "Past Week", exact: true }).click()
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
})

test("logout and a new login cannot display the previous user's cached portfolio", async ({ page, apiMocks }) => {
  let nextUser = false
  let release!: () => void
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.route("**/api/portfolio?**", async route => {
    if (!nextUser) return route.fallback()
    await responseGate
    await route.fulfill({ json: {
      holdings: [{ ticker: "NEW", role: "position" }],
      position_order: ["NEW"],
      positions: { NEW: points },
    } })
  })
  await page.goto("/")
  await expect(page.getByRole("link", { name: "MSFT", exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Sign out", exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  nextUser = true
  await page.route("**/api/auth/login", route => {
    apiMocks.isAuthenticated = true
    return route.fulfill({ json: { username: "next-user", roles: ["admin"], csrfToken: "next-user-csrf" } })
  })
  await page.getByLabel("Password").fill("next-user-password")
  await page.getByRole("button", { name: "Sign in", exact: true }).click()
  await expect(page.getByText("Fetching portfolio data...", { exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "MSFT", exact: true })).toHaveCount(0)
  release()
  await expect(page.getByRole("link", { name: "NEW", exact: true })).toBeVisible()
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(1)
})
