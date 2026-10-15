import type { Page } from "@playwright/test"
import { authenticate, dossierResponse, expect, test } from "./fixtures"
import { dismissFloatingAlerts } from "./operatingWorkflow"

type Kind = "overview" | "management_quality"
type Status = {
  job_id?: string
  status: "idle" | "running" | "done" | "error"
  progress?: { phase: string }
  report_available?: boolean
  error?: string
}

async function mockResearch(page: Page) {
  const reports: Record<Kind, Status> = { overview: { status: "idle" }, management_quality: { status: "idle" } }
  const starts: { ticker: string; kinds: Kind[]; overviewPrompt: string }[] = []
  let prompts = {
    overview_prompt: "Original overview for {ticker}",
    management_quality_prompt: "Original operational management query for {ticker}",
    updated_at: null as string | null,
    model: "gpt-6.1-sol",
    configured: true,
  }
  let dossierReads = 0
  await page.route("**/api/settings/company-research", async route => {
    if (route.request().method() === "PUT") {
      prompts = { ...prompts, ...route.request().postDataJSON(), updated_at: "2026-10-14T22:00:00Z" }
    }
    await route.fulfill({ json: prompts })
  })
  await page.route("**/api/company-research/**", async route => {
    const url = new URL(route.request().url())
    const parts = url.pathname.split("/")
    const ticker = parts[3]
    if (parts[4] === "reports") {
      const kind = parts[5] as Kind
      await route.fulfill({ json: {
        ticker, kind, job_id: reports[kind].job_id,
        generated_at: "2026-10-14T22:00:00Z", model: "gpt-6.1-sol", summary_applied: reports[kind].status === "done",
        sources: [{ title: "Issuer filing", url: "https://example.com/issuer-filing" }],
        content: kind === "overview"
          ? "# Full company report\n\nNewly researched overview. [Issuer filing](https://example.com/issuer-filing)"
          : "# Full management report\n\n## Quarter-by-quarter operational commitment tracker\n\n"
            + "| Fiscal quarter | Source | Commitment | Outcome |\n|---|---|---|---|\n"
            + Array.from({ length: 20 }, (_, n) => `| FY${2022 + Math.floor(n / 4)} Q${n % 4 + 1} | [Issuer filing](https://example.com/issuer-filing) | Production target | Insufficient disclosure |\n`).join(""),
      } })
      return
    }
    if (route.request().method() === "POST") {
      const { kinds } = route.request().postDataJSON() as { kinds: Kind[] }
      starts.push({ ticker, kinds, overviewPrompt: prompts.overview_prompt.replaceAll("{ticker}", ticker) })
      for (const kind of kinds) reports[kind] = {
        job_id: kind === "overview" ? "38e149b0-49fb-4b69-9412-d40d51c8cde1" : "365f9dbd-7ed7-4ac4-aab5-ff5c329e52aa",
        status: "running", progress: { phase: "sources" },
      }
    }
    await route.fulfill({ status: route.request().method() === "POST" ? 202 : 200, json: { ticker, reports } })
  })
  await page.route("**/api/dossier/MSFT", async route => {
    dossierReads++
    await route.fulfill({ json: {
      ...dossierResponse,
      overview_content: reports.overview.status === "done" ? "# MSFT Overview\n\nNewly researched overview." : null,
      management_quality: {
        content: reports.management_quality.status === "done" ? "# MSFT Management Quality\n\nNew management assessment." : null,
        parsed: null,
      },
    } })
  })
  await page.route("**/api/ideas/research-idea", async route => {
    await route.fulfill({ json: {
      idea: { id: "research-idea", ticker: "MSFT", asset: "equity", instrument_type: "security",
        status: "watching", company_name: "Microsoft", tags: [], user_notes: "", metadata: {} },
      documents: { overview_content: null, management_quality_content: null },
      evaluations: [], lifecycle_events: [], record_timeline: [],
    } })
  })
  return {
    reports, starts,
    complete: (kind: Kind) => { reports[kind] = { ...reports[kind], status: "done", report_available: true } },
    fail: (kind: Kind) => { reports[kind] = { ...reports[kind], status: "error", error: "Transcript source unavailable" } },
    getDossierReads: () => dossierReads,
  }
}

