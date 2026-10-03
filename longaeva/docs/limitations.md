# Limitations

Living document for packaging, licensing and evaluation caveats. LON-33 and LON-38
extend this file; LON-12 adds the personal-data and secrets checklist below.

## Personal data and secrets (LON-12 / PR-07)

### What the isolation guard automates

`python -m longaeva_app.cli export-check` (also `make guard` / `make check`) scans the
would-be-exported file set defined by [`.exportignore`](../.exportignore) and fails on:

- Imports outside `longaeva_app`, the Python standard library, pinned third-party
  distributions in `backend/requirements.lock`, or local test helpers
- Symlinks and non-regular files in the export set
- Absolute developer paths (`/Users/…`, `/home/…`, `C:\Users\…`, macOS `/var/folders/…`)
- Path literals that resolve above the package root
- `.env` / `.env.*` files other than `.env.example` when they would ship
- Secret-shaped strings (cloud/provider keys, private-key blocks, JWTs, non-placeholder
  URL credentials, generic `*_KEY` / `*_TOKEN` / `*_SECRET` / `*PASSWORD` assignments)
- **Local-secret leak check:** values of secret-like keys from the package `.env` and
  the process environment (and any email embedded in `SEC_USER_AGENT`) must not appear
  in any exported file. Findings name the key only; values are never printed.

`--strict` additionally fails when an excluded path (for example a local `.env`) is
still present on disk. Use that mode on the unpacked export copy (LON-24), not on the
developer working tree.

**PDF limitation:** retained PDF originals are scanned as raw bytes only. Compressed
PDF streams are not inflated, so a secret placed only inside a compressed stream would
not be detected. Do not embed credentials in PDFs.

### Manual pre-export checklist

Complete before building the submission ZIP (LON-24 / LON-38):

1. `SEC_USER_AGENT` and any provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `GEMINI_API_KEY`, future Tiingo keys, etc.) live only in `.env` or the process
   environment — never in manifests, docs, fixtures or committed source.
2. No personal names, personal emails or account IDs appear in the package.
3. Issuer IR / corporate emails inside retained public SEC filings are expected and
   allowed (they are not personal data of the builder).
4. No Talisman portfolio state, account data or internal identifiers are included.
5. The export contains no `.git` directory. A fresh repository created from the export
   uses the identity chosen at submission time, not a developer machine identity
   copied from Talisman.
6. Screenshots and demo recordings show no local filesystem paths or browser profiles.
7. Validation logs for export rehearsals stay under Talisman's
   `docs/hackathon/planning/validation/` directory and are **not** bundled in the
   package export.

## Engine caveats (LON-19)

- **Uncalibrated defaults.** Parameter defaults in `companies/visa/parameters.py` are
  placeholders. A run on defaults is not a forecast. Prefer a LON-20 calibrated
  parameter set (`make calibrate ARGS='--persist'`, scenario name `calibrated`).
- **Cross-border share is an assumption.** Visa does not disclose a cross-border volume
  level at the earnings cutoff (LON-3). `cross_border_share_at_origin` is an
  analyst-assumption parameter (range midpoint 0.20). International yield is scaled by
  that share so next-quarter international revenue is nearly share-insensitive when the
  growth premium and travel shock are zero.
- **Ex-special-items operating profit only.** Path metrics use
  `operating_profit_ex_special_items` / `operating_expenses_ex_special_items`. GAAP
  operating profit remains on fixtures for reporting, not as a simulated path.
- **One shared pricing shock.** The three category yields share a single pricing factor.
  Category-specific yield uncertainty is only through separate drift parameters; residual
  pricing scale is pooled across service and data-processing yields in LON-20.

## Calibration caveats (LON-20)

- **Short post-pandemic history.** FY2020Q2–FY2021Q4 (and YoY bases through FY2022Q4)
  have zero estimation weight, so early origins lean on FY2018Q2–FY2020Q1 growth rates
  and modern-era opex only.
- **Whole-percent growth rounding.** Disclosed driver growth rates are integers; residual
  shock scales inherit that quantization.
