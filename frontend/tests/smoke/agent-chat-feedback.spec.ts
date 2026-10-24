import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

const sessionId = "feedback-session"
const baseline = process.env.TL216_BASELINE === "1"

test.describe.configure({ timeout: 60_000 })

function transcript(answers: number) {
  return Array.from({ length: answers * 2 }, (_, index) => ({
    id: `feedback-message-${index}`,
    parent_id: index ? `feedback-message-${index - 1}` : null,
    role: index % 2 ? "assistant" : "user",
    content: index % 2 ? `Answer ${Math.floor(index / 2)}` : `Question ${Math.floor(index / 2)}`,
    timestamp: index,
    clientTurnId: `feedback-turn-${Math.floor(index / 2)}`,
    status: "complete",
  }))
}

async function openChat(page: Page, answers: number) {
  await page.addInitScript(({ sessionId, messages }) => {
    localStorage.setItem("agent-chat-current", JSON.stringify({ sessionId, messages }))
  }, { sessionId, messages: transcript(answers) })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).last().click()
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(`Answer ${answers - 1}`, { exact: true })).toBeVisible({ timeout: 15_000 })
}

for (const answers of [1, 10, 100]) {
  test(`loading ${answers} answers batches feedback`, async ({ page }) => {
    const requests: URL[] = []
    await page.route("**/api/agent/feedback?**", route => {
      requests.push(new URL(route.request().url()))
      return route.fulfill({ json: { feedback: [] } })
    })
    await openChat(page, answers)
    // Vite's Strict Mode remount runs each legacy per-message effect twice.
    await expect.poll(() => requests.length).toBe(baseline ? answers * 2 : 1)
    if (!baseline) {
      expect(requests[0].searchParams.get("session_id")).toBe(sessionId)
      expect(requests[0].searchParams.has("client_turn_id")).toBe(false)
    }
    console.log(JSON.stringify({ phase: baseline ? "before" : "after", answers, feedbackRequests: requests.length }))
  })
}

test("a rating is saved with one click and no training consent", async ({ page }) => {
  const submitted: Record<string, unknown>[] = []
  await page.route("**/api/agent/feedback", async route => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = route.request().postDataJSON() as Record<string, unknown>
    submitted.push(body)
    await route.fulfill({ json: {
      feedback: { ...body, feedback_id: "feedback-1", trajectory_id: "trajectory-1", training_eligible: false },
      disclosure: "Saved for evaluation; training requires opt-in.",
    } })
  })
  await openChat(page, 1)
  await page.getByText("Answer 0", { exact: true }).hover()
  await page.getByRole("button", { name: baseline ? "Approve" : "Good response", exact: true }).click()
  if (baseline) await page.getByRole("button", { name: "Save feedback", exact: true }).click()
  await expect.poll(() => submitted.length).toBe(1)
  expect(submitted[0]).toMatchObject({ session_id: sessionId, client_turn_id: "feedback-turn-0", decision: "approve", eligible_for_training: false })
  await expect(page.getByRole("dialog", { name: "Approve Stan response" })).toHaveCount(0)
  console.log(JSON.stringify({ phase: baseline ? "before" : "after", ratingClicks: baseline ? 2 : 1 }))
})

async function mockFeedbackWrites(page: Page) {
  const submitted: Record<string, unknown>[] = []
  await page.route("**/api/agent/feedback", async route => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = route.request().postDataJSON() as Record<string, unknown>
    submitted.push(body)
    await route.fulfill({ json: {
      feedback: { ...body, feedback_id: "feedback-1", trajectory_id: "trajectory-1", training_eligible: body.eligible_for_training },
      disclosure: "Saved for evaluation; training requires opt-in.",
    } })
  })
  return submitted
}

test("thumbs can change a rating and survive reopening without refetching", async ({ page }) => {
  let reads = 0
  await page.route("**/api/agent/feedback?**", route => {
    reads++
    return route.fulfill({ json: { feedback: [] } })
  })
  const submitted = await mockFeedbackWrites(page)
  await openChat(page, 1)
  await page.getByText("Answer 0", { exact: true }).hover()
  await page.getByRole("button", { name: "Bad response", exact: true }).click()
  await expect(page.getByRole("button", { name: "Bad response", exact: true })).toHaveAttribute("aria-pressed", "true")
  await page.getByRole("button", { name: "Good response", exact: true }).click()
  await expect(page.getByRole("button", { name: "Good response", exact: true })).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("button", { name: "Bad response", exact: true })).toHaveAttribute("aria-pressed", "false")
  await page.getByRole("button", { name: "Close Stan", exact: true }).click()
  await page.getByRole("button", { name: "Open Stan", exact: true }).click()
  await expect(page.getByRole("button", { name: "Good response", exact: true })).toHaveAttribute("aria-pressed", "true")
  expect(submitted.map(body => body.decision)).toEqual(["reject", "approve"])
  expect(reads).toBe(1)
})

