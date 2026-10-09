# Longaeva requirements — planning v1

October 1, 2026 · Phase 2 draft for review · Builds on [approach v2](approach.md). Companion documents: [README](README.md), [data plan](data-plan.md), [implementation plan](implementation-plan.md), [issue drafts](linear-backlog.md).

Requirement IDs are stable within planning v1. Each requirement names its classification (MVP, stretch, deferred, blocked), its source, and acceptance criteria. "Proposal p. N" cites the submitted PDF; "recap §" cites the meeting recap section; "rules" cites the official competition page PDF; "certification" cites the participant certification PDF.

## 1. Product statement

**User.** An investor or analyst deciding which Visa business assumptions to change and what to research next.

**Decision.** Given new dated evidence, what should change in expected next-quarter and four-quarter revenue and operating profit, how uncertain is that change, and does it justify holding, adding, trimming or exiting an illustrative Visa position at the current price?

**Central hypothesis.** Spending composition (domestic vs cross-border, transaction frequency) and revenue timing (service revenue follows prior-quarter payments volume) carry information beyond aggregate growth extrapolation. The system must be able to show that this is true, false or undetermined for the eligible history; improvement is not assumed. (Proposal pp. 1–2, 5.)

**End-to-end demonstration.** Dated evidence → reviewed observations → explicit parameter changes → four quarterly operating transitions → revenue/profit distributions → source-linked scenario comparison → valuation and cost-aware illustrative actions → evaluation against baselines, benchmarks and a failure case. (Proposal pp. 2, 5–6; approach v2 "Demo flow".)

**Delivery form.** A self-contained project directory, provisionally `longaeva/`, exportable as a ZIP or fresh repository, runnable without the rest of Talisman. (User decision, October 1, 2026.)

## 2. Commitment map

Every material proposal commitment, its classification, and the requirement(s) that carry it.

