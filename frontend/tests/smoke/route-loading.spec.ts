import { expect, test } from "./fixtures"

const baseline = process.env.TL197_BASELINE === "1"
const measure = process.env.TL197_MEASURE === "1"
test.beforeEach(async ({ page }) => {
  await page.route("**/api/thesis/meta", route => route.fulfill({
    status: 200, contentType: "application/json", body: "[]",
  }))
})
const routes = [
  { path: "/", page: "PortfolioDashboard", api: "/api/portfolio", title: "Portfolio Dashboard" },
  { path: "/workspace", page: "Workspace", api: "/api/workspace", title: "Action queue" },
  { path: "/liquidity", page: "Liquidity", api: "/api/liquidity", title: "Liquidity Dashboard" },
  { path: "/dossier/MSFT", page: "PositionDossier", api: "/api/dossier/MSFT", title: "MSFT" },
]

for (const scenario of routes) {
  test(`starts auth, chunk and data together on ${scenario.path}`, async ({ page }) => {
    let authFinished = false
    let dataStartedBeforeAuth = false
    let chunkStartedBeforeAuth = false
    let authRequests = 0
    const dataRequests: string[] = []
    const starts: Record<string, number> = {}
    page.on("request", request => {
      const url = new URL(request.url())
      let key: string | undefined
      if (url.pathname === "/api/auth/me") { key = "auth"; authRequests += 1 }
      else if (url.pathname === scenario.api) {
        key = "data"
        dataRequests.push(request.url())
        if (starts.data === undefined) dataStartedBeforeAuth = !authFinished
      } else if ((url.pathname.includes(`/${scenario.page}`) && url.pathname.endsWith(".js")) ||
        url.pathname === `/src/pages/${scenario.page}.tsx`) {
        key = "chunk"
        chunkStartedBeforeAuth = !authFinished
      }
      if (key && starts[key] === undefined) starts[key] = Date.now()
    })
    await page.route("**/api/auth/me", async route => {
      await new Promise(resolve => setTimeout(resolve, 400))
      authFinished = true
      await route.fallback()
    })
    await page.route(/\/(?:assets|src\/pages)\/.*\.(?:js|tsx)(?:\?.*)?$/, async route => {
      if (route.request().url().includes(`/${scenario.page}`)) {
        await new Promise(resolve => setTimeout(resolve, 200))
      }
      await route.fallback()
    })
    const firstData = page.waitForResponse(response => new URL(response.url()).pathname === scenario.api)
    await page.goto(scenario.path)
    expect((await firstData).status()).toBe(200)
    await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible()
    await expect(page.getByRole("heading", { name: scenario.title, exact: true })).toBeVisible()
    const spread = Math.max(...Object.values(starts)) - Math.min(...Object.values(starts))
    console.log(`TL197_TIMING ${JSON.stringify({ path: scenario.path, starts, spread })}`)
    if (!baseline) {
      expect(Object.keys(starts).sort()).toEqual(["auth", "chunk", "data"])
      expect(dataStartedBeforeAuth).toBe(true)
      expect(chunkStartedBeforeAuth).toBe(true)
      expect(authRequests).toBe(1)
      expect(dataRequests.filter(url => url === dataRequests[0])).toHaveLength(1)
      if (measure) expect(spread).toBeLessThanOrEqual(50)
    }
  })
}

