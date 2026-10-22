import type { Page, Request, Route } from "@playwright/test"

import { expect, test } from "./fixtures"
import { dismissFloatingAlerts } from "./operatingWorkflow"

const baseline = process.env.TL199_BASELINE === "1"
const SIMULATED_LATENCY_MS = 200

const pageResponses: Record<string, unknown> = {
  "/api/sentiment/put-call": {},
  "/api/sentiment/surveys": { aaii: [], naaim: [] },
  "/api/sentiment/volatility": [],
  "/api/positioning/instruments": { instruments: { ES: "E-MINI S&P 500" } },
  "/api/positioning/summary": [],
  "/api/positioning/timeseries": [],
  "/api/market-breadth": {},
  "/api/top50-breadth": {},
  "/api/price-volume-signals": {},
  "/api/vix-term-structure": {},
  "/api/sector-metrics": { weights_df: [] },
  "/api/sector-metrics/series": {},
  "/api/admin/jobs/enqueue-market-snapshot-refresh": { status: "done", result: {} },
  // The old RefreshButton cleared the backend cache; answer it so the baseline run can be counted.
  "/api/cache": { status: "cleared" },
}

async function mockPages(page: Page) {
  let latencyMs = 0
  await page.route(url => url.pathname in pageResponses, route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(pageResponses[new URL(route.request().url()).pathname]),
  }))
  // Registered last so it runs first: hold every /api response for the same time in before and after runs.
  await page.route("**/api/**", async (route: Route) => {
    if (latencyMs) await new Promise(resolve => setTimeout(resolve, latencyMs))
    await route.fallback()
  })
  return { setLatency: (ms: number) => { latencyMs = ms } }
}

function waitForApi(page: Page, path: string) {
  return page.waitForResponse(response => new URL(response.url()).pathname === path)
}

// Let idle-time prefetches finish so they don't land inside the measured refresh.
async function waitForQuietApi(page: Page, quietMs = 500) {
  let last = Date.now()
  const touch = (request: Request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) last = Date.now()
  }
  page.on("request", touch)
  page.on("requestfinished", touch)
  try {
    while (Date.now() - last < quietMs) await page.waitForTimeout(100)
  } finally {
    page.off("request", touch)
    page.off("requestfinished", touch)
  }
}

async function visit(page: Page, link: string, heading: string) {
  await page.getByRole("link", { name: link, exact: true }).click()
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible()
}

// Fill the query cache with other pages first, as a real session would.
async function tourOtherPages(page: Page) {
  await page.goto("/")
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
  await visit(page, "Liquidity", "Liquidity Dashboard")
  await page.getByRole("link", { name: "Workspace", exact: true }).click()
  await expect(page.getByText("Here's where your book stands and the few things worth your attention.")).toBeVisible()
}

async function clickRefresh(page: Page) {
  // The staged action item alert floats over the page header's Refresh button.
  await dismissFloatingAlerts(page)
  await waitForQuietApi(page)
  const requests: Request[] = []
  const record = (request: Request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) requests.push(request)
  }
  page.on("request", record)
  // Time the busy state in the page itself; Playwright's assertion polling is too coarse for this.
  await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll("button")).find(b => b.textContent === "Refresh Data")
    if (!button) throw new Error("Refresh Data button not found")
    const timing = new Promise<number>(resolve => {
      let started: number | null = null
      const observer = new MutationObserver(() => {
        if (started === null && button.textContent === "Refreshing...") started = performance.now()
        if (started !== null && button.textContent === "Refresh Data" && !button.disabled) {
          observer.disconnect()
          resolve(performance.now() - started)
        }
      })
      observer.observe(button, { attributes: true, characterData: true, childList: true, subtree: true })
    })
    Object.assign(window, { refreshTiming: timing })
  })
  await page.getByRole("button", { name: "Refresh Data" }).click()
  const refreshMs = Math.round(await page.evaluate(() => (window as unknown as { refreshTiming: Promise<number> }).refreshTiming))
  page.off("request", record)
  return {
    refreshMs,
    requests: requests.map(request => {
      const url = new URL(request.url())
      return { method: request.method(), path: url.pathname, search: url.search }
    }),
  }
}

