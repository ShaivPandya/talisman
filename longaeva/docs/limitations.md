# Limitations

Packaging, licensing and evaluation caveats consolidated for LON-33. See the
[evaluation report](evaluation-report.md) for measured results and the documented
failure case. Final export validation is performed with `make verify-export` and
`ARGS=--final`; its dated evidence is kept outside the package (LON-38).

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
- **Pooled set in runs.** Submitted runs use the pooled parameter set. Evaluation
  rows (LON-27) also record ensemble members and weights in `details`.

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
- **Buildable origins.** Committed LON-3 fixtures cover 2024-07-23 and 2025-10-28;
  other candidate/prospective cutoffs are built from as-of observations. FY2022Q3
  and FY2022Q4 cannot be built (missing FY2021Q3 payments-volume level in the
  parsed 10-K tables).
- **Progress is status only.** There is no per-path progress stream; poll
  `GET /runs/{id}` (`queued` / `running` / `succeeded` / `failed`).
- **Prospective vs retrospective** archive checks use the static
  `data/fixtures/origins.csv` target-release timestamps, not a live EDGAR fetch.

## Evaluation (LON-27)

- **Small n.** Sixteen scored origins (10 primary + 6 extension); report `n` with
  every aggregate. Two extension origins are excluded for the FY2021Q3 volume gap.
- **Driver approximations.** Payments-volume YoY uses a labeled one-quarter FX
  adjustment on 10-Q levels; cross-border YoY has no disclosed level and uses a
  persistence / model QoQ for the year-ago step.
- **Whole-percent growth.** Reported driver growth rates are integers, so driver
  error distributions inherit that quantization.
- **Engine growth metrics are annualized QoQ.** Scoring recovers quarterly rates
  before the history-anchored YoY transform; do not treat path
  `payments_volume_growth_constant` as true YoY.

## Baselines (LON-29)

- **External effects are conditional.** The full model now applies reviewed Booking
  and Census mapping rules; financial-only matches the no-external-commentary
  ablation. Effects are mixed across targets, horizons and retained parameter
  ranges. They are not evidence of a generally predictive external signal.
- **Deck guidance is a different basis from the actual.** Outlook slides state
  adjusted constant-dollar growth. Scoring uses GAAP nominal actuals. Rows carry
  `basis_note`. The residual distribution absorbs the systematic gap; it is not
  removed.
- **Guidance residuals fall back.** Prior guidance errors are used once four have
  actuals published at or before the cutoff. Otherwise the seasonal/trend
  residual spread is used and the row is flagged
  `residual_source=seasonal_trend_fallback`.
- **Image-era levels are unusable.** The same quality gate as calibration drops
  image-text and FY2017 net revenue and operating profit. FY2022Q1 and FY2022Q2
  therefore have no seasonal level point, and the FY2022Q1 revenue outlook cannot
  be applied, because the year-ago quarter is image-era.
- **Guidance does not cover drivers or four quarters.** Those rows are marked
  unavailable. No row is labeled consensus. The only estimates string is the
  config note `consensus unavailable (no licensed free historical source)`.
- **Guided operating profit is derived**, not a company outlook for profit.
  FY2023Q1 and FY2023Q2 resolve a relative opex phrase against reported growth.

## Extraction (LON-16)

- **Passage-only prompts do not remove hindsight.** The model still has pretrained
  knowledge. The prompt forbids outside knowledge and requires a verbatim quote,
  and a quote that is not in the passage is dropped. That is a check, not a
  proof the model ignored anything else it knows.
- **Outputs vary by provider.** Anthropic, OpenAI, and Gemini can disagree on the
  same passage. The cache is per provider and model; a hit replays that call's
  parsed items, not a consensus.
- **Raw responses are kept.** `extraction_call.response_text` stores the provider
  body for audit, including invalid payloads (`parsed` stays null so a confidence
  field is not stored as structured data). Do not point extraction at text you
  would not retain.
- **Review is required.** Extracted observations stay `pending` until an accept
  or correct decision. `POST /runs` rejects a parameter set that cites a pending
  or rejected observation row. Extraction never writes a parameter set.
- **Disabled by default.** With `LLM_PROVIDER` unset, fresh extraction returns
  503. Keys belong in `.env` only.

## Scenarios and attribution (LON-22)

- **Persistent shifts only.** A mix shift or spend reduction is applied once and then
  carried by state. There is no pulse, ramp, or path-dependent rule.
- **Transactions are unchanged** by `total_spend_reduction`. Data-processing revenue
  does not move because volume moved.
- **Overrides keep the base ranges.** A child parameter set changes the value and
  marks it as an assumption. Sensitivity still sweeps the base low and high.