test("shows the shell while keeping protected content and actions behind auth", async ({ page }) => {
  let releaseAuth!: () => void
  const authGate = new Promise<void>(resolve => { releaseAuth = resolve })
  const requests: string[] = []
  page.on("request", request => { if (request.url().includes("/api/")) requests.push(request.url()) })
  await page.route("**/api/auth/me", async route => { await authGate; await route.fallback() })
  await page.goto("/")
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible()
  await expect(page.getByRole("progressbar", { name: "Loading page" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeDisabled()
  expect(requests.some(url => url.includes("approvals/summary"))).toBe(false)
  releaseAuth()
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
  await expect(page.getByRole("progressbar", { name: "Loading page" })).toHaveCount(0)
})

test("starts the initial GET on every automatic-data deep link before auth resolves", async ({ page }) => {
  test.setTimeout(60_000)
  // Hold auth and data at the network boundary: this checks startup scheduling
  // without mounting pages against fabricated business-data responses.
  await page.route("**/api/**", () => {})
  const deepLinks = [
    ["/", "/api/portfolio"], ["/portfolio/edit", "/api/portfolio-positions"],
    ["/risk", "/api/risk/dashboard/latest"], ["/workspace", "/api/workspace"],
    ["/ideas", "/api/ideas"], ["/ideas/example", "/api/ideas/example"],
    ["/theses", "/api/thesis/meta"], ["/analyzer", "/api/settings/llm"],
    ["/hedging-tool", "/api/hedging-tool/prefill"], ["/sizer", "/api/portfolio-sizer/prefill"],
    ["/momentum", "/api/momentum"], ["/ontology", "/api/ontology/runs"],
    ["/index-dashboard", "/api/index-dashboard"], ["/fx-dashboard", "/api/fx-dashboard"],
    ["/commodities", "/api/commodities"], ["/market-technicals", "/api/vix-term-structure"],
    ["/sector-metrics", "/api/sector-metrics"], ["/positioning", "/api/positioning/instruments"],
    ["/sentiment", "/api/sentiment/put-call"], ["/fx-model", "/api/fx-model/pairs"],
    ["/economic-growth", "/api/economic-growth"], ["/labor-market", "/api/labor-market"],
    ["/housing", "/api/housing"], ["/liquidity", "/api/liquidity"],
    ["/country-dashboard", "/api/country-dashboard"], ["/central-banks", "/api/central-banks"],
    ["/industry-monitor", "/api/industry-monitor"], ["/yield-curve", "/api/yield-curve"],
    ["/bond-dashboard", "/api/bond-dashboard"], ["/commodities-curve", "/api/commodities-curve"],
    ["/commodity-research", "/api/commodity-research"], ["/portfolio-news", "/api/portfolio-news"],
    ["/settings/ai", "/api/settings/llm"], ["/settings/policy-matrix", "/api/settings/financial-policy-matrix"],
    ["/alternative-data?ticker=NVDA", "/api/alternative-data/catalog"],
    ["/dossier/BRK.B", "/api/dossier/BRK.B"], ["/explore/nvda", "/api/dossier/NVDA"],
  ]
  for (const [path, api] of deepLinks) {
    const firstData = page.waitForRequest(request => new URL(request.url()).pathname === api)
    await page.goto(path)
    const request = await firstData
    expect(request.method(), path).toBe("GET")
    await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeDisabled()
  }
})

for (const intent of ["hover", "focus"] as const) {
  test(`${intent} preloads a page and clicking reuses its chunk`, async ({ page }) => {
    await page.goto("/")
    await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
    const chunk = /\/(?:assets\/ThesisManager-[^/]+\.js|src\/pages\/ThesisManager\.tsx)(?:\?.*)?$/
    let downloads = 0
    page.on("request", request => { if (chunk.test(request.url())) downloads += 1 })
    const link = page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Investment Theses", exact: true })
    const loaded = page.waitForResponse(response => chunk.test(response.url()))
    await link[intent]()
    await (await loaded).finished()
    await link.click()
    await expect(page).toHaveURL(/\/theses$/)
    await expect(page.getByRole("heading", { name: "Investment Theses", exact: true })).toBeVisible()
    expect(downloads).toBe(1)
  })
}

test("shows progress for a cold navigation and handles browser history", async ({ page }) => {
  let releaseChunk!: () => void
  const gate = new Promise<void>(resolve => { releaseChunk = resolve })
  const chunk = /\/(?:assets\/ThesisManager-[^/]+\.js|src\/pages\/ThesisManager\.tsx)(?:\?.*)?$/
  await page.route(chunk, async route => { await gate; await route.fallback() })
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
  // A DOM click avoids hover prefetch, exercising a genuinely cold navigation.
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Investment Theses", exact: true }).dispatchEvent("click", { button: 0 })
  await expect(page.getByRole("progressbar", { name: "Loading page" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
  releaseChunk()
  await expect(page.getByRole("heading", { name: "Investment Theses", exact: true })).toBeVisible()
  await expect(page.getByRole("progressbar", { name: "Loading page" })).toHaveCount(0)
  await page.goBack()
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
  await page.goForward()
  await expect(page.getByRole("heading", { name: "Investment Theses", exact: true })).toBeVisible()
})

test.describe("logged out", () => {
  test.use({ authenticated: false })
  test("redirects once when speculative data also returns 401", async ({ page }) => {
    let documents = 0
    page.on("request", request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents += 1 })
    await page.route("**/api/portfolio?**", async route => {
      await new Promise(resolve => setTimeout(resolve, 100))
      await route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"Not authenticated"}' })
    })
    await page.goto("/")
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toHaveCount(0)
    await expect(page.getByLabel("Password", { exact: true })).toBeVisible()
    expect(documents).toBe(1)
  })
})
