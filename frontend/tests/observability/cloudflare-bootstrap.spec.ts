import { expect, test } from "../smoke/fixtures"

test("Cloudflare probe and session start together, with password fallback when Access is unavailable", async ({ page }) => {
  const starts: Record<string, number> = {}
  page.on("request", request => {
    const path = new URL(request.url()).pathname
    if (path === "/api/auth/me" || path === "/cdn-cgi/access/get-identity") starts[path] = Date.now()
  })
  await page.route("**/cdn-cgi/access/get-identity", async route => {
    await new Promise(resolve => setTimeout(resolve, 300))
    await route.fulfill({ status: 404 })
  })
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
  expect(Math.abs(starts["/api/auth/me"] - starts["/cdn-cgi/access/get-identity"])).toBeLessThan(50)
  await page.getByRole("button", { name: "Sign out", exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible()
})

test("retains Access authentication when the optional session lookup fails", async ({ page }) => {
  await page.route("**/cdn-cgi/access/get-identity", route => route.fulfill({ json: { email: "user@example.com" } }))
  await page.route("**/api/auth/me", route => route.fulfill({ status: 401, json: { detail: "No password session" } }))
  await page.route("**/cdn-cgi/access/logout", route => route.fulfill({ status: 200, body: "Signed out" }))
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Sign out", exact: true }).click()
  await expect(page).toHaveURL(/\/cdn-cgi\/access\/logout$/)
})

test("keeps a rejected Access identity out of protected pages", async ({ page }) => {
  await page.route("**/cdn-cgi/access/get-identity", route => route.fulfill({ status: 401 }))
  await page.goto("/workspace")
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole("heading", { name: "Action queue", exact: true })).toHaveCount(0)
})
