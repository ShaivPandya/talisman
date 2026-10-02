# Gate: Benchmark and price data decision

LON-6 · planning v1 · settled October 2, 2026.

## Question

Which license-compliant free source supports after-cost excess-return scoring?

## Answer

**Option B as primary, with Visa prices blocked.** No free API key was registered
for this gate. The primary benchmark is an **approximation** of S&P 500 total
return built from the FRED `SP500` daily price index plus Shiller monthly
dividends accrued evenly across trading days. Ken French daily `Mkt-RF + RF` is
the secondary reference and is never relabeled as the S&P 500. Visa daily prices
have no license-compliant free source without a key, so Visa buy-and-hold and
portfolio scoring (LON-28) are recorded as **not run**. Visa dividends remain
available from SEC Ex. 99.1 declarations (public domain).

## Decision

| Option | Role | Status | Series |
| --- | --- | --- | --- |
| A | Rejected primary | rejected (no key) | SPY dividend-adjusted close via Tiingo |
| **B** | **Primary benchmark** | **selected** | FRED `SP500` + Shiller `ie_data.xls` dividends |
| C | Secondary reference | selected | Ken French daily `Mkt-RF + RF` |
| Visa prices | Comparison input | **blocked** | Unblock via Tiingo `V` (personal email) |
| Visa dividends | Comparison input | selected | SEC Ex. 99.1 declarations |

Fallback chain: **A → B → C**. With no key, A is skipped and B is primary.

## Exact UI labels (reviewer approval)

| Role | Label text |
| --- | --- |
| Primary | `S&P 500 total return (approximation: FRED S&P 500 price index + Shiller monthly dividends, accrued daily)` |
| Primary footnote | `Not the official S&P 500 Total Return index. Prices: S&P Dow Jones Indices via FRED (SP500). Dividends: Shiller ie_data.xls (four-quarter S&P totals interpolated monthly), spread evenly across trading days. Fetched by script; not redistributed.` |
| Secondary | `US total-market total return (Ken French Mkt-RF + RF, CRSP value-weighted) - not the S&P 500` |
| Visa | `Visa buy-and-hold total return: not run (no license-compliant free daily Visa price source)` |

Label rule enforced by tests: any string containing "S&P 500 total return" must
also say "approximation" and name FRED and Shiller. The Ken French label must
contain "not the S&P 500". The word "consensus" does not appear.

## Method

\[
TR_t = TR_{t-1} \times \frac{P_t + d_t}{P_{t-1}},\quad
d_t = \frac{D_m}{12 \times N_m}
\]

- \(P_t\): FRED `SP500` daily close (price index, not total return).
- \(D_m\): Shiller annualized dividend for calendar month \(m\) (four-quarter S&P
  totals interpolated monthly).
- \(N_m\): count of FRED trading days in month \(m\).
- If Shiller has not yet published month \(m\), carry forward the last available
  \(D_m\) and flag the result as **estimated**.

Visa ex-dividend convention: ex-date = record date from 2024-05-28 onward (T+1
settlement); before that, one business day before the record date.

### Known approximation errors

1. FRED `SP500` is a **price** index; official S&P 500 Total Return is not free.
2. Shiller dividends are monthly interpolations of quarterly totals, not
   day-accurate ex-dividend drops of the index constituents.
3. Spreading \(D_m / 12\) evenly across trading days mis-times intra-month
   dividend cash flows.
4. FRED retains a rolling ~10-year daily window for this series.
5. Ken French is CRSP value-weighted total market, not the S&P 500, and has a
   monthly update lag.

## Terms summary (retrieval date 2026-10-02)

