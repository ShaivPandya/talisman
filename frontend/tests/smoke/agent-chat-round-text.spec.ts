import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

const sessionId = "round-text-session"
const narration = "Let me pull your book."
const answer = "Your book has concentrated technology exposure."
const content = `${narration}\n\n${answer}`

test.describe.configure({ timeout: 60_000 })

async function openChat(page: Page) {
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

type RoundStream = {
  roundTextEvent: (event: string, payload: Record<string, unknown>) => void
  closeRoundTextStream: () => void
}

async function pushEvent(page: Page, event: string, payload: Record<string, unknown>) {
  await page.evaluate(({ event, payload }) => {
    (window as unknown as RoundStream).roundTextEvent(event, payload)
  }, { event, payload })
}

test("tool-round paragraphs render live and survive local and server history reloads", async ({ page }) => {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    const encoder = new TextEncoder()
    let stream: ReadableStreamDefaultController<Uint8Array> | undefined
    Object.assign(window, {
      roundTextEvent(event: string, payload: Record<string, unknown>) {
        stream?.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`))
      },
      closeRoundTextStream() { stream?.close(); stream = undefined },
    })
    window.fetch = (input, init) => {
      if (typeof input === "string" && input.endsWith("/agent/chat") && init?.method === "POST") {
        return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
          start(controller) { stream = controller },
          cancel() { stream = undefined },
        }), { headers: { "Content-Type": "text/event-stream" } }))
      }
      return originalFetch(input, init)
    }
  })
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "Round-separated reply", started_at: new Date().toISOString(), message_count: 2,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "Round-separated reply", active_jobs: [],
    transcript: [
      { role: "user", content: "Review my positions", timestamp: 1 },
      { role: "assistant", content, timestamp: 2, status: "complete", is_streaming: false },
    ],
  } }))

  await page.goto("/workspace")
  await openChat(page)
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Review my positions")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible()
  await pushEvent(page, "delta", { text: narration })
  await pushEvent(page, "tool_call", { name: "query_ontology", id: "round-tool" })
  await expect(page.getByText(narration, { exact: true })).toBeVisible()
  await pushEvent(page, "tool_result", { name: "query_ontology", id: "round-tool", status: "ok" })
  await pushEvent(page, "delta", { text: `\n\n${answer}` })
  const liveText = page.getByRole("dialog").locator(".whitespace-pre-wrap").filter({ hasText: narration })
  await expect(liveText).toHaveText(content)
  expect(await liveText.textContent()).toBe(content)
  await pushEvent(page, "done", { usage: {}, session_id: sessionId })
  await page.evaluate(() => (window as unknown as RoundStream).closeRoundTextStream())

  const paragraphs = page.getByRole("dialog").locator(".prose").filter({ hasText: narration }).locator("p")
  await expect(paragraphs).toHaveText([narration, answer])
  expect(await page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}")
    return saved.messages?.at(-1)?.content
  })).toBe(content)

  await page.reload()
  await openChat(page)
  await expect(paragraphs).toHaveText([narration, answer])

  // With no local transcript, History must restore the server's saved text.
  await page.evaluate(() => {
    localStorage.removeItem("agent-chat-current")
    localStorage.removeItem("agent-chat-sessions:v1")
  })
  await page.reload()
  await openChat(page)
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Round-separated reply", { exact: true }).click()
  await expect(paragraphs).toHaveText([narration, answer])
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden()
})
