import { readFile } from "node:fs/promises"
import type { Page } from "@playwright/test"
import type { SessionSummary } from "../../src/hooks/useAgentChat"
import { expect, test } from "./fixtures"

function session(index: number): SessionSummary {
  return {
    session_id: `history-${index}`, title: `Research ${index}`,
    started_at: "2026-10-24T00:00:00Z", ended_at: "2026-10-24T01:00:00Z",
    message_count: 2, key_tickers: null, key_topics: null, summary: null,
    title_source: "manual", title_updated_at: null, pinned_at: null,
  }
}

async function mockHistory(page: Page, count = 65) {
  const state = {
    sessions: Array.from({ length: count }, (_, index) => session(index)),
    requests: [] as { query: string; cursor: string | null }[],
    deletes: [] as string[],
    exports: [] as string[],
    failList: false,
    failDelete: false,
  }
  await page.route("**/api/memory/sessions**", async route => {
    const request = route.request()
    const url = new URL(request.url())
    const sid = url.pathname.split("/")[4]
    if (!sid) {
      const query = url.searchParams.get("q") ?? ""
      const cursor = url.searchParams.get("cursor")
      state.requests.push({ query, cursor })
      if (state.failList) return route.fulfill({ status: 503, json: { detail: "History is unavailable" } })
      const matches = state.sessions.filter(item => !query || item.title?.toLowerCase().includes(query.toLowerCase())
        || (query.toLowerCase() === "cobalt" && item.session_id === "history-64"))
        .toSorted((left, right) => Number(Boolean(right.pinned_at)) - Number(Boolean(left.pinned_at)))
      const offset = Number(cursor ?? 0)
      return route.fulfill({ json: {
        sessions: matches.slice(offset, offset + 30),
        next_cursor: offset + 30 < matches.length ? String(offset + 30) : null,
      } })
    }
    const item = state.sessions.find(row => row.session_id === sid)
    if (!item) return route.fulfill({ status: 404, json: { detail: "Session not found" } })
    if (request.method() === "DELETE") {
      state.deletes.push(sid)
      if (state.failDelete) return route.fulfill({ status: 500, json: { detail: "Deletion is unavailable" } })
      state.sessions = state.sessions.filter(row => row.session_id !== sid)
      return route.fulfill({ json: { status: "deleted" } })
    }
    if (request.method() === "PATCH") {
      const body = request.postDataJSON() as { pinned?: boolean; title?: string }
      if (body.pinned !== undefined) item.pinned_at = body.pinned ? "2026-10-24T02:00:00Z" : null
      if (body.title) item.title = body.title
      return route.fulfill({ json: item })
    }
    if (url.pathname.endsWith("/export")) {
      state.exports.push(sid)
      return route.fulfill({ contentType: "text/markdown", body: `# ${item.title}\n\n## User\n\nSaved question\n\n## Stan\n\n**Saved answer**\n` })
    }
    return route.fulfill({ json: {
      ...item, active_jobs: [], transcript: [
        { id: `${sid}-user`, role: "user", content: "Saved question", timestamp: 1, parent_id: null },
        { id: `${sid}-answer`, role: "assistant", content: "Saved answer", timestamp: 2, parent_id: `${sid}-user` },
      ],
    } })
  })
  return state
}

async function openChat(page: Page) {
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).first().click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible()
}

async function openHistory(page: Page) {
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await expect(page.getByRole("searchbox", { name: "Search conversations" })).toBeVisible()
}

