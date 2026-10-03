# Visa release and 10-Q structured table parser

LON-14. Offline, offset-preserving parser for Visa 8-K Ex. 99.1 earnings releases
(FY2017Q1–FY2026Q3) and the prior 10-Q/10-K payments-volume tables.

## Commands

```bash
# One-time EDGAR fetch of originals (needs SEC_USER_AGENT). Reuses LON-3 files.
python -m longaeva_app.collect.visa_filings fetch

# Offline parse of every origin. --write regenerates the committed CSVs.
python -m longaeva_app.cli parse-visa --write
```

Outputs (under `data/fixtures/visa_releases/`):

- `sources/` — deterministic `.htm.gz` originals plus `manifest.json` (SHA-256).
  Filings already in `data/fixtures/states/sources/` are referenced, not copied.
- `parse_status.csv` — one row per origin quarter.
- `observations.csv` — flattened measured/derived observations with raw spans.

## Format eras

| Era | Periods | How we parse |
| --- | --- | --- |
| `table_2017` | FY2017Q1–Q4 | HTML tables; older labels (`Net operating revenues`, plural categories). No Key Business Drivers table — growth from prose when present. |
| `image_text_layer` | FY2018Q1–FY2021Q2 | Page images with a hidden 1-pt / white text layer and no `<table>` markup. Regex over the text layer. Best effort. |
| `table_modern` | FY2021Q3–FY2026Q3 | Standard HTML tables. Q4 releases add a twelve-month column group; the parser takes the three-month GAAP column. |

## Primary vs cross-check

Locations match the LON-3 fixtures:

| Fields | Primary location |
| --- | --- |
| Categories, incentives, net revenue, opex, non-operating, KBD growth | Income-statement summary / KBD table |
| Tax rate, processed-transaction count, prior-quarter PV growth | Release prose |
| Diluted class A shares | Statement of operations |
| 10-Q volumes | `Total nominal payments volume` table (Visa Inc. column; geography-tagged US/International also emitted) |

Secondary locations (summary tax-rate row, recon vs summary Non-GAAP opex, prose vs table growth) are recorded as `location=cross_check`. Prior-year 10-Q columns have `vintage_role=comparative` and are never a first print (DR-04).

If a release lists no operating-expense adjustments, `operating_expenses_ex_special_items` is recorded as `derived` (equal to GAAP), never as measured.

## Identities (parse time)

Tolerance is half a reported unit per rounded term (0.5 for `usd_millions`, 1.5 for `usd_billions` on a three-term sum):

- categories − incentives = net revenue
- net revenue − GAAP opex = operating profit
- GAAP opex + signed bridge lines = Non-GAAP opex
- summary Non-GAAP opex = recon Non-GAAP opex
- 10-Q: US + International = Visa Inc.; payments + cash = total (when both present)

## Status

`parsed` / `partial` / `failed` per quarter in `parse_status.csv`. Target: all 21
`table_modern` releases `parsed`. FY2017 and the image era are best effort with a
reason on every non-`parsed` row.

## Known gaps

- Operational Performance Data **volume levels** in FY2017–FY2021Q2 releases are not
  parsed (follow-up for LON-20 / LON-16). Growth rates come from KBD or prose.
- Image-era text layers are lossy: some KBD tables never appear in the hidden run.
- Restated comparative 10-Q columns are flagged `comparative` and ignored as first prints.

## Handoff

- **LON-20:** `observations.csv` is the golden flattened series for pandas alignment.
- **LON-16:** consume `parse_status.csv` missing-field reasons; do not re-extract fields already `parsed`.
- **LON-37:** join parser `source_id` (`accession/document`) and content SHA-256 to collector `source` rows. This CLI does not write the database.
- **LON-24:** originals in `visa_releases/sources/` ship in the export set; `SEC_USER_AGENT` does not.