| # | Proposal commitment (page) | Class | Carried by | Reason / condition |
| --- | --- | --- | --- | --- |
| C1 | Starting state from reported activity, revenue, incentives, expenses with period/units/source (p. 2) | MVP | FR-01, FR-03, MR-01, MR-07, DR-02 | Core; verified against primary filings. |
| C2 | AI extraction of observations from filings, prepared remarks and selected airline, travel-platform, retailer, payment-processor disclosures (p. 2) | MVP | FR-02, FR-04, FR-05, DR-03 | Visa + Booking + Census gated first; one airline, one retailer, one processor added through DR-03 gate. Prepared-remarks availability unverified (data plan §3.1). |
| C3 | Observation-to-parameter rule; estimate where history exists, analyst range otherwise; qualitative statements do not become precise changes (p. 3) | MVP | FR-07, MR-09, MR-12 | Core. |
| C4 | Four quarterly transitions with carried-forward volumes and inspectable business rules (p. 3) | MVP | MR-02, MR-03, FR-08 | Core. |
| C5 | Separate revenue categories; incentives; opex; recurring vs exceptional (p. 3) | MVP | MR-04, MR-07 | Core. |
| C6 | Accounting checks: cross-border within total volume, VAS not double counted, PV/TXN coverage difference (p. 3) | MVP | MR-05 | Core; tested. |
| C7 | Monte Carlo with correlated conditions (p. 3) | MVP | MR-08 | Core. |
| C8 | Evidence → assumption → size → rule → result record; context-only when vague (p. 4) | MVP | FR-07, FR-11 | Core. |
| C9 | Source-family removal and historical tests of evidence value (p. 4) | MVP | ER-08 | Ablations rebuild inputs. |
| C10 | Architecture: Python collection, LLM JSON extraction with Pydantic, PostgreSQL/SQLAlchemy, object storage, pandas/NumPy/SciPy model, FastAPI + worker, React/Vite/Recharts, pytest (p. 4) | MVP | PR-01, PR-03, NR-03 | Preserved inside the standalone package; object storage becomes local artifact storage; cloud hosting conditional (SR-04). |
| C11 | Four core records: source, observation, parameter set, simulation run (p. 4) | MVP | FR-01, FR-03, FR-06, FR-09 | Core schema. |
| C12 | Postgres text search filtered by company, period, publication date (p. 4) | MVP | FR-02 | Core. |
| C13 | Run → run id → worker → progress → saved results; charts refer to the saved run (p. 4) | MVP | FR-08 | Core. |
| C14 | Runs preserve cutoff, document versions, parameters, code version, seed (p. 4) | MVP | FR-09, ER-03 | Core. |
| C15 | Docker packaging; Cloud Run/Cloud SQL/Cloud Storage deployment (p. 4) | MVP (Docker) / stretch (cloud) | PR-03, SR-04 | Hosting depends on submission rules, unresolved. |
| C16 | Main screen: assumptions, ranges, evidence; change an assumption and see range move (p. 5) | MVP | UF-01–UF-03, FR-11 | Core. |
| C17 | Spending-mix comparison with conserved total; total-spend reduction showing service lag; shared sampled conditions (p. 5) | MVP | FR-10, MR-11 | Core. |
| C18 | Explanations identify high-impact, weakly supported assumptions; model-conditional language (p. 5) | MVP | FR-11 | Core. |
| C19 | Compare with company guidance where metric/period match (p. 5) | MVP | FR-15, ER-07 | Guidance source availability gated (data plan §3.1). |
| C20 | Compare with historical analyst consensus when licensed data are available (p. 5) | Blocked | FR-15 | No free licensed historical consensus verified; report "consensus unavailable"; guidance kept under its own label. |
| C21 | Operating profit → earnings with tax, net interest, share count; multiple range; business vs multiple uncertainty separated (p. 5) | MVP | FR-12 | Core. |
| C22 | Hold/add/trim/exit with trading costs; excess return vs fixed S&P 500 total-return benchmark after costs; Visa buy-and-hold comparison; rule and horizon fixed before scoring (p. 5) | MVP (conditional on DR-07) | FR-13, FR-14, ER-11 | Free total-return source unverified; approximation must be labeled, never silently relabeled. |
| C23 | At least eight eligible next-quarter forecasts; earlier estimation period; report actual count and exclusions (p. 5) | MVP target | DR-05, DR-06, ER-05 | Count unproven until DRAFT-01/03 complete; fewer than eight is a reported shortfall. |
| C24 | Prospective forecasts saved and evaluated separately (p. 5) | MVP | FR-17, ER-10 | One prospective origin exists (data plan §2.4). |
| C25 | Baselines: seasonal/trend; financial-only driver model; LLM with the same dated documents (p. 5) | MVP | ER-07 | All three. |
| C26 | Errors in net revenue, operating profit, drivers; 80% interval coverage; proper scoring rule (p. 5) | MVP | ER-05, ER-06 | Core. |
| C27 | Three ablations: remove external commentary; pool spending types; remove service lag (p. 5) | MVP | ER-08, MR-11 | All three. |
| C28 | Reviewed extraction-error sample (facts, units, periods, geography) (p. 5) | MVP | ER-09 | Core. |
| C29 | Hindsight/pretrained-model limitation; restrict extraction to supplied passages; preserve original versions (p. 5) | MVP | FR-04, DR-04, ER-10 | Core; also required by certification item 4 (look-ahead bias). |
| C30 | Ranges for hidden fees/incentives; retain alternative parameter combinations (p. 6) | MVP | MR-06, MR-09 | Core. |
| C31 | External sources keep their limits; repeated versions count once; government revisions handled by availability date (p. 6) | MVP | DR-04, DR-08 | Core. |
| C32 | Permitted sources only; Longaeva data only after NDA; paid data not required (p. 6) | MVP | DR-01 | Longaeva/paid access confirmed unavailable; excluded from dependencies. |
| C33 | Deliverable: working Visa simulation, scenario controls, inspectable evidence, saved forecasts, evaluation report, model specification, failure-case demo (p. 6) | MVP | FR-16, ER-12, PR-04 | Core. |
| C34 | Architecture supports additional companies through separate business models with shared formats (p. 6) | MVP (boundary) / stretch (second company) | FR-18, SR-01 | Boundary in scope; Mastercard stretch. |
| C35 | Rules: show which signals moved outputs; scalable, repeatable pipeline; consistent evaluation (rules pp. 4–5) | MVP | FR-11, NR-03, ER-* | Judging criteria (recap "Data Analysis Tools and Project Scoping"). |
| C36 | Certification: 100% public sources, documented and referenced; no look-ahead bias; original work in the window | MVP | DR-01, DR-04, NR-06 | Hard constraint on sources and disclosure. |

