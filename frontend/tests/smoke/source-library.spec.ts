import { type Page } from "@playwright/test"
import { dossierResponse, expect, test } from "./fixtures"
import type { NameDocument, SourceLibraryFile } from "@/lib/api"

function file(char: string, name: string, tickers: string[], extra: Partial<SourceLibraryFile> = {}): SourceLibraryFile {
  return {
    sha256: char.repeat(64), name, other_names: [], mime_type: "text/plain", size: 2048,
    created_at: "2026-10-20T12:00:00Z", url: `/api/names/${tickers[0]}/documents/${char.repeat(32)}/content`, tickers, ...extra,
  }
}

const FILES = [
  file("a", "cdw-sellside.pdf", ["CDW", "MSFT"], { other_names: ["CDW Q3 note.pdf"], mime_type: "application/pdf", size: 3 * 1024 * 1024 }),
  file("b", "notes.md", ["MSFT"]),
  file("c", "fx-outlook.txt", ["EURUSD=X"]),
]

// Any ticker can open a dossier; the shared fixtures only mock MSFT.
async function mockDossiers(page: Page) {
  await page.route("**/api/dossier/**", route => {
    const ticker = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-1)!)
    return route.fulfill({ json: { ...dossierResponse, ticker, position: { ...dossierResponse.position, ticker } } })
  })
  await page.route("**/api/valuation/*", route => route.fulfill({
    json: { ticker: new URL(route.request().url()).pathname.split("/").at(-1), status: "unavailable", valuation: null },
  }))
}

async function mockLibrary(page: Page, initial: SourceLibraryFile[], deleteStatus?: number) {
  let files = [...initial]
  await mockDossiers(page)
  await page.route("**/api/names/*/documents", route => {
    const ticker = decodeURIComponent(new URL(route.request().url()).pathname.split("/")[3])
    const documents: NameDocument[] = files.filter(entry => entry.tickers.includes(ticker)).map(entry => ({
      id: entry.sha256.slice(0, 32), ticker, name: entry.name, mime_type: entry.mime_type, size: entry.size,
      created_at: entry.created_at, source_kind: "private_upload", url: entry.url,
    }))
    return route.fulfill({ json: { ticker, documents, count: documents.length } })
  })
  await page.route("**/api/source-files**", route => {
    const request = route.request()
    if (request.method() === "DELETE") {
      if (deleteStatus) return route.fulfill({ status: deleteStatus, json: { message: "Administrator access is required." } })
      const sha256 = new URL(request.url()).pathname.split("/").at(-1)
      files = files.filter(entry => entry.sha256 !== sha256)
      return route.fulfill({ status: 204 })
    }
    return route.fulfill({ json: { files, count: files.length } })
  })
}

test("lists every uploaded file once with every name it is attached to", async ({ page }) => {
  await mockLibrary(page, FILES)
  await page.goto("/source-files")
  await expect(page.getByRole("heading", { name: "Source Library", exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "3 source files", exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "cdw-sellside.pdf", exact: true })).toHaveCount(1)
  await expect(page.getByRole("list", { name: "Names cdw-sellside.pdf is attached to" }).getByRole("listitem")).toHaveText(["CDW", "MSFT"])
  await expect(page.getByRole("list", { name: "Names notes.md is attached to" }).getByRole("listitem")).toHaveText(["MSFT"])
  await expect(page.getByText("Also uploaded as CDW Q3 note.pdf")).toBeVisible()
  await expect(page.getByText("3.0 MB")).toBeVisible()
  await expect(page.getByRole("link", { name: "fx-outlook.txt", exact: true })).toHaveAttribute("href", FILES[2].url)
  await page.screenshot({ path: test.info().outputPath("source-library.png"), fullPage: true })
})

test("deleting asks first, then removes the file from every name and leaves the others", async ({ page }) => {
  await mockLibrary(page, FILES)
  await page.goto("/dossier/MSFT")
  const panel = page.getByRole("region", { name: "Source files for MSFT" })
  await expect(panel.getByRole("link", { name: "cdw-sellside.pdf", exact: true })).toBeVisible()

  await page.goto("/source-files")
  const open = page.getByRole("button", { name: "Delete cdw-sellside.pdf from every name" })
  await open.click()
  const confirm = page.getByRole("group", { name: "Confirm deleting cdw-sellside.pdf" })
  await expect(confirm).toContainText("from CDW, MSFT")
  await expect(confirm).toContainText("Research and Stan will stop using it")
  await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused()
  await confirm.getByRole("button", { name: "Cancel" }).click()
  await expect(confirm).toHaveCount(0)
  await expect(open).toBeFocused()
  await expect(page.getByRole("link", { name: "cdw-sellside.pdf", exact: true })).toBeVisible()

  await open.click()
  await page.getByRole("button", { name: "Delete file", exact: true }).click()
  await expect(page.getByRole("link", { name: "cdw-sellside.pdf", exact: true })).toHaveCount(0)
  await expect(page.getByRole("heading", { name: "2 source files", exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "notes.md", exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "fx-outlook.txt", exact: true })).toBeVisible()

  await page.goto("/dossier/MSFT")
  await expect(panel.getByRole("link", { name: "notes.md", exact: true })).toBeVisible()
  await expect(panel.getByRole("link", { name: "cdw-sellside.pdf", exact: true })).toHaveCount(0)
  await page.goto("/dossier/CDW")
  await expect(page.getByRole("region", { name: "Source files for CDW" })).toContainText("No source files")
})

