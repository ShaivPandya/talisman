import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

// TL-219: a model call retried mid-stream sends `reset`, and the bubble shows the answer once.

const sessionId = "retry-reset-session"

test.describe.configure({ timeout: 60_000 })

function frame(event: string, payload: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
}

async function openChat(page: Page) {
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

async function sendMessage(page: Page, message: string) {
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill(message)
  await input.press("Enter")
}

async function streamLiveReply(page: Page, frames: string[]) {
  await page.route("**/api/agent/chat", async route => {
    if (route.request().method() !== "POST") return route.fallback()
    await route.fulfill({
      headers: { "Content-Type": "text/event-stream" },
      body: [...frames, frame("done", { usage: {}, session_id: sessionId })].join(""),
    })
  })
}

test("a live stream that retried shows the answer once", async ({ page }) => {
  await streamLiveReply(page, [
    frame("delta", { text: "Hello " }),
    frame("delta", { text: "wor" }),
    frame("reset", { text: "" }),
    frame("delta", { text: "Hello " }),
    frame("delta", { text: "world" }),
  ])
  await openChat(page)
  await sendMessage(page, "Say hello")

  await expect(page.getByText("Hello world", { exact: true })).toBeVisible()
  await expect(page.getByText("Hello worHello world")).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden()
})

test("a reset keeps the text streamed before the failed attempt", async ({ page }) => {
  await streamLiveReply(page, [
    frame("delta", { text: "Let me check. " }),
    frame("delta", { text: "Based on " }),
    frame("reset", { text: "Let me check. " }),
    frame("delta", { text: "Based on that, fine." }),
  ])
  await openChat(page)
  await sendMessage(page, "Say hello")

  await expect(page.getByText("Let me check. Based on that, fine.", { exact: true })).toBeVisible()
  await expect(page.getByText(/Based on Based on/)).toHaveCount(0)
})

for (const narrated of [false, true]) {
  test(`a server budget error survives stream completion${narrated ? " after tool narration" : ""}`, async ({ page }) => {
    let duplicateJobs = 0
    await page.route("**/api/agent/chat/async", route => {
      duplicateJobs += 1
      return route.fulfill({ status: 500, json: { detail: "Unexpected replay" } })
    })
    await streamLiveReply(page, [
      ...(narrated ? [
        frame("delta", { text: "Let me read the reports." }),
        frame("narration", { id: "narration:0", text: "Let me read the reports." }),
        frame("reset", { text: "" }),
      ] : []),
      frame("tool_result", { id: "report-1", name: "read_name_document", status: "ok" }),
      frame("error", { message: "Input token budget exceeded (200000)" }),
    ])
    await openChat(page)
    await sendMessage(page, "Analyze all the DAL reports")

    await expect(page.getByText("Input token budget exceeded (200000)", { exact: true })).toBeVisible()
    await expect(page.getByText("Agent returned an empty response.")).toHaveCount(0)
    await expect(page.getByText("I couldn't generate a response for that request. Please try again.")).toHaveCount(0)
    await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden()
    expect(duplicateJobs).toBe(0)
    await expect.poll(() => page.evaluate(() => {
      const saved = JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}")
      return saved.messages?.at(-1)?.messageStatus
    })).toBe("failed")
  })
}

test("a durable job replays a retry's reset and shows the answer once", async ({ page }) => {
  await page.route("**/api/agent/chat/async", route => route.fulfill({ json: {
    job_id: "retry-reset-job", session_id: sessionId, status: "running", next_seq: 1,
    events: [{ seq: 1, event_type: "status", payload: { status: "running" } }],
  } }))
  await page.route("**/api/agent/chat/async/retry-reset-job/events?**", route => route.fulfill({ json: {
    job_id: "retry-reset-job", session_id: sessionId, status: "done", next_seq: 7,
    events: [
      { seq: 2, event_type: "delta", payload: { text: "Hello wor" } },
      { seq: 3, event_type: "reset", payload: { text: "" } },
      { seq: 4, event_type: "delta", payload: { text: "Hello " } },
      { seq: 5, event_type: "delta", payload: { text: "world" } },
      { seq: 7, event_type: "done", payload: { session_id: sessionId } },
    ],
  } }))
  await openChat(page)
  await page.getByRole("button", { name: "Use console layout" }).click()
  await page.getByRole("button", { name: "Weekly Portfolio Review", exact: true }).click()

  await expect(page.getByText("Hello world", { exact: true })).toBeVisible()
  await expect(page.getByText("Hello worHello world")).toHaveCount(0)
})
