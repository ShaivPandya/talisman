import { authenticate, expect, test } from "./fixtures"
import { riskDashboardFixture } from "./risk-fixture"
import { dismissFloatingAlerts } from "./operatingWorkflow"

function metric(page: import("@playwright/test").Page, title: string) {
  return page.getByText(title, { exact: true }).locator("..")
}

test("loads saved risk read-only and navigates from sidebar, search and Workspace", async ({ page }) => {
  let refreshRequests = 0
  page.on("request", request => { if (request.method() === "POST" && request.url().endsWith("/risk/dashboard/refresh")) refreshRequests++ })
  await authenticate(page)
  await page.goto("/workspace")
  await page.getByRole("link", { name: "Portfolio risk", exact: true }).click()
  await expect(page).toHaveURL(/\/risk$/)
  await expect(page.getByRole("heading", { name: "Portfolio Risk", exact: true })).toBeVisible()
  await expect(metric(page, "Gross linear exposure")).toContainText("19.0%")
  expect(refreshRequests).toBe(0)
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Portfolio Dashboard", exact: true }).click()
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Portfolio Risk", exact: true }).click()
  await expect(page).toHaveURL(/\/risk$/)
  await page.getByRole("button", { name: "Search pages" }).click()
  await page.getByPlaceholder("Search pages").fill("Portfolio Risk")
  await page.getByRole("option", { name: /Portfolio Risk/ }).click()
  await expect(page).toHaveURL(/\/risk$/)
})

test("held hedge toggle changes exposure, beta, concentrations and position rows together", async ({ page }) => {
  await page.goto("/risk")
  const table = page.getByRole("table", { name: "Linear position details", exact: true })
  await expect(metric(page, "Net linear exposure")).toContainText("9.0%")
  await expect(table.getByRole("link", { name: "IWM", exact: true })).toBeVisible()
  await expect(page.getByText("SPY · 0.080×", { exact: true })).toBeVisible()
  await page.getByRole("checkbox", { name: "Include held hedges" }).uncheck()
  await expect(metric(page, "Gross linear exposure")).toContainText("14.0%")
  await expect(metric(page, "Net linear exposure")).toContainText("14.0%")
  await expect(table.getByRole("link", { name: "IWM", exact: true })).toHaveCount(0)
  await expect(page.getByText("SPY · 0.140×", { exact: true })).toBeVisible()
  await page.getByText("All underlying concentration values", { exact: true }).click()
  const concentration = page.getByRole("table", { name: "Underlying concentration values" })
  await expect(concentration).toContainText("71.4%")
  await expect(concentration).not.toContainText("IWM")
  await expect(page.getByRole("table", { name: "Option premiums" })).toContainText("$200.00")
})

test("searches, sorts and inspects position evidence without filtering headline metrics", async ({ page }) => {
  await page.goto("/risk")
  const table = page.getByRole("table", { name: "Linear position details", exact: true })
  await expect(table.locator("tbody tr").nth(1)).toContainText("IWM")
  await table.getByRole("button", { name: "Ticker" }).click()
  await expect(table.locator("tbody tr").nth(1)).toContainText("GLD")
  await page.getByRole("searchbox", { name: "Search positions" }).fill("GLD")
  await expect(table.locator("tbody tr")).toHaveCount(1)
  await expect(table.getByRole("link", { name: "GLD", exact: true })).toHaveAttribute("href", "/dossier/GLD")
  await expect(metric(page, "Gross linear exposure")).toContainText("19.0%")
  await table.getByText("Prices and drivers", { exact: true }).click()
  await expect(table).toContainText("Beta eligibility: unsupported asset")
  await page.getByRole("searchbox", { name: "Search positions" }).fill("does-not-exist")
  await expect(page.getByText("No positions match this search.", { exact: true })).toBeVisible()
})