test("a name's open source file list refreshes when its file is deleted from the library", async ({ page }) => {
  await mockLibrary(page, FILES)
  await page.goto("/dossier/CDW")
  const panel = page.getByRole("region", { name: "Source files for CDW" })
  await expect(panel.getByRole("link", { name: "cdw-sellside.pdf", exact: true })).toBeVisible()
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Source Library", exact: true }).click()
  await expect(page).toHaveURL(/\/source-files$/)
  await page.getByRole("button", { name: "Delete cdw-sellside.pdf from every name" }).click()
  await page.getByRole("button", { name: "Delete file", exact: true }).click()
  await expect(page.getByRole("link", { name: "cdw-sellside.pdf", exact: true })).toHaveCount(0)
  await page.goBack()
  await expect(panel).toContainText("No source files")
})

test("a failed delete keeps the file and reports why", async ({ page }) => {
  await mockLibrary(page, FILES, 403)
  await page.goto("/source-files")
  await page.getByRole("button", { name: "Delete notes.md from every name" }).click()
  await page.getByRole("button", { name: "Delete file", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("Administrator access is required")
  await expect(page.getByRole("link", { name: "notes.md", exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "3 source files", exact: true })).toBeVisible()
})

test("an empty library says where files come from", async ({ page }) => {
  await mockLibrary(page, [])
  await page.goto("/source-files")
  await expect(page.getByRole("heading", { name: "0 source files", exact: true })).toBeVisible()
  await expect(page.getByText("No source files have been uploaded yet.")).toBeVisible()
})

test("library delete reaches every name through the real local API", async ({ page }) => {
  const base = process.env.NAME_DOCUMENTS_API_URL
  test.skip(!base, "Set NAME_DOCUMENTS_API_URL to an isolated local API to run the storage integration check.")
  const login = await page.request.post(`${base}/auth/login`, {
    data: { password: "testpass" },
    headers: { "X-Request-Schema-Name": "post:/api/auth/login", "X-Request-Schema-Version": "1" },
  })
  expect(login.ok()).toBeTruthy()
  const { csrfToken } = await login.json() as { csrfToken: string }
  for (const pattern of ["**/api/names/**", "**/api/source-files**"]) {
    await page.route(pattern, async route => {
      const request = route.request()
      const url = new URL(request.url())
      const response = await route.fetch({ url: `${base}${url.pathname.replace(/^\/api/, "")}${url.search}`, headers: { ...request.headers(), "X-CSRF-Token": csrfToken } })
      await route.fulfill({ response })
    })
  }
  await mockDossiers(page)
  const stamp = Date.now()
  const shared = `shared-${stamp}.txt`
  const kept = `kept-${stamp}.txt`
  await page.goto("/dossier/MSFT")
  const panel = page.getByRole("region", { name: "Source files for MSFT" })
  await panel.getByLabel("Add source files").setInputFiles([
    { name: shared, mimeType: "text/plain", buffer: Buffer.from(`Proprietary survey ${stamp} counted 731 violet satellites.`) },
    { name: kept, mimeType: "text/plain", buffer: Buffer.from(`Unrelated note ${stamp}.`) },
  ])
  const sharedRow = panel.getByRole("listitem").filter({ hasText: shared })
  await expect(sharedRow).toBeVisible()
  await expect(panel.getByRole("link", { name: kept, exact: true })).toBeVisible()
  await sharedRow.getByText("Attach to other names").click()
  await sharedRow.getByLabel("Symbols, separated by commas").fill("GC=F")
  await sharedRow.getByRole("button", { name: "Attach file", exact: true }).click()
  await expect(panel.getByRole("status")).toContainText("File attached")

  await page.goto("/source-files")
  await expect(page.getByRole("list", { name: `Names ${shared} is attached to` }).getByRole("listitem")).toHaveText(["GC=F", "MSFT"])
  await expect(page.getByRole("list", { name: `Names ${kept} is attached to` }).getByRole("listitem")).toHaveText(["MSFT"])
  await page.getByRole("button", { name: `Delete ${shared} from every name` }).click()
  await page.getByRole("button", { name: "Delete file", exact: true }).click()
  await expect(page.getByRole("link", { name: shared, exact: true })).toHaveCount(0)
  await expect(page.getByRole("link", { name: kept, exact: true })).toBeVisible()

  await page.goto("/dossier/GC=F")
  await expect(page.getByRole("region", { name: "Source files for GC=F" })).toContainText("No source files")
  await page.goto("/dossier/MSFT")
  await expect(panel.getByRole("link", { name: kept, exact: true })).toBeVisible()
  await expect(panel.getByRole("link", { name: shared, exact: true })).toHaveCount(0)

  await page.goto("/source-files")
  await page.getByRole("button", { name: `Delete ${kept} from every name` }).click()
  await page.getByRole("button", { name: "Delete file", exact: true }).click()
  await expect(page.getByRole("link", { name: kept, exact: true })).toHaveCount(0)
})
