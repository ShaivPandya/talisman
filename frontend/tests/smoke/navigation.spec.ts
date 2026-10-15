import type { Page } from "@playwright/test"

import { authenticate, expect, test } from "./fixtures"

async function fulfillJson(page: Page, url: string, body: unknown, status = 200) {
  await page.route(url, route => route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  }))
}

async function mockCompanyExplorer(page: Page) {
  await page.route("**/api/chart", async route => {
    const body = route.request().postDataJSON() as { ticker?: string }
    const ticker = String(body.ticker || "").toUpperCase()
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ticker,
        name: ticker === "NVDA" ? "NVIDIA Corporation" : ticker,
        price_data: [
          { Date: "2026-01-02", Close: 100 },
          { Date: "2026-06-02", Close: 120 },
        ],
      }),
    })
  })

  await fulfillJson(page, "**/api/financials", {
    data_source: "sec_edgar",
    financial_currency: "USD",
    metrics: {
      revenue_cagr_3y: 0.42,
      eps_cagr_3y: 0.2,
      avg_yoy_revenue_growth_3q: 0.1,
      avg_yoy_eps_growth_3q: 0.05,
      market_cap: 3_000_000_000_000,
      market_cap_currency: "USD",
      interest_coverage: 12,
      operating_margin: 0.5,
      net_income_margin: 0.4,
    },
  })

  await fulfillJson(page, "**/api/dossier/NVDA", {
    ticker: "NVDA",
    position: { ticker: "NVDA", asset: "equity", instrument_type: "security", direction: "long" },
    related_portfolio_legs: [],
    overview_content: "NVDA sells accelerated computing.",
    overview_parsed: null,
    management_quality: { content: null, parsed: null },
    thesis: {
      meta: { ticker: "NVDA", status: "active", last_evaluated: null },
      content: "NVIDIA remains the accelerated computing platform.",
      status_history: [],
    },
    thesis_claims: [],
    catalysts: [],
    kill_conditions: [],
    evaluations: [],
    what_changed: { counts: { total: 0 }, items: [] },
    action_items: [],
    watch_triggers: [],
    pending_approvals: [],
  })

  await fulfillJson(page, "**/api/dossier/ZZZZ", {
    ticker: "ZZZZ",
    position: null,
    related_portfolio_legs: [],
    overview_content: null,
    overview_parsed: null,
    management_quality: { content: null, parsed: null },
    thesis: { meta: null, content: null, status_history: [] },
    thesis_claims: [],
    catalysts: [],
    kill_conditions: [],
    evaluations: [],
  })

  await fulfillJson(page, "**/api/valuation/NVDA", {})
  await fulfillJson(page, "**/api/risk/positions/NVDA/latest", { detail: "missing" }, 404)
}

function primaryNav(page: import("@playwright/test").Page) {
  return page.getByRole("navigation", { name: "Primary navigation" })
}

test("shows grouped sidebar sections on desktop", async ({ page }) => {
  await authenticate(page)
  await page.goto("/")

  const nav = primaryNav(page)
  await expect(nav.getByText("Core", { exact: true })).toBeVisible()
  await expect(nav.getByText("Labs", { exact: true })).toBeVisible()
  await expect(nav.getByText("Monitors", { exact: true })).toBeVisible()
  await expect(nav.getByText("Macro", { exact: true })).toBeVisible()
  await expect(nav.getByText("Assets", { exact: true })).toBeVisible()
  await expect(nav.getByText("Settings", { exact: true })).toBeVisible()
})

