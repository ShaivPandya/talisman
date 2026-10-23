import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

test.describe.configure({ timeout: 60_000 })

const workflows = [
  { name: "morning_brief", label: "Morning Brief", requires_ticker: false },
  { name: "thesis_review", label: "Thesis Review", requires_ticker: true },
  { name: "pre_earnings", label: "Pre-Earnings Prep", requires_ticker: true },
  { name: "post_earnings_review", label: "Post-Earnings Review", requires_ticker: true },
  { name: "weekly_portfolio_review", label: "Weekly Portfolio Review", requires_ticker: false },
  { name: "thesis_invalidation_check", label: "Thesis Invalidation Check", requires_ticker: true },
  { name: "position_dossier_pressure_test", label: "Position Dossier Pressure Test", requires_ticker: true },
  { name: "future_workflow", label: "New Configured Workflow", requires_ticker: false },
].map(workflow => ({ ...workflow, description: `Run ${workflow.label}.` }))

type ChatBody = { message: string; screen_context?: unknown; response_preferences: { thinking_enabled: boolean } }

async function openChat(page: Page) {
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).last().click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

async function mockMentions(page: Page) {
  const requests = { positions: 0, theses: 0 }
  await page.route("**/api/portfolio-positions", route => {
    requests.positions++
    return route.fulfill({ json: { positions: [
      { ticker: "NVDA", asset: "equity", direction: "long" },
      { ticker: "MSFT", asset: "equity", direction: "short" },
    ] } })
  })
  await page.route("**/api/thesis/meta", route => {
    requests.theses++
    return route.fulfill({ json: [
      { ticker: "NVDA", status: "active" }, { ticker: "META", status: "under_review" },
    ] })
  })
  return requests
}

async function recordTurns(page: Page) {
  // Keep composer option assertions independent of new-session allocation.
  await page.addInitScript(() => {
    localStorage.setItem("agent-chat-current", JSON.stringify({ sessionId: "composer-session", messages: [] }))
  })
  const requests: ChatBody[] = []
  await page.route("**/api/agent/chat", route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ contentType: "text/event-stream", body:
      `event: delta\ndata: ${JSON.stringify({ text: `Composer reply ${requests.length}` })}\n\n`
      + `event: done\ndata: ${JSON.stringify({ session_id: "composer-session" })}\n\n`,
    })
  })
  await page.route("**/api/agent/chat/async", route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: {
      job_id: "composer-job", session_id: "composer-session", status: "done", next_seq: 1,
      events: [{ seq: 1, event_type: "done", payload: { session_id: "composer-session", text: "Workflow finished." } }],
    } })
  })
  return requests
}

for (const workflow of workflows) {
  test(`slash menu starts ${workflow.label}`, async ({ page }) => {
    await mockMentions(page)
    const turns = await recordTurns(page)
    await page.route("**/api/agent/workflows", route => route.fulfill({ json: workflows }))
    await openChat(page)
    const input = page.getByRole("textbox", { name: "Message Stan" })
    await input.fill("/")
    await page.getByRole("option").filter({ has: page.getByText(workflow.label, { exact: true }) }).click()
    if (workflow.requires_ticker) {
      await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeDisabled()
      await input.pressSequentially("nvda")
      await input.press("Enter")
    }
    expect(turns).toHaveLength(0)
    await page.getByRole("button", { name: "Send message", exact: true }).click()
    await expect.poll(() => turns.map(turn => turn.message)).toEqual([
      `/workflow:${workflow.name}${workflow.requires_ticker ? ":NVDA" : ""}`,
    ])
  })
}

test("mentions complete tickers, positions and theses without fetching per keystroke", async ({ page }) => {
  const requests = await mockMentions(page)
  await openChat(page)
  expect(requests).toEqual({ positions: 0, theses: 0 })
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("Compare @nv against cash")
  await input.evaluate(element => {
    element.setSelectionRange(12, 12)
  })
  await input.press("ArrowLeft")
  await page.getByRole("option").filter({ has: page.getByText("NVDA thesis", { exact: true }) }).click()
  await expect(input).toHaveValue("Compare @NVDA thesis against cash")
  await input.fill("@ms")
  await page.getByRole("option").filter({ has: page.getByText("MSFT position", { exact: true }) }).click()
  await expect(input).toHaveValue("@MSFT position ")
  await input.fill("@meta")
  await page.getByRole("option").filter({ has: page.getByText("META", { exact: true }) }).click()
  await expect(input).toHaveValue("@META ")
  await input.fill("@brk.b")
  await input.press("Enter")
  await expect(input).toHaveValue("@BRK.B ")
  expect(requests).toEqual({ positions: 1, theses: 1 })
})

