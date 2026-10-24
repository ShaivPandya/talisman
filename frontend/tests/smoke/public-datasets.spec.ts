import { expect, test } from "./fixtures"

test("shows dated publisher forecasts and missing data alongside the market panel", async ({ page }) => {
  await page.route(url => url.pathname.startsWith("/api/economic-growth"), async route => {
    const backdrop = new URL(route.request().url()).pathname.endsWith("/backdrop")
    await route.fulfill({ json: backdrop ? {
      fetched_at: "2026-10-24T12:00:00Z", as_of: "2026-10-23", note: "Published forecasts belong to their publishers.",
      readings: [
        { key: "payrolls", label: "Nonfarm payrolls", value: 159044, unit: "thousands of persons", as_of: "2026-09-01", source_url: "https://fred.stlouisfed.org/series/PAYEMS", status: "ok", kind: "observation" },
        { key: "nyfed", label: "New York Fed Staff Nowcast", value: 2.5, unit: "% annualized", as_of: "2026-10-23", vintage_date: "2026-10-23", forecast_period: "2026Q3", next_release_note: "Fridays except federal holidays", source_url: "https://www.newyorkfed.org/research/policy/nowcast", status: "ok", kind: "publisher_nowcast" },
        { key: "cleveland", label: "Cleveland Fed CPI nowcast", value: null, unit: "% YoY", as_of: "2026-10-23", forecast_period: "2026-10", source_url: "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting", status: "missing", kind: "publisher_nowcast" },
      ],
    } : { commodities: {}, equities: {}, currencies: {}, equity_periods: ["1-mo"], currency_periods: ["1-mo"], crb_available: false } })
  })
  await page.goto("/economic-growth")
  const panel = page.getByRole("region", { name: "Economic activity and published forecasts" })
  await expect(panel.getByRole("cell", { name: "159,044" })).toBeVisible()
  await expect(panel.getByRole("row").filter({ hasText: "Cleveland Fed CPI nowcast" })).toContainText("Missing")
  await expect(panel.getByRole("row").filter({ hasText: "New York Fed Staff Nowcast" })).toContainText("2026Q3")
  await expect(panel.getByText("Publisher vintage: 2026-10-23")).toBeVisible()
  await expect(panel.getByText(/Next release: Fridays/)).toBeVisible()
  await expect(panel.getByRole("link", { name: "Official source" }).first()).toHaveAttribute("href", "https://fred.stlouisfed.org/series/PAYEMS")
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})

test("a person can confirm, select, and remove an exact company mapping", async ({ page }) => {
  const mappings: Array<Record<string, unknown>> = []
  const source = {
    source_id: "alternative_clinical_trials", name: "ClinicalTrials.gov studies", group: "healthcare", group_label: "Clinical and drug evidence",
    question: "What studies list the reviewed lead sponsor?", coverage: "Exact reviewed sponsor", cadence: "Weekdays", url: "https://clinicaltrials.gov/data-api/api",
    license_url: "https://clinicaltrials.gov/about-site/terms-conditions", attribution: "ClinicalTrials.gov", notes: "Exact sponsor required.", reviewed_field: "sponsor", access: "public",
    availability: { status: "ready", message: "Exact sponsor required.", missing_credentials: [] },
    parameter_schema: { properties: { mapping_id: { type: "string" }, sponsor: { type: "string" } }, required: [] },
  }
  await page.route("**/api/alternative-data/**", async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith("/catalog")) return route.fulfill({ json: { sources: [source], groups: { healthcare: "Clinical and drug evidence" }, sites: [], site_proposals: [], reviewed_mappings: mappings } })
    if (path.endsWith("/mappings/confirm")) {
      const mapping = { ...route.request().postDataJSON(), mapping_id: "alt-mapping-reviewed", confirmed_at: "2026-10-24", confirmed_by: "person" }
      mappings.push(mapping)
      return route.fulfill({ json: mapping })
    }
    if (route.request().method() === "DELETE") { mappings.splice(0); return route.fulfill({ json: { status: "inactive" } }) }
    return route.fulfill({ status: 404, json: { error: "Unexpected fixture request" } })
  })
  await page.goto("/alternative-data?ticker=ABC&source=alternative_clinical_trials")
  await page.getByLabel("Exact reviewed name or title").fill("Reviewed Sponsor Inc")
  await page.getByLabel("Mapping evidence URL").fill("https://example.com/annual-report")
  await page.getByRole("button", { name: "Confirm company mapping", exact: true }).click()
  await expect(page.getByText("Reviewed Sponsor Inc · reviewed")).toBeVisible()
  await page.getByRole("combobox", { name: "Reviewed company mapping" }).selectOption("alt-mapping-reviewed")
  await expect(page.getByRole("combobox", { name: "Reviewed company mapping" })).toHaveValue("alt-mapping-reviewed")
  await page.getByRole("button", { name: "Remove mapping" }).click()
  await expect(page.getByText("Reviewed Sponsor Inc · reviewed")).toHaveCount(0)
})