- **The flag threshold is a heuristic.** `high_sensitivity_weak_support` fires when
  normalized sensitivity times `(1 − support)` is at least 0.25. On default ranges,
  seasonal parameters dominate that ranking. `cross_border_share_at_origin` has
  support 0 and a very small normalized sensitivity, so it is not flagged. On the
  calibrated 2024-07-23 set the wide seasonal ranges are observation-backed, so the
  flag list can be empty.
- **Labels are model-conditional.** Sequential order is fixed (parameters by name,
  then interventions as listed). One-at-a-time terms need not sum to the total; the
  joint residual is that gap. The API does not treat these effects as identified
  effects outside the model.
- **Comparison reads saved paths.** Subtracting two runs' published quantiles is not
  the comparison. `GET /scenarios/comparison` differences the path arrays in
  `paths.npz`. Attribution re-simulates and returns 409 if the recomputed hash does
  not match the saved run.

## Mapping rules (LON-21)

- **Anchors and betas are analyst assumptions.** Booking uses an 8% room-nights anchor
  and betas 0.2–0.4, which discount Booking's global mix. Census uses a 3% retail
  anchor and betas 0.25–0.75. Neither pair is a fitted coefficient on the retained
  history.
- **US share is assumed.** Census is scaled by 0.45, an explicit assumption for the
  US share of Visa volume. No observation parses that share. `payments_volume_nominal_us`
  is US dollars, not the United States.
- **Estimated rules depend on retained history.** Booking remains sparse and uses
  an analyst fallback. Census fits when at least 12 eligible aligned quarter-end
  pairs exist; otherwise it records a fallback assumption. A fitted slope still
  reflects the selected retrospective corpus and the assumed US scaling.
- **Guidance widens the range.** A low–high outlook uses the midpoint as the point
  update and the half-width in the recorded range. That width is not a probability.
- **The first apply wins the update text.** Re-applying the same child hash does not
  rewrite `parameter_update.rationale`.
- **Context is not a coefficient.** Airline, retailer, and processor observations, plus
  Booking gross bookings and qualitative statements, do not change the parameter set.

## Valuation (LON-25)

- **Buyback average, not a close.** The multiple uses the quarterly average
  price Visa paid to repurchase shares (Issuer Purchases of Equity Securities),
  not a market close. Visa daily prices remain blocked (LON-6). The notes'
  "average repurchase cost" can differ by about a dollar from that Item 2
  average; the bridge uses Item 2.
- **GAAP tax rate on an ex-special-items profit.** `tax_rate` is the GAAP
  effective rate from the release. It is applied to operating profit excluding
  identified special items. Those bases do not match.
- **Flat shares and net interest/other.** Both stay at the origin value for all
  four quarters. Buybacks and a changing share count are not simulated.
- **Trailing multiple on forward earnings.** The P/E is trailing four-quarter
  EPS excluding special items. It is applied to the model's forward EPS, which
  is a different earnings construct.
- **Short window.** History runs FY2023Q1–FY2026Q2 (14 quarters). A cutoff keeps
  only filings accepted by then, and fewer than four quarters is unsupported.
  The 2024-07-23 origin therefore excludes the FY2024Q3 10-Q, accepted about
  two hours after the earnings release.
- **The outer envelope is not a probability.** It multiplies the EPS p10 by the
  low multiple and the EPS p90 by the high multiple. Earnings-driven and
  multiple-driven spreads are the separated pieces.

## Illustrative actions (LON-26)

- **Buyback average, and circular with the multiple.** The reference price is
  the latest quarterly average repurchase price accepted by the cutoff, the
  same series as the trailing P/E numerator. Value per share is forward EPS
  times the median of those trailing multiples. The margin compares that value
  with the latest buyback average. It is not a discount to a market close.
  Visa daily prices remain blocked (LON-6).
- **Flat basis-point costs.** Transaction, slippage, and impact do not depend
  on volume or volatility. Funding is off in the committed rule. If it is set,
  it applies only to added notional over the 63-day holding period.
- **Long only.** The demo position is 1,000 shares long. There is no short, no
  leverage, and no book-level constraint. A trim fraction above 1 is clamped
  at zero shares; the committed fractions are 0.25.
- **Not advice.** Every action label says illustrative. The net value gap is
  not a probability and is not a forecast of trading profit. The rule is fixed
  configuration. LON-28 retains benchmark-window aggregates; Visa strategy and
  buy-and-hold scoring remain not run because daily Visa prices are unavailable.
- **Hold is the no-action outcome.** An unsupported bridge, or a cutoff with no
  repurchase price and no request override, returns hold and the reason. No
  price or value is filled in to make the rule fire.

## Frontend (LON-11)

- **No authentication.** The web app is local-review only; `/api` is proxied without
  credentials. Do not expose Compose ports beyond `127.0.0.1`.
- **Paired charts read saved differences.** The scenario workspace is implemented.
  Subtracting two independently summarized quantiles is not a paired effect.
