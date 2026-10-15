import type { Page } from "@playwright/test"
import { authenticate, expect, test } from "./fixtures"

test.use({ timezoneId: "America/New_York" })

async function installCatalog(page: Page) {
  const source = {
    source_id: "alternative_tsa", name: "TSA Checkpoint Travel Numbers", group: "demand", group_label: "Demand and traffic",
    question: "Is airline demand strengthening?", coverage: "US travel throughput; sector proxy", cadence: "Daily", notes: "Sector proxy, not company revenue.",
    url: "https://www.tsa.gov/travel/passenger-volumes", license_url: "https://www.tsa.gov/website-information", attribution: "TSA",
    availability: { status: "ready", message: "Public daily observations", missing_credentials: [] },
    parameter_schema: { properties: { limit: { type: "integer", default: 500, minimum: 1, maximum: 1000 } }, required: [] },
  }
  const proposed = { ticker: "MSFT", name: "Example operating site", bbox: [-118.25, 33.73, -118.24, 33.74],
    citations: [{ title: "Company site reference", url: "https://www.microsoft.com" }], proposal_id: "proposal-1", status: "needs_confirmation" }
  const sites: object[] = []
  await page.route("**/api/alternative-data/**", async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown
    if (path.endsWith("/catalog")) body = { sources: [source, { ...source, source_id: "alternative_firms", name: "NASA FIRMS",
      group: "physical", group_label: "Sites and physical conditions", availability: { status: "setup_required", message: "Free MAP_KEY required", missing_credentials: ["FIRMS_MAP_KEY"] } }],
      groups: { demand: "Demand and traffic", physical: "Sites and physical conditions" }, sites, site_proposals: [] }
    else if (path.endsWith("/fetch")) body = { source_id: source.source_id, status: "ok", observations: [
      { date: "2026-10-12", metric: "checkpoint_travelers", value: 2400000, unit: "people" },
      { date: "2026-10-13", metric: "checkpoint_travelers", value: 2500000, unit: "people" }],
      as_of: "2026-10-13", fetched_at: "2026-10-14T12:00:00Z", freshness: { stale: false, status: "known" }, citations: [{ title: "TSA official data", url: source.url }], warnings: [source.notes] }
    else if (path.endsWith("/sites/suggest")) body = { job_id: "site-job", status: "done", result: { proposals: [proposed] } }
    else if (path.endsWith("/sites/confirm")) { const site = { ...route.request().postDataJSON(), site_id: "site-1", status: "confirmed" }; sites.push(site); body = site }
    else if (route.request().method() === "DELETE" && path.endsWith("/sites/site-1")) { sites.splice(0); body = { status: "inactive" } }
    else return route.fulfill({ status: 404, json: { error: "Unknown fixture route" } })
    await route.fulfill({ json: body })
  })
}

test.beforeEach(async ({ page }) => { await installCatalog(page); await authenticate(page) })

test("searches a shared catalog and displays cited observations", async ({ page }) => {
  await page.goto("/alternative-data")
  await expect(page.getByRole("heading", { name: "Alternative Data", exact: true })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Alternative Data" })).toHaveCount(1)
  await page.getByRole("textbox", { name: "Search alternative data" }).fill("airline")
  await page.getByRole("button", { name: /TSA Checkpoint/ }).click()
  await page.getByRole("button", { name: "Fetch data", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Source result" })).toBeVisible()
  await expect(page.getByRole("link", { name: "TSA official data" })).toBeVisible()
  await expect(page.getByRole("cell", { name: "2,500,000", exact: true })).toBeVisible()
  await expect(page.locator("dl > div").filter({ hasText: "Observed through" }).locator("dd")).toHaveText("10/13/2026")
  await page.getByRole("application").scrollIntoViewIfNeeded()
  await expect(page.getByRole("application")).toContainText("Oct 13")
  await expect(page.getByText("Sector proxy, not company revenue.").first()).toBeVisible()
})

test("shows credential setup without offering a broken fetch", async ({ page }) => {
  await page.goto("/alternative-data?source=alternative_firms")
  await expect(page.getByText(/Setup required: FIRMS_MAP_KEY/)).toBeVisible()
  await expect(page.getByRole("button", { name: "Fetch data", exact: true })).toBeDisabled()
})

test("requires a person to confirm cited site proposals", async ({ page }) => {
  await page.goto("/alternative-data?ticker=MSFT")
  await page.getByRole("button", { name: "Suggest sites", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Example operating site" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Company site reference" })).toBeVisible()
  await page.getByRole("button", { name: "Confirm site", exact: true }).click()
  await expect(page.getByText("Example operating site · confirmed")).toBeVisible()
  await expect(page.getByRole("button", { name: "Confirm site", exact: true })).toHaveCount(0)
  await page.getByRole("button", { name: "Remove site", exact: true }).click()
  await expect(page.getByText("Example operating site · confirmed")).toHaveCount(0)
})

test("keeps catalog controls within a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/alternative-data?source=alternative_tsa")
  await expect(page.getByRole("heading", { name: "TSA Checkpoint Travel Numbers", exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})

test("shows durable job failures immediately", async ({ page }) => {
  await page.route("**/api/alternative-data/fetch", route => route.fulfill({ json: {
    job_id: "failed-job", status: "error", error: "Source worker was unavailable",
  } }))
  await page.goto("/alternative-data?source=alternative_tsa")
  await page.getByRole("button", { name: "Fetch data", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("Source worker was unavailable")
  await expect(page.getByRole("button", { name: "Fetch data", exact: true })).toBeEnabled()
})

test("links enriched analyzer evidence to the shared catalog without changing scores", async ({ page }) => {
  await page.route("**/api/portfolio-analyzer/async", route => route.fulfill({ json: {
    job_id: "analyzer-job", status: "done", result: { course_of_action: { action_queue: [{
      ticker: "MSFT", asset: "Microsoft", direction: "long", action: "Hold Long", conviction_band: "small",
      priority_score: 55, scenario_score: 72, score_delta: 2, confidence: 0.8, gate_status: "pass",
      deterministic_rationale: "Deterministic score is unchanged.", factor_breakdown: [],
    }] } },
  } }))
  await page.route("**/api/portfolio-analyzer/course-of-action/brief/async", route => route.fulfill({ json: {
    job_id: "brief-job", status: "done", result: { brief: "Hold. Sector hiring provides context.",
      alternative_data: { ticker: "MSFT", coverage_warnings: ["Hiring is a sector proxy."], citations: [], catalog_url: "/alternative-data?ticker=MSFT",
        evidence: [{ source_id: "alternative_indeed", attribution: "Indeed Hiring Lab", status: "ok", as_of: "2026-10-02", observations: [],
          result_url: "/alternative-data?source=alternative_indeed&ticker=MSFT" }] } },
  } }))
  await page.goto("/analyzer")
  await page.getByRole("button", { name: "Run Mission", exact: true }).click()
  await expect(page.getByText("Deterministic score is unchanged.")).toBeVisible()
  await page.getByRole("button", { name: "AI Brief", exact: true }).click()
  await expect(page.getByText("Hiring is a sector proxy.")).toBeVisible()
  await expect(page.getByRole("link", { name: "Indeed Hiring Lab" })).toHaveAttribute("href", "/alternative-data?source=alternative_indeed&ticker=MSFT")
  await expect(page.getByText("Deterministic score is unchanged.")).toBeVisible()
})
