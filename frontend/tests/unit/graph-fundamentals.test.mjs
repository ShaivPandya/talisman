import assert from "node:assert/strict"
import test from "node:test"
import {
  arithmetic,
  baseSeries,
  chartCsv,
  decodeChart,
  defaultChart,
  displaySeries,
  encodeChart,
  paneIssue,
  removeSeries,
  tableRows,
  transformPoints,
  validateChart,
} from "../../src/lib/graphFundamentals.ts"

const points = Array.from({ length: 17 }, (_, i) => ({
  date: `${2022 + Math.floor(i / 4)}-${["03-31", "06-30", "09-30", "12-31"][i % 4]}`,
  value: 100 * 1.1 ** i,
  estimate: false,
}))
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`)
test("all transforms match hand calculations and use warm-up history", () => {
  const start = points[12].date
  near(transformPoints(points, "none", "quarters", start)[12].value, points[12].value)
  near(transformPoints(points, "yoy", "quarters", start)[12].value, (1.1 ** 4 - 1) * 100)
  near(transformPoints(points, "cagr", "quarters", start)[12].value, (1.1 ** 4 - 1) * 100)
  near(transformPoints(points, "change", "quarters", start)[13].value, 10)
  near(transformPoints(points, "index", "quarters", start)[13].value, 110)
  assert.equal(transformPoints(points, "yoy", "quarters", start)[0].value, null)
  const missing = points.filter((_, i) => i !== 8)
  assert.equal(transformPoints(missing, "yoy", "quarters", start).find((p) => p.date === start).value, null)
})
test("zero and negative baselines remain finite; CAGR does not invent growth across losses", () => {
  const negative = points.map((p, i) => ({ ...p, value: i === 0 ? -100 : 100 }))
  assert.equal(transformPoints(negative, "cagr", "quarters", points[0].date)[12].value, null)
  const zero = points.map((p) => ({ ...p, value: 0 }))
  assert.ok(transformPoints(zero, "index", "quarters", points[0].date).every((p) => p.value === null))
})
function display(id, values, unit = "percent", currency = null) {
  return {
    config: { ...baseSeries("AAA", "roic", 0), id },
    label: id,
    unit,
    currency,
    points: values.map((value, i) => ({ date: points[i].date, value })),
  }
}
test("all arithmetic operators, zero division, unit and grid refusal", () => {
  const a = display("a", [10, 20]),
    b = display("b", [2, 0])
  for (const [operation, expected] of [
    ["subtract", 8],
    ["add", 12],
    ["divide", 5],
    ["multiply", 20],
  ])
    assert.equal(arithmetic(a, b, { ...a.config, operation }).points[0].value, expected)
  assert.equal(arithmetic(a, b, { ...a.config, operation: "divide" }).points[1].value, null)
  assert.throws(() => arithmetic(a, display("b", [2]), { ...a.config, operation: "subtract" }), /period grid/)
  assert.throws(
    () => arithmetic(a, display("b", [2, 3], "currency", "USD"), { ...a.config, operation: "add" }),
    /matching units/,
  )
  assert.ok(paneIssue([a, display("b", [1], "currency", "USD")]))
})
test("state round-trip preserves every editor option and rejects invalid references and limits", () => {
  const state = defaultChart()
  state.panes[0].series[0] = {
    ...state.panes[0].series[0],
    label: 'Møøse, "peer"',
    transform: "index",
    visualization: "bar",
    width: 4,
  }
  assert.deepEqual(decodeChart(encodeChart(state)), state)
  assert.throws(() => validateChart({ ...state, tickers: Array(7).fill("AAA") }))
  state.panes[0].series.push({ ...baseSeries("", "", 0), id: "cycle", operation: "divide", a: "cycle", b: "cycle" })
  assert.throws(() => validateChart(state), /Invalid/)
})
test("table and CSV export use exactly the transformed chart data and quote labels", () => {
  const state = {
    ...defaultChart(),
    tickers: ["AAA"],
    panes: [
      {
        id: "p",
        field: "revenue",
        series: [{ ...baseSeries("AAA", "revenue", 0), id: "a", label: 'A, "B"', transform: "index" }],
      },
    ],
  }
  const result = displaySeries(
    state,
    {
      series: [
        {
          ticker: "AAA",
          field: "revenue",
          unit: "currency",
          currency: "USD",
          source: "SEC",
          as_of: "2026-01-01",
          points,
          estimate_coverage: { supported: true },
        },
      ],
      start_date: points[12].date,
      end_date: null,
      period: "quarters",
    },
    [],
  )
  const all = [...result.values()]
  near(tableRows(all, points[12].date, null)[0].a, 100)
  assert.ok(chartCsv(all, points[12].date, null).includes('A, ""B""'))
  assert.ok(chartCsv(all, points[12].date, null).includes('"100"'))
})
test("removing an input also removes dependent calculations and empty panes", () => {
  const state = defaultChart(),
    input = state.panes[0].series[0]
  state.panes.push({
    id: "calc",
    series: [{ ...baseSeries("", "", 0), id: "c", operation: "subtract", a: input.id, b: state.panes[0].series[1].id }],
  })
  const next = removeSeries(state, input.id)
  assert.ok(!next.panes.some((p) => p.id === "calc"))
  assert.equal(next.panes[0].series.length, 3)
})

test("different fiscal calendars keep continuous lines without fabricating values", async () => {
  const { panePlotData } = await import("../../src/lib/graphFundamentals.ts")
  const cdns = {
    ...display("CDNS", []),
    points: [
      { date: "2025-03-31", value: 20 },
      { date: "2025-06-30", value: 25 },
      { date: "2025-09-30", value: 30 },
    ],
  }
  const snps = {
    ...display("SNPS", []),
    points: [
      { date: "2025-04-30", value: 10 },
      { date: "2025-07-31", value: 15 },
      { date: "2025-10-31", value: 20 },
    ],
  }
  const dates = [...cdns.points, ...snps.points].map((p) => p.date).sort()
  const plot = panePlotData([cdns, snps], dates)
  assert.equal(plot.lines.length, 2)
  assert.deepEqual(
    plot.lines.map((line) => line.points.length),
    [3, 3],
  )
  assert.equal(plot.rows.find((row) => row.date === "2025-04-30")[plot.lines[0].key], undefined)
  assert.deepEqual(plot.lines[0].points, cdns.points)
})

test("real missing periods split lines and isolated observations remain visible", async () => {
  const { panePlotData } = await import("../../src/lib/graphFundamentals.ts")
  const a = {
    ...display("A", []),
    points: [
      { date: "2025-03-31", value: 10 },
      { date: "2025-06-30", value: null },
      { date: "2025-09-30", value: 20 },
      { date: "2026-03-31", value: 30 },
    ],
  }
  const plot = panePlotData(
    [a],
    a.points.map((p) => p.date),
  )
  assert.deepEqual(
    plot.lines.map((line) => line.points.map((p) => p.value)),
    [[10], [20], [30]],
  )
  assert.equal(plot.lines.filter((line) => line.showLegend).length, 1)
})

test("estimates and bars preserve their own observations on a mixed date grid", async () => {
  const { panePlotData } = await import("../../src/lib/graphFundamentals.ts")
  const a = {
    ...display("A", []),
    points: [
      { date: "2025-03-31", value: 10 },
      { date: "2025-06-30", value: 15, estimate: true },
      { date: "2025-09-30", value: 20, estimate: true },
    ],
  }
  a.config.visualization = "bar"
  const dates = ["2025-03-31", "2025-04-30", "2025-06-30", "2025-07-31", "2025-09-30"]
  const plot = panePlotData([a], dates)
  assert.deepEqual(
    plot.lines[0].points.map((p) => p.value),
    [10, 15, 20],
  )
  assert.equal(plot.lines[0].estimate, true)
  assert.equal(plot.rows[0].A, 10)
  assert.equal(plot.rows[1].A, undefined)
})

test("hidden warm-up points are excluded from plotted lines", async () => {
  const { panePlotData } = await import("../../src/lib/graphFundamentals.ts")
  const a = {
    ...display("A", []),
    points: [
      { date: "2021-03-31", value: 10 },
      { date: "2025-03-31", value: null },
    ],
  }
  const plot = panePlotData([a], ["2025-03-31"])
  assert.equal(plot.lines[0].points.length, 0)
})
