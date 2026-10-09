# Gate: Second-wave disclosure families

Source review dated October 2, 2026.

## Question

Which airline, retailer and payment processor EDGAR earnings releases provide a
dated metric tied to a named Visa driver under the evidence-mapping criteria?

## Answer

**United Airlines (airline), Costco (retailer) and PayPal (pure processor).**
Each family’s eligible Item 2.02 Ex. 99.1 (and Ex. 99.2 when the metric lives
there) covers all 19 Visa candidate/prospective origins. Selection used, in
order: metric present at the most origins → next-quarter guidance covering the
Visa target → lower median age → stronger driver link. **Strict processor
scope:** card networks and bank issuers (Mastercard, Amex, JPMorgan) are
outside this disclosure sample.

## Recommendation

All three families are retained as **context**. Their metrics are not estimated
coefficients in the operating model.

| Family | Company | Visa driver | Stance | Note |
| --- | --- | --- | --- | --- |
| Airline | United | `cross_border_ex_intra_europe_growth_constant` | context | Atlantic / Pacific / Latin America tables. Ex. 99.2 investor-update guidance may become an analyst-ranged rule in mapping rules only where it covers the Visa target quarter. |
| Retailer | Costco | `payments_volume_growth_constant`, `processed_transactions_growth` | context | U.S. / Other International comps; traffic and ticket on Ex. 99.2. No next-quarter guidance. |
| Processor | PayPal | `payments_volume_growth_constant` | context | TPV (FXN) and payment transactions as a PV cross-check. Same-day at 5 origins. |

Company-specific bases (`fx_neutral`, `ex_gas_fx`, `ex_fuel`) must **not** be
relabeled as Visa `constant_dollar` ([definitions.md](../definitions.md) §5).

## Selection criteria (applied)

1. Metric present in the release eligible at the most of the 19 origins.
2. Next-quarter guidance covers Visa’s target quarter at more origins.
3. Lower median age at the cutoff.
4. Stronger link to a named Visa driver in `FIELDS`.

## Candidate screen

Timing table: [`data/fixtures/second_wave/timing.csv`](../../data/fixtures/second_wave/timing.csv)
(14 × 19 = 266 rows). Snapshot:
[`data/fixtures/second_wave/filing_index.json`](../../data/fixtures/second_wave/filing_index.json).
Ages are days from the company’s EDGAR acceptance to the Visa cutoff.

| ID | Family | Status | Median age (d) | Same-day | Metric / limitation |
| --- | --- | --- | --- | --- | --- |
| **united** | airline | **selected** | 7.0 | 0 | Atlantic/Pacific/Latin America passenger revenue, PRASM, capacity; Ex. 99.2 guidance |
| delta | airline | finalist_rejected | 13.4 | 0 | Metric present; older than United; Transatlantic mostly prose |
| american | airline | rejected | 5.4 | 2 | Next release ≤7 days after Visa at 3 origins |
| **costco** | retailer | **selected** | 49.0 | 0 | Comps by U.S./Canada/Other International; traffic/ticket on Ex. 99.2; no NQ guidance |
| walmart | retailer | finalist_rejected | 68.2 | 0 | Transactions / ticket / comps + NQ guidance; older than Costco |
| target | retailer | rejected | 69.4 | 0 | Traffic in prose only; no ticket table |
| **paypal** | processor | **selected** | 83.0 | 5 | TPV + payment transactions; FXN growth |
| block | processor | finalist_rejected | 81.8 | 0 | Square GPV present; never same-day; older than PayPal’s best cases |
| fiserv | processor | rejected | 77.1 | 4 | No payment-volume / GPV in Ex. 99.1 |
| global_payments | processor | rejected | 84.4 | 0 | No payment-volume metric |
| shift4 | processor | rejected | 80.4 | 1 | One 182-day age gap |
| mastercard | out_of_family | stretch_s6 | 89.3 | 4 | Card network; next release ≤7d after Visa at 13 origins |
| amex | out_of_family | stretch_s6 | 5.2 | 0 | Card network / issuer |
| jpmorgan | out_of_family | stretch_s6 | 13.2 | 0 | Bank issuer; fresher but covers the quarter Visa just reported |

Finalist scan (metric/guidance probe):
[`data/fixtures/second_wave/release_scan.csv`](../../data/fixtures/second_wave/release_scan.csv)
— 114 rows, 0 errors. Selected companies have metric hits at **19/19** origins.
United and PayPal show guidance language at every origin; Costco shows none.

## Retained cutoffs

Uses the same Visa origins as the Booking evidence and bundled starting states.

| | Origin A | Origin B |
| --- | --- | --- |
| Visa cutoff (UTC) | `2024-07-23T20:05:38Z` | `2025-10-28T20:06:03Z` |
| United accession | `0000100517-24-000117` (2024-07-17) | `0000100517-25-000190` (2025-10-15) |
| United age | 6.0 days | 13.0 days |
| Costco accession | `0000909832-24-000026` (2024-05-30) | `0000909832-25-000093` (2025-09-25) |
| Costco age | 54.0 days | 33.0 days |
| PayPal accession | `0001193125-24-123690` (2024-04-30) | `0001633917-25-000194` (2025-10-28) |
| PayPal age | 84.4 days | 0.4 days (same Eastern day) |