**Differences between the planned minimum demo and the proposal.** None in functional scope. Differences are in delivery and conditions: standalone package instead of in-app Talisman integration; cloud hosting conditional; historical consensus blocked and replaced by labeled guidance plus a "consensus unavailable" statement; Longaeva data excluded; S&P 500 total-return benchmark conditional on a verified free source or a labeled approximation; eight eligible forecasts remain a target to be counted, not a promise.

## 3. User flows

| ID | Flow | Acceptance |
| --- | --- | --- |
| UF-01 | Open a saved Visa state at a chosen cutoff; inspect each starting value with fiscal period, unit, basis (nominal/constant, GAAP/special items) and a link to its source span. | Every displayed starting value shows period, unit, basis and source; clicking the source opens the passage at the stored span. |
| UF-02 | From a dated passage, view the extracted observation, its review status, the mapping rule, and the resulting parameter range; accept, adjust (with rationale) or reject; see unsupported items retained as context. | Review decision persisted with user, time, rationale; the approved parameter set changes only after acceptance; context-only observations display without a numeric change. |
| UF-03 | Define two scenarios (e.g. mix shift with conserved total; total-spend reduction), run four quarters, compare net revenue and operating profit distributions under shared draws, and trace the difference to inputs and passages. | Run returns an id; progress visible; results come from the saved run; both scenarios share the seed; attribution panel lists changed parameters, sizes, rules and sources. |
| UF-04 | View the earnings/multiple valuation bridge and hold/add/trim/exit outcomes with costs for the illustrative position. | Business and multiple uncertainty shown separately; each action shows cost components; unsupported cases (e.g. non-positive earnings) show a documented message, not a number. |
| UF-05 | Inspect evaluation: origin table, errors vs baselines, interval coverage and scores, ablations, benchmark comparison, extraction-error sample, failure case. | Report pages render from saved evaluation artifacts; counts and exclusions are displayed; failure case is reachable from the main navigation. |
| UF-06 | Replay a saved run from its record and confirm the output hash matches, with no LLM credentials configured. | CLI and API replay succeed with `LLM_PROVIDER` unset; hash equality reported; mismatches explained by recorded library versions. |
| UF-07 | Run fresh extraction on a new document with a configured provider. | Documented in setup; disabled gracefully when no provider configured; results enter review, never the approved parameter set directly. |
| UF-08 | A reviewer unpacks the export in an empty directory and starts the application with one documented command, then completes UF-01, UF-03 and UF-06. | Validated per PR-06 in a directory outside Talisman. |

## 4. Functional requirements

