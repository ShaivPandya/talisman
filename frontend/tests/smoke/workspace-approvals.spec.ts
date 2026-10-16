import type { Page } from "@playwright/test"
import type { ApprovalRecord } from "../../src/lib/api"
import { expect, smokeApproval, test } from "./fixtures"
import { expectPrimaryControlsSeparated } from "./operatingWorkflow"

type DecisionAction = "approve" | "reject"
type DecisionBody = { note?: string; requirement_id?: string }
type DecisionResponse = { approval: ApprovalRecord } | { status: number; error: string }

function approval(overrides: Partial<ApprovalRecord> = {}): ApprovalRecord {
  return { ...structuredClone(smokeApproval), ...overrides }
}

function resolved(approval: ApprovalRecord, action: DecisionAction): DecisionResponse {
  return { approval: {
    ...approval,
    status: action === "approve" ? "approved" : "rejected",
    application_status: action === "approve" ? "applied" : "not_applicable",
    can_approve: false,
    can_reject: false,
  } }
}

async function mockApprovals(page: Page, initial = [approval()]) {
  const state = {
    approvals: initial,
    requests: [] as { id: string; action: DecisionAction; body: DecisionBody }[],
    summaryReads: 0,
    resolve: async (item: ApprovalRecord, action: DecisionAction): Promise<DecisionResponse> => resolved(item, action),
  }
  await page.route("**/api/approvals**", async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const pending = state.approvals.filter(item => item.status === "pending")
    if (request.method() === "GET") {
      if (path === "/api/approvals/summary") {
        state.summaryReads++
        await route.fulfill({ json: {
          count: pending.length, items: pending, recommendation_approval_count: 0,
          has_more: false, status: "pending", ticker: null, application_status: null, limit: 5,
        } })
      } else if (path === "/api/approvals") {
        await route.fulfill({ json: { approvals: pending, count: pending.length } })
      } else {
        await route.fulfill({ json: state.approvals.find(item => item.id === decodeURIComponent(path.split("/").at(-1)!)) })
      }
      return
    }
    const match = path.match(/^\/api\/approvals\/([^/]+)\/(approve|reject)$/)
    expect(request.method()).toBe("POST")
    expect(match).not.toBeNull()
    expect(request.headers()["x-csrf-token"]).toBe("smoke-csrf")
    const id = decodeURIComponent(match![1])
    const action = match![2] as DecisionAction
    state.requests.push({ id, action, body: request.postDataJSON() as DecisionBody })
    const response = await state.resolve(state.approvals.find(item => item.id === id)!, action)
    if ("approval" in response) {
      state.approvals = state.approvals.map(item => item.id === id ? response.approval : item)
      await route.fulfill({ json: response.approval })
    } else {
      await route.fulfill({ status: response.status, json: { detail: response.error } })
    }
  })
  return state
}

function row(page: Page, id = "smoke-approval") {
  return page.getByRole("button", { name: `View approval ${id} trace`, exact: true }).locator("../..")
}

function queue(page: Page) {
  return page.locator("section").filter({ has: page.getByRole("heading", { name: "Action queue", exact: true }) })
}

for (const action of ["approve", "reject"] as const) {
  test(`fast ${action} sends the expected note and stays resolved after refetch`, async ({ page }) => {
    const state = await mockApprovals(page)
    await page.goto("/workspace")
    const reads = state.summaryReads
    await row(page).getByRole("button", { name: action === "approve" ? "Approve" : "Reject", exact: true }).click()
    await expect.poll(() => state.requests.length).toBe(1)
    expect(state.requests[0]).toEqual({ id: "smoke-approval", action, body: action === "approve" ? { note: "LGTM" } : {} })
    await expect(page.getByRole("dialog", { name: "Review Approval" })).toBeHidden()
    await expect(queue(page).getByRole("button", { name: /^Approvals\s+0$/ })).toBeVisible()
    await expect.poll(() => state.summaryReads).toBeGreaterThan(reads)
    await expect(row(page)).toHaveCount(0)
    await page.reload()
    await expect(queue(page).getByRole("button", { name: /^Approvals\s+0$/ })).toBeVisible()
    await expect(row(page)).toHaveCount(0)
  })
}