- **Cross-border seasonals assumed.** Only YoY cross-border growth is disclosed, so
  `cross_border_seasonal_q*` stay at 1.0 with `assumption=true`.
- **Pooled set in runs.** Ensemble members and weights are in the calibration artifact;
  submitted runs use the pooled parameter set until LON-27 records weights with each run.

## Collector caveats (LON-13)

- **IR publication timestamps** come from the CDN `Last-Modified` header, not an
  EDGAR acceptance field. Decks are checked against a one-hour event window around
  the origin cutoff; mismatches are flagged in `source.attributes` but still stored.
  Missing `Last-Modified` refuses ingest (DR-04).
- **Census integrity:** some archived MARTS PDFs are flagged `possibly_replaced` in
  the release calendar; the collector carries the flag into `source.attributes` and
  still uses the printed release line as `publication_ts`.
- **Excluded vintages:** the revised Census XLSX (`mrtssales92-present.xlsx`) and
  EDGAR XBRL `companyfacts` feeds are not collected here — they lack a single
  immutable publication vintage suitable for DR-04.
- **IR redistribution:** Visa IR decks/transcripts are fetch-by-script only and must
  not be bundled in the export ZIP (see `visa_ir.yaml` terms).
- **Visa parser (LON-14):** FY2018Q1–FY2021Q2 releases are page images. The hidden
  text layer is incomplete for some Key Business Drivers tables; those quarters stay
  `partial` rather than fabricating growth rates. Operational Performance Data volume
  *levels* in older releases are out of scope (LON-20 / LON-16).

## Runs and replay (LON-23)

- **Bit-exact replay** holds only in the same numerical environment (same NumPy /
  BLAS). Across macOS Accelerate and the container OpenBLAS, replay may return
  `numerically_equivalent` (max relative difference ≤ 1e-9) instead of `exact_match`.
- **Runs on uncalibrated defaults are not forecasts.** `POST /runs/{id}/forecasts`
  refuses all-assumption parameter sets.
- **Two origins only.** Reconciled starting states exist for 2024-07-23 and
  2025-10-28. Other cutoffs return 422 until LON-27 wires calibrated starts.
- **Progress is status only.** There is no per-path progress stream; poll
  `GET /runs/{id}` (`queued` / `running` / `succeeded` / `failed`).
- **Prospective vs retrospective** archive checks use the static
  `data/fixtures/origins.csv` target-release timestamps, not a live EDGAR fetch.

## Frontend (LON-11)

- **No authentication.** The web app is local-review only; `/api` is proxied without
  credentials. Do not expose Compose ports beyond `127.0.0.1`.
- **PairedDiffChart is not mounted.** Path-wise difference summaries do not exist until
  paired scenarios land. Subtracting two runs' quantiles is not the same statistic.
- **Metric labels are a frontend catalog** aligned with `VisaModel.metrics`. The results
  API does not send units; unknown metric keys fall back to raw numbers.
- **Playwright is not in this package yet.** Frontend checks are ESLint, Vitest, and
  `tsc` via `npm run build`.

## Export rehearsal (LON-24)

- **Log lives outside the package.** Validation logs belong in Talisman's
  `docs/hackathon/planning/validation/` and are attached to the Linear issue; they are
  not bundled in the ZIP.
- **UF-01 / UF-03 browser flows are not automated.** This rehearsal smokes HTTP and
  charts via the existing Run page; Playwright and the full scenario workspace land in
  LON-34 / LON-36.
- **Cold image builds need the network.** `--no-cache` pulls from PyPI and npm.
- **Docker Desktop must share `/tmp`.** The verifier unpacks under `/tmp/longaeva-verify.*`
  and bind-mounts that tree into Compose. If file sharing excludes `/tmp`, `make up`
  from the unpacked copy will fail.
- **Ports.** The verifier defaults to API 18000, web 13000, Postgres 15432 so it does
  not collide with a developer stack on 8000 / 3000 / 55432.
- **Replay after restart** keeps named volumes (`make down` without `-v`) so artifacts
  and Postgres survive. Final teardown uses `down -v --rmi local`.

