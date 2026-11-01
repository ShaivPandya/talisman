import { expect, test } from "./fixtures"

test.beforeEach(async ({ page }) => {
  await page.route("**/api/portfolio-positions", route => route.fulfill({ json: { positions: [] } }))
  await page.route("**/api/hedge-positions", route => route.fulfill({ json: { positions: [] } }))
  await page.route("**/api/portfolio-settings", route => route.fulfill({ json: { book_size: 135000 } }))
})

test("catches up a stale broker statement and links to approval review", async ({ page }) => {
  let completed = false
  let starts = 0
  let polls = 0
  await page.route("**/api/portfolio-positions/ibkr-flex-status", route => route.fulfill({ json: {
    configured: true, status: completed ? "ok" : "stale", stale: !completed,
    as_of: completed ? "2026-10-30" : "2026-10-29", expected_as_of: "2026-10-30",
    pending_proposals: completed ? [{ approval_id: "smoke-approval", action_id: "update_portfolio_positions" }] : [],
  } }))
  await page.route("**/api/admin/jobs/enqueue-ibkr-flex-sync", route => {
    starts++
    expect(route.request().method()).toBe("POST")
    expect(route.request().headers()["x-csrf-token"]).toBe("smoke-csrf")
    return route.fulfill({ status: 202, json: { job_id: "flex-sync", status: "queued" } })
  })
  await page.route("**/api/admin/jobs/flex-sync", route => {
    polls++
    completed = true
    return route.fulfill({ json: { job_id: "flex-sync", status: "done", result: {} } })
  })
  await page.goto("/portfolio/edit")
  const panel = page.getByRole("region", { name: "IBKR Flex sync" })
  await expect(panel.getByText("IBKR Flex · Statement is stale")).toBeVisible()
  await expect(panel.getByText(/Expected statement: 2026-10-30/)).toBeVisible()
  await panel.getByRole("button", { name: "Sync IBKR Flex now" }).click()
  await expect(panel.getByRole("button", { name: "Pulling statement…" })).toBeDisabled()
  await expect(panel.getByText("IBKR Flex · Statement received")).toBeVisible()
  await expect(panel.getByText(/1 broker change proposal\(s\) awaiting approval/)).toBeVisible()
  await expect(panel.getByRole("link", { name: "Review positions" })).toHaveAttribute("href", "/workspace?approval_id=smoke-approval")
  expect(starts).toBe(1)
  expect(polls).toBe(1)
  await panel.getByRole("link", { name: "Review positions" }).click()
  await expect(page.getByRole("dialog", { name: "Review Approval" })).toBeVisible()
})

test("reports a failed broker pull and permits retry", async ({ page }) => {
  await page.route("**/api/portfolio-positions/ibkr-flex-status", route => route.fulfill({ json: {
    configured: true, status: "stale", stale: true, as_of: "2026-10-29",
  } }))
  await page.route("**/api/admin/jobs/enqueue-ibkr-flex-sync", route => route.fulfill({
    status: 202, json: { job_id: "failed-flex", status: "queued" },
  }))
  await page.route("**/api/admin/jobs/failed-flex", route => route.fulfill({ json: {
    job_id: "failed-flex", status: "error", error: "Unable to reach IBKR Flex Web Service.",
  } }))
  await page.goto("/portfolio/edit")
  const panel = page.getByRole("region", { name: "IBKR Flex sync" })
  await panel.getByRole("button", { name: "Sync IBKR Flex now" }).click()
  await expect(panel.getByText(/Unable to reach IBKR Flex Web Service/)).toBeVisible()
  await expect(panel.getByRole("button", { name: "Sync IBKR Flex now" })).toBeEnabled()
  await expect(panel.getByText("Statement as of 2026-10-29")).toBeVisible()
})
