import { test, expect, smokeApproval } from "./fixtures"
import type { Page } from "@playwright/test"

const sessionId = "rich-session"
const answer = "NVDA trades above its 200-day average and the thesis needs a review."
const suggestions = ["How does NVDA compare with AMD?", "What would invalidate the thesis?"]

const days = Array.from({ length: 40 }, (_, index) => new Date(Date.UTC(2026, 8, 1 + index)).toISOString().slice(0, 10))
const chart = {
  id: "chart-call",
  tool: "run_chart",
  kind: "line",
  title: "NVIDIA Corporation (NVDA)",
  subtitle: "2Y daily close with moving averages",
  as_of: days[days.length - 1],
  x_key: "date",
  y_format: "price",
  series: [{ key: "Close", name: "Close" }, { key: "100D SMA", name: "100D SMA" }],
  rows: days.map((date, index) => ({ date, Close: 100 + index, "100D SMA": 90 + index / 2 })),
  sampled_from: 503,
}
const curve = {
  id: "curve-call",
  tool: "get_yield_curve",
  kind: "curve",
  title: "United States yield curve",
  subtitle: "Yield by tenor",
  as_of: "2026-10-23",
  x_key: "label",
  y_format: "yield",
  series: [{ key: "current", name: "Current" }, { key: "historical", name: "90d ago" }],
  rows: [
    { label: "2Y", current: 4.1, historical: 4.3 },
    { label: "10Y", current: 4.2, historical: 4.4 },
    { label: "30Y", current: 4.6, historical: 4.7 },
  ],
}
const bars = {
  id: "bars-call",
  tool: "get_price_volume_signals",
  kind: "bars",
  title: "Latest session return by market",
  subtitle: "Signals: S&P 500: high-volume churn",
  x_key: "label",
  y_format: "percent",
  series: [{ key: "RetPct", name: "Return %" }],
  rows: [{ label: "S&P 500", RetPct: -1.2 }, { label: "Nasdaq", RetPct: 0.6 }],
}
const proposal = {
  id: "proposal-call",
  tool: "propose_thesis_status_change",
  approval_id: smokeApproval.id,
  entity_type: "thesis",
  ticker: "NVDA",
}

async function openChat(page: Page) {
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
}

function frame(event: string, payload: Record<string, unknown>) {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
}

type Decision = { id: string; action: string; body: { note?: string } }

/** Serves one approval and records what the card sends; `fail` makes the next decision fail with that message. */
async function mockApproval(page: Page, options: { fail?: string } = {}) {
  const state = { approval: structuredClone(smokeApproval) as Record<string, unknown>, decisions: [] as Decision[] }
  await page.route("**/api/approvals**", async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === "GET") {
      if (path === "/api/approvals/summary") {
        await route.fulfill({ json: {
          count: 0, items: [], recommendation_approval_count: 0, has_more: false,
          status: "pending", ticker: null, application_status: null, limit: 5,
        } })
      } else if (path === "/api/approvals") {
        await route.fulfill({ json: { approvals: [], count: 0 } })
      } else {
        await route.fulfill({ json: state.approval })
      }
      return
    }
    const match = path.match(/^\/api\/approvals\/([^/]+)\/(approve|reject)$/)
    expect(match).not.toBeNull()
    state.decisions.push({ id: decodeURIComponent(match![1]), action: match![2], body: request.postDataJSON() })
    if (options.fail) {
      await route.fulfill({ status: 409, json: { detail: options.fail } })
      return
    }
    state.approval = {
      ...state.approval,
      status: match![2] === "approve" ? "approved" : "rejected",
      application_status: match![2] === "approve" ? "applied" : "not_applicable",
      can_approve: false,
      can_reject: false,
    }
    await route.fulfill({ json: state.approval })
  })
  return state
}

async function mockHistory(page: Page, transcript: Record<string, unknown>[]) {
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "Rich reply", started_at: new Date().toISOString(), message_count: transcript.length,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "Rich reply", active_jobs: [], transcript,
  } }))
}

const savedTranscript = (parts: Record<string, unknown>) => [
  { id: "rich-user", role: "user", content: "Review NVDA", timestamp: 1, status: "complete" },
  { id: "rich-answer", parent_id: "rich-user", role: "assistant", content: answer, timestamp: 2, status: "complete", ...parts },
]

async function expectRichAnswer(page: Page, options: { approvedState?: boolean } = {}) {
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByTestId("agent-chart")).toContainText("NVIDIA Corporation (NVDA)")
  await expect(dialog.getByTestId("agent-chart")).toContainText("Showing 40 of 503 points")
  await expect(dialog.getByTestId("agent-chart").locator(".recharts-line").first()).toBeVisible()
  const card = dialog.getByTestId("agent-proposal-card")
  await expect(card).toContainText("Thesis Status Proposal")
  if (options.approvedState) await expect(card).toContainText("Approved and applied.")
  else await expect(card).toContainText("Pending Approval")
  for (const question of suggestions) await expect(dialog.getByRole("button", { name: question })).toBeVisible()
}