test("History batches feedback with the transcript and hydrates the right turns", async ({ page }) => {
  let reads = 0
  const saved = [{
    feedback_id: "saved-0", trajectory_id: "trajectory-0", session_id: sessionId, client_turn_id: "feedback-turn-0",
    decision: "reject", notes: "Check the source", failure_tags: ["source_quality"], training_eligible: false,
  }, {
    feedback_id: "saved-59", trajectory_id: "trajectory-59", session_id: sessionId, client_turn_id: "feedback-turn-59",
    decision: "approve", training_eligible: false,
  }]
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "Feedback history", message_count: 120,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "Feedback history", transcript: transcript(60), active_jobs: [],
  } }))
  await page.route("**/api/agent/feedback?**", route => {
    reads++
    expect(new URL(route.request().url()).searchParams.has("client_turn_id")).toBe(false)
    return route.fulfill({ json: { feedback: saved } })
  })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Feedback history", { exact: true }).click()
  await expect(page.getByText("Answer 59", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Good response", exact: true }).nth(59)).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("button", { name: "Bad response", exact: true }).nth(0)).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("button", { name: "Bad response", exact: true }).nth(1)).toHaveAttribute("aria-pressed", "false")
  expect(reads).toBe(1)
  await page.getByRole("button", { name: "Feedback details", exact: true }).first().click()
  await expect(page.getByRole("dialog", { name: "Reject Stan response" })).toBeVisible()
  await expect(page.getByRole("textbox", { name: "Review note (optional)" })).toHaveValue("Check the source")
  await expect(page.getByRole("button", { name: "Source quality", exact: true })).toHaveAttribute("aria-pressed", "true")
})

