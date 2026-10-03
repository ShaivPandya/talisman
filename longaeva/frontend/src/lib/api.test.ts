import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError, getRunResults, listRuns } from "./api"

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

describe("api client", () => {
  it("returns JSON on success", async () => {
    const payload = [{ id: "run-1", status: "succeeded" }]
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, payload)),
    )
    await expect(listRuns()).resolves.toEqual(payload)
    expect(fetch).toHaveBeenCalledWith("/api/runs?limit=50")
  })

  it("surfaces FastAPI detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(422, { detail: "cutoff not supported" })),
    )
    await expect(listRuns()).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      detail: "cutoff not supported",
    })
  })

  it("treats unfinished results as 409", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(409, { detail: "Run has not succeeded" })),
    )
    try {
      await getRunResults("abc")
      throw new Error("expected ApiError")
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect(err).toMatchObject({ status: 409, detail: "Run has not succeeded" })
    }
  })
})