| ID | Requirement | Class | Acceptance | Trace |
| --- | --- | --- | --- | --- |
| FR-01 | Source record: provider, document type, company, publication timestamp (EDGAR acceptance time where applicable), observation period(s), retrieval timestamp, URL, content hash, original file retained, license note, supersedes/revision link. | MVP | Schema and tests; ingesting a document twice yields one source with two retrieval records; publication ≠ retrieval in all fixtures. | C1, C11, C31; proposal p. 4 |
| FR-02 | Document text stored with page/character spans; PostgreSQL full-text search filtered by company, observation period and publication date ≤ cutoff. | MVP | Search for "cross-border" with cutoff 2024-07-23 returns no passage published after that timestamp; spans resolve to the stored text. | C2, C12 |
| FR-03 | Observation schema: typed value or range, unit, activity type, geography, period, source span, source family, statement type ∈ {measured, guidance, qualitative, analyst_assumption, intervention}, review status, extractor id/version. | MVP | Pydantic validation rejects missing unit/period; fixtures cover each statement type. | C1, C3, C11 |
| FR-04 | LLM extraction returns JSON validated by Pydantic; prompt includes only supplied passages; provider configurable (Anthropic/OpenAI/Gemini-compatible); responses cached by (model, prompt hash); extraction failures recorded. | MVP | Unit test with a stubbed provider; cache hit avoids a call; no network when `LLM_PROVIDER` unset. | C2, C29 |
| FR-05 | Review workflow: accept / reject / correct with rationale; decisions persisted and versioned; an extracted observation never changes an approved parameter without a review decision. | MVP | Test: extraction creates pending observation; approved parameter set unchanged until accept. | C3, C8 |
| FR-06 | Parameter set: parameter values and ranges, each linked to observations or an explicit assumption label with rationale; versioned; content-hashed; derived from a cutoff. | MVP | Every parameter in a saved set has ≥1 evidence link or `assumption=true`; hash stable across serialization. | C3, C11, C30 |
| FR-07 | Mapping rule registry: rule id, input observation type, target parameter, transform (estimated or analyst range), before/after values, size, rationale; qualitative observations without supported transform remain context. | MVP | Rule application produces a provenance record; a qualitative observation with no rule leaves parameters unchanged and is listed as context. | C3, C8 |
| FR-08 | Scenario run: API accepts scenario definition + parameter set + cutoff + seed + n_paths, returns run id; worker executes; status endpoint; results persisted; UI reads saved results. | MVP | Integration test through API → worker → stored result → fetch. | C13 |
| FR-09 | Run record: cutoff, source manifest (ids + content hashes), parameter set hash, code version (git hash or package version + file hash), seed, n_paths, library versions, outputs hash; `replay` reproduces outputs without any LLM call. | MVP | Replay test: identical hash on the same environment; recorded versions shown when different. | C14, C29 |
| FR-10 | Paired scenarios share random draws; intervention types include mix shift with conserved total spending and total-spend reduction; difference distributions computed path-wise. | MVP | Test: mix-shift scenario total spending equals baseline on every path and quarter within tolerance; same seed → same base paths. | C17 |
| FR-11 | Attribution panel: parameter changes with sizes, rules and passages; sensitivity ranking; flags for assumptions with high sensitivity and weak support; all effects labeled conditional on the model; order dependence or joint residual shown for interacting changes. | MVP | Panel renders for a saved paired run; flags computed from sensitivity × support score; no "causal" wording. | C8, C18, C35 |
| FR-12 | Valuation bridge: operating profit paths → forward earnings using stated tax rate, net interest/other and diluted share count → value range using a multiple range; business and multiple uncertainty reported separately; unsupported cases documented. | MVP | Test with synthetic paths; non-positive earnings path returns `unsupported` with reason. | C21 |
| FR-13 | Illustrative actions hold/add/trim/exit for a labeled, editable demo position with explicit transaction, slippage and impact costs; decision rule, sizing and holding period fixed in configuration before scoring; no-action outcome included. | MVP | Config file with rule parameters is versioned; tests cover each action's cost arithmetic. | C22 |
| FR-14 | Benchmarks: S&P 500 total return (verified source or labeled approximation) and Visa buy-and-hold; metrics: excess return after costs, drawdown, exposure; labeled exploratory; sample size displayed. | MVP (conditional on DR-07) | Benchmark series carry source and method labels in the UI; no series labeled "S&P 500 total return" unless its derivation is documented. | C22 |
| FR-15 | Guidance comparison where metric and period match (labeled "company guidance"); consensus shown as "unavailable (no licensed free historical source)". | MVP | Guidance records include statement type `guidance`, source, date; UI never uses the word consensus for guidance. | C19, C20 |
| FR-16 | Evaluation report, model specification and failure case accessible in the UI and exported as Markdown/HTML in the package. | MVP | Files present in export; UI pages render them. | C33 |
| FR-17 | Immutable forecast archive: saved forecasts with origin, cutoff, target period, created time; prospective forecasts flagged and stored separately from retrospective reconstructions. | MVP | Archive entries cannot be edited via API; prospective entry for the Q4 FY2026 target exists before results are published. | C24 |
| FR-18 | Company-model boundary: observation, scenario, run and result formats are company-agnostic; Visa economics live in one company module with a declared interface. | MVP | A stub second company passes the interface tests without engine changes. | C34, C35 |