test("docked chat keeps the page usable and console switching preserves the draft", async ({ page }) => {
  await openChat(page)
  const chat = page.getByRole("dialog", { name: "Stan assistant" })
  const main = page.getByRole("main")
  await expect(chat).not.toHaveAttribute("aria-modal", "true")
  const mainBox = await main.boundingBox()
  const chatBox = await chat.boundingBox()
  expect(mainBox && chatBox && mainBox.x + mainBox.width <= chatBox.x + 1).toBe(true)
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Keep this draft")
  const riskLink = page.getByRole("link", { name: "Portfolio Risk", exact: true })
  await riskLink.focus()
  await expect(riskLink).toBeFocused()
  await riskLink.click()
  await expect(page).toHaveURL(/\/risk$/)
  await expect(chat).toBeVisible()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toHaveValue("Keep this draft")
  await page.screenshot({ path: "../tmp/tl214-docked.png" })
  await chat.getByRole("button", { name: "Use console layout" }).click()
  await expect(chat).toHaveAttribute("aria-modal", "true")
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toHaveValue("Keep this draft")
  await page.screenshot({ path: "../tmp/tl214-console.png" })
  await chat.getByRole("button", { name: "Use docked chat" }).click()
  await expect(chat).not.toHaveAttribute("aria-modal", "true")
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toHaveValue("Keep this draft")
})

test("History loads subsequent pages and searches beyond the original first 30 chats", async ({ page }) => {
  const state = await mockHistory(page)
  await openChat(page)
  await openHistory(page)
  await expect(page.getByText("Research 29", { exact: true })).toBeAttached()
  await page.getByRole("button", { name: "Load more conversations", exact: true }).scrollIntoViewIfNeeded()
  await expect(page.getByText("Research 59", { exact: true })).toBeAttached()
  await page.getByRole("button", { name: "Load more conversations", exact: true }).scrollIntoViewIfNeeded()
  await expect(page.getByText("Research 64", { exact: true })).toBeAttached()
  await expect(page.getByRole("button", { name: "Load more conversations", exact: true })).toBeHidden()
  expect(state.requests.map(item => item.cursor)).toEqual([null, "30", "60"])
  const search = page.getByRole("searchbox", { name: "Search conversations" })
  await search.fill("cobalt")
  await expect(page.getByText("Research 64", { exact: true })).toBeVisible()
  await expect(page.getByText("Research 0", { exact: true })).toBeHidden()
  expect(state.requests.at(-1)).toEqual({ query: "cobalt", cursor: null })
  await search.fill("no matching text")
  await expect(page.getByText("No matching conversations")).toBeVisible()
  await search.fill("")
  await expect(page.getByText("Research 0", { exact: true })).toBeVisible()
})

test("resizing from a desktop dock to mobile preserves the draft and restores the full-screen dialog", async ({ page }) => {
  await openChat(page)
  const composer = page.getByRole("textbox", { name: "Message Stan" })
  await composer.fill("A draft across screen sizes")
  await page.setViewportSize({ width: 1024, height: 768 })
  const chat = page.getByRole("dialog", { name: "Stan assistant" })
  await expect(chat).toHaveAttribute("aria-modal", "false")
  const mainBox = await page.getByRole("main").boundingBox()
  const chatBox = await chat.boundingBox()
  expect(mainBox && chatBox && mainBox.x + mainBox.width <= chatBox.x + 1).toBe(true)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(chat).toHaveAttribute("aria-modal", "true")
  await expect(composer).toHaveValue("A draft across screen sizes")
  await expect(page.getByRole("button", { name: "Use console layout" })).toBeHidden()
  await page.getByRole("button", { name: "Close Stan" }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test("pinning survives reopening History and unpinning restores normal ordering", async ({ page }) => {
  const state = await mockHistory(page, 3)
  await openChat(page)
  await openHistory(page)
  await page.getByRole("button", { name: "Pin Research 2", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Pinned", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Unpin Research 2", exact: true })).toHaveAttribute("aria-pressed", "true")
  expect(state.sessions[2].pinned_at).toBeTruthy()
  await page.reload()
  await page.getByRole("button", { name: "Open Stan" }).first().click()
  await openHistory(page)
  await expect(page.getByRole("heading", { name: "Pinned", exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Unpin Research 2", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Pinned", exact: true })).toBeHidden()
  expect(state.sessions[2].pinned_at).toBeNull()
})

test("Undo cancels deletion, including after the panel is closed", async ({ page }) => {
  await page.clock.install()
  const state = await mockHistory(page, 2)
  await openChat(page)
  await openHistory(page)
  await page.getByRole("button", { name: "Delete Research 0", exact: true }).click()
  await expect(page.getByText("Research 0", { exact: true })).toHaveCount(1) // Only the Undo notice remains.
  await page.getByRole("button", { name: "Close Stan" }).click()
  await page.getByRole("button", { name: "Undo delete Research 0", exact: true }).click()
  await page.clock.fastForward(11_000)
  expect(state.deletes).toEqual([])
  await page.getByRole("button", { name: "Open Stan" }).first().click()
  await expect(page.getByRole("button", { name: "Delete Research 0", exact: true })).toBeVisible()
})

test("expired deletion removes the current conversation and its local snapshot", async ({ page }) => {
  await page.clock.install()
  const state = await mockHistory(page, 2)
  await openChat(page)
  await openHistory(page)
  await page.getByText("Research 0", { exact: true }).click()
  await expect(page.getByText("Saved answer", { exact: true })).toBeVisible()
  await openHistory(page)
  await page.getByRole("button", { name: "Delete Research 0", exact: true }).click()
  await page.clock.fastForward(10_001)
  await expect.poll(() => state.deletes).toEqual(["history-0"])
  await expect(page.getByRole("button", { name: "Delete Research 0", exact: true })).toBeHidden()
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("agent-chat-current") || "{}").sessionId)).toBeNull()
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("agent-chat-sessions:v1") || "{}")["history-0"])).toBeUndefined()
})

