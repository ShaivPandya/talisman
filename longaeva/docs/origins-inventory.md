# Visa eligible-origin and vintage inventory

Generated for LON-1 · snapshot retrieved `2026-10-01T17:42:45Z` · cutoff convention: EDGAR acceptance timestamp of Visa's quarter-q earnings 8-K (data plan §2.3).

## Method

- Sources: SEC EDGAR `submissions` JSON for Visa (CIK 1403161) and Booking Holdings (CIK 1075531), including older `submissions-00N.json` pages when present.
- A contact User-Agent was declared for all live requests (value not recorded here). Rate ≤ 2 requests/s.
- Documents are eligible for an origin only when `acceptance_ts ≤ cutoff_ts` (timezone-aware UTC comparison).
- Fiscal quarters: Visa FY ends 30 September. Release dates map to the latest quarter-end before the release; cross-checked against `period_of_report` when present.
- Census MARTS timing uses the LON-5 release calendar (`data/fixtures/census/release_calendar.csv`): newest advance PDF with printed `publication_ts` ≤ cutoff.

## Counts (exact; not rounded up)

- Inventory rows (FY2017Q1–FY2026Q3): **39**
- Calibration quarters (FY2017–FY2023) with timestamps: **28**
- FY2022–FY2026 window rows (incl. prospective): **19**
- Candidate origins (timestamp checks pass; realized target quarter): **18**
- Prospective origins: **1**
  - `2026-07-28` release → target FY2026Q4 (accession `0001403161-26-000103`)
- Excluded rows: **0**
- Census-eligible origins (advance release ≤ cutoff): **39**

These counts reflect EDGAR timestamp, prior-10-Q availability and Census release timing. Definition stability (LON-2) and starting-state reconstruction (LON-3) are settled separately and did not lower the count.

## Exclusion reasons

- None at the timestamp/prior-10-Q layer.

## Same-quarter 10-Q / 10-K lag vs cutoff

| Origin | Same-quarter form | Hours after cutoff | Eligible at cutoff |
| --- | --- | --- | --- |
| FY2022Q1 | 10-Q | 23.97 | false |
| FY2022Q2 | 10-Q | 48.03 | false |
| FY2022Q3 | 10-Q | 47.97 | false |
| FY2022Q4 | 10-K | 529.02 | false |
| FY2023Q1 | 10-Q | 24.00 | false |
| FY2023Q2 | 10-Q | 25.51 | false |
| FY2023Q3 | 10-Q | 2.27 | false |
| FY2023Q4 | 10-K | 529.03 | false |
| FY2024Q1 | 10-Q | 2.20 | false |
| FY2024Q2 | 10-Q | 2.02 | false |
| FY2024Q3 | 10-Q | 2.12 | false |
| FY2024Q4 | 10-K | 362.13 | false |
| FY2025Q1 | 10-Q | 2.02 | false |
| FY2025Q2 | 10-Q | 2.03 | false |
| FY2025Q3 | 10-Q | 2.00 | false |
| FY2025Q4 | 10-K | 217.06 | false |
| FY2026Q1 | 10-Q | 2.04 | false |
| FY2026Q2 | 10-Q | 2.09 | false |
| FY2026Q3 | 10-Q | 2.05 | false |

Under the §2.3 cutoff convention the same-quarter 10-Q is typically accepted hours after the earnings 8-K and is therefore **not** eligible as an input for that origin. LON-3 should use the prior-quarter 10-Q for nominal payments-volume levels.

## Booking release age at Visa cutoffs

| Origin | Booking accession | Age (days) | Age (weeks) | Same-day | Margin (s) | Guidance covers target | Fallback | Eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FY2022Q1 | `0001075531-21-000051` | 85.0 | 12.1491 | false |  | false | `` | true |
| FY2022Q2 | `0001075531-22-000006` | 62.0 | 8.8514 | false |  | false | `` | true |
| FY2022Q3 | `0001075531-22-000020` | 83.0 | 11.8572 | false |  | false | `` | true |
| FY2022Q4 | `0001075531-22-000031` | 83.0 | 11.8571 | false |  | false | `` | true |
| FY2023Q1 | `0001075531-22-000042` | 85.0 | 12.1489 | false |  | false | `` | true |
| FY2023Q2 | `0001075531-23-000012` | 61.0 | 8.7086 | false |  | false | `` | true |
| FY2023Q3 | `0001075531-23-000029` | 82.0 | 11.7146 | false |  | false | `` | true |
| FY2023Q4 | `0001075531-23-000045` | 82.0 | 11.7145 | false |  | false | `` | true |
| FY2024Q1 | `0001075531-23-000060` | 84.0 | 12.0062 | false |  | false | `` | true |
| FY2024Q2 | `0001075531-24-000011` | 61.0 | 8.7087 | false |  | false | `` | true |
| FY2024Q3 | `0001075531-24-000026` | 82.0 | 11.7146 | false |  | false | `` | true |
| FY2024Q4 | `0001075531-24-000039` | 89.0 | 12.7144 | false |  | false | `` | true |
| FY2025Q1 | `0001075531-24-000047` | 92.0 | 13.1490 | false |  | false | `` | true |
| FY2025Q2 | `0001075531-25-000021` | 0.0 | 0.0001 | true | 71 | false | `0001075531-25-000009` | true |
| FY2025Q3 | `0001075531-25-000035` | 0.0 | 0.0004 | true | 233 | true | `0001075531-25-000021` | true |
| FY2025Q4 | `0001075531-25-000050` | 0.0 | 0.0004 | true | 224 | true | `0001075531-25-000035` | true |
| FY2026Q1 | `0001075531-25-000050` | 93.0 | 13.2920 | false |  | false | `` | true |
| FY2026Q2 | `0001075531-26-000024` | 0.0 | 0.0002 | true | 137 | true | `0001075531-26-000008` | true |
| FY2026Q3 | `0001075531-26-000024` | 91.0 | 13.0002 | false |  | false | `` | true |

