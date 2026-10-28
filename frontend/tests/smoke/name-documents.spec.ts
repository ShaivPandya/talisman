import { type Page } from "@playwright/test"
import { dossierResponse, expect, test } from "./fixtures"
import type { NameDocument } from "@/lib/api"

async function mockDocuments(page: Page) {
  const byName = new Map<string, NameDocument[]>()
  let nextId = 0
  await page.route("**/api/dossier/**", route => {
    const ticker = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-1)!)
    const asset = ticker.endsWith("=X") ? "fx" : ticker.endsWith("=F") ? "commodity" : "equity"
    return route.fulfill({ json: { ...dossierResponse, ticker, position: { ...dossierResponse.position, ticker, asset } } })
  })
  await page.route("**/api/names/**", async route => {
    const request = route.request()
    const [, , , rawTicker, , id, action] = new URL(request.url()).pathname.split("/")
    const ticker = decodeURIComponent(rawTicker)
    const documents = byName.get(ticker) ?? []
    if (action === "content") {
      await route.fulfill({ body: "Proprietary survey counted 731 violet satellites.", headers: { "Content-Disposition": 'attachment; filename="survey.txt"' } })
      return
    }
    if (action === "attach") {
      const source = documents.find(document => document.id === id)!
      const names = (request.postDataJSON() as { tickers: string[] }).tickers
      for (const name of names) byName.set(name, [...(byName.get(name) ?? []), { ...source, ticker: name, url: source.url.replace(ticker, name) }])
      await route.fulfill({ json: { documents: names.map(name => byName.get(name)?.at(-1)) } })
      return
    }
    if (request.method() === "DELETE") {
      byName.set(ticker, documents.filter(document => document.id !== id))
      await route.fulfill({ status: 204 })
      return
    }
    if (request.method() === "POST") {
      const name = /filename="([^"]+)"/.exec(request.postDataBuffer()?.toString() ?? "")?.[1] ?? "survey.txt"
      if (name === "scan.pdf") {
        await route.fulfill({ status: 422, json: { message: "No readable text was found. Scanned PDFs need OCR before uploading." } })
        return
      }
      const id = String(++nextId).padStart(32, "0")
      const document: NameDocument = { id, ticker, name, mime_type: "text/plain", size: 100, created_at: "2026-10-24T12:00:00Z", source_kind: "private_upload", url: `/api/names/${ticker}/documents/${id}/content` }
      byName.set(ticker, [...documents, document])
      await route.fulfill({ status: 201, json: document })
      return
    }
    await route.fulfill({ json: { ticker, documents, count: documents.length } })
  })
  return byName
}

for (const ticker of ["MSFT", "EURUSD=X", "GC=F"]) {
  test(`source files persist and delete individually for ${ticker}`, async ({ page }) => {
    await mockDocuments(page)
    await page.goto(`/dossier/${ticker}`)
    const panel = page.getByRole("region", { name: `Source files for ${ticker}` })
    await panel.getByLabel("Add source files").setInputFiles([
      { name: "survey.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF fixture") },
      { name: "survey.txt", mimeType: "text/plain", buffer: Buffer.from("731 violet satellites") },
      { name: "survey.md", mimeType: "text/markdown", buffer: Buffer.from("# Survey\n731 violet satellites") },
    ])
    for (const name of ["survey.pdf", "survey.txt", "survey.md"]) await expect(panel.getByRole("link", { name, exact: true })).toBeVisible()
    await page.reload()
    await expect(panel.getByRole("link", { name: "survey.txt", exact: true })).toBeVisible()
    await panel.getByRole("button", { name: `Remove survey.pdf from ${ticker}` }).click()
    await expect(panel.getByRole("link", { name: "survey.pdf", exact: true })).toHaveCount(0)
    await expect(panel.getByRole("link", { name: "survey.txt", exact: true })).toBeVisible()
    await expect(panel.getByRole("link", { name: "survey.md", exact: true })).toBeVisible()
  })
}

test("a file can be attached to another name and downloaded privately", async ({ page }) => {
  await mockDocuments(page)
  await page.goto("/dossier/MSFT")
  const panel = page.getByRole("region", { name: "Source files for MSFT" })
  await panel.getByLabel("Add source files").setInputFiles({ name: "survey.txt", mimeType: "text/plain", buffer: Buffer.from("731 violet satellites") })
  await panel.getByText("Attach to other names").click()
  await panel.getByLabel("Symbols, separated by commas").fill("GC=F")
  await panel.getByRole("button", { name: "Attach file", exact: true }).click()
  await expect(panel.getByRole("status")).toContainText("File attached")
  await panel.getByRole("button", { name: "Remove survey.txt from MSFT" }).click()
  await page.goto("/dossier/GC=F")
  const other = page.getByRole("region", { name: "Source files for GC=F" })
  await expect(other.getByRole("link", { name: "survey.txt", exact: true })).toBeVisible()
  const download = page.waitForEvent("download")
  await other.getByRole("link", { name: "survey.txt", exact: true }).click()
  expect((await download).suggestedFilename()).toBe("survey.txt")
  await page.goto("/dossier/USDJPY=X")
  await expect(page.getByRole("region", { name: "Source files for USDJPY=X" })).toContainText("No source files")
})

