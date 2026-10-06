# Census MARTS archived releases and vintage series

LON-15. Parsed vintage table for every archived advance retail release from
`adv1611` through `adv2606`, with revision links and an as-of query that never
returns a print published after the cutoff.

## Commands

```bash
cd backend

# Download originals into gitignored var/cache/census/. Skip files whose
# SHA-256 already matches data/manifest/census.yaml. A mismatch is a failure
# and the new bytes are not written.
python -m longaeva_app.collect.census_sources fetch-archive

# Copy five seeded releases into data/fixtures/census/sources/ (seed 15).
python -m longaeva_app.collect.census_sources sample

# Parse the calendar. Uses a committed fixture PDF when one exists, otherwise
# the cache. Writes the two files below.
python -m longaeva_app.collect.census_sources vintages
```

`SEC_USER_AGENT` in `longaeva/.env` is sent on Census requests. The client
waits at least one second between requests and does not retry HTTP 403.

## Outputs

| File | What it is |
| --- | --- |
| [`data/fixtures/census/vintages.csv.gz`](../data/fixtures/census/vintages.csv.gz) | Selected series, one row per print. 20,734 rows. |
| [`data/fixtures/census/parse_status.csv`](../data/fixtures/census/parse_status.csv) | One row per release: parse status, row counts, error, integrity flag, hash check, PDF dates, NAICS era. |

The other 109 originals stay in `var/cache/census/` (gitignored) and are
checked against the SHA-256 values in
[`data/manifest/census.yaml`](../data/manifest/census.yaml).

## Parse result

**115 of 116 releases parsed (99.1%).** Every cached PDF also matched its
headline seasonally adjusted total and its Table 2 month-over-month change
within rounding.

| Release | Why it failed |
| --- | --- |
| `adv2301` | The live PDF no longer matches the hash pinned from the October 2, 2026 calendar (`864fda9f…` expected, `755bba95…` downloaded). The replaced bytes were not parsed. |

Department-store and general-merchandise codes switch from `4521` to `4522`
starting with `adv2504` (reference month 2025-04). Parsed releases: 100 in era
`4521`, 15 in era `4522`. `naics_era` is stored on every row. A revision link
is left empty when the NAICS code for that series changes, so department-store
levels are not joined across the break. Stable series such as the retail total
still chain.

## Sample originals

Seven PDFs are committed. `adv2406` and `adv2506` are the LON-5 gate files.
The other five were chosen with seed 15 from the remaining 114 releases, then
sorted:

`adv1612`, `adv1703`, `adv1901`, `adv2205`, `adv2410`.

`sources/manifest.json` records them as `advance_pdf` entries. The revised
workbook is unchanged and is still negative evidence only: its June 2024
seasonally adjusted total is 666,040, not a vintage.

## What the table keeps

Series: retail and food services total, retail total, totals excluding motor
vehicles and/or gasoline, GAFO, and NAICS 441, 447, 452, 454, and 722,
including department stores (`naics_452_dept`).

Each series keeps seasonally adjusted and not-adjusted levels for every print
(advance, preliminary, revised, year-ago) and the Table 2 percent changes.
Year-to-date columns are not stored.

A cell is `(series_key, measure, basis, period, base period)`.
`supersedes_release_id` points at the previous release that printed the same
cell.

## As-of query

`as_of(cutoff)` in `extract/census_vintages.py` uses only releases published at
or before the cutoff and returns the newest print of each cell.
`estimate_status`, `integrity_flag`, and `naics_era` stay on the row. A cutoff
given as a date alone is the start of that UTC day.

At `2024-07-23`, the June 2024 seasonally adjusted total is **704,324** from
`adv2406` (the first print). It is not 692,922. That later figure is the
`adv2506` revision, published `2025-07-17`, and it appears only at cutoffs on
or after that publication time.

`first_print` returns the advance print. `revision_history` returns every
print of one cell, oldest first.

## `possibly_replaced`

Fourteen calendar rows are flagged because HTTP Last-Modified was more than
two days after the printed release. The vintage build does not change those
flags. PDF creation and modification dates are extra evidence only
(`pdf_creation_vs_release`, `pdf_mod_vs_release`). Eight of the fourteen have
a PDF date more than two days after publication; the other six do not, so
Last-Modified alone is not proof the bytes changed.

`as_of(..., allow_possibly_replaced=False)` skips those releases and falls
back to the newest release flagged `ok`. For the December 2018 total, the
only print available by `2019-02-20` is `adv1812`, so the strict query returns
nothing. The November 2018 total falls back to an `ok` release.

## Quarterly mapping and evaluation (LON-31)

`extract/census_quarters.py` selects the latest print available by each cutoff
for SA retail-and-food-services `yoy_3m_pct` ending March, June, September or
December. There is one observation per Visa quarter, with no averaging of
overlapping monthly windows. Both the mapping-rule fit and evaluation use this
selector. Releases must be parsed, hash verified and flagged `ok`; blank,
flagged and nonfinite values are excluded. The revised workbook is never read.

The evaluation loader uses the newest eligible complete quarter as the signal,
retaining its period and publication date. When a quarter's release is suspect,
an older eligible quarter can remain the newest signal; this is visible in the
saved snapshot. Historical fits count unique quarters and use only Visa and
Census prints published by the origin cutoff, with pandemic quarters excluded.

The rule is `census_retail_yoy_to_payments_volume_growth` v2. The v1 registry
record and earlier parameter sets remain available. The parser checklist is
recorded as an acceptance decision for newly loaded quarterly observations;
existing rejection or correction decisions are preserved. Review occurred
retrospectively; this does not claim the research decisions were made at the
historical cutoff.
