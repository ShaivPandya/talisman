# Graph Fundamentals

Open `/graph-fundamentals` next to Chart. The default compares SPGI, MCO,
MSCI and MORN over five years in ROIC, FCF Yield and Operating Margin panes.
Adding a ticker adds it to each field-based pane. Charts support six tickers,
four panes and 24 series, including calculated series. Empty panes disappear.

Search one input for companies or curated fields, or browse the categories.
Each series has colour, width, line/bar, stroke, pane, transform and estimate
settings. Incompatible units require a transform or separate panes. Mixed
currencies display a warning; there is no FX conversion. Moving a series into a
new pane creates a custom pane without a field template.

## Data and definitions

The catalog endpoint exposes all 40 fields enumerated in TL-251, with formulas,
units, categories and estimate eligibility. Actuals prefer SEC companyfacts;
tickers without usable SEC revenue histories use limited yfinance statements.
When SEC revenue is usable but reported debt, shares, balance-sheet inputs or
pretax/operating income are missing, matching-currency yfinance statements fill
only those gaps. Existing SEC values are preserved. A unique fiscal period
within seven days accommodates provider month-end labels for 52/53-week filers;
the original provider date is retained. Tooltips and series metadata label the
fallback, whose limited history may leave older periods unavailable.
There is no non-GAAP adjustment engine: EPS actuals are **Diluted EPS (GAAP)**.

The period selector controls flows: discrete quarters, rolling four-quarter
sums (LTM), or reported full years. Balance-sheet values remain period-end
stocks in all three modes. Margins divide aligned flows. ROIC, ROE, ROA and asset
turnover use opening/closing average capital, equity or assets for the selected
period. Quarterly returns are quarterly rates, not annualized rates. ROIC uses
operating income after the reported effective tax rate; invalid tax rates and
nonpositive capital denominators produce gaps.

Total debt prefers reported long-term debt including current maturities, adding
separately reported short-term borrowings. Otherwise it uses non-overlapping
current and noncurrent components. Cash uses reported cash and equivalents;
when only a combined total is available, it includes restricted cash, as stated
in the field definition. EBITDA uses a reported combined D&A flow or the sum of
explicit depreciation and intangible amortization flows. Missing components
are not assumed to be zero.

Market histories are computed by Talisman. A price is the close on the reporting
period end, or the preceding trading day within seven calendar days. Future
prices are never used. Yahoo's split-adjusted Close is restored to the period's
share basis using subsequent split events, then multiplied by reported
period-end shares. A newer DEI cover-page share count cannot displace the GAAP
period-end count. Missing period-end shares, incompatible quote/reporting
currencies and unsupported ADR conversions leave gaps. P/E, P/S, EV/EBITDA and
yields use trailing annual flows even on a quarterly grid. Negative earnings
produce an unavailable P/E rather than a misleading multiple.

Filing selection follows Financials: period-owned filings and explicit
amendments take precedence over later comparative copies. Concept chains fill
missing periods in vetted order. Filing dates and links are available in the
tooltip/table. This is descriptive history, **not a point-in-time backtest**.

Consensus is yfinance EPS and revenue only, for the supplied current/next
quarter and current/next year. No LTM or derived estimates are manufactured.
Dotted tails show analyst counts, the observed fetch time and the accounting
basis when supplied. Older yfinance versions cannot request GAAP methodology;
the chart explicitly labels an unspecified basis, which may differ from GAAP
actuals. The fetch timestamp is not represented as the provider's publication
date. Missing or stale filing coverage disables the forecast extension.

## Calculations and persistence

Transforms apply to fetched histories before the visible range is clipped:
YoY compares matching periods one year apart; change-from-start uses
`(value - baseline) / abs(baseline)`; indexing uses `value / baseline * 100`;
rolling 3Y CAGR requires positive endpoints three years apart. Zero denominators
and missing comparison periods remain null. Three years of warm-up history are
included so the first visible point can have a valid transform.

Arithmetic supports subtraction, division, addition and multiplication between
existing series. Date grids must match exactly, including estimate settings.
Addition/subtraction require matching units and currencies; cross-currency
arithmetic is refused. Division by zero produces a gap. Removing an input also
removes dependent calculations. Chart, table and CSV use the same calculations;
CSV exports full numeric precision while the UI formats numbers for reading.
Companies can report on different fiscal dates: line segments connect each
series' own observations across other tickers' date slots. Explicit missing
observations and missing reporting periods still break the line. Isolated valid
observations render as dots, and the pane reports availability for the visible
range rather than counting hidden warm-up data.

Saved charts persist versioned layout state, not frozen data. Open refreshes
values from sources; Save updates, Save As creates a copy, and the name input
supports renaming. Every read/update/delete is scoped to the authenticated
owner. Share URLs carry compact chart configuration without accessing another
owner's saved object. Recipients must already be able to sign in. Sign-in
preserves the original path and query. Invalid shared layouts fall back to a
default chart with an explanation.

## Operations and verification

Apply migration `20261106_0001` before deploying the new API. The catalog is
`GET /api/graph-fundamentals/catalog`; comparison data is
`POST /api/graph-fundamentals`; chart CRUD is under
`/api/graph-fundamental-charts`, including PUT for update/rename. Securities search
uses `/api/graph-fundamentals/securities?q=...`.

Raw ticker bundles and computed ticker/period grids use `long_cache`, independent
of requested fields and range. A cache miss bypasses the EDGAR fetcher's process
lifetime cache so the one-hour route TTL can refresh filings. Six shared workers
bound ticker concurrency; the route returns partial results after a 50-second
budget, below the existing 60-second client timeout. Provider requests already
running may finish and populate the cache after the response.

Validation commands:

```
python -m pytest tests/test_graph_fundamentals.py tests/test_edgar_periods.py tests/test_financials_history.py tests/test_screener_runs.py tests/test_data_job_pacing.py tests/test_source_registry.py -q
cd frontend
npm run test:graph-fundamentals
npm run lint
npm run build
```

TL-251 verification used live SEC/Yahoo observations for the four default peers,
fixture-based arithmetic and period identities, and disposable Postgres 18 for
migration upgrade/downgrade and owner-scoped chart CRUD. The browser's exported
CSV matched all 229 populated cells across 20 periods and 12 default series.
A failing fifth ticker added three empty series with reasons while the four
working peers continued rendering.

A live cold request for SPGI/MCO/MSCI/MORN/AAPL/MSFT, four fields and 10Y
returned 24 populated series in 4.45 seconds with exactly six companyfacts
fetches. The same warm request took 0.003 seconds with no additional fetches.
These observations measure provider conditions at verification time, not a
latency guarantee during upstream outages.


### Mixed-calendar regression verification

CDNS/SNPS exposed a chart alignment bug: inserting every peer's dates as nulls
broke all interleaved lines while their actual values were present. Plot segments
now distinguish other companies' date slots from missing reported observations,
and single valid observations remain visible as dots. Yahoo raw statement labels
also require normalization (for example `TotalDebt`, not only `Total Debt`).
Matching-currency fallback supplies missing reported balance and ROIC income
inputs without replacing SEC values. Data cache keys are versioned to invalidate
older incomplete results.

The follow-up checks used CDNS, SNPS, ADBE, NVDA, COST, ORCL, MSFT, AAPL and the
four original peers across Quarters, LTM and Annual. CDNS/SNPS browser checks
confirmed actual SVG paths for both companies in all three default panes and
visible isolated points in LTM. Older ROIC and valuation gaps remain when the
required reported inputs are outside the available statement coverage.