## 5. Model requirements

| ID | Requirement | Class | Acceptance | Trace |
| --- | --- | --- | --- | --- |
| MR-01 | State variables: nominal payments volume index (constant-dollar growth tracked alongside), cross-border volume excluding intra-Europe index, total cross-border (context/share), processed transactions index, effective yield per revenue category, incentive intensity, recurring opex baseline. Growth rates remain growth rates unless a level is supported by a disclosure. | MVP | State schema documented in the model specification; levels carry source links; indices documented as normalized. | C1, C6; review "First priority" |
| MR-02 | Transition order per quarter: sample common conditions (demand, travel, FX) → update activity → compute category revenue using the correct period → subtract incentives → subtract opex → operating profit. | MVP | Engine code mirrors the written rule list; a test walks one quarter by hand. | C4 |
| MR-03 | Service revenue in quarter t depends on payments volume in t−1; data processing on current processed transactions; international transaction on current cross-border ex-intra-Europe and a currency/yield factor; other revenue on a stated rule. | MVP | Lag test: shifting PV in t−1 changes service revenue in t, not t−1. Verified against the release language ("recognized based on payments volume in the prior quarter"). | C4, C5; Visa Q3 FY2024 release |
| MR-04 | Identities on every path and quarter: Σ category revenue − client incentives = net revenue; net revenue − operating expenses = operating profit; relative tolerance ≤ 1e-9. | MVP | Property test over random parameter sets and seeds. | C5 |
| MR-05 | No double counting: cross-border handled as a share/sub-index of payments volume; value-added services inform yields, not a fifth bucket; payments volume ÷ processed transactions is never labeled average purchase value. | MVP | Static checks in model spec; test that total spending is not increased by independently sampled cross-border shocks. | C6 |
| MR-06 | Yields are effective revenue per unit of activity with uncertainty; not contract fees; proposal teaching fees ($1/$3 per $100) are not inputs anywhere. | MVP | Grep test for teaching constants; spec language. | C30 |
| MR-07 | Preserve fiscal quarters (FY ends September 30), nominal vs constant-dollar, GAAP vs identified special items, geography, units; adjusted and GAAP never interchanged silently. | MVP | Each stored financial value carries basis fields; evaluation uses one declared basis per metric. | C5 |
| MR-08 | Monte Carlo with correlated shocks (shared demand factor, travel factor, FX factor), seeded, path-complete outputs, default n_paths ≥ 5,000 with Monte Carlo standard error reported. | MVP | Same seed → identical paths; SE displayed. | C7 |
| MR-09 | Six to eight free transition parameters with explicit ranges; alternative parameter combinations retained (ensemble weights) when several fit history; sensitivity analysis for yield and incentive assumptions. | MVP | Parameter count enforced in spec; ensemble weights saved with the run. | C3, C30 |
| MR-10 | Chronological calibration: fit at each origin using only observations with publication ≤ cutoff; later vintages excluded. | MVP | Leakage test fails if any input publication > cutoff. | C23, C29 |
| MR-11 | Mix-shift intervention conserves total spending by construction; "remove service lag" and "pool spending types" ablations are engine configuration changes with their own code paths, not display changes. | MVP | Tests for each ablation path. | C17, C27 |
| MR-12 | Qualitative evidence becomes a range with an assumption label only; LLM confidence is never used as an outcome probability. | MVP | Schema forbids probability fields derived from extractor confidence. | C3; review |