| Source | Terms URL | Summary | Redistribution |
| --- | --- | --- | --- |
| FRED `SP500` | [fred.stlouisfed.org/series/SP500](https://fred.stlouisfed.org/series/SP500) | S&P Dow Jones Indices copyright; FRED tags "Copyrighted: Pre-Approval Required". Reproduction prohibited without S&P written permission. | fetch script; never bundle |
| Shiller `ie_data.xls` | [shillerdata.com](https://shillerdata.com/) | Academic research dataset for *Irrational Exuberance*. Not an official S&P TR product. | fetch script; never bundle |
| Ken French daily | [data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) | Free for research with citation; monthly update lag; CRSP VW, not S&P 500. | fetch script (or derived demo returns with attribution) |
| Tiingo (rejected / unblock) | [app.tiingo.com/tos](https://app.tiingo.com/tos/) | Starter/Trial: no persistent storage of Tiingo Data (§1.6(a)). API is internal consumption only (§7.3). Corporate email → business account (§4.9). Aggregate Derived Products that cannot reconstruct prices may be retained (§1.6(c)). | fetch script; key required |
| Alpha Vantage (rejected) | [terms](https://www.alphavantage.co/terms_of_service/) | Free key is personal, non-commercial (§2). Daily adjusted is premium; free `outputsize=full` is premium-only (latest 100 bars on free compact). | rejected |
| Visa dividends (SEC) | [EDGAR fair access](https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm) | Public domain. | bundle ok |

Both FRED and Ken French appear in the hackathon dataset catalog (pp. 5–6).

## Rejected sources

| Source | Reason |
| --- | --- |
| Tiingo option A | Requires a free key; user chose no-key path |
| Alpha Vantage | Free tier: 100 daily bars; adjusted daily is premium; personal license |
| S&P DJI direct | 403 to scripted requests |
| Stooq | JavaScript challenge; not bypassed (DR-09) |
| Nasdaq API | Timed out during planning checks |
| yfinance | Unofficial; not allowed in the package |
| Visa 10-Q repurchase average | Monthly averages; too coarse for daily scoring (note for LON-25) |

## Redistribution policy

- No FRED, Shiller, Ken French or Tiingo payloads are written to disk or shipped
  in the ZIP.
- The probe processes each vendor response **in memory** and records only
  sha256, size, Last-Modified, column names, row counts and date bounds.
- The UI must show holding-period returns and aggregate figures only — never
  chart raw index levels.

## Visa prices: blocked and unblock path

**Blocked.** No license-compliant free daily Visa price series works without a
key. LON-28 must mark Visa buy-and-hold and strategy scoring as
`not run` with the Visa label above.

**Unblock (later):** register a free Tiingo Individual key with a **personal**
email; set `TIINGO_API_KEY` in `longaeva/.env` (gitignored); fetch `V` prices
in memory only; store and display only aggregate Derived Products that cannot
reconstruct the price path (Tiingo §1.6).

## Probe results

Candidate window (from `origins.csv`): **2022-01-27 → 2026-07-28** (18 candidates).

| Source | Status | First → last | Rows | Covers window | sha256 (12) |
| --- | --- | --- | --- | --- | --- |
| FRED `SP500` | ok | 2016-10-03 → 2026-10-01 | 2609 | yes | `8dad2c6099d0` |
| Shiller `ie_data` | ok | 1871-01 → 2026-09 | 1869 | yes | `044196dafe44` |
| Ken French daily | ok | 1926-07-01 → 2026-08-31 | 26317 | yes | `2f29e2254606` |

Shiller last month with a published dividend at probe time: **2026-06** (carry
forward for later months; flag estimated).

Visa dividends from retained Ex. 99.1 releases:

| Release | Amount | Record | Ex-date | Payable |
| --- | --- | --- | --- | --- |
| 2024-04-23 | $0.52 | 2024-05-17 | 2024-05-16 | 2024-06-03 |
| 2024-07-23 | $0.52 | 2024-08-09 | 2024-08-09 | 2024-09-03 |
| 2025-07-29 | $0.59 | 2025-08-12 | 2025-08-12 | 2025-09-02 |
| 2025-10-28 | $0.67 | 2025-11-12 | 2025-11-12 | 2025-12-01 |

## Reviewer checklist

| # | Check | Evidence |
| --- | --- | --- |
| 1 | Primary label says approximation and names FRED + Shiller | Labels table; `test_label_rule` |
| 2 | Ken French never called "S&P 500" | Secondary label; tests |
| 3 | No raw vendor files under `data/fixtures/benchmarks/` | Only `probe.json` |
| 4 | Terms URLs and retrieval date 2026-10-02 present | Manifest + this note |
| 5 | Visa buy-and-hold labeled not run | Visa label |
| 6 | Probe covers candidate window for B and C | `probe.json` |

## Originals and commands

```bash
cd backend
PYTHONPATH=. python -m longaeva_app.collect.benchmark_sources probe
```

Artifacts:

- Manifest: [`data/manifest/benchmarks.yaml`](../../data/manifest/benchmarks.yaml)
- Probe metadata: [`data/fixtures/benchmarks/probe.json`](../../data/fixtures/benchmarks/probe.json)

## Handoff

- **LON-28:** Build B and C series from the manifest. Mark Visa buy-and-hold and
  strategy scoring `not run` with the Visa label. Measure how far the B
  approximation drifts from Shiller's own total-return column when available.
- **LON-25 / LON-26:** Multiple range and value-versus-price need Visa prices.
  Use a clearly labeled analyst range / price assumption, or the 10-Q
  "Average Purchase Price per Share" as a coarse historical input — never as a
  silent daily price substitute.
- **LON-36 / LON-33:** Use the exact label strings; never chart raw index levels.
- **LON-37 / LON-38:** No FRED, Shiller or Ken French files in the ZIP.
- **LON-13:** Extend the `data/manifest/*.yaml` collector format; this file is
  the first manifest entry.
