# Gate: Booking Holdings family

Source review dated October 2, 2026.

## Question

Does Booking provide usable, dated observations whose timing can inform a Visa
cross-border prior?

## Answer

**Yes, with constraints.** Two retained Ex. 99.1 releases (2024-05-02 and
2025-10-28) yield measured growth facts, a qualitative passage, and — on the
later release — an EDGAR-dated guidance table. Every Visa origin in
`origins.csv` has a Booking earnings 8-K accepted ≤ cutoff. Staleness is
**not** uniformly 10–12 weeks: since April 2025 four candidate origins are
same-day (Booking accepted 71–233 seconds before Visa). Ex. 99.1 guidance
tables begin with the 2025-07-29 release; earlier outlooks lived in prepared
remarks on Booking's IR site (not EDGAR) and are out of scope here.

## Recommendation

**Required external family for the cross-border prior, with constraints:**

- **Measured** room-nights / constant-currency gross-bookings growth at every
  origin is a candidate for an **estimated, lagged** mapping rule in mapping rules
  (Booking's reported quarter is typically the calendar quarter before Visa's
  reported quarter, except on same-day origins).
- **Guidance** counts only at the three origins where
  `booking_guidance_covers_target=true` (FY2025Q3, FY2025Q4, FY2026Q2), as an
  **analyst-ranged** rule. Elsewhere guidance is absent or covers a different
  quarter and stays context.
- **Qualitative** CEO / quarter-to-date commentary remains **context only**; it does not become a precise parameter change.
- Evaluation must also report a **same-day fallback variant**
  that substitutes `booking_fallback_accession` whenever `booking_same_day=true`,
  so results do not silently depend on a few-minute EDGAR margin.
- Geography: Booking is global (domestic + cross-border + intra-Europe). Attribute
  Booking-driven updates to Visa's **cross-border ex-intra-Europe** factor only
  after an explicit, reviewed rule; do not treat room nights as a drop-in for
  Visa payments volume.

## Cutoffs retained

| | Origin A | Origin B |
| --- | --- | --- |
| Visa cutoff (UTC) | `2024-07-23T20:05:38Z` | `2025-10-28T20:06:03Z` |
| Visa fiscal quarter | FY2024Q3 | FY2025Q4 |
| Visa target | FY2024Q4 | FY2026Q1 |
| Booking accession | `0001075531-24-000026` | `0001075531-25-000050` |
| Booking Ex. 99.1 | `ex99133124.htm` | `q3-25bkngearningsrelease.htm` |
| Booking acceptance (UTC) | `2024-05-02T20:02:05Z` | `2025-10-28T20:02:19Z` |
| Age at cutoff | **11.71 weeks** (82.0 days) | **224 seconds** (same Eastern day) |
| Guidance covers target? | no (no Ex. 99.1 table) | **yes** (Q4 2025 → Visa FY2026Q1) |
| Fixture | [`booking_2024-05-02.json`](../../data/fixtures/observations/booking_2024-05-02.json) | [`booking_2025-10-28.json`](../../data/fixtures/observations/booking_2025-10-28.json) |

The issue text's second example (`2026-08-04`) is retained only as a
**post-cutoff negative test** at the prospective origin (see below). It is not
an input fixture.

## Observations

### Origin A — Booking Q1 2024 (`2024-05-02`)

| ID | Type | Metric | Value | Period | Basis |
| --- | --- | --- | --- | --- | --- |
| `bkng_2024q1_room_nights_yoy` | measured | room nights YoY | 9% | 2024-01-01…2024-03-31 | units |
| `bkng_2024q1_gross_bookings_yoy` | measured | gross travel bookings YoY | 10% | 2024-01-01…2024-03-31 | as_reported |
| `bkng_2024q1_ceo_qualitative` | qualitative | travel demand | — | 2024-01-01…2024-03-31 | as_reported |

No Ex. 99.1 outlook table. The release states prepared remarks will be posted to
the Booking IR website after the call.

### Origin B — Booking Q3 2025 (`2025-10-28`)

| ID | Type | Metric | Value | Period | Basis |
| --- | --- | --- | --- | --- | --- |
| `bkng_2025q3_room_nights_yoy` | measured | room nights YoY | 8% | 2025-07-01…2025-09-30 | units |
| `bkng_2025q3_gross_bookings_cc_yoy` | measured | gross bookings YoY | 10% | 2025-07-01…2025-09-30 | constant_currency |
| `bkng_2025q4_room_nights_guidance` | guidance | room nights YoY | 4%–6% | 2025-10-01…2025-12-31 | units |
| `bkng_2025q4_gross_bookings_cc_guidance` | guidance | gross bookings YoY | 6%–8% | 2025-10-01…2025-12-31 | constant_currency |
| `bkng_2025q4_qtd_demand_qualitative` | qualitative | travel demand QTD | — | 2025-10-01…2025-12-31 | as_reported |

As-reported gross bookings growth was +14%; the fixture stores the
constant-currency figure (+10%) because it is closer to Visa's constant-dollar
driver language (still not identical — see currency notes).

## Timing at every origin

Release calendar: [`data/fixtures/booking/release_calendar.csv`](../../data/fixtures/booking/release_calendar.csv)
(20 rows). Full per-origin table: [`docs/origins-inventory.md`](../origins-inventory.md)
§ Booking.

| Regime | Origins | Age | Guidance covers target |
| --- | --- | --- | --- |
| Lagged (~8.7–13.3 weeks) | 15 of 19 candidate+prospective | prior Booking quarter | never (no table, or table covers a different quarter) |
| Same-day (71–233 s) | FY2025Q2, FY2025Q3, FY2025Q4, FY2026Q2 | Booking filed minutes before Visa | true at FY2025Q3, FY2025Q4, FY2026Q2 |