## 6. Data requirements

| ID | Requirement | Class | Acceptance | Trace |
| --- | --- | --- | --- | --- |
| DR-01 | Public/free sources only; keys requiring free registration are listed separately from paid products; no Longaeva or paid data in any dependency; each source has a license/terms note; files are redistributed in the package only where terms permit, otherwise fetched by script. | MVP | `docs/data-licenses.md` in the package lists every source with terms and redistribution decision. | C32, C36 |
| DR-02 | Visa primary sources: 8-K Item 2.02 earnings releases (Exhibit 99.1), 10-Q/10-K, XBRL `companyfacts` for standard tags; publication time = EDGAR acceptance timestamp; SEC fair-access rules (declared User-Agent, ≤10 requests/s) honored. | MVP | Collector tests; manifest covers FY2017–FY2026 releases. | C1; data plan §2 |
| DR-03 | External families: Booking Holdings earnings releases (travel platform) and Census MARTS advance releases (retail) required after their feasibility gates; one airline, one retailer and one payment processor disclosure family selected through a timeboxed gate; I-94 and BEA PCE reserve. Each family maps to a named driver and a named test. | MVP (gated) | Gate artifacts record pass/fail per family; failed families are documented, not silently dropped. | C2; data plan §3 |
| DR-04 | Vintage integrity: original release versions used; later revisions linked but excluded from earlier cutoffs; retrieval time never substituted for publication time; sources without recoverable publication vintage excluded from historical tests. | MVP | Tests on Census revision fixtures and on EDGAR timestamps. | C29, C31, C36 |
| DR-05 | Eligible origin: a Visa earnings-release acceptance timestamp for quarter q with a realized quarter q+1 outcome and all required inputs published ≤ cutoff. Inventory lists candidate origins, eligibility per input family, exclusions and reasons; the eligible count is reported, target ≥ 8. | MVP target | `origins.csv` and inventory note in the package; UI shows count and exclusions. | C23 |
| DR-06 | Calibration history: FY2017–FY2023 quarters (proposed) inventoried with the same vintage rules; FY2020–FY2021 flagged as pandemic-distorted with a documented treatment decision. | MVP | Calibration window and treatment recorded in the model specification. | C23 |
| DR-07 | Benchmark and price data: a license-compliant source for Visa daily prices and dividends and for S&P 500 total return (or a labeled approximation with method); terms reviewed; redistribution decision made before the package is built. | MVP (gate) | Decision artifact names the series, provider, terms and label text. | C22 |
| DR-08 | Duplicate statements (press release copied to 10-Q, re-published transcripts) count once as evidence; duplicates are linked. | MVP | Dedup by normalized passage hash; test fixture. | C31 |
| DR-09 | Curated source manifest, no general crawler; polite rate limits; caching of originals; no bypass of access controls (e.g., JS challenges, 403s) — such sources are marked unavailable for automation. | MVP | Manifest file; collector logs; Stooq/TSA documented as unavailable for automated access. | Prompt constraints |

## 7. Evaluation requirements

