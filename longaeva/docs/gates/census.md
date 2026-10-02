# Gate: Census MARTS vintage integrity

LON-5 · planning v1 · settled October 2, 2026.

## Question

Can archived advance-release PDFs (`advYYMM.pdf`) yield stable, nominal, seasonally
adjusted series with recoverable publication timestamps and vintage integrity?

## Answer

**Yes.** Two retained vintages (`adv2406`, `adv2506`) parse cleanly into long-format
observation CSVs. Printed release times convert unambiguously to UTC. A full release
calendar covering `adv1611`…`adv2606` (116 files) supplies a dated advance release for
every Visa origin in `origins.csv`. The revised workbook
`mrtssales92-present.xlsx` is **not** a vintage source: its June 2024 seasonally
adjusted total (666,040) differs from both the first print (704,324) and the
one-year-later advance reprint (692,922).

## Recommendation

**Required external family (DR-03), with constraints:**

- Use archived advance PDFs only; never the revised XLSX for historical cutoffs (DR-04).
- Prefer growth rates computed **within a single release** over level comparisons across
  vintages (levels revise).
- Attribute Census-driven parameter updates to the **US** component of Visa payments
  volume only (Census is US retail; Visa is global).
- Treat `possibly_replaced` calendar rows (HTTP Last-Modified more than 2 days after the
  printed release) with caution in LON-15; do not silently substitute them for earlier
  first prints when a cleaner neighbor exists.

## Vintages retained

| | adv2406 | adv2506 |
| --- | --- | --- |
| Reference month | 2024-06 | 2025-06 |
| Release number | CB24-110 | CB25-106 |
| Publication (UTC) | `2024-07-16T12:30:00Z` | `2025-07-17T12:30:00Z` |
| SA advance total ($ millions) | 704,324 | 720,106 |
| Headline | $704.3 billion | $720.1 billion |
| Fixture CSV | [`data/fixtures/census/adv2406.csv`](../../data/fixtures/census/adv2406.csv) | [`data/fixtures/census/adv2506.csv`](../../data/fixtures/census/adv2506.csv) |
| Original PDF | [`sources/adv2406.pdf`](../../data/fixtures/census/sources/adv2406.pdf) | [`sources/adv2506.pdf`](../../data/fixtures/census/sources/adv2506.pdf) |

Each CSV has 570 rows (Table 1 levels + Table 2 percent changes) with `publication_ts`,
`basis` (`sa`/`nsa`), `estimate_status` (`advance`/`preliminary`/`revised`/`year_ago`/
`ytd`/`three_month`), and US geography.

## Revision example (June 2024 SA total, $ millions)

| Vintage | Source | June 2024 SA total | Notes |
| --- | --- | --- | --- |
| First print | `adv2406` Table 1 advance column | **704,324** | Released 2024-07-16 |
| One year later | `adv2506` Table 1 year-ago column | **692,922** | Released 2025-07-17 |
| Current revised workbook | `mrtssales92-present_20261002.xlsx` sheet 2024, ADJUSTED | **666,040** | Last-Modified 2026-09-28; header cites Annual Integrated Economic Survey |

First-print year-over-year growth (Table 2): **+2.3%** (June 2024 vs June 2023 SA).
The later advance reprint revises the June 2024 **level** down by 11,402 ($ millions);
the revised XLSX revises it further. Using the XLSX at a 2024-07-23 Visa cutoff would
be look-ahead bias.

## Why the XLSX is not a vintage source

1. It is a **continuously revised** series, not an archived first print.
2. Its title block references the Annual Integrated Economic Survey / administrative
   records, not the Advance Monthly Retail Trade Survey vintage.
3. Cell values for past months change when Census rebases or revises; there is no
   per-release publication timestamp on each cell.
4. Snapshot retained only as negative evidence under
   [`data/fixtures/census/sources/`](../../data/fixtures/census/sources/) with SHA-256 in
   `manifest.json`.

## Category continuity

| Series | Stable across 2024→2025? | Notes |
| --- | --- | --- |
| Retail & food services total | yes | Primary mapping target |
| Retail total | yes | |
| Nonstore retailers (454) | yes | Present through `adv2606` |
| Food services & drinking places (722) | yes | |
| Department stores | **code change** | `4521` (2024) → `4522` (2025); same `series_key=naics_452_dept`, **level break** |
| Other general merchandise | **code change** | `4529`/`45291`/`45299` → `4523`/`452311`/`452319` |

LON-15 should key on `series_key` plus NAICS era, not raw NAICS alone.

## Timing against Visa origins

Release calendar: [`data/fixtures/census/release_calendar.csv`](../../data/fixtures/census/release_calendar.csv)
(116 rows, `adv1611`…`adv2606`). Integrity: **102 ok**, **14 possibly_replaced**,
**0 unparsed**, **0 fetch failures** after legacy-header support for `adv1611` and
Unicode-hyphen release numbers (`adv2403`).

Every one of the 39 inventory origins has `census_status=eligible`. Ages (candidate +
prospective, days from Census publication to Visa cutoff): min **7.3**, median **11.3**,
max **42.3**.

| Visa cutoff | Census release | Reference month | Age (days) | Note |
| --- | --- | --- | --- | --- |
| 2024-07-23 (LON-3 origin A) | `adv2406` | 2024-06 | 7.3 | Fresh June advance |
| 2025-07-29 | `adv2506` | 2025-06 | 12.3 | Fresh June advance |
| 2025-10-28 (LON-3 origin B) | `adv2508` | 2025-08 | 42.3 | **2025 shutdown**: `adv2509` released 2025-11-25 |
| 2019-01-30 | `adv1811` | 2018-11 | 47.3 | **2018–19 shutdown**: `adv1812` released 2019-02-14 (after cutoff) |
| 2026-07-28 (prospective) | `adv2606` | 2026-06 | 12.3 | |

`adv1812` is flagged `possibly_replaced` (Last-Modified ~2 months after its delayed
printed release). LON-15 should prefer neighboring first prints when hashing originals.

## Three-cell manual check

Re-checked against retained PDFs on October 2, 2026:

| # | File | Page | Cell | Parsed | Printed quote |
| --- | --- | --- | --- | --- | --- |
| 1 | `adv2406.pdf` | 1 | Headline SA total | 704.3 → 704,324 | `June 2024 $704.3 billion` |
| 2 | `adv2406.pdf` | 5 | Table 1 SA June advance total | 704,324 | `…722,019 704,324 704,483…` |
| 3 | `adv2506.pdf` | 5 | Table 1 SA June 2024 (year-ago) | 692,922 | `…721,789 692,922 692,774` |

## Originals and commands

```bash
cd backend
python -m longaeva_app.collect.census_sources fetch      # retained PDFs + XLSX snapshot
python -m longaeva_app.collect.census_sources calendar   # release_calendar.csv
python -m longaeva_app.collect.census_sources build      # adv2406.csv / adv2506.csv
python -m longaeva_app.collect.edgar_index build         # refresh origins Census columns
```

Manifest: [`data/fixtures/census/sources/manifest.json`](../../data/fixtures/census/sources/manifest.json).

## Handoff

- **LON-15:** extend `extract/census_marts.py` across the calendar window; skip or flag
  `possibly_replaced` files; query “latest vintage as of cutoff T” must return first-print
  values only.
- **LON-21:** map Census SA growth (within-release) → US domestic payments-volume prior;
  keep qualitative/category-mix as context until a ranged rule is reviewed; never feed
  XLSX cells into parameters.
- **LON-1 inventory:** Census timing filled; 0 origins excluded by missing Census release.
