import type { Page } from "@playwright/test"
import { dossierResponse, expect, smokeApproval, test } from "./fixtures"

const baseline = process.env.TL198_BASELINE === "1"
const production = process.env.TL198_PRODUCTION === "1"

async function instrument(page: Page) {
  await page.addInitScript(production => {
    type Fiber = {
      type?: { name?: string; displayName?: string }
      flags: number
      child?: Fiber
      sibling?: Fiber
    }
    const metrics = { active: false, renders: {} as Record<string, number>, longTasks: [] as number[], started: 0 }
    let previous = new Set<Fiber>()
    const hook = {
      supportsFiber: true,
      renderers: new Map(),
      inject(renderer: unknown) { this.renderers.set(1, renderer); return 1 },
      onCommitFiberRoot(_id: number, root: { current: Fiber }) {
        const committed = new Set<Fiber>()
        const walk = (fiber?: Fiber) => {
          if (!fiber) return
          committed.add(fiber)
          const name = fiber.type?.displayName ?? fiber.type?.name
          // Bailed-out subtrees retain flags from their last render. Count
          // performed work only on fibers that changed in this commit.
          if (metrics.active && !previous.has(fiber) && name && (fiber.flags & 1)) {
            metrics.renders[name] = (metrics.renders[name] ?? 0) + 1
          }
          walk(fiber.child)
          walk(fiber.sibling)
        }
        walk(root.current)
        previous = committed
      },
      onCommitFiberUnmount() {},
    }
    Object.assign(window, { renderingMetrics: metrics })
    // Render counts need the development hook. Production timings should
    // measure the app without walking its whole fiber tree on every commit.
    if (!production) Object.assign(window, { __REACT_DEVTOOLS_GLOBAL_HOOK__: hook })
    new PerformanceObserver(list => {
      if (metrics.active) metrics.longTasks.push(...list.getEntries().filter(entry => entry.startTime >= metrics.started).map(entry => entry.duration))
    }).observe({ type: "longtask" })
  }, production)
}

async function startMeasurement(page: Page) {
  // Wait for pending work before measuring the next user interaction.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await page.evaluate(() => {
    const { renderingMetrics: metrics } = window as unknown as { renderingMetrics: { active: boolean; renders: object; longTasks: number[]; started: number } }
    metrics.renders = {}
    metrics.longTasks = []
    metrics.started = performance.now()
    metrics.active = true
  })
}

async function report(page: Page, name: string) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const result = await page.evaluate(() => {
    const { renderingMetrics: metrics } = window as unknown as { renderingMetrics: { active: boolean; renders: Record<string, number>; longTasks: number[] } }
    metrics.active = false
    return {
      renders: Object.fromEntries(Object.entries(metrics.renders).filter(([name]) => /Workspace|PositionDossier|MarkdownRenderer|Dialog|DataTable|TimeSeriesChart|Form|Results/.test(name))),
      longTasks: metrics.longTasks, longestTaskMs: Math.max(0, ...metrics.longTasks),
    }
  })
  console.log(JSON.stringify({ name, baseline, production, ...result }))
  await test.info().attach(name, { body: JSON.stringify(result, null, 2), contentType: "application/json" })
  return result
}

for (const dialog of ["workspace approval", "dossier approval", "dossier status"]) {
  test(`${dialog} typing renders only its dialog`, async ({ page }) => {
    test.skip(production, "Component render names are measured with the development React renderer")
    await instrument(page)
    const content = Array.from({ length: 150 }, (_, i) => `## Evidence ${i}\n\n**Margins** support the thesis.\n\n- Recheck demand.\n- Watch pricing.\n`).join("\n")
    await page.route("**/api/dossier/MSFT", route => route.fulfill({ json: {
      ...dossierResponse,
      thesis: { ...dossierResponse.thesis, content },
      pending_approvals: [smokeApproval],
    } }))
    let note
    if (dialog === "workspace approval") {
      await page.goto("/workspace?approval_id=smoke-approval")
      note = page.getByLabel("Decision note", { exact: true })
    } else {
      await page.goto("/dossier/MSFT?tab=thesis")
      if (dialog === "dossier status") {
        await page.getByRole("button", { name: "Dismiss action item alert", exact: true }).click()
        await page.getByRole("button", { name: "Propose Status Change", exact: true }).click()
        note = page.getByPlaceholder("Why is the status changing?")
      } else {
        await page.getByTitle("Review and apply internal state change", { exact: true }).click()
        note = page.getByLabel("Approval note", { exact: true })
      }
    }
    await expect(note).toBeVisible()
    await startMeasurement(page)
    await note.pressSequentially("Reviewed the evidence", { delay: 20 })
    const result = await report(page, dialog)
    if (!baseline) {
      expect(result.renders.Workspace ?? 0).toBe(0)
      expect(result.renders.PositionDossier ?? 0).toBe(0)
      expect(result.renders.MarkdownRenderer ?? 0).toBe(0)
      expect(result.renders.WorkspaceRiskCard ?? 0).toBe(0)
      if (dialog === "dossier approval") expect(result.renders.ThesisStatusDialog ?? 0).toBe(0)
      expect(Object.values(result.renders).some(count => count > 0)).toBe(true)
    }
  })
}