test("starts both reports, recovers after reload, refreshes summaries and displays cited full reports", async ({ page }) => {
  const research = await mockResearch(page)
  await authenticate(page)
  await page.goto("/dossier/MSFT")
  const controls = page.getByRole("region", { name: "Company research" })
  await controls.getByRole("button", { name: "Run Company Research" }).click()
  await expect.poll(() => research.starts.length).toBe(1)
  expect(research.starts[0].kinds).toEqual(["overview", "management_quality"])
  await expect(controls.getByText("Gathering sources")).toHaveCount(2)
  await expect(controls.getByRole("button", { name: "Run Company Research" })).toBeDisabled()
  await page.reload()
  await expect(controls.getByText("Gathering sources")).toHaveCount(2)
  const reads = research.getDossierReads()
  research.complete("overview")
  research.complete("management_quality")
  await expect(controls.getByText("Saved to company sheet")).toHaveCount(2, { timeout: 10_000 })
  await expect.poll(research.getDossierReads).toBeGreaterThan(reads)
  await controls.getByText("Full overview research", { exact: true }).click()
  await expect(controls.getByText("Newly researched overview.", { exact: false })).toBeVisible()
  await expect(controls.getByRole("link", { name: "Issuer filing" }).first()).toHaveAttribute("href", "https://example.com/issuer-filing")
  await controls.getByText("Full management quality research", { exact: true }).click()
  await expect(controls.getByRole("cell", { name: "FY2022 Q1" })).toBeVisible()
  await expect(controls.getByRole("cell", { name: "FY2026 Q4" })).toBeVisible()
  await expect(controls.getByRole("row")).toHaveCount(21)
  await page.screenshot({ path: test.info().outputPath("company-research.png"), fullPage: true })
})

for (const failed of ["overview", "management_quality"] as const) {
  test(`retains the successful report when ${failed} fails and retries only that report`, async ({ page }) => {
    const research = await mockResearch(page)
    await page.goto("/dossier/MSFT")
    const controls = page.getByRole("region", { name: "Company research" })
    await controls.getByRole("button", { name: "Run Company Research" }).click()
    await expect.poll(() => research.starts.length).toBe(1)
    research.fail(failed)
    research.complete(failed === "overview" ? "management_quality" : "overview")
    await page.reload()
    await expect(controls.getByText("Saved to company sheet")).toBeVisible()
    await expect(controls.getByText("Transcript source unavailable")).toBeVisible()
    await page.reload()
    await expect(controls.getByText("Transcript source unavailable")).toBeVisible()
    await controls.getByRole("button", { name: /Retry/ }).click()
    await expect.poll(() => research.starts.length).toBe(2)
    expect(research.starts[1].kinds).toEqual([failed])
    await expect(controls.getByText("Saved to company sheet")).toBeVisible()
  })
}

test("saves global prompts across reload and another company while unsaved edits have no effect", async ({ page }) => {
  const research = await mockResearch(page)
  await page.goto("/dossier/MSFT")
  await page.getByRole("button", { name: "Edit Research Prompts" }).click()
  const dialog = page.getByRole("dialog", { name: "Edit Research Prompts" })
  await expect(dialog.getByText(/Saved prompts apply to every company/)).toBeVisible()
  await dialog.getByLabel("Company overview prompt").fill("UNSAVED {ticker}")
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.getByRole("button", { name: "Edit Research Prompts" }).click()
  await expect(dialog.getByLabel("Company overview prompt")).toHaveValue("Original overview for {ticker}")
  await dialog.getByLabel("Company overview prompt").fill("UPDATED overview {ticker}")
  await dialog.getByLabel("Management quality prompt").fill("UPDATED management {ticker}")
  await dialog.getByRole("button", { name: "Save Research Prompts" }).click()
  await expect(dialog).toBeHidden()
  await page.reload()
  await page.getByRole("button", { name: "Edit Research Prompts" }).click()
  await expect(dialog.getByLabel("Company overview prompt")).toHaveValue("UPDATED overview {ticker}")
  await dialog.getByLabel("Company overview prompt").fill("Missing placeholder")
  await expect(dialog.getByRole("button", { name: "Save Research Prompts" })).toBeDisabled()
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.route("**/api/dossier/NVDA", route => route.fulfill({ json: { ...dossierResponse, ticker: "NVDA",
    position: { ticker: "NVDA", asset: "equity", instrument_type: "security", direction: "long" } } }))
  await page.route("**/api/valuation/NVDA", route => route.fulfill({ json: { ticker: "NVDA", status: "unavailable", valuation: null } }))
  await page.goto("/dossier/NVDA")
  await page.getByRole("button", { name: "Run Company Research" }).click()
  await expect.poll(() => research.starts.length).toBe(1)
  expect(research.starts[0].overviewPrompt).toBe("UPDATED overview NVDA")
})

test("uses the same controls on equity Ideas and keeps uploads available on mobile", async ({ page }) => {
  const research = await mockResearch(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/ideas/research-idea")
  await dismissFloatingAlerts(page)
  const controls = page.getByRole("region", { name: "Company research" })
  await controls.getByRole("button", { name: "Run Company Research" }).click()
  await expect.poll(() => research.starts.length).toBe(1)
  await expect(page.getByText("Upload", { exact: true }).first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
