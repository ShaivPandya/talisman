# Earnings/multiple valuation bridge

LON-25 / FR-12.

The bridge turns a saved run's operating-profit paths into forward earnings and a
value range. It does not discount cash flows and it does not ingest prices
(LON-28). Visa daily closes stay blocked (LON-6), so the multiple is a trailing
P/E built from filings already in the package.

## Forward earnings

The engine metric is `operating_profit_ex_special_items`, in USD millions, on
each path and quarter. The first four simulated quarters are the forward year.
Later quarters, if a run has them, are ignored.

Tax rate, net interest/other, and diluted shares are held flat at the origin
starting state (`tax_rate`, `net_interest_other`, `diluted_shares`). A request
may override any of them. The response names each assumption's source as
`starting_state` or `request_override`.

```
earnings_q = (operating_profit_q + net_interest_other) * (1 - tax_rate)
forward_eps = sum(earnings_q over 4 quarters) / diluted_shares
```

Operating profit and net interest/other are USD millions. Diluted shares are
millions of shares, so forward EPS is USD per share. Equity value in USD
millions is forward EPS times the multiple times the share count, which is the
same as forward earnings times the multiple.

## Multiple band

For each fiscal quarter from FY2023Q1 through FY2026Q2:

- Price is the Total row of **Average Purchase Price per Share** in the Issuer
  Purchases of Equity Securities table (10-Q Item 2 or 10-K Item 5). The quote
  and character span point at that number in the retained HTML.
- Trailing EPS is the sum of that quarter and the previous three quarters of
  diluted EPS excluding special items, from the earnings releases.
- Trailing P/E is price divided by that sum.

FY2023Q1 is the first quarter with four releases of EPS excluding special items
(the series starts at FY2022Q2). The history is
[`data/fixtures/valuation/visa_pe_history.csv`](../data/fixtures/valuation/visa_pe_history.csv).

| Period | Avg purchase price | TTM EPS | Trailing P/E | Price filing accepted |
| --- | --- | --- | --- | --- |
| FY2023Q1 | 198.74 | 7.88 | 25.22 | 2023-01-27 |
| FY2023Q2 | 222.09 | 8.18 | 27.15 | 2023-04-26 |
| FY2023Q3 | 229.19 | 8.36 | 27.42 | 2023-07-25 |
| FY2023Q4 | 241.03 | 8.76 | 27.51 | 2023-11-15 |
| FY2024Q1 | 239.45 | 8.99 | 26.64 | 2024-01-25 |
| FY2024Q2 | 280.80 | 9.41 | 29.84 | 2024-04-23 |
| FY2024Q3 | 276.75 | 9.67 | 28.62 | 2024-07-23 |
| FY2024Q4 | 270.85 | 10.05 | 26.95 | 2024-11-13 |
| FY2025Q1 | 300.61 | 10.39 | 28.93 | 2025-01-30 |
| FY2025Q2 | 340.26 | 10.64 | 31.98 | 2025-04-29 |
| FY2025Q3 | 349.24 | 11.20 | 31.18 | 2025-07-29 |
| FY2025Q4 | 349.77 | 11.47 | 30.49 | 2025-11-06 |
| FY2026Q1 | 342.13 | 11.89 | 28.77 | 2026-01-29 |
| FY2026Q2 | 320.66 | 12.44 | 25.78 | 2026-04-28 |

A quarter is inside a cutoff only when the price filing **and** all four EPS
releases were accepted at or before that cutoff. low / mid / high are the
minimum, median, and maximum of those ratios. The median of an even count is
the average of the two central ratios. Fewer than four quarters is unsupported.

At the 2024-07-23 origin (`2024-07-23T20:05:38Z`) the FY2024Q3 earnings release
is already in, but the FY2024Q3 10-Q is accepted about two hours later, so that
quarter's P/E stays out. The band is FY2023Q1–FY2024Q2 (6 quarters).

Label, returned on the band:

> Trailing P/E from Visa's average open-market repurchase price (SEC 10-Q/10-K Issuer Purchases of Equity Securities, quarterly Average Purchase Price per Share) divided by trailing four-quarter diluted EPS excluding special items (SEC earnings releases). This is a quarterly buyback average, not a market close. The trailing multiple is applied to forward earnings.

The window phrase is appended (`Window: FY2023Q1–FY2024Q2 (6 quarters).`).

A request may pass `multiple_range: {low, mid, high}` instead. That band is
labeled a request override and is not described as the historical window.

Rebuild the fixture from the bundled originals (Compose mounts `data/`
read-only, so use the host venv):

```bash
make valuation-multiples
# or: cd backend && .venv/bin/python -m longaeva_app.cli valuation-multiples --write
```

## What the value grid separates

Forward EPS is summarized by its mean and by p10, p50, and p90 across paths.
The grid is those three EPS points times low, mid, and high, as USD per share
and as equity in USD millions.

- **Earnings-driven.** Hold the mid multiple. The spread is p90 minus p10.
  This is the business uncertainty.
- **Multiple-driven.** Hold median EPS (p50). The spread is the high multiple
  minus the low multiple. This is the multiple uncertainty.
- **Outer envelope.** p10 EPS times the low multiple, through p90 EPS times the
  high multiple. The label is `not a probability interval`. It is the product
  of the two extremes, not a joint probability.

## Unsupported

The response is HTTP 200 with `status: "unsupported"`, a reason, and no value
grid, forward EPS, spreads, or envelope:

| Condition | Why |
| --- | --- |
| Fewer than 4 simulated quarters | Forward earnings are a year. |
| Missing tax rate, non-finite net interest/other, tax rate outside [0, 1), or non-positive diluted shares | The bridge will not invent an assumption. Net interest/other may be negative. |
| Multiple band missing, shorter than 4 quarters, or not ordered `low <= mid <= high` with each value positive | Includes early cutoffs before four repurchase quarters are public. |
| Any path has forward EPS ≤ 0 | The reason states how many paths. Those paths are not dropped; dropping them would bias the value upward. |

A run that has not succeeded is HTTP 409. An unknown run id is HTTP 404.

## API

| Method | Path |
| --- | --- |
| POST | `/valuation/bridge` `{run_id, tax_rate?, net_interest_other?, diluted_shares?, multiple_range?}` |
| GET | `/valuation/multiples?cutoff_ts=` |

`GET /valuation/multiples` without a cutoff returns the full FY2023Q1–FY2026Q2
history and the band over all 14 quarters. With `cutoff_ts`, both the rows and
the band are limited to filings accepted at or before that time.

## Handoffs

- **LON-26.** Illustrative actions should consume this per-share value and the
  separated spreads. If the bridge is unsupported, show the reason and do not
  invent a price. Do not treat the outer envelope as a probability.
- **LON-36.** The Valuation page calls `POST /valuation/bridge` once per saved
  run and `GET /valuation/multiples` for the window. Draw earnings-driven and
  multiple-driven spreads as separate bars. Keep the buyback-average label.