test("each pending deletion keeps its own Undo window", async ({ page }) => {
  await page.clock.install()
  const state = await mockHistory(page, 3)
  await openChat(page)
  await openHistory(page)
  await page.getByRole("button", { name: "Delete Research 0", exact: true }).click()
  await page.clock.fastForward(5_000)
  await page.getByRole("button", { name: "Delete Research 1", exact: true }).click()
  await page.clock.fastForward(5_001)
  await expect.poll(() => state.deletes).toEqual(["history-0"])
  await page.getByRole("button", { name: "Undo delete Research 1", exact: true }).click()
  await page.clock.fastForward(11_000)
  expect(state.deletes).toEqual(["history-0"])
  await expect(page.getByRole("button", { name: "Delete Research 1", exact: true })).toBeVisible()
})

test("failed deletions restore the row and running conversations cannot be deleted", async ({ page }) => {
  await page.clock.install()
  const state = await mockHistory(page, 2)
  state.failDelete = true
  state.sessions[1].has_active_job = true
  await openChat(page)
  await openHistory(page)
  await expect(page.getByRole("button", { name: "Delete Research 1", exact: true })).toBeDisabled()
  await page.getByRole("button", { name: "Delete Research 0", exact: true }).click()
  await page.clock.fastForward(10_001)
  await expect(page.getByRole("alert").filter({ hasText: "Deletion is unavailable" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Delete Research 0", exact: true })).toBeVisible()
})

test("History exports saved Markdown without opening or generating a chat", async ({ page }) => {
  const state = await mockHistory(page, 1)
  await openChat(page)
  await openHistory(page)
  const downloading = page.waitForEvent("download")
  await page.getByRole("button", { name: "Export Research 0 to Markdown", exact: true }).click()
  const download = await downloading
  expect(download.suggestedFilename()).toBe("Research 0.md")
  expect(await readFile((await download.path())!, "utf8")).toContain("**Saved answer**")
  expect(state.exports).toEqual(["history-0"])
  await expect(page.getByRole("searchbox", { name: "Search conversations" })).toBeVisible()
})

test("History shows request failures with retry and hides zero-message rows", async ({ page }) => {
  const state = await mockHistory(page, 2)
  state.failList = true
  state.sessions[1].message_count = 0
  await openChat(page)
  await openHistory(page)
  await expect(page.getByRole("alert").filter({ hasText: "History is unavailable" })).toBeVisible()
  state.failList = false
  await page.getByRole("button", { name: "Retry history" }).click()
  await expect(page.getByText("Research 0", { exact: true })).toBeVisible()
  await expect(page.getByText("Research 1", { exact: true })).toBeHidden()
  await expect(page.getByRole("alert").filter({ hasText: "History is unavailable" })).toBeHidden()
})