test("charts, proposal cards and suggestions render live, approve from the card, and survive reloads", async ({ page }) => {
  const sent: Record<string, unknown>[] = []
  await page.route("**/api/agent/chat", async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    sent.push(body)
    await route.fulfill({
      headers: { "Content-Type": "text/event-stream" },
      body: [
        frame("tool_call", { name: "run_chart", id: chart.id }),
        frame("tool_result", { name: "run_chart", id: chart.id, status: "ok", result_preview: "{}", chart }),
        frame("tool_call", { name: proposal.tool, id: proposal.id }),
        frame("tool_result", { name: proposal.tool, id: proposal.id, status: "ok", result_preview: "{}", proposal }),
        frame("delta", { text: answer }),
        frame("done", {
          session_id: sessionId,
          user_message_id: body.user_message_id,
          assistant_message_id: body.assistant_message_id,
          proposals: [proposal],
        }),
      ].join(""),
    })
  })
  let suggestionReads = 0
  await page.route("**/api/memory/sessions/*/messages/*/suggestions", route => {
    suggestionReads++
    // The follow-up job has not written them on the first look.
    return route.fulfill({ json: { suggestions: suggestionReads === 1 ? [] : suggestions } })
  })
  const approvals = await mockApproval(page)
  await mockHistory(page, savedTranscript({ charts: [chart], proposals: [proposal], suggestions: suggestions.map(text => ({ text })) }))

  await page.goto("/workspace")
  await openChat(page)
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Review NVDA")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByRole("dialog").locator(".prose").filter({ hasText: answer })).toBeVisible()
  await expectRichAnswer(page)
  expect(suggestionReads).toBeGreaterThanOrEqual(2)

  // Approving needs a note, and goes through the same endpoint as the Workspace.
  const card = page.getByRole("dialog").getByTestId("agent-proposal-card")
  const approve = card.getByRole("button", { name: "Approve", exact: true })
  await expect(approve).toBeDisabled()
  await card.getByLabel("Decision note").fill("Checked the thesis.")
  await approve.click()
  await expect(card).toContainText("Approved and applied.")
  expect(approvals.decisions).toEqual([{ id: smokeApproval.id, action: "approve", body: { note: "Checked the thesis." } }])

  // The local snapshot restores the chart, the card (now approved) and the questions.
  await page.reload()
  await openChat(page)
  await expectRichAnswer(page, { approvedState: true })

  // So does the server's saved message, with no local snapshot.
  await page.evaluate(() => {
    localStorage.removeItem("agent-chat-current")
    localStorage.removeItem("agent-chat-sessions:v1")
  })
  await page.reload()
  await openChat(page)
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Rich reply", { exact: true }).click()
  await expectRichAnswer(page, { approvedState: true })

  // A suggestion is sent like a typed question.
  await page.getByRole("dialog").getByRole("button", { name: suggestions[0] }).click()
  await expect.poll(() => sent.at(-1)?.message).toBe(suggestions[0])
})

test("curve and bar charts, and a rejected card, come back from the saved message", async ({ page }) => {
  await mockApproval(page)
  await mockHistory(page, savedTranscript({ charts: [curve, bars] }))

  await page.goto("/workspace")
  await openChat(page)
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Rich reply", { exact: true }).click()

  const dialog = page.getByRole("dialog")
  const charts = dialog.getByTestId("agent-chart")
  await expect(charts).toHaveCount(2)
  await expect(charts.first()).toContainText("United States yield curve")
  await expect(charts.first().locator(".recharts-line")).toHaveCount(2)
  await expect(charts.nth(1)).toContainText("Signals: S&P 500: high-volume churn")
  await expect(charts.nth(1).locator(".recharts-bar-rectangle")).toHaveCount(2)
  await expect(dialog.getByTestId("agent-proposal-card")).toHaveCount(0)
})

test("a failed approval shows its error on the card and leaves it pending", async ({ page }) => {
  const approvals = await mockApproval(page, { fail: "Approval already resolved by another reviewer." })
  await mockHistory(page, savedTranscript({ proposals: [proposal] }))

  await page.goto("/workspace")
  await openChat(page)
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Rich reply", { exact: true }).click()

  const card = page.getByRole("dialog").getByTestId("agent-proposal-card")
  await card.getByLabel("Decision note").fill("Reviewed.")
  await card.getByRole("button", { name: "Approve", exact: true }).click()
  await expect(card.getByRole("alert")).toContainText("already resolved")
  await expect(card).toContainText("Pending Approval")
  expect(approvals.decisions).toHaveLength(1)

  // Rejecting needs no note.
  await card.getByRole("button", { name: "Reject", exact: true }).click()
  await expect.poll(() => approvals.decisions.at(-1)?.action).toBe("reject")
})
