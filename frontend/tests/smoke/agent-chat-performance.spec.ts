import { test, expect } from "./fixtures"
import type { Page } from "@playwright/test"

const sessionId = "chat-performance-session"
const baseline = process.env.TL187_BASELINE === "1"

// Each test seeds history, opens the lazily loaded chat and streams; allow for
// a loaded machine running the suite in parallel.
test.describe.configure({ timeout: 60_000 })

async function prepareChat(page: Page, historyLength = 200) {
  await page.addInitScript(({ sessionId, historyLength }) => {
    const messages = Array.from({ length: historyLength }, (_, index) => ({
      id: `history-${index}`,
      role: index % 2 === 0 ? "user" : "assistant",
      content: index % 2 === 0
        ? `Review portfolio risk for position ${index}.`
        : `### Position ${index}\n\nEarnings and liquidity support the thesis. **Watch valuation** as rates change.\n\n| Signal | Reading |\n| --- | --- |\n| Earnings | Improving |\n| Liquidity | Stable |\n\n- Recheck margins next quarter.\n- Keep position size within the risk budget.`,
      timestamp: index,
    }))
    if (!sessionStorage.getItem("chat-performance-seeded")) {
      localStorage.setItem("agent-chat-current", JSON.stringify({ messages, sessionId }))
      localStorage.setItem("agent-chat-sessions:v1", JSON.stringify({
        [sessionId]: { messages, sessionTitle: "Performance chat", sessionTitleSource: null, error: null },
      }))
      sessionStorage.setItem("chat-performance-seeded", "true")
    }

    type Fiber = {
      type?: { name?: string; displayName?: string }
      flags: number
      alternate?: Fiber
      child?: Fiber
      sibling?: Fiber
      memoizedProps?: { message?: { id: string; isStreaming?: boolean } }
    }
    const metrics = {
      phase: "idle",
      started: 0,
      renders: 0,
      mounts: 0,
      chatRenders: 0,
      writes: [] as { key: string; time: number }[],
      longTasks: [] as number[],
      frames: [] as number[],
      scrolls: [] as number[],
      lastFrame: 0,
    }
    const hook = {
      supportsFiber: true,
      renderers: new Map(),
      inject(renderer: unknown) {
        this.renderers.set(1, renderer)
        return 1
      },
      onCommitFiberRoot(_id: number, root: { current: Fiber }) {
        const walk = (fiber?: Fiber) => {
          if (!fiber) return
          const name = fiber.type?.displayName ?? fiber.type?.name
          if (name === "AgentMessage" && fiber.memoizedProps?.message?.id.startsWith("history-")) {
            if (!fiber.alternate) metrics.mounts++
            else if (metrics.phase !== "idle" && (fiber.flags & 1)) metrics.renders++
          }
          if (name === "AgentChat" && metrics.phase !== "idle" && (fiber.flags & 1)) metrics.chatRenders++
          walk(fiber.child)
          walk(fiber.sibling)
        }
        walk(root.current)
      },
      onCommitFiberUnmount() {},
    }
    Object.assign(window, { __REACT_DEVTOOLS_GLOBAL_HOOK__: hook, chatMetrics: metrics })
    const setItem = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (metrics.phase !== "idle" && key.startsWith("agent-chat-")) {
        metrics.writes.push({ key, time: performance.now() })
      }
      return setItem.call(this, key, value)
    }
    new PerformanceObserver(list => {
      if (metrics.phase !== "idle") {
        metrics.longTasks.push(...list.getEntries()
          .filter(entry => entry.startTime >= metrics.started)
          .map(entry => entry.duration))
      }
    }).observe({ type: "longtask" })
    const tick = (time: number) => {
      if (metrics.phase !== "idle" && metrics.lastFrame) metrics.frames.push(time - metrics.lastFrame)
      metrics.lastFrame = time
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
    const scrollTo = Element.prototype.scrollTo
    Element.prototype.scrollTo = function (...args: Parameters<Element["scrollTo"]>) {
      if (metrics.phase !== "idle" && this.closest('[role="dialog"]')) metrics.scrolls.push(metrics.lastFrame)
      return scrollTo.apply(this, args)
    }

    const originalFetch = window.fetch.bind(window)
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined
    const encoder = new TextEncoder()
    Object.assign(window, {
      pushChatEvent(event: string, payload: Record<string, unknown>) {
        streamController?.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`))
      },
      closeChatStream() { streamController?.close(); streamController = undefined },
    })
    window.fetch = (input, init) => {
      if (typeof input === "string" && input.endsWith("/agent/chat") && init?.method === "POST") {
        return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
          start(controller) { streamController = controller },
          cancel() { streamController = undefined },
        }), { headers: { "Content-Type": "text/event-stream" } }))
      }
      return originalFetch(input, init)
    }
  }, { sessionId, historyLength })
  await page.goto("/workspace")
  await page.getByRole("button", { name: "Open Stan" }).click()
  // The chat chunk loads on first open; a busy dev server can take a while.
  await expect(page.getByRole("textbox", { name: "Message Stan" })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(`Review portfolio risk for position ${historyLength - 2}.`, { exact: true })).toBeAttached()
}

async function startStream(page: Page) {
  await page.getByRole("textbox", { name: "Message Stan" }).fill("Stream a portfolio update")
  await page.getByRole("button", { name: "Send message", exact: true }).click()
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible()
}

async function pushEvent(page: Page, event: string, payload: Record<string, unknown>) {
  await page.evaluate(({ event, payload }) => {
    const browser = window as unknown as { pushChatEvent: (event: string, payload: Record<string, unknown>) => void }
    browser.pushChatEvent(event, payload)
  }, { event, payload })
}

test("200-message chat streams and types without rendering finished messages", async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  await prepareChat(page)
  await startStream(page)
  const cdp = await page.context().newCDPSession(page)
  await cdp.send("Performance.enable")
  const before = await cdp.send("Performance.getMetrics")
  await page.evaluate(() => new Promise<void>(resolve => {
    const browser = window as unknown as { chatMetrics: { phase: string; started: number; mounts: number } }
    if (browser.chatMetrics.mounts < 200) throw new Error("React render instrumentation did not observe history mounts")
    browser.chatMetrics.phase = "stream"
    browser.chatMetrics.started = performance.now()
    const push = (window as unknown as { pushChatEvent: (event: string, payload: object) => void }).pushChatEvent
    let count = 0
    const timer = setInterval(() => {
      push("delta", { text: `token${count++} `, session_id: "chat-performance-session" })
      if (count === 120) {
        clearInterval(timer)
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
      }
    }, 25)
  }))
  const streaming = await page.evaluate(() => {
    const browser = window as unknown as { chatMetrics: { phase: string; started: number; renders: number; chatRenders: number; writes: { key: string }[]; frames: number[]; longTasks: number[]; scrolls: number[] } }
    const result = { ...structuredClone(browser.chatMetrics), elapsedMs: performance.now() - browser.chatMetrics.started }
    browser.chatMetrics.phase = "idle"
    return result
  })
  await expect(page.getByText(/token119/)).toBeVisible()
  const after = await cdp.send("Performance.getMetrics")
  const timing = Object.fromEntries(after.metrics
    .filter(metric => ["ScriptDuration", "LayoutDuration", "RecalcStyleDuration", "TaskDuration"].includes(metric.name))
    .map(metric => [metric.name, metric.value - (before.metrics.find(value => value.name === metric.name)?.value ?? 0)]))
  await pushEvent(page, "done", { session_id: sessionId })
  await page.evaluate(() => (window as unknown as { closeChatStream: () => void }).closeChatStream())
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeVisible()

  await page.evaluate(() => {
    const { chatMetrics: metrics } = window as unknown as { chatMetrics: { phase: string; renders: number; chatRenders: number; started: number } }
    metrics.phase = "typing"
    metrics.renders = 0
    metrics.chatRenders = 0
    metrics.started = performance.now()
  })
  await page.getByRole("textbox", { name: "Message Stan" }).pressSequentially("Explain the risk budget", { delay: 25 })
  const typing = await page.evaluate(() => {
    const browser = window as unknown as { chatMetrics: { phase: string; renders: number; chatRenders: number } }
    const result = structuredClone(browser.chatMetrics)
    browser.chatMetrics.phase = "idle"
    return result
  })
  const frames = streaming.frames.toSorted((a, b) => a - b)
  const result = {
    streamingFinishedMessageRenders: streaming.renders,
    typingFinishedMessageRenders: typing.renders,
    typingChatRenders: typing.chatRenders,
    historyWrites: streaming.writes.filter(write => write.key === "agent-chat-sessions:v1").length,
    streamMs: Math.round(streaming.elapsedMs),
    storageWrites: streaming.writes.length,
    longTaskCount: streaming.longTasks.length,
    longestTaskMs: Math.max(0, ...streaming.longTasks),
    frameP95Ms: frames[Math.floor(frames.length * 0.95)] ?? 0,
    maxScrollsPerFrame: Math.max(0, ...streaming.scrolls.map(time => streaming.scrolls.filter(value => value === time).length)),
  }
  console.log(JSON.stringify({ chatPerformance: result }))
  console.log(JSON.stringify({ browserTiming: timing }))
  await testInfo.attach("chat-performance", { body: JSON.stringify(result, null, 2), contentType: "application/json" })
  if (!baseline) {
    expect(result.streamingFinishedMessageRenders).toBe(0)
    expect(result.typingFinishedMessageRenders).toBe(0)
    expect(result.typingChatRenders).toBe(0)
    // Timing acceptance runs alone on the dedicated benchmark server; the
    // regular parallel smoke suite asserts the deterministic work counts.
    if (process.env.TL187_MEASURE === "1") expect(result.longestTaskMs).toBeLessThanOrEqual(50)
    // One history write per 1 s checkpoint, not per token. The 120 tokens take
    // about 3 s, longer on a loaded machine, so bound by the measured duration.
    expect(result.historyWrites).toBeGreaterThanOrEqual(2)
    expect(result.historyWrites).toBeLessThanOrEqual(Math.ceil(result.streamMs / 1000) + 2)
    expect(result.maxScrollsPerFrame).toBeLessThanOrEqual(1)
  }
})

test("checkpoints transient events and saves tool, completion and error state", async ({ page }) => {
  await prepareChat(page, 4)
  await startStream(page)
  await pushEvent(page, "status", { status: "running", session_id: sessionId })
  await pushEvent(page, "phase", { phase: "model_writing" })
  await pushEvent(page, "delta", { text: "Checkpointed response." })
  await expect(page.getByText("Checkpointed response.", { exact: true })).toBeVisible()
  // Only the 1 s checkpoint can save transient events.
  await expect.poll(() => page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-sessions:v1") ?? "{}")
    return saved["chat-performance-session"]?.messages.at(-1)?.content
  })).toBe("Checkpointed response.")

  // Tool calls, completion and errors are saved in the state update itself, so
  // storage holds them by the time the UI shows them. A save left to the
  // checkpoint would lag the UI, so read once instead of polling.
  await pushEvent(page, "tool_call", { name: "get_portfolio", id: "checkpoint-tool" })
  await expect(page.getByRole("dialog").getByTitle(/^Portfolio: /)).toBeVisible()
  expect(await page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}")
    return saved.messages?.at(-1)?.toolCalls?.[0]?.id
  })).toBe("checkpoint-tool")
  await pushEvent(page, "tool_result", { name: "get_portfolio", id: "checkpoint-tool", status: "ok" })
  await pushEvent(page, "done", { session_id: sessionId })
  await page.evaluate(() => (window as unknown as { closeChatStream: () => void }).closeChatStream())
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeVisible()
  expect(await page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}")
    return saved.messages?.at(-1)?.isStreaming
  })).toBe(false)

  await startStream(page)
  await pushEvent(page, "error", { message: "Test stream failure" })
  await expect(page.getByRole("alert").getByText("Test stream failure")).toBeVisible()
  expect(await page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-sessions:v1") ?? "{}")
    return saved["chat-performance-session"]?.error
  })).toBe("Test stream failure")
})

test("polled deltas and resume cursors are checkpointed together across reload", async ({ page }) => {
  await prepareChat(page, 4)
  let finish!: () => void
  const done = new Promise<void>(resolve => { finish = resolve })
  const cursors: number[] = []
  await page.route("**/api/agent/chat/async", route => route.fulfill({ json: {
    job_id: "performance-job", session_id: sessionId, status: "running", next_seq: 1,
    events: [{ seq: 1, event_type: "status", payload: { status: "running" } }],
  } }))
  await page.route("**/api/agent/chat/async/performance-job/events?**", async route => {
    const cursor = Number(new URL(route.request().url()).searchParams.get("after_seq"))
    cursors.push(cursor)
    if (cursor < 4) {
      await route.fulfill({ json: {
        job_id: "performance-job", session_id: sessionId, status: "running", next_seq: 4,
        events: ["alpha ", "beta ", "gamma"].map((text, index) => ({
          seq: index + 2, event_type: "delta", payload: { text },
        })),
      } })
      return
    }
    await done
    await route.fulfill({ json: {
      job_id: "performance-job", session_id: sessionId, status: "done", next_seq: 5,
      events: [{ seq: 5, event_type: "done", payload: { session_id: sessionId } }],
    } })
  })
  await page.getByRole("button", { name: "Weekly Portfolio Review", exact: true }).click()
  await expect(page.getByText("alpha beta gamma", { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => {
    const current = JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}")
    const jobs = JSON.parse(localStorage.getItem("agent-chat-jobs:v1") ?? "{}")
    return { content: current.messages?.at(-1)?.content, cursor: current.activeJob?.afterSeq, jobCursor: jobs["chat-performance-session"]?.afterSeq }
  })).toEqual({ content: "alpha beta gamma", cursor: 4, jobCursor: 4 })
  const requestsBeforeReload = cursors.length
  await page.reload()
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(page.getByText("alpha beta gamma", { exact: true })).toBeVisible()
  await expect.poll(() => cursors.length).toBeGreaterThan(requestsBeforeReload)
  expect(cursors.at(-1)).toBe(4)
  finish()
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden()
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}").activeJob)).toBeNull()
})

test("composer drafts, selection and queued edits survive panel and dialog changes", async ({ page }) => {
  await prepareChat(page, 4)
  await startStream(page)
  const input = page.getByRole("textbox", { name: "Message Stan" })
  await input.fill("Draft with a selection\nand another line")
  await input.evaluate((element: HTMLTextAreaElement) => {
    element.setSelectionRange(6, 12)
    element.dispatchEvent(new Event("select", { bubbles: true }))
  })
  await page.getByRole("button", { name: "Close Stan" }).click()
  await page.getByRole("button", { name: "Open Stan" }).click()
  await expect(input).toHaveValue("Draft with a selection\nand another line")
  await expect.poll(() => input.evaluate((element: HTMLTextAreaElement) => [element.selectionStart, element.selectionEnd])).toEqual([6, 12])
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByRole("button", { name: "Back to chat" }).click()
  await expect(input).toHaveValue("Draft with a selection\nand another line")
  await page.getByRole("button", { name: "Queue follow-up", exact: true }).click()
  await expect(input).toHaveValue("")
  await page.getByRole("button", { name: "Edit queued message" }).click()
  await expect(input).toHaveValue("Draft with a selection\nand another line")
  await expect(page.getByRole("button", { name: "Edit queued message" })).toBeHidden()
  await input.fill("")
  await page.getByRole("button", { name: "Stop generating" }).click()
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeVisible()
})

test("background sessions checkpoint polled text without changing the active conversation", async ({ page }) => {
  await prepareChat(page, 4)
  let continueBackground!: () => void
  let finish!: () => void
  const background = new Promise<void>(resolve => { continueBackground = resolve })
  const done = new Promise<void>(resolve => { finish = resolve })
  await page.route("**/api/memory/sessions?**", route => route.fulfill({ json: [{
    session_id: "other-chat-session", title: "Other conversation", started_at: new Date().toISOString(), message_count: 1,
  }] }))
  await page.route("**/api/memory/sessions/other-chat-session", route => route.fulfill({ json: {
    title: "Other conversation", active_jobs: [],
    transcript: [{ id: "other-message", role: "assistant", content: "Other conversation answer.", timestamp: 1 }],
  } }))
  await page.route("**/api/agent/chat/async", route => route.fulfill({ json: {
    job_id: "background-job", session_id: sessionId, status: "running", next_seq: 1,
    events: [{ seq: 1, event_type: "status", payload: { status: "running" } }],
  } }))
  await page.route("**/api/agent/chat/async/background-job/events?**", async route => {
    const cursor = Number(new URL(route.request().url()).searchParams.get("after_seq"))
    if (cursor >= 3) await done
    else if (cursor >= 2) await background
    await route.fulfill({ json: {
      job_id: "background-job", session_id: sessionId, status: cursor >= 3 ? "done" : "running",
      next_seq: cursor + 1,
      // The last poll completes without a separate done event.
      events: [{ seq: cursor + 1, event_type: "delta", payload: {
        text: cursor < 2 ? "foreground " : cursor < 3 ? "background " : "finished",
      } }],
    } })
  })
  await page.getByRole("button", { name: "Weekly Portfolio Review", exact: true }).click()
  await expect(page.getByText("foreground", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Open conversation history" }).click()
  await page.getByText("Other conversation", { exact: true }).click()
  await expect(page.getByText("Other conversation answer.", { exact: true })).toBeVisible()
  continueBackground()
  await expect.poll(() => page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-sessions:v1") ?? "{}")
    const jobs = JSON.parse(localStorage.getItem("agent-chat-jobs:v1") ?? "{}")
    return { text: saved["chat-performance-session"]?.messages.at(-1)?.content, cursor: jobs["chat-performance-session"]?.afterSeq }
  })).toEqual({ text: "foreground background ", cursor: 3 })
  finish()
  await expect.poll(() => page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("agent-chat-sessions:v1") ?? "{}")
    return saved["chat-performance-session"]?.messages.at(-1)?.content
  })).toBe("foreground background finished")
  const current = await page.evaluate(() => JSON.parse(localStorage.getItem("agent-chat-current") ?? "{}"))
  expect(current.sessionId).toBe("other-chat-session")
  expect(current.messages.at(-1).content).toBe("Other conversation answer.")
  expect(current.activeJob).toBeNull()
})