test("optional details and Correct preserve consent and reset to the chosen decision", async ({ page }) => {
  const submitted = await mockFeedbackWrites(page)
  await openChat(page, 1)
  await page.getByText("Answer 0", { exact: true }).hover()
  await page.getByRole("button", { name: "Bad response", exact: true }).click()
  await page.getByRole("button", { name: "Feedback details", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Reject Stan response" })).toBeVisible()
  await page.getByRole("textbox", { name: "Review note (optional)" }).fill("Use the current report")
  await page.getByRole("button", { name: "Source quality", exact: true }).click()
  await expect(page.getByRole("checkbox")).not.toBeChecked()
  await page.getByRole("button", { name: "Save feedback", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Reject Stan response" })).toHaveCount(0)

  await page.getByRole("button", { name: "Correct response", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Correct Stan response" })).toBeVisible()
  await expect(page.getByRole("textbox", { name: "Review note (optional)" })).toHaveValue("Use the current report")
  await page.getByRole("textbox", { name: "Corrected response" }).fill("Corrected answer")
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "Save feedback", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Correct Stan response" })).toHaveCount(0)
  expect(submitted.at(-1)).toMatchObject({ decision: "correct", corrected_response: "Corrected answer", eligible_for_training: true, failure_tags: ["source_quality"] })

  await page.getByRole("button", { name: "Feedback details", exact: true }).click()
  await expect(page.getByRole("textbox", { name: "Corrected response" })).toHaveValue("Corrected answer")
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.getByRole("button", { name: "Good response", exact: true }).click()
  await expect(page.getByRole("button", { name: "Good response", exact: true })).toHaveAttribute("aria-pressed", "true")
  expect(submitted.at(-1)).toMatchObject({ decision: "approve", eligible_for_training: false })
})

test("a failed rating stays unselected and can be retried", async ({ page }) => {
  let writes = 0
  await page.route("**/api/agent/feedback", route => {
    writes++
    return route.fulfill(writes === 1
      ? { status: 503, json: { detail: "Feedback unavailable" } }
      : { json: { feedback: { decision: "reject", feedback_id: "retry-feedback", trajectory_id: "retry-trajectory" } } })
  })
  await openChat(page, 1)
  await page.getByText("Answer 0", { exact: true }).hover()
  await page.getByRole("button", { name: "Bad response", exact: true }).click()
  await expect(page.getByRole("alert")).toBeVisible()
  await expect(page.getByRole("button", { name: "Bad response", exact: true })).toHaveAttribute("aria-pressed", "false")
  await page.getByRole("button", { name: "Bad response", exact: true }).click()
  await expect(page.getByRole("button", { name: "Bad response", exact: true })).toHaveAttribute("aria-pressed", "true")
  expect(writes).toBe(2)
})

test("only proposals carry decision and scope badges", async ({ page }) => {
  const messages = transcript(2).map(message => message.id === "feedback-message-3" ? {
    ...message, toolCalls: [{ id: "proposal-tool", name: "propose_action_item", status: "ok" }],
  } : message)
  await page.addInitScript(({ sessionId, messages }) => {
    localStorage.setItem("agent-chat-current", JSON.stringify({ sessionId, messages }))
  }, { sessionId, messages })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  const chat = page.getByRole("dialog", { name: "Stan assistant" })
  await expect(chat.getByText("Answer 1", { exact: true })).toBeVisible()
  await expect(chat.getByText("Analysis", { exact: true })).toHaveCount(0)
  await expect(chat.getByText("Read-only", { exact: true })).toHaveCount(0)
  await expect(chat.getByText("Proposal", { exact: true })).toHaveCount(1)
  await expect(chat.getByText("Internal State", { exact: true })).toHaveCount(1)
  await expect(chat.getByText("Review this response:")).toHaveCount(0)
  await expect(chat.getByText("Human-reviewed feedback is stored", { exact: false })).toHaveCount(0)
})

for (const outcome of ["done", "error", "cancelled"] as const) {
  test(`a closed chat ${outcome === "done" ? "shows one completion toast" : `does not show success for ${outcome}`}`, async ({ page }) => {
    let finish!: () => void
    const ready = new Promise<void>(resolve => { finish = resolve })
    let polls = 0
    await page.route("**/api/agent/chat/async", route => route.fulfill({ json: {
      job_id: "notification-job", session_id: sessionId, status: "running", next_seq: 1,
      events: [{ seq: 1, event_type: "status", payload: { status: "running" } }],
    } }))
    await page.route("**/api/agent/chat/async/notification-job/events?**", async route => {
      polls++
      await ready
      await route.fulfill({ json: {
        job_id: "notification-job", session_id: sessionId, status: outcome, next_seq: 3,
        events: [
          { seq: 2, event_type: "delta", payload: { text: "Workflow answer" } },
          { seq: 3, event_type: outcome, payload: { session_id: sessionId, message: "Workflow failed" } },
        ],
      } })
    })
    await openChat(page, 1)
    await page.getByRole("button", { name: "Weekly Portfolio Review", exact: true }).click()
    await expect.poll(() => polls).toBe(1)
    await page.getByRole("button", { name: "Close Stan", exact: true }).click()
    finish()
    if (outcome === "done") {
      await expect(page.getByText("Stan finished responding", { exact: true })).toHaveCount(1)
      await page.getByRole("button", { name: "Dismiss completion notification" }).click()
      await expect(page.getByText("Stan finished responding", { exact: true })).toHaveCount(0)
      await page.getByRole("button", { name: "Open Stan" }).click()
      await expect(page.getByText("Workflow answer", { exact: true })).toBeVisible()
      await expect(page.getByText("Stan finished responding", { exact: true })).toHaveCount(0)
    } else {
      await page.getByRole("button", { name: "Open Stan" }).click()
      await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0)
      await expect(page.getByText("Stan finished responding", { exact: true })).toHaveCount(0)
    }
  })
}

test("a resumed background job notifies even if no done event was returned", async ({ page }) => {
  await page.addInitScript(({ sessionId }) => {
    const job = { jobId: "resumed-job", assistantId: "resumed-answer", clientTurnId: "resumed-turn", sessionId, afterSeq: 7 }
    localStorage.setItem("agent-chat-current", JSON.stringify({ sessionId, activeJob: job, messages: [
      { id: "resumed-answer", role: "assistant", content: "Background result", clientTurnId: "resumed-turn", isStreaming: true },
    ] }))
  }, { sessionId })
  await page.route("**/api/agent/chat/async/resumed-job/events?**", route => route.fulfill({ json: {
    job_id: "resumed-job", session_id: sessionId, status: "done", next_seq: 7, events: [],
  } }))
  await page.goto("/workspace")
  await expect(page.getByText("Stan finished responding", { exact: true })).toHaveCount(1)
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByText("Background result", { exact: true })).toBeVisible()
})

test("slow or failed feedback does not block opening History or trigger row retries", async ({ page }) => {
  let finish!: () => void
  const ready = new Promise<void>(resolve => { finish = resolve })
  let reads = 0
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: sessionId, title: "Slow feedback", message_count: 20,
  }] }))
  await page.route(`**/api/memory/sessions/${sessionId}`, route => route.fulfill({ json: {
    title: "Slow feedback", transcript: transcript(10), active_jobs: [],
  } }))
  await page.route("**/api/agent/feedback?**", async route => {
    reads++
    await ready
    await route.fulfill({ status: 503, json: { detail: "Feedback unavailable" } })
  })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Slow feedback", { exact: true }).click()
  await expect(page.getByText("Answer 9", { exact: true })).toBeVisible()
  finish()
  await expect(page.getByRole("button", { name: "Good response", exact: true }).last()).toBeEnabled()
  expect(reads).toBe(1)
})