Fixtures:

- [`united_2024-07-17.json`](../../data/fixtures/observations/united_2024-07-17.json),
  [`united_2025-10-15.json`](../../data/fixtures/observations/united_2025-10-15.json)
- [`costco_2024-05-30.json`](../../data/fixtures/observations/costco_2024-05-30.json),
  [`costco_2025-09-25.json`](../../data/fixtures/observations/costco_2025-09-25.json)
- [`paypal_2024-04-30.json`](../../data/fixtures/observations/paypal_2024-04-30.json),
  [`paypal_2025-10-28.json`](../../data/fixtures/observations/paypal_2025-10-28.json)

Originals (gzipped HTML) under
[`data/fixtures/second_wave/sources/`](../../data/fixtures/second_wave/sources/)
with hash manifest
[`sources/manifest.json`](../../data/fixtures/second_wave/sources/manifest.json).

## Observations (summary)

### United

| Release | Measured | Qualitative / guidance presence |
| --- | --- | --- |
| 2024-07-17 | Capacity +8.3%; Atlantic passenger revenue +2.9% | Premium-mix commentary; Ex. 99.2 investor-update guidance presence |
| 2025-10-15 | Capacity +7.2%; Atlantic passenger revenue +1.3% | Atlantic expansion commentary; Ex. 99.2 guidance presence |

Numeric Ex. 99.2 guidance ranges are deferred to LLM extraction; fixtures record
presence as qualitative rather than inventing numeric values.

### Costco

| Release | Measured |
| --- | --- |
| 2024-05-30 | U.S. comps +6.2%; Other International +7.7%; traffic +0.5%; ticket +20.7%; e-commerce +20.7% |
| 2025-09-25 | U.S. comps +5.1%; Other International +8.6%; traffic +13.6%; ticket +2.6%; e-commerce +13.6% |

### PayPal

| Release | Measured | Qualitative |
| --- | --- | --- |
| 2024-04-30 | TPV +14% (also 14% FXN); payment transactions +11% | EPS vs prior guidance reference |
| 2025-10-28 | TPV +8% (7% FXN); payment transactions −5% | Raises full-year guidance |

## Reviewer checklist

Re-checked against retained EDGAR HTML on October 2, 2026:

| # | Release | Field | Quote | URL |
| --- | --- | --- | --- | --- |
| 1 | United 2024-07-17 | capacity +8.3% | `Capacity up` → `8.3%` | [ual_06302024erex991.htm](https://www.sec.gov/Archives/edgar/data/100517/000010051724000117/ual_06302024erex991.htm) |
| 2 | United 2025-10-15 | Atlantic revenue +1.3% | `3,280` → `1.3%` | [ual_09302025erex991.htm](https://www.sec.gov/Archives/edgar/data/100517/000010051725000190/ual_09302025erex991.htm) |
| 3 | Costco 2024-05-30 | U.S. comps +6.2% | `U.S.` → `6.2%` | [costex9918-k51224.htm](https://www.sec.gov/Archives/edgar/data/909832/000090983224000026/costex9918-k51224.htm) |
| 4 | Costco 2025-09-25 | traffic +13.6% | `Comparable Traffic` → `+13.6%` | [costex9928-k92525.htm](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9928-k92525.htm) |
| 5 | PayPal 2024-04-30 | TPV +14% FXN | `14% to $403.9` → `14% FXN` | [d831310dex991.htm](https://www.sec.gov/Archives/edgar/data/1633917/000119312524123690/d831310dex991.htm) |
| 6 | PayPal 2025-10-28 | TPV +8% / 7% FXN | `increased 8% to $458.1 billion` → `7% FXN` | [pypl3q-25earningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm) |

Index-page `Accepted` timestamps match the snapshot for every retained accession
(see `sources/manifest.json`).

## Originals and commands

```bash
cd backend
python -m longaeva_app.collect.second_wave snapshot   # filing_index.json (14 candidates)
python -m longaeva_app.collect.second_wave timing     # timing.csv (offline)
python -m longaeva_app.collect.second_wave scan       # release_scan.csv (finalists)
python -m longaeva_app.collect.second_wave fetch      # retained .htm.gz + manifest
python -m longaeva_app.collect.second_wave locate data/fixtures/observations/united_YYYY-MM-DD.json
```

Manifest: [`data/manifest/second_wave.yaml`](../../data/manifest/second_wave.yaml).

## Integration

- Ingest retained Ex. 99.1 / 99.2 originals from the sources manifest.
- LLM extraction over retained passages; extract numeric Ex. 99.2
  guidance ranges; statement types follow the extraction schema.
- Second-wave passages enter the extraction evaluation set.
- Mapping rules start as context; promote airline guidance only with
  a documented rationale where `guidance_covers_target` would be true.
- **Forecast evaluation:** ablation (a) rebuilds without second-wave updates.
- **Origin eligibility:** unchanged — second-wave families are
  context-first and do not add columns to `origins.csv`.
