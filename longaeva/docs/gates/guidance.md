# Gate: Guidance availability and analyst-estimate confirmation

Source review dated October 2, 2026.

## Question

Can the guidance baseline cover all eligible origins?

## Answer

**Mostly yes — 16 of 19 origins have a recoverable next-quarter outlook.** Eleven
primary/prospective origins (FY2024Q1–FY2026Q3) carry next-quarter guidance on the
Visa earnings presentation. Five extension origins (FY2022Q1, FY2022Q3–FY2023Q2)
carry spoken next-quarter outlook in Visa-posted FactSet CallStreet transcripts.
Three gaps remain: FY2022Q2 (transcript gives second-half / full-year outlook
only), FY2023Q3 and FY2023Q4 (no transcript PDF on the Visa CDN; FY2023Q4 deck is
full-year only).

Guidance is **company guidance** for comparison only. It is never a model
input. Analyst estimates are recorded as
**consensus unavailable (no licensed free historical source)**.

## Per-origin availability

| Origin | Window | Source | Outlook | Comparable NR | Comparable opex | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FY2022Q1 | extension | transcript | next quarter | yes (nominal) | — | "high end of high teens" |
| FY2022Q2 | extension | none | — | — | — | second-half / full-year only |
| FY2022Q3 | extension | transcript | next quarter | yes | — | "high-teens to 20%" |
| FY2022Q4 | extension | transcript | next quarter | yes | yes (nominal non-GAAP) | "high single-digit" / "low teens" |
| FY2023Q1 | extension | transcript | next quarter | yes | derived (relative) | "high-single digits" |
| FY2023Q2 | extension | transcript | next quarter | yes | derived (relative) | "low-double digits"; sample fixture |
| FY2023Q3 | extension | none | — | — | — | transcript absent from CDN |
| FY2023Q4 | extension | none | full-year deck | — | — | transcript absent; FY outlook only |
| FY2024Q1–FY2026Q3 | primary / prospective | deck | next quarter + FY | yes | yes | outlook + recon slides; all within ±1 h of cutoff |

Full machine-readable table: [`data/fixtures/guidance/availability.csv`](../../data/fixtures/guidance/availability.csv).
Parsed phrases: [`data/fixtures/guidance/statements.csv`](../../data/fixtures/guidance/statements.csv).

## Outlook eras

