import { afterEach, expect, it, vi } from "vitest"
import { getSavedReport, replayRun } from "./reportApi"
import { getValuationActions } from "./valuationApi"

afterEach(() => vi.unstubAllGlobals())

it("retains pending content ownership from the API", async () => {
  const pending = {
    key: "extraction",
    status: "pending",
    owner_issue: "LON-18",
    forecast: null,
  }
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(pending), {
          headers: { "content-type": "application/json" },
        }),
      ),
  )
  expect(await getSavedReport("extraction")).toEqual(pending)
})

it("uses saved defaults for valuation and the explicit replay endpoint", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          new Response("{}", {
            headers: { "content-type": "application/json" },
          }),
        ),
      ),
  )
  await getValuationActions("saved-id")
  expect(fetch).toHaveBeenLastCalledWith(
    "/api/valuation/actions",
    expect.objectContaining({ method: "POST", body: '{"run_id":"saved-id"}' }),
  )
  await replayRun("saved-id")
  expect(fetch).toHaveBeenLastCalledWith(
    "/api/runs/saved-id/replay",
    expect.objectContaining({ method: "POST", body: undefined }),
  )
})