test("Screener typing skips 500 results and results survive navigation", async ({ page }) => {
  test.skip(production, "Render counts use the development renderer")
  await instrument(page)
  await page.route("**/api/quality-screen/async", route => route.fulfill({ json: {
    job_id: "rendering-screen", status: "done", result: {
      results_df: Array.from({ length: 500 }, (_, i) => ({ ticker: `PERF${i}`, quality: i / 500 })),
      benchmark_name: "S&P 500", scored_count: 500,
    },
  } }))
  await page.goto("/screeners")
  await page.getByRole("button", { name: "Custom Tickers", exact: true }).click()
  await page.getByRole("button", { name: "Run Screen", exact: true }).click()
  await expect(page.getByRole("cell", { name: "PERF0", exact: true })).toBeVisible()
  await startMeasurement(page)
  await page.getByPlaceholder("AAPL, MSFT, GOOG").pressSequentially("AAPL, MSFT", { delay: 20 })
  const result = await report(page, "screener typing")
  if (!baseline) expect(result.renders.DataTable ?? 0).toBe(0)
  await page.getByRole("button", { name: "Short", exact: true }).click()
  await page.getByRole("button", { name: "Quality", exact: true }).click()
  if (!baseline) await expect(page.getByRole("cell", { name: "PERF0", exact: true })).toBeVisible()
  const retainedOnTab = await page.getByRole("cell", { name: "PERF0", exact: true }).count()
  await page.getByRole("link", { name: "Workspace", exact: true }).click()
  await page.getByRole("link", { name: "Screeners", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Screeners", exact: true })).toBeVisible()
  if (!baseline) await expect(page.getByRole("cell", { name: "PERF0", exact: true })).toBeVisible()
  const retainedOnRoute = await page.getByRole("cell", { name: "PERF0", exact: true }).count()
  console.log(JSON.stringify({ name: "screener retention", retainedOnTab, retainedOnRoute }))
  if (!baseline) {
    expect(retainedOnTab).toBe(1)
    expect(retainedOnRoute).toBe(1)
  }
})

for (const screen of [
  { tab: "Short", endpoint: "short-screen", row: { Ticker: "RETAINED", Company: "Original" } },
  { tab: "Long", endpoint: "long-screen", row: { Ticker: "RETAINED", Company: "Original" } },
  { tab: "Price Momentum", endpoint: "price-momentum", row: { ticker: "RETAINED" } },
  { tab: "Fund. Momentum", endpoint: "fundamental-momentum", row: { ticker: "RETAINED" } },
]) {
  test(`${screen.tab} retains its last completed run and accepts new results`, async ({ page }) => {
    let runs = 0
    await page.route(`**/api/${screen.endpoint}/async`, route => {
      const row = runs++ === 0 ? screen.row : { ...screen.row, ticker: "REPLACED", Ticker: "REPLACED" }
      const result = screen.endpoint === "fundamental-momentum" ? { eps: { results_df: [row] } } : { results_df: [row] }
      return route.fulfill({ json: { job_id: "retention-test", status: "done", result } })
    })
    await page.goto("/screeners")
    await page.getByRole("button", { name: screen.tab, exact: true }).click()
    await page.getByRole("button", { name: "Run Screen", exact: true }).click()
    await expect(page.getByRole("cell", { name: "RETAINED", exact: true })).toBeVisible()
    await page.getByRole("link", { name: "Workspace", exact: true }).click()
    await page.getByRole("link", { name: "Screeners", exact: true }).click()
    await page.getByRole("button", { name: screen.tab, exact: true }).click()
    await expect(page.getByRole("cell", { name: "RETAINED", exact: true })).toBeVisible()
    await page.getByRole("button", { name: "Run Screen", exact: true }).click()
    await expect(page.getByRole("cell", { name: "REPLACED", exact: true }).first()).toBeVisible()
    await expect(page.getByRole("cell", { name: "RETAINED", exact: true })).toHaveCount(0)
  })
}

test("an in-flight Screener cannot restore cached results after logout", async ({ page, apiMocks }) => {
  let release!: () => void
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.route("**/api/quality-screen/async", async route => {
    await responseGate
    await route.fulfill({ json: { job_id: "old-user", status: "done", result: { results_df: [{ ticker: "OLD_USER" }] } } })
  })
  await page.goto("/screeners")
  const started = page.waitForRequest("**/api/quality-screen/async")
  await page.getByRole("button", { name: "Run Screen", exact: true }).click()
  await started
  await page.getByRole("button", { name: "Sign out", exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  const completed = page.waitForResponse("**/api/quality-screen/async")
  release()
  await completed
  await page.route("**/api/auth/login", route => {
    apiMocks.isAuthenticated = true
    return route.fulfill({ json: { username: "next-user", roles: ["admin"], csrfToken: "next-user-csrf" } })
  })
  await page.getByLabel("Password").fill("next-user-password")
  await page.getByRole("button", { name: "Sign in", exact: true }).click()
  await page.getByRole("link", { name: "Screeners", exact: true }).click()
  await expect(page.getByText("Configure inputs above and click Run Screen.", { exact: true })).toBeVisible()
  await expect(page.getByRole("cell", { name: "OLD_USER", exact: true })).toHaveCount(0)
})

test("Dossier status dialog preserves a canceled reason and submits the edited draft", async ({ page }) => {
  let submitted: unknown
  await page.route("**/api/thesis/MSFT/status", async route => {
    submitted = route.request().postDataJSON()
    await route.fulfill({ json: { status: "pending_approval_created", approval_id: "status-test" } })
  })
  await page.goto("/dossier/MSFT")
  await page.getByRole("button", { name: "Dismiss action item alert", exact: true }).click()
  await page.getByRole("button", { name: "Propose Status Change", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "Propose Thesis Status Change", exact: true })
  await dialog.getByPlaceholder("Why is the status changing?").fill("Recheck demand")
  await page.keyboard.press("Escape")
  await expect(dialog).toBeHidden()
  await page.getByRole("button", { name: "Propose Status Change", exact: true }).click()
  await expect(dialog.getByPlaceholder("Why is the status changing?")).toHaveValue("Recheck demand")
  await dialog.getByPlaceholder("Why is the status changing?").fill("Demand recovered")
  await dialog.getByRole("button", { name: "Propose Status Change", exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(submitted).toEqual({ status: "under_review", reason: "Demand recovered" })
})

test("rapid timeframe changes finish every portfolio tile with the latest return", async ({ page, apiMocks }) => {
  apiMocks.approvalsDismissed = true
  const requests = new Set<string>()
  const tickers = Array.from({ length: 20 }, (_, i) => `RACE${i}`)
  await page.route("**/api/portfolio?**", route => {
    const timeframe = new URL(route.request().url()).searchParams.get("timeframe") ?? "This Week"
    requests.add(timeframe)
    const endValues: Record<string, number> = { "This Week": 110, Daily: 125, Weekly: 150, Monthly: 200 }
    const end = endValues[timeframe] ?? 110
    return route.fulfill({ json: {
      holdings: tickers.map(ticker => ({ ticker, role: "position" })), position_order: tickers,
      positions: Object.fromEntries(tickers.map(ticker => [ticker, [
        { date: "2026-05-13", value: 100 }, { date: "2026-05-14", value: end },
      ]])),
    } })
  })
  await page.goto("/")
  await expect(page.getByText("+10.00%", { exact: true })).toHaveCount(20)
  await expect.poll(() => requests.size).toBe(4)
  const monthly = await page.getByRole("button", { name: "Monthly", exact: true }).elementHandle()
  const daily = await page.getByRole("button", { name: "Daily", exact: true }).elementHandle()
  await monthly!.evaluate(button => (button as HTMLButtonElement).click())
  await page.waitForFunction(() => document.querySelector('[aria-label="Portfolio position charts"]')?.getAttribute("aria-busy") === "true")
  await daily!.evaluate(button => (button as HTMLButtonElement).click())
  await page.waitForFunction(() => document.querySelector('[aria-label="Portfolio position charts"]')?.getAttribute("aria-busy") === "false")
  await expect(page.getByText("+25.00%", { exact: true })).toHaveCount(20)
  await expect(page.getByText("+100.00%", { exact: true })).toHaveCount(0)
})

test("20-position dashboard timeframe switch avoids long tasks", async ({ page, apiMocks }) => {
  test.setTimeout(120_000)
  await instrument(page)
  apiMocks.approvalsDismissed = true
  const tickers = Array.from({ length: 20 }, (_, i) => `PERF${i}`)
  await page.route("**/api/portfolio?**", route => {
    const timeframe = new URL(route.request().url()).searchParams.get("timeframe")
    // Match portfolio_dashboard.TIMEFRAMES: 5 days of 15m bars, 90 daily
    // points, 2 years of weekly points, and 5 years of monthly points.
    const count = timeframe === "Monthly" ? 60 : timeframe === "Weekly" ? 104 : timeframe === "Daily" ? 90 : 130
    const date = (point: number) => new Date(timeframe === "Monthly"
      ? Date.UTC(2021, 9 + point, 1)
      : timeframe === "Weekly"
        ? Date.UTC(2024, 9, 1 + point * 7)
        : timeframe === "Daily"
          ? Date.UTC(2026, 6, point + 1)
          : Date.UTC(2026, 9, 19 + Math.floor(point / 26), 13, 30 + (point % 26) * 15)).toISOString()
    return route.fulfill({ json: {
      holdings: tickers.map(ticker => ({ ticker, role: "position" })), position_order: tickers,
      positions: Object.fromEntries(tickers.map((ticker, i) => [ticker, Array.from({ length: count }, (_, point) => ({
        date: date(point), value: 100 + i + point / 5,
      }))])),
    } })
  })
  await page.goto("/")
  await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(20)
  // Warm every timeframe, then measure the same cached switches in each build.
  for (const timeframe of ["Daily", "Weekly", "Monthly", "Past Week"]) {
    await page.getByRole("button", { name: timeframe, exact: true }).click()
    await expect(page.getByRole("button", { name: timeframe, exact: true })).toHaveAttribute("data-active", "true")
    await expect(page.getByRole("status").filter({ hasText: /^Updating/ })).toHaveCount(0)
  }
  await page.waitForTimeout(1700)
  const longestTasks: number[] = []
  const profiler = process.env.TL198_PROFILE === "1" ? await page.context().newCDPSession(page) : null
  await profiler?.send("Profiler.enable")
  for (const timeframe of ["Monthly", "Daily", "Weekly", "Past Week"]) {
    // Resolve the accessible target before timing. Playwright's role lookup
    // walks the SVG-heavy page and must not count as application work.
    const button = await page.getByRole("button", { name: timeframe, exact: true }).elementHandle()
    if (!button) throw new Error(`Missing timeframe control: ${timeframe}`)
    await startMeasurement(page)
    await profiler?.send("Profiler.start")
    await button.click()
    await page.waitForFunction(button => button?.getAttribute("data-active") === "true", button)
    await page.waitForFunction(() => document.querySelector('[aria-label="Portfolio position charts"]')?.getAttribute("aria-busy") !== "true")
    // Entry animations run for 1.5 seconds in the baseline build.
    await page.waitForTimeout(1700)
    const result = await report(page, `dashboard ${timeframe}`)
    longestTasks.push(result.longestTaskMs)
    await expect(page.locator("main .recharts-wrapper > .recharts-surface")).toHaveCount(20)
    if (profiler) {
      const { profile } = await profiler.send("Profiler.stop")
      await test.info().attach(`cpu-${timeframe}`, { body: JSON.stringify(profile), contentType: "application/json" })
    }
  }
  if (!baseline && process.env.TL198_MEASURE === "1") expect(Math.max(...longestTasks)).toBeLessThanOrEqual(50)
})