Age is from Booking's EDGAR acceptance to the Visa cutoff. `same_day` is true when both accepted timestamps fall on the same US/Eastern calendar date. Since April 2025 four candidate origins are same-day (Booking accepted 71–233 seconds earlier); the evaluation should also report a variant that falls back to `booking_fallback_accession`. `guidance_covers_target` is true only when the Ex. 99.1 outlook table's next quarter equals Visa's target quarter mapped to a calendar quarter (see `docs/gates/booking.md`). Ex. 99.1 guidance tables begin with the 2025-07-29 release.

## Census release age at Visa cutoffs

| Origin | Census release | Reference month | Age (days) | Status |
| --- | --- | --- | --- | --- |
| FY2022Q1 | `adv2112` | 2021-12 | 13.3 | eligible |
| FY2022Q2 | `adv2203` | 2022-03 | 12.3 | eligible |
| FY2022Q3 | `adv2206` | 2022-06 | 11.3 | eligible |
| FY2022Q4 | `adv2209` | 2022-09 | 11.3 | eligible |
| FY2023Q1 | `adv2212` | 2022-12 | 8.3 | eligible |
| FY2023Q2 | `adv2303` | 2023-03 | 11.3 | eligible |
| FY2023Q3 | `adv2306` | 2023-06 | 7.3 | eligible |
| FY2023Q4 | `adv2309` | 2023-09 | 7.3 | eligible |
| FY2024Q1 | `adv2312` | 2023-12 | 8.3 | eligible |
| FY2024Q2 | `adv2403` | 2024-03 | 8.3 | eligible |
| FY2024Q3 | `adv2406` | 2024-06 | 7.3 | eligible |
| FY2024Q4 | `adv2409` | 2024-09 | 12.3 | eligible |
| FY2025Q1 | `adv2412` | 2024-12 | 14.3 | eligible |
| FY2025Q2 | `adv2503` | 2025-03 | 13.3 | eligible |
| FY2025Q3 | `adv2506` | 2025-06 | 12.3 | eligible |
| FY2025Q4 | `adv2508` | 2025-08 | 42.3 | eligible |
| FY2026Q1 | `adv2511` | 2025-11 | 15.3 | eligible |
| FY2026Q2 | `adv2603` | 2026-03 | 7.3 | eligible |
| FY2026Q3 | `adv2606` | 2026-06 | 12.3 | eligible |

Ages are days from the printed MARTS release timestamp to the Visa earnings 8-K cutoff. The 2025 federal shutdown delayed `adv2509` to 2025-11-25, so the 2025-10-28 Visa origin uses `adv2508`. The 2018–2019 shutdown delayed `adv1812`/`adv1901`; see `docs/gates/census.md`.

## Amendment scan

- No Item 2.02 8-K/A amendments in the inventory window.
- Item 2.02 8-K filings kept as earnings releases in snapshot: 43

## Spot-check: submissions acceptance vs filing index page

Five earnings 8-K timestamps were compared to the `Accepted` field on the EDGAR filing index page (Eastern wall-clock). Agreement confirms that submissions `acceptanceDateTime` is Eastern time.

| Accession | Filed | Submissions UTC | Index page (ET) | Index → UTC | Match |
| --- | --- | --- | --- | --- | --- |
| `0001403161-17-000010` | 2017-02-02 | `2017-02-02T21:10:32Z` | `2017-02-02 16:10:32` | `2017-02-02T21:10:32Z` | yes |
| `0001403161-19-000002` | 2019-01-30 | `2019-01-30T21:05:27Z` | `2019-01-30 16:05:27` | `2019-01-30T21:05:27Z` | yes |
| `0001403161-21-000009` | 2021-01-28 | `2021-01-28T21:02:48Z` | `2021-01-28 16:02:48` | `2021-01-28T21:02:48Z` | yes |
| `0001403161-24-000013` | 2024-01-25 | `2024-01-25T21:05:41Z` | `2024-01-25 16:05:41` | `2024-01-25T21:05:41Z` | yes |
| `0001403161-26-000044` | 2026-01-29 | `2026-01-29T21:05:49Z` | `2026-01-29 16:05:49` | `2026-01-29T21:05:49Z` | yes |

## Pending checks (can only lower the count)

- LON-2: Visa driver and accounting definition stability across the window. **Done — 0 exclusions.**
- LON-3: reconstructable starting state from release + prior 10-Q under the cutoff convention. **Done — complete with eligible-family inputs; 0 exclusions. See `docs/gates/starting-states.md`.**
- LON-5: Census MARTS vintage timing relative to each Visa cutoff. **Done — every inventory origin has a Census advance release ≤ cutoff; 0 exclusions from timing. See `docs/gates/census.md`.**
- LON-4: Booking Holdings family gate (measured + qualitative/guidance passages, staleness in weeks, same-day margin). **Done — required family with lagged measured rules and guidance only where it covers the Visa target quarter; same-day fallback variant required. See `docs/gates/booking.md`.**
- LON-7: Visa IR guidance availability (earnings deck / transcript outlook) and analyst-estimate confirmation. **Done — guidance is a comparison baseline only (never a model input), so gaps do not change origin eligibility. 16/19 origins have next-quarter company guidance; consensus unavailable (no licensed free historical source). See `docs/gates/guidance.md`.**
- LON-8: Second-wave disclosure families (one airline, one retailer, one pure payment processor). **Done — context-first families; selection and timing live in `docs/gates/second-wave.md` and do not change origin eligibility.**

