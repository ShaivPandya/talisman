import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

const original = "NVDA packaging capacity is the key constraint."
const revised = "NVDA demand is improving; verify current numbers."
const entry = { session_id: "past", title: "NVDA outlook", summary: original, started_at: "2026-10-01", ended_at: "2026-10-01" }
const prompt = `## Relevant Conversation Memory\n\n[2026-10-01] ${original}`
const context = { enabled: true, memories: [entry], prompt }
async function setup(page: Page) {
  const state = { entries: [{ ...entry }], enabled: true, failSave: false, bodies: [] as Record<string, unknown>[] }
  await page.route("**/api/memory/entries**", async route => {
    const request = route.request()
    if (request.method() === "PATCH") {
      if (state.failSave) return route.fulfill({ status: 503, json: { detail: "Memory save failed" } })
      state.entries[0].summary = (request.postDataJSON() as { summary: string }).summary
    } else if (request.method() === "DELETE") state.entries = []
    const q = new URL(request.url()).searchParams.get("q")?.toLowerCase() || ""
    await route.fulfill({ json: request.method() === "GET" ? { entries: state.entries.filter(item => item.summary.toLowerCase().includes(q)), has_more: false } : { status: "updated" } })
  })
  await page.route("**/api/memory/sessions/*/memory", async route => {
    if (route.request().method() === "PATCH") state.enabled = (route.request().postDataJSON() as { enabled: boolean }).enabled
    await route.fulfill({ json: { enabled: state.enabled } })
  })
  await page.route("**/api/memory/sessions/*/summarize", route => route.fulfill({ json: { summary: "Saved" } }))
  await page.route("**/api/agent/chat", async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    state.bodies.push(body)
    if (body.memory_enabled !== undefined) state.enabled = Boolean(body.memory_enabled)
    const used = state.enabled ? context : { enabled: false, memories: [], prompt: "" }
    const frame = (event: string, payload: unknown) => `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
    await route.fulfill({ contentType: "text/event-stream", body:
      frame("memory_context", { session_id: "memory-chat", ...used }) + frame("delta", { text: "Here is the outlook." }) +
      frame("done", { session_id: "memory-chat", memory_context: used }) })
  })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  return state
}
async function openMemory(page: Page) {
  await page.getByRole("button", { name: "Open conversation memory" }).click()
  await expect(page.getByRole("searchbox", { name: "Search saved memory" })).toBeVisible()
}
async function send(page: Page) {
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Review NVDA")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByRole("dialog").locator(".prose").filter({ hasText: "Here is the outlook." }).last()).toBeVisible()
}

test("panel matches streamed memory, persists snapshots, and edits/deletes saved memory", async ({ page }, testInfo) => {
  const state = await setup(page)
  await send(page)
  await openMemory(page)
  await page.screenshot({ path: testInfo.outputPath("memory-panel.png") })
  const used = page.getByRole("region", { name: "Memory used for latest reply" })
  const saved = page.getByRole("region", { name: "Saved conversation memory" })
  await expect(used.getByText(original, { exact: true })).toBeVisible()
  await used.getByText("Exact memory sent", { exact: true }).click()
  await expect(used.locator("pre")).toHaveText(prompt)
  await saved.getByRole("button", { name: "Edit memory", exact: true }).click()
  await saved.getByRole("textbox", { name: "Edit memory summary" }).fill(revised)
  await saved.getByRole("button", { name: "Save memory", exact: true }).click()
  await expect(saved.getByText(revised, { exact: true })).toBeVisible()
  await expect(used.getByText(original, { exact: true })).toBeVisible()
  await saved.getByRole("button", { name: "Delete memory", exact: true }).click()
  await expect(saved.getByText("No saved conversation memory yet.")).toBeVisible()
  expect(state.entries).toHaveLength(0)
  await page.reload()
  await page.getByRole("button", { name: "Open Stan" }).click()
  await openMemory(page)
  await expect(page.getByRole("region", { name: "Memory used for latest reply" }).getByText(original, { exact: true })).toBeVisible()
})
test("switch applies before first message, persists per chat, and resets for new chat", async ({ page }) => {
  const state = await setup(page)
  await openMemory(page)
  await page.getByRole("checkbox", { name: "Don’t use memory in this chat" }).check()
  await page.getByRole("button", { name: "Back to chat" }).click()
  await send(page)
  expect(state.bodies[0].memory_enabled).toBe(false)
  await openMemory(page)
  await expect(page.getByRole("checkbox", { name: "Don’t use memory in this chat" })).toBeChecked()
  await expect(page.getByText("Memory was off for this reply.")).toBeVisible()
  await page.getByRole("checkbox", { name: "Don’t use memory in this chat" }).uncheck()
  await expect.poll(() => state.enabled).toBe(true)
  await page.getByRole("button", { name: "Back to chat" }).click()
  await page.getByRole("button", { name: "Start new chat" }).click()
  await openMemory(page)
  await expect(page.getByRole("checkbox", { name: "Don’t use memory in this chat" })).not.toBeChecked()
})
test("failed saves keep the draft and show a retryable error", async ({ page }) => {
  const state = await setup(page)
  await openMemory(page)
  await page.getByRole("button", { name: "Edit memory", exact: true }).click()
  await page.getByRole("textbox", { name: "Edit memory summary" }).fill(revised)
  state.failSave = true
  await page.getByRole("button", { name: "Save memory", exact: true }).click()
  await expect(page.getByRole("alert").filter({ hasText: "Memory save failed" })).toBeVisible()
  await expect(page.getByRole("textbox", { name: "Edit memory summary" })).toHaveValue(revised)
  state.failSave = false
  await page.getByRole("button", { name: "Save memory", exact: true }).click()
  await expect(page.getByText(revised, { exact: true })).toBeVisible()
  await page.getByRole("searchbox", { name: "Search saved memory" }).fill("unrelated")
  await expect(page.getByText("No matching memories.")).toBeVisible()
})

test("waits for a per-chat preference save before returning to send the next turn", async ({ page }) => {
  const state = await setup(page)
  await send(page)
  await openMemory(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route("**/api/memory/sessions/*/memory", async route => {
    if (route.request().method() === "PATCH") {
      await gate
      state.enabled = (route.request().postDataJSON() as { enabled: boolean }).enabled
    }
    await route.fulfill({ json: { enabled: state.enabled } })
  })
  await page.getByRole("checkbox", { name: "Don’t use memory in this chat" }).check()
  await expect(page.getByRole("button", { name: "Back to chat" })).toBeDisabled()
  await expect(page.getByRole("status").filter({ hasText: "Saving memory preference" })).toBeVisible()
  release()
  await expect(page.getByRole("button", { name: "Back to chat" })).toBeEnabled()
  await page.getByRole("button", { name: "Back to chat" }).click()
  await send(page)
  await expect.poll(() => state.bodies.length).toBe(2)
  await openMemory(page)
  await expect(page.getByText("Memory was off for this reply.")).toBeVisible()
})
