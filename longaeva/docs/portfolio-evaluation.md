# Benchmark and portfolio evaluation

Benchmark evaluation follows the [source availability review](gates/benchmarks.md).
Daily Visa prices are unavailable, so Visa strategy results remain unscored.

## Run and outputs

```bash
# From longaeva/ after building the API image:
make evaluate-portfolio ARGS='--output /out/visa_portfolio.json'

# Existing host venv; no database or LLM required:
cd backend
.venv/bin/python -m longaeva_app.cli evaluate-portfolio \
  --output ../data/evaluation/visa_portfolio.json
.venv/bin/python -m longaeva_app.cli evaluate-portfolio \
  --window primary --origin 2024-07-23 --json
```

`--window` accepts `all`, `primary`, or `extension`; `--origin` is repeatable.
An unknown origin, or one outside the selected window, is an error. A source
download/parse failure is recorded in the report and gives CLI exit code 1.
Per-window coverage failures are unavailable rows, with their own sample counts;
they do not trigger a silent source substitution. `--output` writes only the
aggregate report; `--json` prints that same report without progress messages.

The versioned report is
[`data/evaluation/visa_portfolio.json`](../data/evaluation/visa_portfolio.json),
suite `lon28-v1`. Its contract contains:

- `config`, `config_hash`, and `rule_frozen_at`: rule values/hash, origin inventory,
  source and implementation hashes, cutoff/session convention, and as-of date.
- `sources`: status, source/terms URLs, retrieval time, response hash/size,
  Last-Modified, row count, and date bounds. Raw error bodies are never retained.
- `origins`: cutoff, entry/exit dates, exact benchmark labels, per-window return,
  drawdown, exposure, estimation flags, or an explicit unavailable status/reason.
- `aggregates`: independent-window arithmetic mean returns, worst window
  drawdown, and separate scored/unavailable/estimated counts for each series.
- `exclusions`, `overlap`, partial SEC dividend declarations, and the aggregate
  Shiller drift diagnostic.
- `visa_strategy` and `visa_buy_and_hold`: `not_run`, reason, `n_scored: 0`,
  and `metrics: null`. Their per-origin metrics and excess returns are also null.

The Evaluation page and written evaluation report read this saved report.

## Dates, coverage, and benchmarks

Use the harness's origin eligibility rules, including the two known starting-state
exclusions. A prospective origin is listed as excluded from realized scoring.
Enter at the close of the first observed trading session strictly after the
cutoff's America/New_York calendar date. Exit at the close **63 sessions later**:
64 prices and 63 close-to-close return intervals. A later release does not shorten
the holding period. The entry day's close-to-close return is not earned.

The session grid is the union of non-missing FRED price dates and dated Ken French
observations. FRED holiday placeholders alone are not sessions. If either source
identifies a session absent from the other, the other series has a coverage gap.
This is an observed-session grid, not an independently verified exchange calendar;
a date missing from both providers cannot be detected this way. Prices and returns
are never forward-filled. Only completed calendar months are used for the primary
benchmark, because the dividend divisor requires the full month's sessions.

The primary series preserves the manifest formula:

`gross_return(t) = (P(t) + D(month) / (12 × N(month))) / P(t−1)`

Here `D` is Shiller's annualized monthly dividend, and `N` is the month's observed
FRED trading-session count. Require full price coverage for the dividend month.
Carry the latest prior dividend forward only when the current dividend is missing;
flag every affected holding window as estimated. Never fill backward from a future
month. The secondary series compounds `(Mkt-RF + RF) / 100` daily. Missing cells,
including missing RF, are unavailable rather than zero.

These are latest-vintage **outcome benchmarks**, not information supplied to the
forecast at its historical cutoff. The primary is an approximation; Ken French is
US total market. Exact labels and the primary footnote come from the benchmark data review manifest.
Benchmark returns are gross reference returns; they do not incur strategy fees.

The drift diagnostic compares monthly percentage changes in the average daily
approximate wealth divided by monthly CPI with Shiller's **Real Total Return
Price**. It requires recognized column headings, matching CPI, and complete
consecutive months. It records only mean signed/absolute and maximum absolute
differences in percentage points. This measures differences in monthly construction
and timing; it does not validate against the official S&P total-return index.

## Synthetic scoring conventions

`score_synthetic_window` is a pure function for tests, with no live Visa adapter.
It requires a complete explicit session/price panel, cutoff-valid value and
reference-price timestamps, full dividend coverage, and the pinned decision rule.
The rule hash is verified before live fetching/scoring and checked again before a
report returns. The fixed thresholds and 63-session horizon are never fit to results.

All independent windows begin with the same cash capital. The base allocation is
`1 / (1 + add_fraction) = 80%`. Existing sizing rules give hold/add/trim/exit
targets of 80%/100%/60%/0%. For target weight `w` and per-side friction `c`, the
entry notional is `capital × w / (1 + c + funding_rate)`. Remaining capital stays
in cash at zero yield. This funds costs without leverage. The configured funding
rate is zero; its reservation, if nonzero in a separately approved future rule,
would apply only to the incremental add allocation.

Each window opens and liquidates its actual holdings, including the hold case.
Transaction/slippage/impact are 1/3/5 bps on both entry and terminal notional.
The synthetic Visa buy-and-hold comparator invests 100% of the same starting
capital less entry costs and pays the same exit friction. Benchmark comparisons
use the gross reference return. The action table's hold has no rebalance cost;
this evaluation instead charges a complete standalone holding-window round trip.

Dividend entitlement requires `entry_date < ex_date <= exit_date`. A purchase at
the ex-date close earns nothing for that event. Entitlement is a receivable on
the ex-date, becomes cash on the payable date, and is never counted twice or
reinvested. Terminal wealth includes unpaid receivables. Prices must already be
split-consistent; an incomplete dividend ledger is an error, never assumed zero.

Drawdown uses daily marked equity including cash/receivables and entry/exit costs.
Average exposure uses the 63 start-of-interval invested-equity fractions.
Each origin is an independent experiment. Overlaps are disclosed as counts;
returns are not compounded into a single portfolio or treated as independent
observations for statistical significance.

## Recorded run — October 6, 2026

All three selected sources downloaded and parsed successfully. Both benchmark
series scored all **16** eligible origins. Two historical origins and the one
prospective origin were excluded. The primary has one estimated window, from
the April 28, 2026 cutoff, because July dividends were carried forward.

| Series | n | Mean window return | Worst window drawdown |
| --- | ---: | ---: | ---: |
| S&P approximation (FRED + Shiller) | 16 | 4.218988% | −18.752029% |
| US total market (Ken French) | 16 | 4.230213% | −19.557597% |
| Visa strategy / buy-and-hold | 0 | not run | not run |

Nine window pairs overlap, involving 14 windows. These means are exploratory
holding-period summaries, not cumulative or annualized returns.
The drift diagnostic has 53 monthly comparisons: mean absolute difference
0.011046 percentage points; maximum absolute difference 0.241979 percentage points.
The JSON contains the precise values and source hashes.

Only four SEC dividend declarations are retained by the existing parser. They
have source references and hashes but do not establish complete coverage.
Ex-dates use the benchmark data review convention and are not exchange-verified. Real Visa returns,
strategy performance, and excess returns therefore remain explicitly **not run**.
