# Longaeva planning — planning v1

October 1, 2026 · Phase 2 drafts for review · Approach reference: [approach.md](approach.md) (v2, approved October 1, 2026). This revision supersedes nothing in `approach.md`; it adds the detailed planning artifacts the approach authorized.

| Artifact | Purpose |
| --- | --- |
| [requirements.md](requirements.md) | Product statement, commitment map (C1–C36), user flows, functional/model/data/evaluation/packaging/non-functional requirements with IDs and acceptance criteria, stretch, non-goals, traceability |
| [data-plan.md](data-plan.md) | Shortlisted sources with verification evidence from October 1 checks, Visa definitions to settle, cutoff convention, preliminary origin inventory, mappings and tests per family, benchmark decision chain, exclusions, licensing policy, feasibility gates |
| [implementation-plan.md](implementation-plan.md) | Standalone architecture and directory, core records, engine design, reuse/adapt/new map with Talisman touchpoints, milestones Oct 1–9, dependencies and critical path, effort, evaluation plan, demo/submission plan, risks |
| [linear-backlog.md](linear-backlog.md) | 39 MVP issue drafts (DRAFT-01…39) and 6 stretch drafts (DRAFT-S1…S6) with outcome, scope, exclusions, requirement IDs, touchpoints, acceptance, validation, dependencies, priority, effort, inputs; coverage matrix; duplicate/cycle check |

Status: no application code, dependencies, repository, export, commit, push, deployment or Linear write has been created or changed. Only the four files above were created; `approach.md`, the proposal, review and prompt documents are unchanged.

## Current assessment

- **Scope is the full submitted proposal** for one company (Visa), delivered as a self-contained `longaeva/` package exportable as a ZIP or fresh repository, with PostgreSQL/SQLAlchemy preserved through Docker Compose. Valuation, illustrative actions with costs, benchmarks, the eight-forecast target, all three baselines, all three ablations, extraction review, uncertainty scoring and prospective separation remain in scope (requirements §2).
- **Feasibility evidence gathered today** (data plan §1): Visa and Booking earnings releases have exact EDGAR acceptance timestamps back to 2015; the Visa release text confirms the service-revenue lag and reports drivers as constant-dollar and nominal growth; Census archived advance-release PDFs make retail vintages recoverable; SEC XBRL `companyfacts` provides vintage-dated standard financials without a key. Ten retrospective origin candidates exist in FY2024–FY2026 plus eight in FY2022–FY2023 and one prospective origin (2026-07-28 → Q4 FY2026). Eligibility is not yet audited; eight remains a target.
- **Open feasibility items:** a license-compliant free daily total-return series for the S&P 500 and Visa (Stooq blocks automation; S&P DJI and TSA return 403; FRED is price-only; Ken French is total-market, not S&P 500); historical availability of Visa outlook PDFs; parsing of 2015–2019 release formats; whether Booking's 10–12-week staleness leaves any measurable signal.
- **Linear:** the MCP connection requires authentication; no reads were possible. The backlog is complete locally.
- **Effort:** itemized MVP total 168–263 hours (backlog summary), above approach v2's area-level 110–186. Over eight calendar days this is a scheduling risk that may require decisions; it is not a scope cut.

## Recommended scope and sequence

Approve the 39 MVP drafts as the issue set. Run gates (DRAFT-01…08) and bootstrap (09–13) in parallel on October 1–2; land the first vertical slice and the early export rehearsal by October 4 (DRAFT-12); evidence/model/evaluation core by October 6; completion October 7; report and final export October 8; October 9 buffer. Stretch drafts stay out of the approved set.

