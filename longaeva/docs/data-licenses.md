# Benchmark data handling

LON-28 implements the decisions and terms review dated October 2, 2026 in
[`gates/benchmarks.md`](gates/benchmarks.md) and
[`data/manifest/benchmarks.yaml`](../data/manifest/benchmarks.yaml).
This inventory covers the benchmark evaluation; other dataset inventories remain
in their respective gate documents for the final submission review.

| Input | Retained / exported | Method |
| --- | --- | --- |
| FRED SP500 | Source metadata/hash and holding-period aggregates only | Fetch CSV into memory; no raw prices or daily series on disk |
| Shiller ie_data.xls | Source metadata/hash and aggregate diagnostic only | Parse workbook in memory; no workbook, CPI, dividend series, or index levels on disk |
| Ken French daily factors | Source metadata/hash and holding-period aggregates only | Read ZIP/CSV in memory; no archive or factor/return series on disk |
| SEC Visa dividend declarations | Existing retained originals plus referenced declarations | Reuse approved SEC fixtures; report the ledger's partial coverage |

The benchmark evaluator bypasses the collector's artifact cache deliberately.
It does not persist vendor payloads in local files, the database, logs, the
frontend, or the submission ZIP. Exceptions expose bounded failure categories,
not response bodies. The committed report has no raw levels or daily returns.

Use the exact labels and primary footnote from the manifest. Show holding-period
returns and aggregate statistics only; never chart raw index levels. Tiingo,
Alpha Vantage, and alternative Visa daily sources are not fetched by this issue.
The Visa gate remains blocked and its performance rows stay `not_run`.
