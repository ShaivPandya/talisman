import { afterEach, describe, expect, it, vi } from "vitest"
import {
  correctionDraft,
  correctionPayload,
  previewKey,
  queryString,
  sameCutoff,
  saveReview,
  type ObservationReview,
} from "./evidence"

afterEach(() => vi.unstubAllGlobals())
const review = {
  observation: {
    id: "obs",
    statement_type: "measured",
    activity_type: "room_nights",
    geography: "global",
    period_start: "2024-01-01",
    period_end: "2024-03-31",
    value: 8,
    range_low: null,
    range_high: null,
    unit: "percent",
    basis: "units",
    source_id: "immutable",
    review_status: "rejected",
  },
  decisions: [
    { version: 1, corrected_payload: { value: 9, geography: "US" } },
    { version: 2, corrected_payload: null },
  ],
  effective: null,
} as unknown as ObservationReview

describe("evidence filters and corrections", () => {
  it("encodes search text and explicit cutoff without empty filters", () => {
    const params = new URLSearchParams(
      queryString({
        q: ' "cross-border" & travel ',
        company: "",
        cutoff_ts: "2024-07-23T16:05:38-04:00",
        offset: 0,
      }),
    )
    expect(params.get("q")).toBe('"cross-border" & travel')
    expect(params.has("company")).toBe(false)
    expect(params.get("offset")).toBe("0")
    expect(params.get("cutoff_ts")).toBe("2024-07-23T16:05:38-04:00")
    expect(sameCutoff(params.get("cutoff_ts")!, "2024-07-23T20:05:38Z")).toBe(
      true,
    )
  })
  it("preserves prior corrections on re-review, never changing source fields", () => {
    const draft = correctionDraft(review)
    expect(draft.value).toBe("9")
    expect(draft.geography).toBe("US")
    const payload = correctionPayload({ ...draft, value: "10", geography: "" })
    expect(payload.value).toBe(10)
    expect(payload.geography).toBeNull()
    expect(payload.range_low).toBeNull()
    expect(payload).not.toHaveProperty("source_id")
    expect(payload.unit).toBe("percent")
  })
  it("refuses invalid numbers, dates and ranges", () => {
    const draft = correctionDraft(review)
    expect(() => correctionPayload({ ...draft, value: "Infinity" })).toThrow(
      "finite",
    )
    expect(() =>
      correctionPayload({ ...draft, period_start: "2025-01-01" }),
    ).toThrow("Period start")
    expect(() =>
      correctionPayload({ ...draft, range_low: "4", range_high: "3" }),
    ).toThrow("Range low")
    expect(() => correctionPayload({ ...draft, unit: " " })).toThrow("required")
  })
  it("invalidates a rule preview for every application input and decision version", () => {
    const args = ["base", "observation", 1, "reviewer", "rationale"] as const
    const key = previewKey(...args)
    expect(
      previewKey(
        "other",
        ...(args.slice(1) as [string, number, string, string]),
      ),
    ).not.toBe(key)
    expect(previewKey("base", "other", 1, "reviewer", "rationale")).not.toBe(
      key,
    )
    expect(
      previewKey("base", "observation", 2, "reviewer", "rationale"),
    ).not.toBe(key)
    expect(previewKey("base", "observation", 1, "other", "rationale")).not.toBe(
      key,
    )
    expect(previewKey("base", "observation", 1, "reviewer", "other")).not.toBe(
      key,
    )
  })
  it("surfaces write failures without retrying or changing the draft", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Invalid correction" }), {
          status: 422,
          headers: { "content-type": "application/json" },
        }),
      )
    vi.stubGlobal("fetch", fetch)
    const body = {
      observation_id: "obs",
      decision: "correct" as const,
      decided_by: "reviewer",
      rationale: "Reason",
      corrected_payload: correctionPayload(correctionDraft(review)),
    }
    const before = JSON.stringify(body)
    await expect(saveReview(body)).rejects.toMatchObject({
      status: 422,
      detail: "Invalid correction",
    })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(body)).toBe(before)
  })
})