test("an unreadable upload reports its reason and leaves readable files available", async ({ page }) => {
  await mockDocuments(page)
  await page.goto("/dossier/MSFT")
  const panel = page.getByRole("region", { name: "Source files for MSFT" })
  await panel.getByLabel("Add source files").setInputFiles([
    { name: "survey.txt", mimeType: "text/plain", buffer: Buffer.from("731 violet satellites") },
    { name: "scan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF scanned") },
  ])
  await expect(panel.getByRole("alert")).toContainText("OCR")
  await expect(panel.getByRole("link", { name: "survey.txt", exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath("name-documents.png"), fullPage: true })
})

test("non-held watchlist names have the same source file panel", async ({ page }) => {
  await mockDocuments(page)
  await page.route("**/api/ideas/source-idea", route => route.fulfill({ json: {
    idea: { id: "source-idea", ticker: "EURUSD=X", asset: "fx", instrument_type: "spot_fx", status: "watching", tags: [], user_notes: "", metadata: {} },
    documents: {}, evaluations: [], lifecycle_events: [], record_timeline: [],
  } }))
  await page.goto("/ideas/source-idea")
  const panel = page.getByRole("region", { name: "Source files for EURUSD=X" })
  await panel.getByLabel("Add source files").setInputFiles({ name: "survey.md", mimeType: "text/markdown", buffer: Buffer.from("# Currency survey") })
  await expect(panel.getByRole("link", { name: "survey.md", exact: true })).toBeVisible()
})

test("browser uploads persist in the real local API and delete individually", async ({ page }) => {
  const base = process.env.NAME_DOCUMENTS_API_URL
  test.skip(!base, "Set NAME_DOCUMENTS_API_URL to an isolated local API to run the storage integration check.")
  const login = await page.request.post(`${base}/auth/login`, {
    data: { password: "testpass" },
    headers: { "X-Request-Schema-Name": "post:/api/auth/login", "X-Request-Schema-Version": "1" },
  })
  expect(login.ok()).toBeTruthy()
  const { csrfToken } = await login.json() as { csrfToken: string }
  await page.route("**/api/names/**", async route => {
    const request = route.request()
    const url = new URL(request.url())
    const response = await route.fetch({ url: `${base}${url.pathname.replace(/^\/api/, "")}`, headers: { ...request.headers(), "X-CSRF-Token": csrfToken } })
    await route.fulfill({ response })
  })
  await page.goto("/dossier/MSFT")
  const panel = page.getByRole("region", { name: "Source files for MSFT" })
  const name = `live-${Date.now()}.txt`
  await panel.getByLabel("Add source files").setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from("Proprietary survey counted 731 violet satellites.") })
  await expect(panel.getByRole("link", { name, exact: true })).toBeVisible()
  await page.reload()
  await expect(panel.getByRole("link", { name, exact: true })).toBeVisible()
  await panel.getByRole("button", { name: `Remove ${name} from MSFT` }).click()
  await expect(panel.getByRole("link", { name, exact: true })).toHaveCount(0)
})

test("fresh chat labels private upload citations separately from web sources", async ({ page }) => {
  const url = `/api/names/MSFT/documents/${"a".repeat(32)}/content`
  const sources = [
    { url, title: "Private upload: survey.txt" },
    { url: "https://example.com/filing", title: "Public filing" },
    { url: "/api/admin/secrets", title: "Invalid relative source" },
  ]
  const frame = (event: string, payload: Record<string, unknown>) => `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
  await page.route("**/api/agent/chat", async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({ headers: { "Content-Type": "text/event-stream" }, body: [
      frame("delta", { text: `The survey counted 731 violet satellites. [Private upload: survey.txt](${url})` }),
      frame("done", { session_id: "name-documents-chat", user_message_id: body.user_message_id, assistant_message_id: body.assistant_message_id, sources, tool_calls: [] }),
    ].join("") })
  })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await page.getByRole("textbox", { name: "Message Stan" }).fill("What does the uploaded MSFT survey say?")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  const dialog = page.getByRole("dialog")
  const privateSources = dialog.locator('[aria-label="Private uploads"]')
  await expect(privateSources.getByRole("link", { name: /survey.txt/ })).toHaveAttribute("href", url)
  await expect(dialog.locator('[aria-label="Public web sources"]').getByRole("link", { name: /Public filing/ })).toBeVisible()
  await expect(dialog.getByRole("link", { name: "Invalid relative source" })).toHaveCount(0)
  await page.reload()
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(privateSources.getByRole("link", { name: /survey.txt/ })).toHaveAttribute("href", url)
})

test("the source files card collapses, remembers it across names, and reopens on upload", async ({ page }) => {
  await mockDocuments(page)
  await page.goto("/dossier/MSFT")
  const panel = page.getByRole("region", { name: "Source files for MSFT" })
  await panel.getByLabel("Add source files").setInputFiles({ name: "survey.txt", mimeType: "text/plain", buffer: Buffer.from("731 violet satellites") })
  const toggle = panel.getByRole("button", { name: /^Source files/ })
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
  await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "false")
  await expect(panel.getByRole("link", { name: "survey.txt", exact: true })).toBeHidden()
  await expect(panel.getByLabel("Add source files")).toBeAttached()

  await page.goto("/dossier/GC=F")
  const other = page.getByRole("region", { name: "Source files for GC=F" })
  await expect(other.getByRole("button", { name: /^Source files/ })).toHaveAttribute("aria-expanded", "false")
  await other.getByLabel("Add source files").setInputFiles({ name: "gold.txt", mimeType: "text/plain", buffer: Buffer.from("Gold survey") })
  await expect(other.getByRole("link", { name: "gold.txt", exact: true })).toBeVisible()
})