| ID | Requirement | Class | Acceptance | Trace |
| --- | --- | --- | --- | --- |
| ER-01 | Accounting identity tests on every path (MR-04, MR-05). | MVP | pytest green. | C5, C6 |
| ER-02 | Source/date/unit correctness tests: each ingested starting state reconciles to its original exhibit (values, periods, units) for at least two historical cutoffs. | MVP | Reconciliation fixtures pass. | C1 |
| ER-03 | Replay exactness: saved run reproduces output hash with no LLM; divergences explained by recorded library versions. | MVP | Replay test. | C14 |
| ER-04 | Historical cutoff guard: any input with publication > cutoff raises; test corpus includes deliberately late documents. | MVP | Leakage tests. | C29, C36 |
| ER-05 | Forecast errors (absolute and percentage) for next-quarter net revenue, operating profit (declared basis) and drivers (payments volume growth, cross-border ex-intra-Europe growth, processed transactions growth) across eligible origins. | MVP | Report table per origin and aggregate. | C26 |
| ER-06 | 80% predictive interval coverage and CRPS or weighted interval score for net revenue and operating profit; computed from path distributions. | MVP | Scores in report; coverage count displayed with n. | C26 |
| ER-07 | Baselines with matched inputs, horizon and scoring: (a) seasonal/trend; (b) financial-only driver model; (c) LLM forecast given the same dated documents; plus company guidance where comparable, with a prior-data-only residual distribution to make point guidance comparable. | MVP | Each baseline has a config and a result row per origin. | C19, C25 |
| ER-08 | Ablations rebuild model inputs and rerun across all eligible origins: (a) remove external commentary; (b) pool spending types into one growth driver; (c) remove service-revenue lag. Persistence of gains across origins and parameter ranges is reported. | MVP | Three result sets with the same origins as the full model. | C9, C27 |
| ER-09 | Extraction-error sample: ≥ 40 manually labeled items covering numeric facts, qualitative statements, contradictions, period/unit/scope edge cases; error rates reported separately from model errors. | MVP | Labeled file and scoring script in the package. | C28 |
| ER-10 | Retrospective reconstructions and prospective forecasts stored and reported separately; hindsight and pretrained-model limitations stated in the report. | MVP | Report sections; archive flag. | C24, C29 |
| ER-11 | Portfolio scoring: fixed long/cash (hold/add/trim/exit) rule, entry at the first eligible session after the cutoff, fixed holding period, explicit round-trip costs, dividends handled, overlapping forecasts handled; excess return vs the benchmark in FR-14 and vs Visa buy-and-hold; drawdown and exposure; no claim of risk-adjusted alpha. | MVP (conditional on DR-07) | Rule config frozen (hash recorded) before the scoring run; report labels results exploratory. | C22 |
| ER-12 | Failure case: at least one origin or scenario where the model performed poorly or an extraction error mattered, documented with observable invalidating conditions. | MVP | Section in report and UI. | C33 |
| ER-13 | Four-quarter scenario scoring kept separate from next-quarter scoring because fewer completed outcomes exist. | MVP | Separate table with its own n. | review "Fourth priority" |

## 8. Packaging and standalone requirements

| ID | Requirement | Class | Acceptance | Trace |
| --- | --- | --- | --- | --- |
| PR-01 | Self-contained project directory with its own frontend, backend, dependency manifests and locks, configuration (`.env.example`), database initialization (migrations), artifact storage, tests and startup documentation. | MVP | Directory tree matches the implementation plan; `README` quickstart verified. | User decision |
| PR-02 | No parent-repository imports, external symlinks, developer-specific absolute paths, or dependencies on Talisman services, database, authentication, portfolio state, cloud accounts or deployment settings; an automated guard test enforces this. | MVP | Guard test passes in the exported copy. | User decision |
| PR-03 | PostgreSQL/SQLAlchemy architecture preserved via bundled Docker Compose (database, API, worker, web) with Alembic migrations; one documented startup command; health endpoint. | MVP | `docker compose up` from the export reaches healthy state; migrations apply on empty database. | C10, C15 |
| PR-04 | Permitted demo inputs and saved forecasts bundled so UF-01, UF-03, UF-05 and UF-06 work without LLM credentials; demo data loaded by the startup command or a documented seed command. | MVP | Fresh install → demo flows pass without `LLM_PROVIDER`. | C33 |
| PR-05 | Provider configuration for fresh extraction and the LLM baseline documented separately; absent configuration degrades gracefully. | MVP | Setup doc section; UI notice. | C2, C25 |
| PR-06 | Export validation twice: after the first vertical slice and against the final ZIP/fresh checkout, each in a temporary directory outside Talisman: startup, scenario execution, saved-run replay, guard test, test suite. | MVP | Validation log saved in the planning directory (not the package). | User decision |
| PR-07 | Export excludes secrets, personal data, unrelated files and Talisman Git history; exclusion manifest and secret scan run before packaging. | MVP | Scan report clean; no `.git` from Talisman in the ZIP. | User decision; certification item 8 |
| PR-08 | Reused Talisman components are copied/adapted into the package with a short provenance note (origin file, adaptations); no runtime import from Talisman. | MVP | `docs/reuse-notes.md` in the package. | approach v2 |