- **Metric labels are a frontend catalog** aligned with `VisaModel.metrics`. The results
  API does not send units; unknown metric keys fall back to raw numbers.
- **Browser automation is external to the package.** Frontend checks are ESLint,
  Vitest and `tsc` via `npm run build`. Final browser evidence is recorded against
  the exported stack separately from the scripted API checks.

## Export rehearsal (LON-24)

- **Log lives outside the package.** Validation logs belong in Talisman's
  `docs/hackathon/planning/validation/` and are attached to the Linear issue; they are
  not bundled in the ZIP.
- **Early rehearsal scope.** The LON-24 rehearsal checked the original run page.
  Scenario and result pages have since been implemented and inspected; the final
  exported application is checked by LON-38 final mode plus a separate browser walkthrough.
  Consult the dated external validation log for the exact ZIP and outcomes.
- **Cold image builds need the network.** `--no-cache` pulls from PyPI and npm.
- **Docker Desktop must share `/tmp`.** The verifier unpacks under `/tmp/longaeva-verify.*`
  and bind-mounts that tree into Compose. If file sharing excludes `/tmp`, `make up`
  from the unpacked copy will fail.
- **Ports.** The verifier defaults to API 18000, web 13000, Postgres 15432 so it does
  not collide with a developer stack on 8000 / 3000 / 55432.
- **Replay after restart** keeps named volumes (`make down` without `-v`) so artifacts
  and Postgres survive. Final teardown uses `down -v --rmi local`.

## Local startup without Docker

- **Python and Node are prerequisites.** `make up-local` (macOS and Linux) and
  `scripts/up-local.ps1` (Windows) require Python 3.12 or newer and Node.js 20.19
  or newer. They do not install those runtimes.
- **The first run needs a network.** It installs locked Python and npm packages
  and downloads PostgreSQL 16.10.0 server binaries (PostgreSQL license, packaged
  by Zonky) into `var/`. Later runs reuse that download. The binaries are not
  part of the submission ZIP.
- **Windows on ARM and musl/Alpine are unsupported.** Those machines should use
  `make up` with Docker. The downloaded Linux binaries require glibc.
- **`make verify-export` still requires Docker.** The no-Docker command is a
  second way to start the demo, not a replacement for the image-based check.
- **`make down` and `make down-local` stop different stacks.** The local command
  stops only processes it started, including its private Postgres data directory.
  It does not stop a Compose database that was already listening on port 55432.

## Search (LON-17)

- **Lexical only.** Search is Postgres english `tsvector` / `websearch_to_tsquery`
  over stored passage text. There is no embedding index and no semantic search.
- **Superseded sources are not collapsed.** A passage in a document that a later
  source supersedes still matches when its text and filters match.
- **Undated sources drop out of a period filter.** A source with a null
  `period_start` or `period_end` is excluded whenever `period_start` or
  `period_end` is passed. The same source remains searchable when no period
  filter is set.
- **A date-only cutoff is midnight UTC.** `cutoff_ts=2024-07-23` means
  `2024-07-23T00:00:00Z`, so a release later that calendar day is excluded.
- **Latency check is a fixture, not the demo seed.** Tests time a filtered
  search over 5,000 synthetic passages. The demo seed is LON-37. The corpus
  collected in development is smaller than that fixture.


## Consolidated evidence (LON-33)

- **Retrospective development.** Publication cutoffs prevent later supplied inputs;
  they cannot remove retrospective source selection, review or model choices.
  Pretrained LLM knowledge may contain outcomes. The retained LLM comparison uses
  evidence excerpts, not complete filings or a historical live workflow.
- **Different denominators.** Missing baseline targets and unavailable four-quarter
  forecasts stay missing. The report uses matched origins for direct comparisons;
  Monte Carlo paths, metrics and sensitivity profiles do not increase independent n.
- **Metric convention.** WIS uses the repository's median-weight-1, denominator-K+1
  variant documented in the model specification. Do not compare these scores with
  another implementation's normalization without aligning formulas.
- **Extraction sample.** The curated passages are purposive; user review covers the
  selected labels, not the whole corpus. Scope, basis and omission errors have
  different denominators. An extraction error rate is not a forecast error rate.
- **Portfolio comparisons unavailable.** Benchmark returns use the exact approximation
  labels in the report. No license-compliant free daily Visa price source was retained,
  so strategy, buy-and-hold and excess-return metrics are not run. Overlapping benchmark
  windows are not an investable portfolio track record.
- **Prospective timing.** The July-cutoff registration was created in October after
  fiscal quarter end and before results publication. It remains unscored; later
  actuals must not alter its original archive or historical sample counts.
- **Report validation limits.** Generation validates retained source hashes, exported
  scores and denominators. It does not independently reproduce old simulations,
  recover absent distribution tails or certify primary-source extraction accuracy.
