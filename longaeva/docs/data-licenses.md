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

## Offline demo inputs (LON-37)

[data-license-inventory.csv](data-license-inventory.csv) lists every bundled data file,
its checksum, authorship, retention decision and provenance/terms reference. It includes
originals, parsed fixtures, calibration, cached model outputs, saved evaluations,
historical NPZ outputs and the unchanged prospective archive. Existing files are
referenced by the seed manifest rather than copied. Census originals needed for the
curated evidence closure are retained under `data/demo/originals/`.

Census-authored statistical releases are documented as public domain. SEC hosting
provides public access; issuer-authored filings and exhibits retain issuer authorship.
The older source manifests’ blanket “SEC EDGAR U.S. government work / public domain”
labels must not be read as a copyright determination for company-authored text. These
retained originals are cited research references under the existing gate decisions,
with attribution retained; this inventory does not claim an issuer redistribution
license. Non-redistributable benchmark vendor payloads and Visa IR/FactSet originals
remain excluded; only existing permitted derived results and cached research excerpts
are bundled. See the individual gate documents for source decisions and limitations.

The seed performs no network requests, provider calls or vendor fetching. It restores
content-addressed originals and run paths to the local artifact volume and inserts
curated database records. The exact replay proof covers the historical demo runs
and the original LON-32 registration; evaluation snapshots retain their original
config hashes and run references.
