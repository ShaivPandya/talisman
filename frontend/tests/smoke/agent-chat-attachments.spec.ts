import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

// TL-225: files and images attached to a chat message.

test.describe.configure({ timeout: 60_000 })

const sessionId = "attachments-session"
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
)
const PDF = Buffer.from("%PDF-1.4\n% smoke test document\n%%EOF\n")
const stored = {
  "10-K.pdf": { id: "a".repeat(32), name: "10-K.pdf", mime_type: "application/pdf", kind: "pdf", size: PDF.length },
  "screenshot.png": { id: "b".repeat(32), name: "screenshot.png", mime_type: "image/png", kind: "image", size: PNG.length },
}

function frame(event: string, payload: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
}

/** Mocks the upload route (by file name) and the file bytes, and records uploads and chat bodies. */
async function mockAttachments(page: Page, options: { uploadDelayMs?: number; uploadFails?: boolean; uniqueIds?: boolean } = {}) {
  const uploads: string[] = []
  const chats: Record<string, unknown>[] = []
  await page.route("**/api/agent/attachments", async route => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = route.request().postData() ?? ""
    const name = Object.keys(stored).find(candidate => body.includes(`filename="${candidate}"`))
    uploads.push(name ?? "unknown")
    if (options.uploadDelayMs) await new Promise(resolve => setTimeout(resolve, options.uploadDelayMs))
    if (options.uploadFails || !name) return route.fulfill({ status: 422, json: { detail: "Unsupported file type." } })
    const descriptor = stored[name as keyof typeof stored]
    // Every upload gets its own id on the server; the mock only repeats one when a test asks it not to.
    return route.fulfill({
      json: options.uniqueIds ? { ...descriptor, id: String(uploads.length).padStart(32, "0") } : descriptor,
    })
  })
  await page.route("**/api/agent/attachments/*", route => route.fulfill({ contentType: "image/png", body: PNG }))
  await page.route("**/api/agent/chat", async route => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = route.request().postDataJSON() as Record<string, unknown>
    chats.push(body)
    await route.fulfill({
      headers: { "Content-Type": "text/event-stream" },
      body: [
        frame("delta", { text: `Answer ${chats.length}` }),
        frame("done", {
          usage: {},
          session_id: sessionId,
          user_message_id: body.user_message_id,
          assistant_message_id: body.assistant_message_id,
        }),
      ].join(""),
    })
  })
  return { uploads, chats }
}

async function openChat(page: Page) {
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

const files = (...names: (keyof typeof stored)[]) =>
  names.map(name => ({
    name,
    mimeType: stored[name].mime_type,
    buffer: name.endsWith(".pdf") ? PDF : PNG,
  }))

test("a PDF and a screenshot are attached, sent by id, and still shown after a reload", async ({ page }) => {
  const { uploads, chats } = await mockAttachments(page)
  await openChat(page)

  await page.locator('input[type="file"]').setInputFiles(files("10-K.pdf", "screenshot.png"))
  const pending = page.getByRole("list", { name: "Files to attach" })
  await expect(pending.getByRole("button", { name: "Remove 10-K.pdf" })).toBeVisible()
  await expect(pending.getByRole("button", { name: "Remove screenshot.png" })).toBeVisible()
  expect(uploads.sort()).toEqual(["10-K.pdf", "screenshot.png"])

  await page.getByRole("textbox", { name: "Message Stan" }).fill("Summarise the 10-K and read the chart")
  await page.getByRole("button", { name: "Send message", exact: true }).click()

  await expect(page.getByText("Answer 1", { exact: true })).toBeVisible()
  expect(chats[0]).toMatchObject({
    message: "Summarise the 10-K and read the chart",
    attachment_ids: [stored["10-K.pdf"].id, stored["screenshot.png"].id].sort(),
  })
  await expect(pending).toHaveCount(0)

  const sent = page.getByRole("list", { name: "Attachments" })
  await expect(sent.getByRole("link", { name: /10-K\.pdf/ })).toBeVisible()
  await expect(sent.getByRole("link", { name: /screenshot\.png/ })).toBeVisible()

  await page.reload()
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByText("Answer 1", { exact: true })).toBeVisible()
  await expect(page.getByRole("list", { name: "Attachments" }).getByRole("link", { name: /10-K\.pdf/ })).toBeVisible()
})

test("a screenshot alone is a valid message", async ({ page }) => {
  const { chats } = await mockAttachments(page)
  await openChat(page)
  const send = page.getByRole("button", { name: "Send message", exact: true })
  await expect(send).toBeDisabled()

  await page.locator('input[type="file"]').setInputFiles(files("screenshot.png"))
  await expect(send).toBeEnabled()
  await send.click()

  await expect(page.getByText("Answer 1", { exact: true })).toBeVisible()
  expect(chats[0]).toMatchObject({ message: "Please review the attached file(s).", attachment_ids: [stored["screenshot.png"].id] })
})