test("first refresh creates a snapshot in the background with CSRF protection", async ({ page }) => {
  let saved = false
  let polls = 0
  await page.route("**/api/risk/dashboard/latest", route => route.fulfill({ status: saved ? 200 : 404, contentType: "application/json", body: JSON.stringify(saved ? riskDashboardFixture : { detail: "Missing snapshot" }) }))
  await page.route("**/api/risk/dashboard/refresh", route => {
    expect(route.request().headers()["x-csrf-token"]).toBe("smoke-csrf")
    return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ job_id: "risk-smoke-job", status: "queued" }) })
  })
  await page.route("**/api/risk/dashboard/async/risk-smoke-job", route => {
    saved = ++polls > 1
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job_id: "risk-smoke-job", status: saved ? "done" : "running", result: saved ? riskDashboardFixture : null }) })
  })
  await page.goto("/risk")
  await expect(page.getByText("No risk dashboard snapshot yet", { exact: true })).toBeVisible()
  await dismissFloatingAlerts(page)
  await page.getByRole("button", { name: "Refresh risk", exact: true }).click()
  await expect(page.getByRole("button", { name: "Refreshing risk…", exact: true })).toBeDisabled()
  await expect(metric(page, "Gross linear exposure")).toContainText("19.0%")
  await expect(page.getByRole("button", { name: "Refresh risk", exact: true })).toBeEnabled()
})

test("failed refresh preserves prior values and exposes a retry", async ({ page }) => {
  let failed = false
  await page.route("**/api/risk/dashboard/latest", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...riskDashboardFixture, freshness: { stale: failed, refresh_error: failed ? "Prices offline" : null } }) }))
  await page.route("**/api/risk/dashboard/async/risk-smoke-job", route => {
    failed = true
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job_id: "risk-smoke-job", status: "error", error: "Prices offline" }) })
  })
  await page.goto("/risk")
  await dismissFloatingAlerts(page)
  await page.getByRole("button", { name: "Refresh risk", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("Prices offline")
  await expect(metric(page, "Gross linear exposure")).toContainText("19.0%")
  await expect(page.getByText("Snapshot needs refresh.", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Refresh risk", exact: true })).toBeEnabled()
})

test("flags changed holdings and book settings on a stale snapshot", async ({ page }) => {
  await page.route("**/api/risk/dashboard/latest", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...riskDashboardFixture, freshness: { stale: true, holdings_changed: true, book_changed: true, market: { fresh: false, expected_as_of_date: "2026-10-15" } } }) }))
  await page.goto("/risk")
  await expect(page.getByText(/Holdings have changed/)).toBeVisible()
  await expect(page.getByText(/Book settings have changed/)).toBeVisible()
  await expect(page.getByText(/The latest expected close is Oct 15/)).toBeVisible()
})

for (const theme of ["light", "dark"] as const) {
  for (const width of [390, 1440]) {
    test(`risk charts and tables render in ${theme} at ${width}px without page overflow`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 })
      await page.addInitScript(value => localStorage.setItem("market-dashboard-theme", value), theme)
      await page.goto("/risk")
      await dismissFloatingAlerts(page)
      await expect(page.getByRole("heading", { name: "Portfolio Risk", exact: true })).toBeVisible()
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
      await expect(page.getByRole("img", { name: "Underlying concentration as shares of measured gross exposure", exact: true })).toBeVisible()
      await expect(page.getByRole("table", { name: "Option premiums" })).toContainText("Unavailable")
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
      expect(overflow).toBe(false)
      if (width === 1440 && theme === "light") await page.screenshot({ path: "test-results/risk-desktop.png", fullPage: true })
      if (width === 390 && theme === "dark") await page.screenshot({ path: "test-results/risk-mobile-dark.png", fullPage: true })
    })
  }
}

test.describe("risk page authentication", () => {
  test.use({ authenticated: false })
  test("redirects unauthenticated direct links to login", async ({ page }) => {
    await page.goto("/risk")
    await expect(page).toHaveURL(/\/login$/)
  })
})

test("option contracts can be searched and premiums sorted independently", async ({ page }) => {
  await page.goto("/risk")
  const table = page.getByRole("table", { name: "Option premiums" })
  await table.getByRole("button", { name: "Premium USD" }).click()
  await expect(table.getByRole("columnheader", { name: "Premium USD" })).toHaveAttribute("aria-sort", "ascending")
  await page.getByRole("searchbox", { name: "Search option contracts" }).fill("none")
  await expect(table.locator("tbody tr")).toHaveCount(0)
  await expect(page.getByText("No option contracts match this search.", { exact: true })).toBeVisible()
  await expect(metric(page, "Gross linear exposure")).toContainText("19.0%")
})