## 9. Non-functional requirements

| ID | Requirement | Class | Acceptance |
| --- | --- | --- | --- |
| NR-01 | CPU-only numerics; a 4-quarter run with 5,000 paths completes in ≤ 60 s on a laptop (target, measured and reported). | MVP | Timing recorded in the implementation log. |
| NR-02 | Model calls are bounded and cached; a full extraction pass over the curated corpus is budgeted and logged; no unbounded loops. | MVP | Call counts in logs; cache hit rate shown. |
| NR-03 | Test suite deterministic; runs in the clean exported environment; backend and frontend lint/type checks pass. | MVP | CI-style script `make check` passes in the export. |
| NR-04 | Job status, errors and durations logged; failed jobs visible in the UI. | MVP | Failed job fixture shows in status endpoint. |
| NR-05 | No authentication for local use; the README states this and that the package is for local review, not hosting. | MVP | README statement. |
| NR-06 | Documentation set: README quickstart, model specification, data licenses, evaluation report, limitations, demo script, reuse notes. | MVP | Files present and linked from README. |

## 10. Stretch (visibly separate; not in the MVP issue set)

| ID | Requirement | Reason it is stretch |
| --- | --- | --- |
| SR-01 | Second company (Mastercard) through the FR-18 boundary. | Proposal p. 6 expansion; separate definitions and validation. |
| SR-02 | Reserve corroborators: I-94 arrivals, BEA PCE expenditure tables, TSA, BTS. | Approach v2 reserve; automated access unverified (TSA 403, BTS timeout). |
| SR-03 | Optional Talisman integration (embedding the standalone app as a route). | Depends on the package, never the reverse. |
| SR-04 | Cloud hosting (Cloud Run/Cloud SQL/Cloud Storage). | Conditional on submission rules, unresolved. |
| SR-05 | Census e-commerce share as a second Census integration. | Approach v2 "later candidate". |
| SR-06 | Broader source discovery beyond the selected families. | Breadth after evaluation (review "Fourth priority"). |

## 11. Non-goals

- Model training, trading execution, market-of-agents simulation, cash-flow/DCF valuation (the existing Talisman DCF needs 5–8 annual projections; the earnings/multiple bridge is used instead).
- Claims of causal proof from observational documents; claims of forecast improvement, eight eligible cases or alpha before measurement.
- Relabeling guidance as consensus or any substitute benchmark as "S&P 500 total return" without a documented derivation.
- Bypassing access controls, scraping sites that block automation, or using Longaeva/paid data.

## 12. Traceability to recap

- "Alternative Data Use in Company Evaluation" and "Sector-Specific Alternative Data Examples": motivate travel and retail demand proxies (DR-03), not mandatory feeds.
- "Data Analysis Tools and Project Scoping": judging emphasizes data use and framework repeatability (FR-18, NR-03, ER-*); scope tightly defined (DR-03 gates; SR-* separated).
- "Communication and Project Management": October 9 Stage 2 deadline (user confirmed 2026); submission format still unconfirmed.