1. **Transcript era (FY2022–FY2023).** Decks generally omit a next-quarter outlook
   slide. Spoken outlook lives in FactSet CallStreet "CORRECTED-TRANSCRIPT" PDFs on
   the Visa CDN. Phrasing varies ("we expect net revenues to grow at…", "Q2 net
   revenue growth would be in the…", "third quarter net revenue growth is expected
   to be in the…"). Relative opex ("2 to 3 points lower than Qref") is flagged
   `derived` for comparison baselines to resolve against reported growth.
2. **Deck era (FY2024Q1 onward).** Slide titled "Financial Outlook for Fiscal
   [next] Quarter and Fiscal Full-Year" on an adjusted constant-dollar basis, with
   an appendix reconciliation to GAAP / non-GAAP nominal and FX.

Internet Archive CDX listings show Visa-posted transcripts back to FY2015Q4 for a
longer residual history if comparison baselines wants more than the extension window.

## Timing rule (same earnings event)

Guidance is **not** a model input, so the strict at-or-before-cutoff input rule
does not apply. A deck counts for its origin when CDN `Last-Modified` is within
±1 hour of the EDGAR cutoff (observed deltas −239 s to +420 s). Supporting
signals: PDF `CreationDate` / `ModDate`, and optional Internet Archive digest
match. A transcript counts when the call date equals the cutoff's US/Eastern
date; both `statement_ts` (call) and `document_ts` (posting, typically 2–6 days
later) are recorded.

**The LLM forecast baseline must not receive these IR decks or transcripts as LLM context.**

## Comparability

Per [`docs/definitions.md`](../definitions.md) §6.2:

| Metric | Guidance basis used | Notes |
| --- | --- | --- |
| Net revenue | GAAP nominal row when present; else outlook phrase / transcript nominal | Scored as GAAP net revenue |
| Operating expenses | Non-GAAP nominal (matches `ex_special_items`) | Transcript relative → `derived` |
| Operating profit | Not guided | The comparison baseline may derive; flag `derived` |
| Diluted EPS | Context only | Not used in the guidance residual |
| Drivers | No numeric guidance | — |
| Full-year | Context only | — |

## Capture and hashing

- **IR HTML pages** at investor.visa.com return HTTP 403 Cloudflare JavaScript
  challenges and are **unavailable for automation** (access controls were not bypassed).
- Documents are fetched from `s1.q4cdn.com` URLs discovered via Internet Archive
  CDX, with ≥10 s spacing and the declared User-Agent.
- Originals stay under `var/cache/visa_ir/` (gitignored / export-ignored).
  Committed artifacts are metadata and short quotes only (`redistribution:
  fetch_script`).
- Probe records HTTP status, ETag, Last-Modified, sha256, base32 SHA-1, PDF
  dates, page count, outlook/recon page numbers, and optional archive digests.

Commands:

```bash
cd backend
python -m longaeva_app.collect.visa_ir probe [--refresh] [--skip-archive]
python -m longaeva_app.collect.visa_ir verify
```

## Licensing

| Source | Terms | Redistribution |
| --- | --- | --- |
| Visa IR / CDN decks | [visa.com/legal](https://www.visa.com/en-us/legal): personal non-commercial download; no public/commercial redistribution without consent | fetch script; never bundle |
| FactSet CallStreet transcripts | "Copyrighted FactSet CallStreet, LLC. All rights reserved." | short quotes only; never bundle |

## Analyst estimates check

Providers reviewed (see manifest `analyst_estimates_checked`):

| Provider | Access | Historical as-of |
| --- | --- | --- |
| LSEG I/B/E/S, FactSet, Capital IQ, Bloomberg, Zacks, Visible Alpha | paid | paid |
| Alpha Vantage | free key | no (EPS only; no as-of vintage; the benchmark review used no-key access) |
| Finnhub, Financial Modeling Prep | free key / paid | limited |
| Yahoo Finance / yfinance | unofficial | not allowed |
| SEC EDGAR | free | no estimates |

**Label (only permitted form):**
`consensus unavailable (no licensed free historical source)`.

## Phrase lexicon v1 (analyst assumption)

| Phrase | Interval (% YoY) |
| --- | --- |
| approximately flat | −1 to 1 |
| low / mid / high single-digit | 1–3 / 4–6 / 7–9 |
| low double-digit | 10–12 |
| low / mid / high teens | 12–14 / 14–16 / 17–19 |
| low / mid / high 20s | 20–23 / 24–26 / 27–29 |

Combinators: "high end of X" / "low end of X" = upper / lower half; "X to Y" =
low of X to high of Y; numeric cells such as `20%` parse as point values.
Unknown phrases fail tests.

## Sample fixtures (statement type `guidance`)

| File | Origin | Role |
| --- | --- | --- |
| `visa_guidance_2023-04-25.json` | FY2023Q2 | transcript era |
| `visa_guidance_2024-07-23.json` | FY2024Q3 | July 2024 origin |
| `visa_guidance_2025-10-28.json` | FY2025Q4 | October 2025 origin |
| `visa_guidance_2026-07-28.json` | FY2026Q3 | prospective |

## Integration

| Component | Use of this evidence |
| --- | --- |
| comparison baselines | Guidance comparison baseline + prior-data residual distribution over the 16 covered origins |
| LLM forecast baseline | Must **not** ingest these decks/transcripts |
| prospective registration | Prospective FY2026Q3 fixture already present |
| evaluation report / result pages | Report and UI labels: company guidance; estimates-unavailable string |

## Artifacts

- Manifest: [`data/manifest/visa_ir.yaml`](../../data/manifest/visa_ir.yaml)
- Probe metadata: [`data/fixtures/guidance/probe.json`](../../data/fixtures/guidance/probe.json)
- Collector: `backend/longaeva_app/collect/visa_ir.py`
- Extractors: `backend/longaeva_app/extract/visa_guidance.py`
