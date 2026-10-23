import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

const sessionId = "activity-session"
const answer = "Your book has concentrated technology exposure."
const narration = "Let me pull your book."
const thinking = "Comparing the book against the benchmark."
const source = { url: "https://example.com/fed-minutes", title: "Fed minutes" }
const tool = {
  id: "activity-tool",
  name: "search_web",
  status: "ok",
  arguments: { query: "Fed minutes" },
  result_preview: JSON.stringify({ summary: "Rates were held steady." }),
  result_bytes: 38,
  elapsed_ms: 1200,
  as_of: "2026-10-22",
  cache: "miss_fetch",
}

async function openChat(page: Page) {
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

function frame(event: string, payload: Record<string, unknown>) {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
}

async function expectActivity(page: Page) {
  const dialog = page.getByRole("dialog")
  const summary = dialog.locator("summary", { hasText: "Activity" })
  await expect(summary).toContainText("1 tool")
  await expect(summary).toContainText("thinking")
  await summary.click()
  await expect(dialog.getByText(thinking, { exact: true })).toBeVisible()
  await expect(dialog.getByText(narration, { exact: true })).toBeVisible()
  const row = dialog.locator("summary", { hasText: "Web Search" })
  await expect(row).toContainText("query: Fed minutes")
  await expect(row).toContainText("1.2 s")
  await expect(row).toContainText("as of Oct 22, 2026")
  await row.click()
  await expect(dialog.getByText("Rates were held steady.")).toBeHidden()
  await dialog.getByText("Result · 38 B").click()
  await expect(dialog.getByText("Rates were held steady.")).toBeVisible()
  await expect(dialog.getByRole("link", { name: /Fed minutes/ })).toHaveAttribute("href", source.url)
  // The answer is the final round only.
  await expect(dialog.locator(".prose").filter({ hasText: answer })).toHaveText(answer)
  await expect(dialog.locator(".prose").getByText(narration)).toHaveCount(0)
}

test("tool activity, narration, thinking and sources render live and survive reloads", async ({ page }) => {
  await page.route("**/api/agent/chat", async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      headers: { "Content-Type": "text/event-stream" },
      body: [
        frame("thinking", { id: "thinking:agent_chat:0:0", text: thinking }),
        frame("delta", { text: narration }),
        frame("tool_call", { name: tool.name, id: tool.id }),
        frame("narration", { id: "narration:0", text: narration }),
        frame("reset", { text: "" }),
        frame("tool_progress", { name: tool.name, id: tool.id, status: "running", arguments: tool.arguments }),
        frame("tool_result", { ...tool, sources: [source] }),
        frame("delta", { text: answer }),
        frame("done", {
          session_id: sessionId,
          user_message_id: body.user_message_id,
          assistant_message_id: body.assistant_message_id,
          tool_calls: [tool],
          sources: [source],
          thinking: [{ id: "thinking:agent_chat:0:0", text: thinking }],
          narration: [{ id: "narration:0", text: narration }],
        }),
      ].join(""),
    })
  })
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "Activity reply", started_at: new Date().toISOString(), message_count: 2,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "Activity reply", active_jobs: [], transcript: [
      { id: "activity-user", role: "user", content: "Review my positions", timestamp: 1, status: "complete" },
      { id: "activity-answer", parent_id: "activity-user", role: "assistant", content: answer, timestamp: 2,
        status: "complete", tool_calls: [tool], sources: [source],
        thinking: [{ id: "thinking:agent_chat:0:0", text: thinking }],
        narration: [{ id: "narration:0", text: narration }] },
    ],
  } }))

  await page.goto("/workspace")
  await openChat(page)
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Review my positions")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByRole("dialog").locator(".prose").filter({ hasText: answer })).toBeVisible()
  await expectActivity(page)

  // The local snapshot restores it all.
  await page.reload()
  await openChat(page)
  await expectActivity(page)

  // So does the server's saved message, with no local snapshot.
  await page.evaluate(() => {
    localStorage.removeItem("agent-chat-current")
    localStorage.removeItem("agent-chat-sessions:v1")
  })
  await page.reload()
  await openChat(page)
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Activity reply", { exact: true }).click()
  await expectActivity(page)
})

test("a running tool shows its arguments before its result arrives", async ({ page }) => {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    const encoder = new TextEncoder()
    let stream: ReadableStreamDefaultController<Uint8Array> | undefined
    Object.assign(window, {
      activityEvent(event: string, payload: Record<string, unknown>) {
        stream?.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`))
      },
    })
    window.fetch = (input, init) => {
      if (typeof input === "string" && input.endsWith("/agent/chat") && init?.method === "POST") {
        return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
          start(controller) { stream = controller },
        }), { headers: { "Content-Type": "text/event-stream" } }))
      }
      return originalFetch(input, init)
    }
  })
  const push = (event: string, payload: Record<string, unknown>) =>
    page.evaluate(({ event, payload }) => {
      (window as unknown as { activityEvent: (e: string, p: Record<string, unknown>) => void }).activityEvent(event, payload)
    }, { event, payload })

  await page.goto("/workspace")
  await openChat(page)
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Search the Fed minutes")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible()
  await push("tool_call", { name: tool.name, id: tool.id })
  await push("tool_progress", { name: tool.name, id: tool.id, status: "running", arguments: tool.arguments })

  const dialog = page.getByRole("dialog")
  const summary = dialog.locator("summary", { hasText: "Activity" })
  await expect(summary).toContainText("Web Search")
  await summary.click()
  const row = dialog.locator("summary", { hasText: "Web Search" }).last()
  await expect(row).toContainText("query: Fed minutes")
  await expect(row).toContainText("Running")

  await push("tool_result", { ...tool, sources: [source] })
  await expect(row).toContainText("Complete")
  await expect(row).toContainText("1.2 s")
  // Sources show as soon as a tool returns them, before the answer is done.
  await expect(dialog.getByRole("link", { name: /Fed minutes/ })).toHaveAttribute("href", source.url)
})