test("keyboard completion, Escape dismissal, Shift+Enter and IME preserve the draft", async ({ page }) => {
  await mockMentions(page)
  const turns = await recordTurns(page)
  await openChat(page)
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("/")
  await input.press("ArrowDown")
  await input.press("Tab")
  await expect(input).toHaveValue("/workflow:position_risk_review:")
  await input.press("Escape")
  await expect(page.getByRole("listbox")).toBeHidden()
  await expect(page.getByRole("dialog")).toBeVisible()
  await input.fill("Draft")
  await input.press("Shift+Enter")
  await expect(input).toHaveValue("Draft\n")
  await input.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true })
  expect(turns).toHaveLength(0)
})

test("context removal and Thinking apply once and never save preferences", async ({ page }) => {
  const turns = await recordTurns(page)
  let preferenceWrites = 0
  page.on("request", request => {
    if (request.method() === "PUT" && request.url().includes("agent-response-preferences")) preferenceWrites++
  })
  await openChat(page)
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await page.getByRole("button", { name: "Remove screen context", exact: true }).click()
  await expect(page.getByText("Not included with the next turn", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Thinking", exact: true }).click()
  await input.fill("First message")
  await input.press("Enter")
  await expect.poll(() => turns.length).toBe(1)
  expect(turns[0]).not.toHaveProperty("screen_context")
  expect(turns[0].response_preferences.thinking_enabled).toBe(true)
  await expect(page.getByRole("button", { name: "Thinking", exact: true })).toHaveAttribute("aria-pressed", "false")
  await expect(page.getByRole("button", { name: "Remove screen context", exact: true })).toBeVisible()
  await expect(page.getByText("Composer reply 1", { exact: true })).toBeVisible()
  await input.fill("Second message")
  await input.press("Enter")
  await expect.poll(() => turns.length).toBe(2)
  expect(turns[1]).toHaveProperty("screen_context")
  expect(turns[1].response_preferences.thinking_enabled).toBe(false)
  expect(preferenceWrites).toBe(0)
})

test("Thinking returns to a saved enabled default, and context can be reattached", async ({ page }) => {
  const turns = await recordTurns(page)
  await page.route("**/api/settings/agent-response-preferences", route => {
    return route.fulfill({ json: {
      personality: "pragmatic", warmth: "less", enthusiasm: "less", headers_lists: "less", emoji: "less",
      fast_answers: true, thinking_enabled: true, custom_instructions: "",
    } })
  })
  await openChat(page)
  const toggle = page.getByRole("button", { name: "Thinking", exact: true })
  await expect(toggle).toHaveAttribute("aria-pressed", "true")
  await toggle.click()
  await page.getByRole("button", { name: "Remove screen context", exact: true }).click()
  await page.getByRole("button", { name: "Attach screen context", exact: true }).click()
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Without thinking")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect.poll(() => turns.length).toBe(1)
  expect(turns[0].response_preferences.thinking_enabled).toBe(false)
  expect(turns[0]).toHaveProperty("screen_context")
  await expect(toggle).toHaveAttribute("aria-pressed", "true")
})

test("queued follow-ups capture message options when queued", async ({ page }) => {
  const turns = await recordTurns(page)
  await page.addInitScript(() => {
    const original = window.fetch.bind(window)
    Object.assign(window, { finishComposerStream: () => {} })
    let first = true
    window.fetch = (input, init) => {
      if (first && typeof input === "string" && input.endsWith("/agent/chat") && init?.method === "POST") {
        first = false
        return Promise.resolve(new Response(new ReadableStream({ start(controller) {
          Object.assign(window, { finishComposerStream() {
            const text = 'event: delta\ndata: {"text":"First complete"}\n\nevent: done\ndata: {"session_id":"composer-session"}\n\n'
            controller.enqueue(new TextEncoder().encode(text))
            controller.close()
          } })
        } }), { headers: { "Content-Type": "text/event-stream" } }))
      }
      return original(input, init)
    }
  })
  await openChat(page)
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("Running message")
  await input.press("Enter")
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible()
  await page.getByRole("button", { name: "Remove screen context", exact: true }).click()
  await page.getByRole("button", { name: "Thinking", exact: true }).click()
  await input.fill("Queued message")
  await input.press("Enter")
  await expect(page.getByText("Queued message", { exact: true })).toBeVisible()
  const queued = await page.evaluate(() => JSON.parse(localStorage.getItem("agent-chat-queues:v1") ?? "{}")["composer-session"][0])
  expect(queued.screenContext).toBeNull()
  expect(queued.responsePreferences.thinking_enabled).toBe(true)
  await page.evaluate(() => (window as unknown as { finishComposerStream: () => void }).finishComposerStream())
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden()
  // Exercise delivery of the captured options through the existing Send now action.
  await page.getByRole("button", { name: "Send queued message now and steer" }).click()
  await expect.poll(() => turns.length).toBe(1)
  expect(turns[0].message).toBe("Queued message")
  expect(turns[0]).not.toHaveProperty("screen_context")
  expect(turns[0].response_preferences.thinking_enabled).toBe(true)
})

test("Escape stops a live stream and keeps its follow-up draft", async ({ page }) => {
  await page.addInitScript(() => {
    const original = window.fetch.bind(window)
    Object.assign(window, { composerAborted: false })
    window.fetch = (input, init) => {
      if (typeof input === "string" && input.endsWith("/agent/chat") && init?.method === "POST") {
        return Promise.resolve(new Response(new ReadableStream({ start(controller) {
          init.signal?.addEventListener("abort", () => {
            Object.assign(window, { composerAborted: true })
            controller.error(new DOMException("Stopped", "AbortError"))
          })
        } }), { headers: { "Content-Type": "text/event-stream" } }))
      }
      return original(input, init)
    }
  })
  await openChat(page)
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("Start live stream")
  await input.press("Enter")
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible()
  await input.fill("Draft during generation")
  await input.press("Escape")
  await expect.poll(() => page.evaluate(() => (window as unknown as { composerAborted: boolean }).composerAborted)).toBe(true)
  await expect(page.getByRole("dialog")).toBeVisible()
  await expect(input).toHaveValue("Draft during generation")
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeEnabled()
})

test("Escape stops a durable turn without closing chat or clearing a follow-up", async ({ page }) => {
  await page.route("**/api/agent/chat/async", route => route.fulfill({ json: {
    job_id: "composer-running", session_id: "composer-session", status: "running", next_seq: 1,
    events: [{ seq: 1, event_type: "status", payload: { status: "running" } }],
  } }))
  let releasePoll!: () => void
  const poll = new Promise<void>(resolve => { releasePoll = resolve })
  await page.route("**/api/agent/chat/async/composer-running/events?**", async route => {
    await poll
    await route.fulfill({ json: { status: "cancelled", events: [], next_seq: 1 } }).catch(() => {})
  })
  let cancellations = 0
  await page.route("**/api/agent/chat/async/composer-running/cancel", route => {
    cancellations++
    releasePoll()
    return route.fulfill({ json: { status: "cancelled" } })
  })
  await openChat(page)
  await page.getByRole("button", { name: "Weekly Portfolio Review", exact: true }).click()
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible()
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("Keep this draft")
  await input.press("Escape")
  await expect.poll(() => cancellations).toBe(1)
  await expect(page.getByRole("dialog")).toBeVisible()
  await expect(input).toHaveValue("Keep this draft")
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeEnabled()
})

test("mobile composer provides workflows, mentions and message controls", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMentions(page)
  await openChat(page)
  await page.getByRole("button", { name: "Choose workflow", exact: true }).click()
  await expect(page.getByRole("listbox", { name: "Workflow suggestions" })).toBeVisible()
  await page.getByRole("textbox", { name: "Message Stan" }).press("Escape")
  await page.getByRole("button", { name: "Mention ticker, position or thesis", exact: true }).click()
  await expect(page.getByRole("listbox", { name: "Mention suggestions" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Thinking", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Remove screen context", exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath("composer-mobile.png") })
})

test("manual mentions work when saved suggestions fail, and emails do not trigger completion", async ({ page }) => {
  await page.route("**/api/portfolio-positions", route => route.fulfill({ status: 503, json: { detail: "Unavailable" } }))
  await page.route("**/api/thesis/meta", route => route.fulfill({ status: 503, json: { detail: "Unavailable" } }))
  await openChat(page)
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("email@example.com")
  await expect(page.getByRole("listbox")).toBeHidden()
  await input.fill("@XYZ")
  await page.getByRole("option").filter({ has: page.getByText("XYZ", { exact: true }) }).click()
  await expect(input).toHaveValue("@XYZ ")
})