async function report(name: string, result: Awaited<ReturnType<typeof clickRefresh>>, isOwn: (path: string) => boolean) {
  const metrics = {
    name,
    baseline,
    refreshMs: result.refreshMs,
    requestCount: result.requests.length,
    cacheDeletes: result.requests.filter(r => r.method === "DELETE" && r.path === "/api/cache").length,
    otherPageRequests: result.requests.filter(r => !isOwn(r.path)).length,
    requests: result.requests.map(r => `${r.method} ${r.path}${r.search}`),
  }
  console.log(JSON.stringify(metrics))
  await test.info().attach(name, { body: JSON.stringify(metrics), contentType: "application/json" })
  return metrics
}

const scopedPages = [
  {
    link: "Sentiment",
    heading: "Sentiment",
    own: ["/api/sentiment/put-call", "/api/sentiment/surveys", "/api/sentiment/volatility"],
    // The put/call tab loads first; surveys and volatility are idle-prefetched for the other tabs.
    loaded: ["/api/sentiment/put-call", "/api/sentiment/surveys", "/api/sentiment/volatility"],
  },
  {
    link: "Positioning",
    heading: "CFTC Positioning",
    own: ["/api/positioning/instruments", "/api/positioning/summary", "/api/positioning/timeseries"],
    loaded: ["/api/positioning/instruments", "/api/positioning/summary", "/api/positioning/timeseries"],
  },
  {
    link: "Market Technicals",
    heading: "Market Technicals",
    own: ["/api/market-breadth", "/api/top50-breadth", "/api/price-volume-signals", "/api/vix-term-structure"],
    // Only the open tab mounts its query, so only it is cached to refetch.
    loaded: ["/api/vix-term-structure"],
  },
]

for (const target of scopedPages) {
  test(`${target.link} refresh only refetches its own data`, async ({ page }) => {
    const { setLatency } = await mockPages(page)
    await tourOtherPages(page)
    const ready = Promise.all(target.loaded.map(path => waitForApi(page, path)))
    await visit(page, target.link, target.heading)
    await ready

    setLatency(SIMULATED_LATENCY_MS)
    const metrics = await report(`${target.link.toLowerCase().replace(/ /g, "-")}-refresh`, await clickRefresh(page), path => target.own.includes(path))
    if (baseline) return

    expect(metrics.cacheDeletes).toBe(0)
    expect(metrics.requests.map(r => r.split("?")[0]).sort()).toEqual(target.loaded.map(path => `GET ${path}`).sort())
  })
}

test("portfolio refresh forces the current timeframe without clearing the backend cache", async ({ page }) => {
  const { setLatency } = await mockPages(page)
  await page.goto("/")
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)

  setLatency(SIMULATED_LATENCY_MS)
  const metrics = await report("portfolio-refresh", await clickRefresh(page), path => path === "/api/portfolio" || path === "/api/thesis/status")
  if (baseline) return

  expect(metrics.cacheDeletes).toBe(0)
  expect(metrics.requests).toContain("GET /api/portfolio?timeframe=This%20Week&force_refresh=true")
  expect(metrics.otherPageRequests).toBe(0)
})

test("sector metrics refresh forces the snapshot-backed table without clearing the backend cache", async ({ page }) => {
  const { setLatency } = await mockPages(page)
  await page.goto("/")
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(2)
  const ready = Promise.all([waitForApi(page, "/api/sector-metrics"), waitForApi(page, "/api/sector-metrics/series")])
  await visit(page, "Sector Metrics", "Sector Metrics")
  await ready

  setLatency(SIMULATED_LATENCY_MS)
  const metrics = await report("sector-metrics-refresh", await clickRefresh(page), path => path.startsWith("/api/sector-metrics") || path.startsWith("/api/admin/jobs/"))
  if (baseline) return

  expect(metrics.cacheDeletes).toBe(0)
  expect(metrics.requests).toContain("GET /api/sector-metrics?force_refresh=true")
  expect(metrics.otherPageRequests).toBe(0)
})
