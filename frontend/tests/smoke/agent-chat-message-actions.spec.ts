import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

// TL-224: copy, regenerate, edit and resend, and the version switcher.

const sessionId = "message-actions-session"

test.describe.configure({ timeout: 60_000 })

function frame(event: string, payload: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
}

/** Answers each chat request with the next reply and records the request bodies. */
async function replyWith(page: Page, replies: string[]) {
  const requests: Record<string, unknown>[] = []
  await page.route("**/api/agent/chat", async route => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = route.request().postDataJSON() as Record<string, unknown>
    const text = replies[requests.length] ?? "Out of replies"
    requests.push(body)
    await route.fulfill({
      headers: { "Content-Type": "text/event-stream" },
      body: [
        frame("delta", { text }),
        frame("done", {
          usage: {},
          session_id: sessionId,
          user_message_id: body.user_message_id,
          assistant_message_id: body.assistant_message_id,
        }),
      ].join(""),
    })
  })
  return requests
}

async function openChat(page: Page) {
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

// The chat title repeats the first question, so look for the question inside the message list.
function question(page: Page, text: string) {
  return page.locator("div.whitespace-pre-wrap", { hasText: new RegExp(`^${text}$`) })
}

async function send(page: Page, message: string) {
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill(message)
  await input.press("Enter")
}

test("copies an answer and a code block", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
  await replyWith(page, ["Run this:\n\n```sh\nnpm run build\n```\n\nThen deploy."])
  await openChat(page)
  await send(page, "How do I build?")

  const answer = page.getByText("Then deploy.")
  await expect(answer).toBeVisible()
  await page.getByRole("button", { name: "Copy response" }).click()
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible()
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied).toContain("Run this:")
  expect(copied).toContain("npm run build")

  await page.getByText("npm run build").hover()
  await page.getByRole("button", { name: "Copy code" }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("npm run build")
})

test("regenerating keeps both answers, and the version shown decides the next turn", async ({ page }) => {
  const requests = await replyWith(page, ["First answer", "Second answer", "Follow-up answer"])
  await openChat(page)
  await send(page, "Question one")
  await expect(page.getByText("First answer", { exact: true })).toBeVisible()

  await page.getByRole("button", { name: "Regenerate response" }).click()
  await expect(page.getByText("Second answer", { exact: true })).toBeVisible()
  await expect(page.getByText("First answer", { exact: true })).toHaveCount(0)
  await expect(page.getByText("2/2", { exact: true })).toBeVisible()
  expect(requests[1]).toMatchObject({
    regenerate_of_message_id: requests[0].assistant_message_id,
    user_message_id: requests[0].user_message_id,
    message: "Question one",
  })
  expect(requests[1].client_turn_id).not.toEqual(requests[0].client_turn_id)
  expect(requests[1].assistant_message_id).not.toEqual(requests[0].assistant_message_id)

  await page.getByRole("button", { name: "Previous version" }).click()
  await expect(page.getByText("First answer", { exact: true })).toBeVisible()
  await expect(page.getByText("Second answer", { exact: true })).toHaveCount(0)
  await expect(page.getByText("1/2", { exact: true })).toBeVisible()

  // Replying now continues the first version, not the newest one.
  await send(page, "Follow up")
  await expect(page.getByText("Follow-up answer", { exact: true })).toBeVisible()
  expect(requests[2]).toMatchObject({ parent_message_id: requests[0].assistant_message_id })
  expect(requests[2].regenerate_of_message_id).toBeUndefined()
  // Only the latest answer can be regenerated.
  await expect(page.getByRole("button", { name: "Regenerate response" })).toHaveCount(1)

  await page.reload()
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByText("Follow-up answer", { exact: true })).toBeVisible()
  await expect(page.getByText("First answer", { exact: true })).toBeVisible()
  await expect(page.getByText("Second answer", { exact: true })).toHaveCount(0)
  await expect(page.getByText("1/2", { exact: true })).toBeVisible()
})

test("editing a sent message adds a version beside it", async ({ page }) => {
  const requests = await replyWith(page, ["Answer to original", "Answer to edited"])
  await openChat(page)
  await send(page, "Original question")
  await expect(page.getByText("Answer to original", { exact: true })).toBeVisible()

  await question(page, "Original question").hover()
  await page.getByRole("button", { name: "Edit message" }).click()
  await page.getByRole("textbox", { name: "Edit message" }).fill("Edited question")
  await page.getByRole("button", { name: "Send", exact: true }).click()

  await expect(page.getByText("Answer to edited", { exact: true })).toBeVisible()
  await expect(question(page, "Edited question")).toBeVisible()
  await expect(question(page, "Original question")).toHaveCount(0)
  expect(requests[1]).toMatchObject({ message: "Edited question", edit_of_message_id: requests[0].user_message_id })
  expect(requests[1].parent_message_id).toBeUndefined()

  await page.getByRole("button", { name: "Previous version" }).click()
  await expect(question(page, "Original question")).toBeVisible()
  await expect(page.getByText("Answer to original", { exact: true })).toBeVisible()
  await expect(page.getByText("Answer to edited", { exact: true })).toHaveCount(0)
})

test("a saved conversation with several answers opens on the newest and keeps the others", async ({ page }) => {
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "Branched", started_at: "2026-10-23T00:00:00Z", message_count: 3,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "Branched", active_jobs: [], transcript: [
      { id: "u1", parent_id: null, role: "user", content: "Saved question", status: "complete", timestamp: 1, client_turn_id: "t1" },
      { id: "a1", parent_id: "u1", role: "assistant", content: "Saved first answer", status: "complete", timestamp: 2, client_turn_id: "t1" },
      { id: "a2", parent_id: "u1", role: "assistant", content: "Saved second answer", status: "complete", timestamp: 3, client_turn_id: "t2" },
    ],
  } }))
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Branched", { exact: true }).click()

  await expect(page.getByText("Saved second answer", { exact: true })).toBeVisible()
  await expect(page.getByText("2/2", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Previous version" }).click()
  await expect(page.getByText("Saved first answer", { exact: true })).toBeVisible()
})
