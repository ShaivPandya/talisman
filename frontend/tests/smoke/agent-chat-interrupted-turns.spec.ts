import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

// TL-208: a turn interrupted mid-stream (stop, tab close, crash) must not leave the composer busy.

const stuckSessionId = "stuck-chat-session"
const interruptedAssistant = {
  id: "stuck-assistant",
  role: "assistant",
  content: "Half an answer about liquidity",
  timestamp: 2,
  clientTurnId: "stuck-turn",
  isStreaming: true,
  statusText: "Running get_portfolio...",
  toolCalls: [{ name: "get_portfolio", id: "tool-1", status: "running" }],
}

test.describe.configure({ timeout: 60_000 })

async function recordChatPosts(page: Page): Promise<string[]> {
  const sent: string[] = []
  await page.route("**/api/agent/chat", async route => {
    if (route.request().method() !== "POST") return route.fallback()
    sent.push(String(route.request().postDataJSON()?.message ?? ""))
    await route.fulfill({
      headers: { "Content-Type": "text/event-stream" },
      body: [
        `event: delta\ndata: ${JSON.stringify({ text: `Reply ${sent.length}` })}\n\n`,
        `event: done\ndata: ${JSON.stringify({ usage: {}, session_id: stuckSessionId })}\n\n`,
      ].join(""),
    })
  })
  return sent
}

async function openChat(page: Page) {
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

async function routeStuckSession(page: Page) {
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: stuckSessionId, title: "Stuck conversation", started_at: new Date().toISOString(), message_count: 2,
  }] }))
  await page.route(`**/api/memory/sessions/${stuckSessionId}`, route => route.fulfill({ json: {
    title: "Stuck conversation",
    active_jobs: [],
    // The server copy as saved before the fix: still streaming, mid tool-run.
    transcript: [
      { id: "stuck-user", role: "user", content: "How is liquidity?", timestamp: 1, client_turn_id: "stuck-turn" },
      {
        ...interruptedAssistant,
        is_streaming: true,
        status_text: interruptedAssistant.statusText,
        client_turn_id: "stuck-turn",
      },
    ],
  } }))
}

test("reopening an interrupted chat from History shows its text and an idle composer", async ({ page }) => {
  const sent = await recordChatPosts(page)
  await routeStuckSession(page)
  await openChat(page)

  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Stuck conversation", { exact: true }).click()
  await expect(page.getByText("Half an answer about liquidity")).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden()

  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("Next question")
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeVisible()
  await input.press("Enter")
  await expect.poll(() => sent).toEqual(["Next question"])
  await expect(page.getByText("Reply 1", { exact: true })).toBeVisible()
})

test("messages queued behind an interrupted turn send when the chat is reopened", async ({ page }) => {
  const sent = await recordChatPosts(page)
  await routeStuckSession(page)
  await page.addInitScript(sessionId => {
    localStorage.setItem("agent-chat-queues:v1", JSON.stringify({
      [sessionId]: [{ id: "queued-1", content: "Queued follow-up", createdAt: 1 }],
    }))
  }, stuckSessionId)
  await openChat(page)

  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Stuck conversation", { exact: true }).click()
  await expect.poll(() => sent).toEqual(["Queued follow-up"])
  await expect(page.getByText("Reply 1", { exact: true })).toBeVisible()
  await expect(page.getByText(/message(s)? queued/)).toBeHidden()
})

test("a reload saved mid tool-run restores an idle composer", async ({ page }) => {
  const sent = await recordChatPosts(page)
  await page.addInitScript(({ sessionId, assistant }) => {
    if (sessionStorage.getItem("interrupted-seeded")) return
    // The local copy saved during a tool run: not streaming, but with a status line and a running chip.
    localStorage.setItem("agent-chat-current", JSON.stringify({
      sessionId,
      messages: [
        { id: "stuck-user", role: "user", content: "How is liquidity?", timestamp: 1, clientTurnId: "stuck-turn" },
        { ...assistant, isStreaming: false },
      ],
    }))
    sessionStorage.setItem("interrupted-seeded", "true")
  }, { sessionId: stuckSessionId, assistant: interruptedAssistant })
  await openChat(page)

  await expect(page.getByText("Half an answer about liquidity")).toBeVisible()
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden()
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("After reload")
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeVisible()
  await input.press("Enter")
  await expect.poll(() => sent).toEqual(["After reload"])
})