test.describe("touch feedback", () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } })
  test("ratings remain visible and work without hover", async ({ page }) => {
    const submitted = await mockFeedbackWrites(page)
    await openChat(page, 1)
    const rating = page.getByRole("button", { name: "Good response", exact: true })
    await expect(page.getByRole("group", { name: "Response feedback" }).locator("..")).toHaveCSS("opacity", "1")
    await rating.tap()
    await expect(rating).toHaveAttribute("aria-pressed", "true")
    expect(submitted).toHaveLength(1)
  })
})

test("keyboard focus reveals feedback and Enter submits the rating", async ({ page }) => {
  const submitted = await mockFeedbackWrites(page)
  await openChat(page, 1)
  const rating = page.getByRole("button", { name: "Good response", exact: true })
  await expect(rating).toBeEnabled()
  const actions = page.getByRole("group", { name: "Response feedback" }).locator("..")
  // Opening chat schedules composer autofocus. Wait until focus stays on the rating.
  await expect.poll(async () => {
    await rating.focus()
    return actions.evaluate(element => getComputedStyle(element).opacity)
  }).toBe("1")
  await rating.press("Enter")
  await expect(rating).toHaveAttribute("aria-pressed", "true")
  expect(submitted).toHaveLength(1)
  await page.screenshot({ path: "../tmp/tl216-feedback.png" })
})

test("a completed durable response in the initial job reply also notifies", async ({ page }) => {
  await openChat(page, 1)
  await page.getByRole("button", { name: "Weekly Portfolio Review", exact: true }).click()
  await expect(page.getByText("Stan finished responding", { exact: true })).toHaveCount(1)
})

test("finishing another conversation notifies without replacing the visible transcript", async ({ page }) => {
  let finish!: () => void
  const ready = new Promise<void>(resolve => { finish = resolve })
  let polls = 0
  await page.route("**/api/agent/chat/async", route => route.fulfill({ json: {
    job_id: "other-conversation-job", session_id: sessionId, status: "running", next_seq: 1,
    events: [{ seq: 1, event_type: "status", payload: { status: "running" } }],
  } }))
  await page.route("**/api/agent/chat/async/other-conversation-job/events?**", async route => {
    polls++
    await ready
    await route.fulfill({ json: { job_id: "other-conversation-job", session_id: sessionId, status: "done", next_seq: 2,
      events: [{ seq: 2, event_type: "done", payload: { session_id: sessionId } }],
    } })
  })
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: "other-conversation", title: "Other conversation", message_count: 2,
  }] }))
  await page.route("**/api/memory/sessions/other-conversation", route => route.fulfill({ json: {
    title: "Other conversation", transcript: [{ id: "other-answer", role: "assistant", content: "Other answer", timestamp: 1 }], active_jobs: [],
  } }))
  await openChat(page, 1)
  await page.getByRole("button", { name: "Weekly Portfolio Review", exact: true }).click()
  await expect.poll(() => polls).toBe(1)
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Other conversation", { exact: true }).click()
  await expect(page.getByText("Other answer", { exact: true })).toBeVisible()
  finish()
  await expect(page.getByText("Stan finished responding", { exact: true })).toHaveCount(1)
  await expect(page.getByText("Other answer", { exact: true })).toBeVisible()
})