## Major decisions recorded in planning v1

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-01 | Standalone `longaeva/` package; Talisman components copied/adapted, never imported | User requirement; avoids app coupling (approach v2) | Confirmed by user |
| D-02 | Keep PostgreSQL/SQLAlchemy via bundled Compose with Alembic; local artifact storage replaces object storage; single Postgres-backed worker | Preserves proposal architecture independently | Proposed |
| D-03 | Cutoff for origin q = Visa earnings-release acceptance timestamp; each document enters on its own timestamp; first eligible session = next trading day | Consistent across origins; verifiable (data plan §2.3) | Proposed; alternative recorded |
| D-04 | Primary evaluation window FY2024Q1–FY2026Q2 origins; extend to FY2022 if needed; calibration FY2017–FY2023 (minimum FY2019–FY2023); pandemic quarters flagged with treatment decided in DRAFT-21 | Balances parsing effort against history (data plan §2.4) | Proposed |
| D-05 | Scoring basis: GAAP net revenue; operating profit excluding identified special items as primary with GAAP also reported; nominal activity indices with constant-dollar growth retained as evidence | Release structure supports it; confirmed in DRAFT-02 | Proposed |
| D-06 | Guidance labeled "company guidance"; historical consensus reported unavailable | No free licensed source | Proposed (blocked commitment C20) |
| D-07 | Benchmark via the option chain in data plan §4; labeled approximation if no verified S&P 500 TR source; Visa dividends from SEC filings; non-redistributable data fetched by script, never bundled | Certification/licensing constraints | Gate DRAFT-06 |
| D-08 | Two export validations in a temp directory outside Talisman (after first slice, and final ZIP), with guard tests for parent imports, symlinks, absolute paths, secrets and personal data | User requirement | Proposed |
| D-09 | Second-wave families (one airline, one retailer, one processor) selected through a timeboxed gate; I-94/BEA/TSA/BTS reserve (stretch) | Proposal names those families; reserve sources unverified or blocked for automation | Proposed |
| D-10 | Illustrative decision rule, holding period and costs fixed in versioned config with a recorded hash before scoring | Proposal p. 5 | Proposed; defaults recommended inside DRAFT-26 |
| D-11 | Planning artifacts live under `docs/hackathon/planning/`; validation logs under `docs/hackathon/planning/validation/`; nothing committed in this phase despite `.cursor/rules` (cloud-agent branch policy) | User instruction governs | Applied |

## Open questions and unresolved decisions

1. **Deadline time and timezone** for October 9, 2026, and the organizer's **submission format** (ZIP, repository link, hosted URL, video/slides). Affects DRAFT-38 and whether SR-04 hosting is needed.
2. **Linear destination** (team/project) and authentication for the Linear MCP connection before any Phase 3 import.
3. **Free API key registration:** willingness to register a free EOD data key (Tiingo/Alpha Vantage) for benchmark option A; otherwise option B applies (data plan §4).
4. **LLM provider and key** for fresh extraction and the LLM baseline (tests run with a stub; real baseline rows need a key).
5. **Pandemic-quarter treatment** in calibration (recommendation to be made in DRAFT-21).
6. **Default cost and rule parameters** for illustrative actions (recommendation inside DRAFT-26).
7. **Task ownership/calendar allocation** across people and agents, given 168–263 itemized hours in eight days.

## Assumptions

- Today is October 1, 2026 (America/New_York); deadline October 9, 2026 confirmed by the user.
- Public/free data only; keys needing free registration are permissible but flagged; no paid or Longaeva data.
- Experienced builders plus coding agents on bounded issues; curated corpus of tens of documents per family; CPU-only numerics; local containers.
- The submitted PDF proposal is authoritative; the Markdown copy matched it in Phase 1.
- Historical consensus remains unavailable; guidance is a separate, labeled comparison.
- No forecast improvement, eight eligible cases or investment alpha is promised before measurement.

## Verification performed in this phase (October 1, 2026)

- Repository state: branch `main`, commit `2bc76f6c90c24339267d5128d03141dc7345aaa2`; untracked `docs/hackathon/` and `talisman_resume_facts.md`; no tracked modifications. Unchanged by this phase except the four new planning files.
- Read: approach v2, planning prompt, Markdown proposal, prior review, recap; extracted text and links from the dataset catalog (17 pp.), the hackathon rules page PDF (7 pp.), the participant certification (2 pp.) and the proposal PDF (6 pp.) into `/tmp` (not retained in the repository).
- Read-only HTTP checks: SEC EDGAR submissions JSON (Visa, Booking), one Visa 8-K index and release exhibit (Q3 FY2024), SEC XBRL companyfacts/companyconcept; Census historic releases page and file HEADs; FRED, Ken French, Shiller downloads (headers/first bytes only); Stooq, S&P DJI, SSGA, Nasdaq API, Alpha Vantage, Tiingo, investor.visa.com, TSA, BTS, I-94 page availability.
- Talisman inspection: dependency manifests, `Dockerfile`, `migrations/env.py`, `frontend/package.json`, `TimeSeriesChart.tsx`, `ChartTile.tsx`, `EvidenceLedgerPanel.tsx` header, `scenario_simulator.py` lines 357–518, ontology module listing, test directory listing.
- Not run: application tests, app startup, bulk ingestion, API-key registration, Linear access, any write outside the planning directory.

## Approval request

Reply to approve **planning v1** and its **39-draft MVP issue set (DRAFT-01…DRAFT-39)**, or request revisions. Phase 3 (Linear creation) additionally needs the Linear team/project and an authenticated connection; a suitable reply is "Approve planning v1; create its MVP issues in [team/project]". Approval of these documents does not authorize implementation, which is a separate later request.