test("a fast multi-step approval records a vote and keeps the proposal pending", async ({ page }) => {
  const requirements = smokeApproval.approval_requirements.map(item => ({ ...item, approved_count: 0, remaining_count: 1, satisfied: false }))
  const state = await mockApprovals(page, [approval({
    approval_requirements: requirements, approval_decisions: [], remaining_approval_requirements: requirements,
    approval_progress: { total_required: 2, recorded_count: 0, remaining_count: 2, completed: false, requirements, remaining_requirements: requirements },
  })])
  state.resolve = async item => ({ approval: {
    ...item, ...structuredClone(smokeApproval),
    approval_decisions: [{ requirement_id: "research_lead", actor_id: "admin", decision: "approved", note: "LGTM" }],
  } })
  await page.goto("/workspace")
  await expect(row(page).getByText("0/2 approvals recorded")).toBeVisible()
  const reads = state.summaryReads
  await row(page).getByRole("button", { name: "Approve", exact: true }).click()
  await expect(row(page).getByText("1/2 approvals recorded")).toBeVisible()
  await expect(queue(page).getByRole("button", { name: /^Approvals\s+1$/ })).toBeVisible()
  await expect.poll(() => state.summaryReads).toBeGreaterThan(reads)
  expect(state.requests[0].body).toEqual({ note: "LGTM" })
  await expect(page.getByRole("dialog", { name: "Review Approval" })).toBeHidden()
  await page.reload()
  await expect(row(page).getByText("1/2 approvals recorded")).toBeVisible()
})

for (const flags of [
  { can_approve: false, can_reject: true },
  { can_approve: true, can_reject: false },
  { can_approve: false, can_reject: false },
]) {
  test(`fast actions honor permissions: approve=${flags.can_approve}, reject=${flags.can_reject}`, async ({ page }) => {
    const state = await mockApprovals(page, [approval(flags)])
    await page.goto("/workspace")
    await expect(row(page).getByRole("button", { name: "Approve", exact: true })).toBeEnabled({ enabled: flags.can_approve })
    await expect(row(page).getByRole("button", { name: "Reject", exact: true })).toBeEnabled({ enabled: flags.can_reject })
    await expect(row(page).getByRole("button", { name: "Review", exact: true })).toBeEnabled()
    expect(state.requests).toHaveLength(0)
  })
}

test("processing disables that row and prevents duplicate submissions", async ({ page }) => {
  const state = await mockApprovals(page)
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  state.resolve = async (item, action) => { await held; return resolved(item, action) }
  await page.goto("/workspace")
  await row(page).getByRole("button", { name: "Approve", exact: true }).evaluate(button => {
    const control = button as HTMLButtonElement
    control.click()
    control.click()
  })
  await expect(row(page).getByRole("button", { name: "Approving...", exact: true })).toBeDisabled()
  await expect(row(page).getByRole("button", { name: "Reject", exact: true })).toBeDisabled()
  await expect(row(page).getByRole("button", { name: "Review", exact: true })).toBeDisabled()
  await expect.poll(() => state.requests.length).toBe(1)
  release()
  await expect(row(page)).toHaveCount(0)
  expect(state.requests).toHaveLength(1)
})

test("overlapping decisions retain independent loading state", async ({ page }) => {
  const state = await mockApprovals(page, [approval(), approval({ id: "second-approval", reason: "Second proposal" })])
  let releaseFirst!: () => void
  let releaseSecond!: () => void
  const first = new Promise<void>(resolve => { releaseFirst = resolve })
  const second = new Promise<void>(resolve => { releaseSecond = resolve })
  state.resolve = async (item, action) => { await (item.id === "smoke-approval" ? first : second); return resolved(item, action) }
  await page.goto("/workspace")
  await row(page).getByRole("button", { name: "Approve", exact: true }).click()
  await row(page, "second-approval").getByRole("button", { name: "Reject", exact: true }).click()
  await expect(row(page).getByRole("button", { name: "Approving...", exact: true })).toBeDisabled()
  await expect(row(page, "second-approval").getByRole("button", { name: "Rejecting...", exact: true })).toBeDisabled()
  releaseFirst()
  await expect(row(page)).toHaveCount(0)
  await expect(row(page, "second-approval").getByRole("button", { name: "Rejecting...", exact: true })).toBeDisabled()
  releaseSecond()
  await expect(row(page, "second-approval")).toHaveCount(0)
  expect(state.requests).toHaveLength(2)
})

