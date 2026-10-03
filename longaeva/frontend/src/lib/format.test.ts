import { describe, expect, it } from "vitest"

import { fmtByUnit, fmtMetricValue, fmtRatioPct, fmtUsdMillions, shortHash } from "./format"

describe("format", () => {
  it("formats usd millions and ratios", () => {
    expect(fmtUsdMillions(4160.3)).toBe("$4,160m")
    expect(fmtRatioPct(0.1234)).toBe("12.3%")
    expect(fmtByUnit(1.25, "usd_billions")).toBe("$1.3bn")
  })

  it("looks up unit from the metric catalog", () => {
    expect(fmtMetricValue(100, "net_revenue")).toBe("$100m")
    expect(fmtMetricValue(0.2, "cross_border_share")).toBe("20.0%")
  })

  it("shortens hashes", () => {
    expect(shortHash("abcdef123456", 6)).toBe("abcdef")
    expect(shortHash(null)).toBe("—")
  })
})
