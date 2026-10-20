import { expect, test } from "../smoke/fixtures"

type Event = {
  type?: string
  transaction?: string
  contexts?: { trace?: { op?: string } }
  op?: string
  measurements?: Record<string, { value: number }>
}

test("Sentry records route navigation and browser vitals with scrubbed content", async ({ page }) => {
  const events: Event[] = []
  const envelopes: string[] = []
  await page.route("https://sentry.invalid/**", async route => {
    const body = route.request().postData() ?? ""
    envelopes.push(body)
    const lines = body.split("\n")
    for (let index = 1; index + 1 < lines.length; index += 2) {
      const header = JSON.parse(lines[index]) as { type: string }
      if (["transaction", "span"].includes(header.type)) events.push(JSON.parse(lines[index + 1]) as Event)
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" })
  })
  await page.goto("/?token=private-query-value")
  await expect(page.getByRole("heading", { name: "Portfolio Dashboard", exact: true })).toBeVisible()
  await expect.poll(() => events.some(event => event.contexts?.trace?.op === "pageload"), { timeout: 15_000 }).toBe(true)

  // Produce a real layout shift before any input (recent-input shifts are
  // intentionally excluded from CLS). Resolve only after Chromium observes it.
  await page.evaluate(() => new Promise<void>(resolve => {
    const observer = new PerformanceObserver(list => {
      if (list.getEntries().some(entry => {
        const shift = entry as PerformanceEntry & { value?: number; hadRecentInput?: boolean }
        return (shift.value ?? 0) > 0 && !shift.hadRecentInput
      })) {
        observer.disconnect()
        resolve()
      }
    })
    observer.observe({ type: "layout-shift", buffered: true })
    const banner = document.createElement("div")
    banner.style.cssText = "height:120px;min-height:120px;background:#fff"
    ;(document.querySelector("main") ?? document.getElementById("root"))?.prepend(banner)
  }))

  // Use a real trusted interaction. A delayed handler makes Chromium emit an
  // EventTiming entry; no production SDK exports or synthetic vital values.
  await page.evaluate(() => {
    const button = document.createElement("button")
    button.id = "baseline-interaction"
    button.textContent = "Measure interaction"
    button.style.cssText = "position:fixed;top:10px;left:10px;z-index:99999"
    button.addEventListener("click", () => {
      const until = performance.now() + 160
      while (performance.now() < until) { /* produce an observable interaction */ }
      button.style.transform = "translateY(1px)"
    })
    document.body.appendChild(button)
  })
  await page.locator("#baseline-interaction").click()
  // Let the browser paint and its EventTiming observer process the interaction
  // before starting a new route transaction.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await page.evaluate(() => document.querySelector("#baseline-interaction")?.remove())
  await page.getByRole("link", { name: "Workspace", exact: true }).first().click()
  await expect(page).toHaveURL(/\/workspace$/)
  await expect.poll(() => events.some(event => event.contexts?.trace?.op === "navigation" && event.transaction === "/workspace"), { timeout: 15_000 }).toBe(true)
  // Browser vitals may be attached to a transaction or sent as standalone spans.
  await expect.poll(() => events.some(event => (event.measurements?.lcp?.value ?? 0) > 0), { timeout: 15_000 }).toBe(true)
  // INP is finalized on page hide in SDK 9, rather than on each interaction.
  await page.goto("about:blank")
  await expect.poll(() => events.some(event => typeof event.measurements?.inp?.value === "number"), { timeout: 15_000 }).toBe(true)
  await expect.poll(() => events.some(event => typeof event.measurements?.cls?.value === "number"), { timeout: 15_000 }).toBe(true)
  expect(envelopes.join("\n")).not.toContain("private-query-value")
  expect(envelopes.join("\n")).not.toContain("Measure interaction")
})