test("finishing another proposal preserves the open review and custom note", async ({ page }) => {
  const state = await mockApprovals(page, [approval(), approval({ id: "second-approval", reason: "Second proposal" })])
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  state.resolve = async (item, action) => { await held; return resolved(item, action) }
  await page.goto("/workspace")
  await row(page).getByRole("button", { name: "Approve", exact: true }).click()
  await row(page, "second-approval").getByRole("button", { name: "Review", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "Review Approval" })
  await dialog.getByLabel("Decision note").fill("Keep this second proposal note")
  release()
  await expect.poll(() => state.approvals[0].status).toBe("approved")
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText("Second proposal", { exact: true })).toBeVisible()
  await expect(dialog.getByLabel("Decision note")).toHaveValue("Keep this second proposal note")
  await expect(dialog.getByRole("button", { name: "Approve & Apply", exact: true })).toBeEnabled()
})

for (const action of ["approve", "reject"] as const) {
  test(`failed fast ${action} opens Review with the error and submitted note`, async ({ page }) => {
    const state = await mockApprovals(page)
    state.resolve = async () => ({ status: 500, error: "Decision service unavailable" })
    await page.goto("/workspace")
    await row(page).getByRole("button", { name: action === "approve" ? "Approve" : "Reject", exact: true }).click()
    const dialog = page.getByRole("dialog", { name: "Review Approval" })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText("500: Decision service unavailable", { exact: true })).toBeVisible()
    await expect(dialog.getByText(smokeApproval.reason, { exact: true })).toBeVisible()
    await expect(dialog.getByLabel("Decision note")).toHaveValue(action === "approve" ? "LGTM" : "")
    state.resolve = async (item, decision) => resolved(item, decision)
    await dialog.getByRole("button", { name: "Reject Proposal", exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect(row(page)).toHaveCount(0)
    expect(state.requests).toHaveLength(2)
  })
}

test("a stale conflict opens Review and refetches the disabled proposal", async ({ page }) => {
  const state = await mockApprovals(page)
  state.resolve = async item => {
    state.approvals = [approval({ ...item, can_approve: false, base_state_status: "stale", base_state_valid: false, can_restage: true })]
    return { status: 409, error: "Approval base state changed" }
  }
  await page.goto("/workspace")
  await expect(row(page).getByRole("button", { name: "Approve", exact: true })).toBeEnabled()
  const reads = state.summaryReads
  await row(page).getByRole("button", { name: "Approve", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "Review Approval" })
  await expect(dialog.getByText("This proposal is stale because the underlying state changed. Reject and restage it to review the current state.", { exact: true })).toBeVisible()
  await expect.poll(() => state.summaryReads).toBeGreaterThan(reads)
  await expect(dialog.getByRole("button", { name: "Approve & Apply", exact: true })).toBeDisabled()
  await expect(dialog.getByRole("button", { name: "Reject & Restage", exact: true })).toBeVisible()
  await expect(dialog.getByLabel("Decision note")).toHaveValue("LGTM")
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click()
  await expect(row(page).getByRole("button", { name: "Approve", exact: true })).toBeDisabled()
  await expect(row(page).getByRole("button", { name: "Reject", exact: true })).toBeEnabled()
})

test("Review still requires and submits a custom approval note", async ({ page }) => {
  const state = await mockApprovals(page)
  await page.goto("/workspace?approval_id=smoke-approval")
  const dialog = page.getByRole("dialog", { name: "Review Approval" })
  const approveButton = dialog.getByRole("button", { name: "Approve & Apply", exact: true })
  await expect(approveButton).toBeDisabled()
  await dialog.getByLabel("Decision note").fill("Reviewed the complete proposal")
  await approveButton.click()
  await expect(dialog).toBeHidden()
  await expect(row(page)).toHaveCount(0)
  expect(state.requests[0].body).toEqual({ note: "Reviewed the complete proposal" })
})

for (const theme of ["light", "dark"]) {
  for (const width of [390, 1440]) {
    test(`queue controls fit ${theme} at ${width}px`, async ({ page }, testInfo) => {
      await mockApprovals(page)
      await page.setViewportSize({ width, height: 900 })
      await page.addInitScript(value => localStorage.setItem("market-dashboard-theme", value), theme)
      await page.goto("/workspace")
      const review = row(page).getByRole("button", { name: "Review", exact: true })
      const approve = row(page).getByRole("button", { name: "Approve", exact: true })
      const reject = row(page).getByRole("button", { name: "Reject", exact: true })
      await expectPrimaryControlsSeparated(review, approve, reject)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      if (width === 390) {
        for (const button of [review, approve, reject]) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      }
      await queue(page).screenshot({ path: testInfo.outputPath(`queue-${theme}-${width}.png`) })
    })
  }
}