test("navigates via workflow sidebar links on desktop", async ({ page }) => {
  await authenticate(page)
  await page.goto("/")

  const nav = primaryNav(page)

  await nav.getByRole("link", { name: "Workspace" }).click()
  await expect(page).toHaveURL(/\/workspace$/)
  await expect(page.getByRole("heading", { name: "Action queue" })).toBeVisible()

  await nav.getByRole("link", { name: "Portfolio Dashboard" }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard" })).toBeVisible()

  await nav.getByRole("link", { name: "Ontology Workbench" }).click()
  await expect(page).toHaveURL(/\/ontology$/)
  await expect(page.getByRole("heading", { name: "Ontology Workbench" })).toBeVisible()

  await nav.getByRole("link", { name: "Liquidity" }).click()
  await expect(page).toHaveURL(/\/liquidity$/)
  await expect(page.getByRole("heading", { name: "Liquidity Dashboard" })).toBeVisible()
})

test("navigates via command palette page search", async ({ page }) => {
  await authenticate(page)
  await page.goto("/")

  await page.getByRole("button", { name: "Search pages" }).click()
  await expect(page.getByPlaceholder("Search pages")).toBeVisible()

  await page.getByPlaceholder("Search pages").fill("Workspace")
  await page.getByRole("option", { name: /Workspace/ }).click()

  await expect(page).toHaveURL(/\/workspace$/)
  await expect(page.getByRole("heading", { name: "Action queue" })).toBeVisible()
})

test("opens company explorer from the labs sidebar", async ({ page }) => {
  await authenticate(page)
  await page.goto("/")

  const nav = primaryNav(page)
  await nav.getByRole("link", { name: "Company Explorer" }).click()

  await expect(page).toHaveURL(/\/explore$/)
  await expect(page.getByRole("heading", { name: "Company Explorer" })).toBeVisible()
  await expect(page.getByLabel("Ticker")).toBeVisible()
  await expect(page.getByText("Enter a ticker to open the company summary.")).toBeVisible()
})

test("shows a company summary and dossier links from the explorer", async ({ page }) => {
  await mockCompanyExplorer(page)
  await authenticate(page)
  await page.goto("/explore")

  await page.getByLabel("Ticker").fill("nvda")
  await page.getByRole("button", { name: "Open", exact: true }).click()

  await expect(page).toHaveURL(/\/explore\/NVDA$/)
  await expect(page.getByText("NVIDIA Corporation")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Price" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Financials" })).toBeVisible()
  await expect(page.getByText("3Y Revenue CAGR")).toBeVisible()
  await expect(page.getByText("+42.00%")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible()
  await expect(page.getByText("NVDA sells accelerated computing.")).toBeVisible()
  await expect(page.getByRole("link", { name: "Dossier", exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "Thesis", exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "Risk", exact: true })).toBeVisible()

  await page.getByRole("link", { name: "Thesis", exact: true }).click()
  await expect(page).toHaveURL(/\/dossier\/NVDA\?tab=thesis$/)
  await expect(page.getByText("NVIDIA remains the accelerated computing platform.")).toBeVisible()

  await page.goto("/explore/NVDA")
  await page.getByRole("link", { name: "Risk", exact: true }).click()
  await expect(page).toHaveURL(/\/dossier\/NVDA\?tab=risk$/)
  await expect(page.getByRole("heading", { name: "Risk Analysis Snapshot" })).toBeVisible()
})

test("loads a company explorer page without dossier links when no dossier exists", async ({ page }) => {
  await mockCompanyExplorer(page)
  await authenticate(page)
  await page.goto("/explore/ZZZZ")

  await expect(page.getByText("ZZZZ", { exact: true }).first()).toBeVisible()
  await expect(page.getByRole("heading", { name: "Price" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Financials" })).toBeVisible()
  await expect(page.getByText("3Y Revenue CAGR")).toBeVisible()
  await expect(page.getByText("No overview on file.")).toBeVisible()
  await expect(page.getByRole("link", { name: "Dossier", exact: true })).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Thesis", exact: true })).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Risk", exact: true })).toHaveCount(0)
})

test("legacy portfolio path redirects to dashboard", async ({ page }) => {
  await authenticate(page)
  await page.goto("/portfolio")

  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard" })).toBeVisible()
})

test("legacy optimizer path redirects to analyzer", async ({ page }) => {
  await authenticate(page)
  await page.goto("/optimizer")

  await expect(page).toHaveURL(/\/analyzer$/)
})

test("legacy screener paths redirect to screeners", async ({ page }) => {
  await authenticate(page)
  await page.goto("/quality")

  await expect(page).toHaveURL(/\/screeners$/)
  await expect(page.getByRole("heading", { name: "Screeners" })).toBeVisible()
})
