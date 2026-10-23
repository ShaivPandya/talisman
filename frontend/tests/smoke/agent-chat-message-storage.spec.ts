import { test, expect } from "./fixtures"

test("server message ids and structured content survive History and reload", async ({ page }) => {
  const sessionId = "message-storage-session"
  const source = { url: "https://example.com/report", title: "Liquidity report" }
  const tool = { id: "stored-tool", name: "get_portfolio", status: "ok", arguments: { fresh: true }, result: { value: 42 } }
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "Stored messages", started_at: "2026-10-23T00:00:00Z", message_count: 2,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "Stored messages", active_jobs: [], transcript: [
      { id: "server-user-id", parent_id: null, role: "user", content: "Review liquidity", status: "complete", timestamp: 1 },
      { id: "server-answer-id", parent_id: "server-user-id", role: "assistant", content: "Stored liquidity answer",
        status: "complete", timestamp: 2, tool_calls: [tool], sources: [source], attachments: [{ id: "file-id" }],
        content_parts: [{ type: "text", text: "Stored liquidity answer" }, { type: "source", data: source }],
        trace_snapshot: { decision_quality_chat: { verdict: "watch" } } },
    ],
  } }))
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Stored messages", { exact: true }).click()
  await expect(page.getByText("Stored liquidity answer", { exact: true })).toBeVisible()
  const snapshot = () => page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}")
    return saved.messages?.at(-1)
  })
  await expect.poll(snapshot).toMatchObject({ id: "server-answer-id", parentId: "server-user-id", messageStatus: "complete",
    sources: [source], toolCalls: [{ id: tool.id, arguments: tool.arguments, result: tool.result }],
    attachments: [{ id: "file-id" }], traceSnapshot: { decisionQualityChat: { verdict: "watch" } } })
  const before = await snapshot()
  await page.reload()
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByText("Stored liquidity answer", { exact: true })).toBeVisible()
  await expect.poll(snapshot).toEqual(before)
})

test("a streamed turn sends the same message ids that the client stores", async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route("**/api/agent/chat", async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    requests.push(body)
    await route.fulfill({ headers: { "Content-Type": "text/event-stream" }, body: [
      `event: delta\ndata: ${JSON.stringify({ text: "Answer with stable ids" })}\n\n`,
      `event: done\ndata: ${JSON.stringify({ session_id: "new-session", user_message_id: body.user_message_id,
        assistant_message_id: body.assistant_message_id, sources: [{ url: "https://example.com/report" }] })}\n\n`,
    ].join("") })
  })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Question with stable ids")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByText("Answer with stable ids", { exact: true })).toBeVisible()
  const body = requests[0]
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}").messages))
    .toMatchObject([
      { id: body?.user_message_id, role: "user", clientTurnId: body?.client_turn_id },
      { id: body?.assistant_message_id, role: "assistant", sources: [{ url: "https://example.com/report" }] },
    ])
  expect(body?.user_message_id).toBeTruthy()
  expect(body?.assistant_message_id).toBeTruthy()
  expect(body?.user_message_id).not.toEqual(body?.assistant_message_id)
})