test("a pasted screenshot is attached, but text pasted from a spreadsheet is left alone", async ({ page }) => {
  const { uploads } = await mockAttachments(page)
  await openChat(page)
  const paste = (text: string) => page.getByRole("textbox", { name: "Message Stan" }).evaluate((field, payload) => {
    const data = new DataTransfer()
    if (payload.text) data.setData("text/plain", payload.text)
    data.items.add(new File([new Uint8Array(payload.bytes)], "screenshot.png", { type: "image/png" }))
    const event = new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true })
    field.dispatchEvent(event)
    return event.defaultPrevented
  }, { text, bytes: [...PNG] })

  expect(await paste("A1\tB1")).toBe(false)
  expect(uploads).toEqual([])
  expect(await paste("")).toBe(true)
  await expect(page.getByRole("button", { name: "Remove screenshot.png" })).toBeVisible()
  expect(uploads).toEqual(["screenshot.png"])
})

test("unsupported files are refused before anything is uploaded", async ({ page }) => {
  const { uploads } = await mockAttachments(page)
  await openChat(page)

  await page.locator('input[type="file"]').setInputFiles({ name: "tool.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") })

  await expect(page.getByRole("alert")).toContainText("tool.exe is not supported")
  expect(uploads).toEqual([])
  await expect(page.getByRole("list", { name: "Files to attach" })).toHaveCount(0)
})

test("Send waits for an upload, and a failed upload can be dismissed", async ({ page }) => {
  await mockAttachments(page, { uploadDelayMs: 800 })
  await openChat(page)
  const send = page.getByRole("button", { name: "Send message", exact: true })

  await page.getByRole("textbox", { name: "Message Stan" }).fill("Read this")
  await page.locator('input[type="file"]').setInputFiles(files("10-K.pdf"))
  await expect(page.getByText("Uploading 10-K.pdf…")).toBeVisible()
  await expect(send).toBeDisabled()
  await expect(page.getByRole("button", { name: "Remove 10-K.pdf" })).toBeVisible()
  await expect(send).toBeEnabled()

  await page.getByRole("button", { name: "Remove 10-K.pdf" }).click()
  await expect(page.getByRole("list", { name: "Files to attach" })).toHaveCount(0)
})

test("a failed upload shows why and can be dismissed", async ({ page }) => {
  await mockAttachments(page, { uploadFails: true })
  await openChat(page)

  await page.locator('input[type="file"]').setInputFiles(files("10-K.pdf"))
  const failed = page.getByRole("list", { name: "Files to attach" }).getByRole("alert")
  await expect(failed).toContainText("10-K.pdf")
  await expect(failed).toContainText("Unsupported file type.")
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeDisabled()

  await page.getByRole("button", { name: "Dismiss 10-K.pdf" }).click()
  await expect(page.getByRole("list", { name: "Files to attach" })).toHaveCount(0)
})

test("at most five files go in one message", async ({ page }) => {
  const { uploads } = await mockAttachments(page, { uniqueIds: true })
  await openChat(page)

  await page.locator('input[type="file"]').setInputFiles(Array.from({ length: 6 }, () => files("screenshot.png")[0]))

  await expect(page.getByRole("alert")).toContainText("up to 5 files")
  await expect(page.getByRole("button", { name: /^Remove screenshot\.png$/ })).toHaveCount(5)
  expect(uploads).toHaveLength(5)
})

test("an edited message is sent with the same files", async ({ page }) => {
  const { chats } = await mockAttachments(page)
  await openChat(page)
  await page.locator('input[type="file"]').setInputFiles(files("10-K.pdf"))
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Original question")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByText("Answer 1", { exact: true })).toBeVisible()

  await page.locator("div.whitespace-pre-wrap", { hasText: /^Original question$/ }).hover()
  await page.getByRole("button", { name: "Edit message" }).click()
  await page.getByRole("textbox", { name: "Edit message" }).fill("Edited question")
  await page.getByRole("button", { name: "Send", exact: true }).click()

  await expect(page.getByText("Answer 2", { exact: true })).toBeVisible()
  expect(chats[1]).toMatchObject({ message: "Edited question", attachment_ids: [stored["10-K.pdf"].id] })
})

test("attachments saved on the server come back with the conversation", async ({ page }) => {
  await mockAttachments(page)
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "With files", started_at: "2026-10-24T00:00:00Z", message_count: 2,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "With files", active_jobs: [], transcript: [
      { id: "u1", parent_id: null, role: "user", content: "Read the 10-K", status: "complete", timestamp: 1,
        attachments: [stored["10-K.pdf"], stored["screenshot.png"]] },
      { id: "a1", parent_id: "u1", role: "assistant", content: "Stored answer", status: "complete", timestamp: 2 },
    ],
  } }))
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("With files", { exact: true }).click()

  const sent = page.getByRole("list", { name: "Attachments" })
  await expect(sent.getByRole("link", { name: /10-K\.pdf/ })).toBeVisible()
  await expect(sent.getByRole("link", { name: /screenshot\.png/ })).toBeVisible()
})