Same-day fallback accessions:

| Origin | Booking at cutoff | Fallback |
| --- | --- | --- |
| FY2025Q2 | `0001075531-25-000021` | `0001075531-25-000009` |
| FY2025Q3 | `0001075531-25-000035` | `0001075531-25-000021` |
| FY2025Q4 | `0001075531-25-000050` | `0001075531-25-000035` |
| FY2026Q2 | `0001075531-26-000024` | `0001075531-26-000008` |

## Guidance availability

| Booking release filed | Reported quarter | Guidance table? | Guidance quarter |
| --- | --- | --- | --- |
| 2021-11-03 … 2025-04-29 | 2021Q3 … 2025Q1 | **false** | — |
| 2025-07-29 | 2025Q2 | true | 2025Q3 |
| 2025-10-28 | 2025Q3 | true | 2025Q4 |
| 2026-02-18 | 2025Q4 | true | 2026Q1 |
| 2026-04-28 | 2026Q1 | true | 2026Q2 |
| 2026-08-04 | 2026Q2 | true | 2026Q3 |

Visa target → calendar quarter mapping (FY ends 30 Sep): FY{Y}Q1→{Y−1}Q4,
FY{Y}Q2→{Y}Q1, FY{Y}Q3→{Y}Q2, FY{Y}Q4→{Y}Q3.

## Geography and currency notes

1. **Global mix.** Booking room nights and gross bookings include domestic travel
   and intra-Europe cross-border activity. Visa's international-revenue driver is
   **cross-border volume excluding transactions within Europe**
   ([definitions.md](../definitions.md) §3). A Booking → Visa rule must state how
   it isolates or discounts the non-overlapping component.
2. **Booked ≠ stayed ≠ card spend.** Room nights are counted when booked (net of
   cancellations), not when the stay occurs, and are not Visa payments volume.
3. **Constant currency ≠ Visa constant-dollar.** Booking converts current-period
   results at prior-year monthly average rates by predominant transactional
   currency. Visa's constant-dollar growth "excludes the impact of foreign
   currency fluctuations against the U.S. dollar" (definitions §5). Labels in
   fixtures use `constant_currency` for Booking and must not be silently
   relabeled as Visa `constant_dollar`.

## After-cutoff example (prospective origin)

| | |
| --- | --- |
| Prospective Visa cutoff | `2026-07-28T20:05:26Z` |
| Eligible Booking release | `0001075531-26-000024` (2026-04-28), **13.00 weeks** old |
| Ineligible Booking release | `0001075531-26-000036` (2026-08-04), accepted ~7 days **after** cutoff |
| Why it matters | The 2026-08-04 Ex. 99.1 has Q3 2026 guidance covering Visa's target FY2026Q4, but using it would be look-ahead bias |

Retained original: [`sources/0001075531-26-000036/`](../../data/fixtures/booking/sources/0001075531-26-000036/)
(role `post_cutoff_check`). `origins.csv` never selects it.

## Reviewer checklist

Re-checked against retained EDGAR HTML on October 2, 2026:

| # | Release | Field | Quote | URL |
| --- | --- | --- | --- | --- |
| 1 | 2024-05-02 | room nights +9% | `Room nights booked increased` → `9%` | [ex99133124.htm](https://www.sec.gov/Archives/edgar/data/1075531/000107553124000026/ex99133124.htm) |
| 2 | 2024-05-02 | gross bookings +10% | `were $43.5 billion, an increase of` → `10%` | same |
| 3 | 2024-05-02 | CEO qualitative | `ahead of our prior expectations` | same |
| 4 | 2025-10-28 | room nights +8% | `Room nights grew` → `8%` | [q3-25bkngearningsrelease.htm](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000050/q3-25bkngearningsrelease.htm) |
| 5 | 2025-10-28 | Q4 room nights guidance | `Room Nights Growth` → `4% - 6%` | same |
| 6 | 2025-10-28 | acceptance vs Visa | Booking `2025-10-28T20:02:19Z` ≤ Visa `2025-10-28T20:06:03Z` (224 s) | EDGAR index pages |

Index-page `Accepted` timestamps match the origin inventory snapshot for all three retained
accessions (see `manifest.json`).

## Originals and commands

```bash
cd backend
python -m longaeva_app.collect.booking_sources fetch      # 3 Ex. 99.1 .htm.gz + manifest
python -m longaeva_app.collect.booking_sources calendar   # release_calendar.csv (20 rows)
python -m longaeva_app.collect.booking_sources locate data/fixtures/observations/booking_YYYY-MM-DD.json
python -m longaeva_app.collect.edgar_index build          # refresh Booking columns in origins.csv
```

Manifest: [`data/fixtures/booking/sources/manifest.json`](../../data/fixtures/booking/sources/manifest.json).

## Integration

- Map lagged measured Booking growth → travel / cross-border
  ex-intra-Europe prior (estimated if ≥ 12 aligned quarters support a
  coefficient; otherwise analyst-ranged). Guidance → ranged rule only where
  `booking_guidance_covers_target=true`. Qualitative stays context.
- **Forecast evaluation:** report the same-day fallback ablation alongside the
  primary run; do not claim Booking is always 10–12 weeks stale.
- Prospective origin uses the 2026-04-28 Booking release; do not
  wait for or include 2026-08-04.
- **Source collection:** collector and LLM extraction should ingest the retained
  originals and fixture observation shapes; statement types follow the extraction schema.
- **Origin inventory:** Booking timing/guidance columns filled; 0 origins
  excluded by missing Booking release.
