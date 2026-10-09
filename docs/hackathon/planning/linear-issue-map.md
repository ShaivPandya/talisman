# Longaeva Linear issue map

Approved revision: **planning v1** (approved October 1, 2026). Approved issue set: **DRAFT-01…DRAFT-39** (39 MVP drafts in [linear-backlog.md](linear-backlog.md)). Stretch drafts DRAFT-S1…S6 are not approved for import.

## Destination (resolved October 1, 2026, ~1:20 PM ET)

The user created both records in the Linear UI; no team, project, label or milestone was created by the import.

- Workspace: `twinleaf`
- Team: **Longaeva**, key `LON`, id `bdcad4b4-d4f5-455a-b56f-d0f9b37a7300` (empty before import)
- Project: **Hackathon**, `P-LON-2`, https://linear.app/twinleaf/project/hackathon-cee7d5563630 (no issues or milestones before import)
- Field mapping: plan P0 → High (2), P1 → Medium (3), P2 → Low (4), as chosen by the user. Status is Backlog. No labels, milestone, cycle, assignee or estimate is set; the hour ranges stay in the issue body because they don't fit a Linear point scale.

## Import status

**Complete (October 1, 2026, issues created ~1:17–1:27 PM ET, verified ~1:30 PM ET).** 39 of 39 approved issues created (LON-1…LON-39); 81 of 81 "blocked by" relations created and verified. 0 failures, 0 duplicates, 0 stretch drafts imported, 0 pre-existing issues modified.

Verification method: `list_issues` on the Longaeva team returned exactly 39 issues, all in project Hackathon, status Backlog, no labels, with titles and priorities matching the plan. `get_issue` with relations on every issue returned "blocked by" sets identical to the plan (no missing, extra, related or duplicate relations).

Earlier pre-import check, kept for the record: **Not started: blocked on the destination. 0 issues created, 0 dependency links created.**

| Check (October 1, 2026, ~1:15 PM ET) | Result |
| --- | --- |
| Linear connection | Authenticated; workspace `twinleaf` (https://linear.app/twinleaf). Issue writes and `blockedBy` relations are supported by the available tools. |
| Requested team "Longaeva" | Does not exist. The only team is Twinleaf (key `TL`, id `d19f4378-b345-488b-89ba-b376f0a371d8`). The Linear tools available here have no team-creation operation. |
| Requested project "hackathon" | Does not exist. The only project is Talisman (`P-TL-1`). A project-creation tool exists, but the authorization also says "Do not create a project", so no project was created. |
| Prior import / duplicates | No earlier `linear-issue-map.md`. Searches for "Longaeva", "Visa" and "DRAFT-", plus issues created in the last day, found no matching issues. The only "DRAFT-" text match is TL-84 (an unrelated Talisman agent-model issue), which was left unchanged. |
| Writes performed | None in Linear. This file is the only local change. |

## Work order (step numbers in titles)

Linear can't renumber issues, so every title starts with its step number: `01 · …` to `39 · …`. Work the issues in step order. Sort by title in Linear to see this order. The LON numbers stay as they are. They only show creation order.

How the order was built:

1. Group by milestone first: M0 to M4 in `implementation-plan.md` §3.
2. Within a milestone, put P0 before P1 and P2.
3. Among issues with equal priority, put first the issue with the longest effort-weighted dependency chain to the end of the backlog.

LON-1 is step 01 because it was already in progress. Every issue comes after all of its blockers.

Changing the titles also changed Linear's suggested branch names, for example `shaiv/lon-9-02-standalone-backend-skeleton-…`. Links from Git still match on the `LON-n` identifier. Applied and checked October 1, 2026 (~1:42 PM ET): all 39 live titles match this table. Only the titles changed. Status, priority, relations and descriptions are unchanged.

| Step | Linear | Draft | Milestone | Plan priority |
| --- | --- | --- | --- | --- |
| 01 | [LON-1](https://linear.app/twinleaf/issue/LON-1/visa-eligible-origin-and-vintage-inventory) | DRAFT-01 | M0 | P0 |
| 02 | [LON-9](https://linear.app/twinleaf/issue/LON-9/standalone-backend-skeleton-with-compose-postgres-alembic-and-worker) | DRAFT-09 | M0 | P0 |
| 03 | [LON-10](https://linear.app/twinleaf/issue/LON-10/core-schema-migrations-artifact-storage-and-api-contracts) | DRAFT-11 | M0 | P0 |
| 04 | [LON-2](https://linear.app/twinleaf/issue/LON-2/visa-driver-and-accounting-definitions-decision) | DRAFT-02 | M0 | P0 |
| 05 | [LON-3](https://linear.app/twinleaf/issue/LON-3/reconstruct-two-historical-starting-states-from-original-exhibits) | DRAFT-03 | M0 | P0 |
| 06 | [LON-5](https://linear.app/twinleaf/issue/LON-5/census-marts-vintage-gate) | DRAFT-05 | M0 | P0 |
| 07 | [LON-4](https://linear.app/twinleaf/issue/LON-4/booking-holdings-family-gate) | DRAFT-04 | M0 | P0 |
| 08 | [LON-6](https://linear.app/twinleaf/issue/LON-6/benchmark-and-price-data-decision) | DRAFT-06 | M0 | P0 |
| 09 | [LON-12](https://linear.app/twinleaf/issue/LON-12/isolation-guard-tests-and-exclusion-manifest) | DRAFT-13 | M0 | P0 |
| 10 | [LON-7](https://linear.app/twinleaf/issue/LON-7/guidance-availability-and-consensus-confirmation) | DRAFT-07 | M0 | P1 |
| 11 | [LON-8](https://linear.app/twinleaf/issue/LON-8/second-wave-disclosure-families-selection-airline-retailer-payment) | DRAFT-08 | M0 | P1 |
| 12 | [LON-13](https://linear.app/twinleaf/issue/LON-13/manifest-driven-collector-with-caching-hashing-and-timestamps) | DRAFT-14 | M1 | P0 |
| 13 | [LON-19](https://linear.app/twinleaf/issue/LON-19/visa-quarterly-engine-core-with-identities-and-seeded-correlated-monte) | DRAFT-20 | M1 | P0 |
| 14 | [LON-14](https://linear.app/twinleaf/issue/LON-14/visa-release-and-10-q-structured-table-parser) | DRAFT-15 | M1 | P0 |
| 15 | [LON-23](https://linear.app/twinleaf/issue/LON-23/run-persistence-worker-execution-and-replay-without-llm) | DRAFT-24 | M1 | P0 |
| 16 | [LON-11](https://linear.app/twinleaf/issue/LON-11/frontend-shell-with-adapted-chart-components-and-a-minimal-run-page) | DRAFT-10 | M1 | P0 |
| 17 | [LON-24](https://linear.app/twinleaf/issue/LON-24/early-export-rehearsal-outside-talisman) | DRAFT-12 | M1 | P0 |
| 18 | [LON-20](https://linear.app/twinleaf/issue/LON-20/parameter-ranges-chronological-calibration-and-ensemble-weighting) | DRAFT-21 | M2 | P0 |
| 19 | [LON-27](https://linear.app/twinleaf/issue/LON-27/evaluation-harness-origins-loop-leakage-guard-errors-coverage-and) | DRAFT-28 | M2 | P0 |
| 20 | [LON-16](https://linear.app/twinleaf/issue/LON-16/llm-structured-extraction-with-pydantic-schemas-caching-and-review) | DRAFT-17 | M2 | P0 |
| 21 | [LON-22](https://linear.app/twinleaf/issue/LON-22/paired-scenarios-interventions-and-attribution) | DRAFT-23 | M2 | P0 |
| 22 | [LON-21](https://linear.app/twinleaf/issue/LON-21/mapping-rule-registry-and-observation-to-parameter-review) | DRAFT-22 | M2 | P0 |
| 23 | [LON-29](https://linear.app/twinleaf/issue/LON-29/baselines-seasonaltrend-financial-only-driver-model-guidance) | DRAFT-29 | M2 | P0 |
| 24 | [LON-25](https://linear.app/twinleaf/issue/LON-25/earningsmultiple-valuation-bridge) | DRAFT-25 | M2 | P1 |
| 25 | [LON-26](https://linear.app/twinleaf/issue/LON-26/illustrative-actions-with-explicit-costs-and-a-predefined-decision) | DRAFT-26 | M2 | P1 |
| 26 | [LON-17](https://linear.app/twinleaf/issue/LON-17/full-text-search-filtered-by-company-period-and-publication-cutoff) | DRAFT-18 | M2 | P1 |
| 27 | [LON-15](https://linear.app/twinleaf/issue/LON-15/census-marts-archived-release-parser-and-vintage-series) | DRAFT-16 | M2 | P1 |
| 28 | [LON-34](https://linear.app/twinleaf/issue/LON-34/scenario-workspace-state-controls-runs-fan-charts-paired-comparison) | DRAFT-34 | M3 | P0 |
| 29 | [LON-31](https://linear.app/twinleaf/issue/LON-31/three-ablations-rebuilt-and-rerun-across-origins) | DRAFT-31 | M3 | P0 |
| 30 | [LON-28](https://linear.app/twinleaf/issue/LON-28/benchmarkprice-ingestion-and-exploratory-portfolio-scoring) | DRAFT-27 | M3 | P1 |
| 31 | [LON-35](https://linear.app/twinleaf/issue/LON-35/evidence-and-review-ui-with-passage-spans-decisions-and-search) | DRAFT-35 | M3 | P1 |
| 32 | [LON-36](https://linear.app/twinleaf/issue/LON-36/valuation-actions-evaluation-and-replay-pages) | DRAFT-36 | M3 | P1 |
| 33 | [LON-18](https://linear.app/twinleaf/issue/LON-18/extraction-evaluation-set-and-scoring) | DRAFT-19 | M3 | P1 |
| 34 | [LON-30](https://linear.app/twinleaf/issue/LON-30/llm-same-document-forecast-baseline) | DRAFT-30 | M3 | P1 |
| 35 | [LON-32](https://linear.app/twinleaf/issue/LON-32/register-the-prospective-q4-fy2026-forecast) | DRAFT-32 | M3 | P1 |
| 36 | [LON-33](https://linear.app/twinleaf/issue/LON-33/evaluation-report-model-specification-and-failure-case) | DRAFT-33 | M4 | P0 |
| 37 | [LON-37](https://linear.app/twinleaf/issue/LON-37/demo-dataset-saved-runs-and-seed-command) | DRAFT-37 | M4 | P0 |
| 38 | [LON-38](https://linear.app/twinleaf/issue/LON-38/final-export-clean-environment-validation-and-submission-docs) | DRAFT-38 | M4 | P0 |
| 39 | [LON-39](https://linear.app/twinleaf/issue/LON-39/demo-rehearsal-and-presentation-notes) | DRAFT-39 | M4 | P2 |

## Import order and issue table

Creation order followed dependencies, so every blocker existed before its dependents:
01, 02, 03, 04, 05, 06, 07, 08, 09, 11, 10, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 12, 25, 26, 28, 27, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39.

Linear numbers follow that order, so LON-n is the n-th draft created. They match the draft numbers for DRAFT-01…09, 25, 26 and 29…39, and differ for DRAFT-10…24, 27 and 28 (for example DRAFT-11 is LON-10, DRAFT-10 is LON-11, DRAFT-12 is LON-24, DRAFT-28 is LON-27). Use the table below rather than assuming the numbers line up.

The backlog has 81 "blocked by" edges, and they form an acyclic graph. Each issue body contains a header line (plan ID, revision), a shared context paragraph, and the full draft text: outcome, question/timebox where present, scope and exclusions, requirement IDs, package touchpoints, acceptance criteria, validation, dependencies (draft ID plus Linear ID), priority, effort and inputs. Hour-range effort stays in the body; no Linear estimate was set.

| Draft | Title | Blocked by (drafts) | Plan priority | Linear ID | URL | Created | Links |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DRAFT-01 | Visa eligible-origin and vintage inventory | — | P0 | LON-1 | [LON-1](https://linear.app/twinleaf/issue/LON-1/visa-eligible-origin-and-vintage-inventory) | yes | verified: none (no blockers) |
| DRAFT-02 | Visa driver and accounting definitions decision | — | P0 | LON-2 | [LON-2](https://linear.app/twinleaf/issue/LON-2/visa-driver-and-accounting-definitions-decision) | yes | verified: none (no blockers) |
| DRAFT-03 | Reconstruct two historical starting states from original exhibits | 01, 02 | P0 | LON-3 | [LON-3](https://linear.app/twinleaf/issue/LON-3/reconstruct-two-historical-starting-states-from-original-exhibits) | yes | verified: LON-1, LON-2 |
| DRAFT-04 | Booking Holdings family gate | — | P0 | LON-4 | [LON-4](https://linear.app/twinleaf/issue/LON-4/booking-holdings-family-gate) | yes | verified: none (no blockers) |
| DRAFT-05 | Census MARTS vintage gate | — | P0 | LON-5 | [LON-5](https://linear.app/twinleaf/issue/LON-5/census-marts-vintage-gate) | yes | verified: none (no blockers) |
| DRAFT-06 | Benchmark and price data decision | — | P0 | LON-6 | [LON-6](https://linear.app/twinleaf/issue/LON-6/benchmark-and-price-data-decision) | yes | verified: none (no blockers) |
| DRAFT-07 | Guidance availability and consensus confirmation | — | P1 | LON-7 | [LON-7](https://linear.app/twinleaf/issue/LON-7/guidance-availability-and-consensus-confirmation) | yes | verified: none (no blockers) |
| DRAFT-08 | Second-wave disclosure families selection (airline, retailer, payment processor) | 02 | P1 | LON-8 | [LON-8](https://linear.app/twinleaf/issue/LON-8/second-wave-disclosure-families-selection-airline-retailer-payment) | yes | verified: LON-2 |
| DRAFT-09 | Standalone backend skeleton with Compose, Postgres, Alembic and worker | — | P0 | LON-9 | [LON-9](https://linear.app/twinleaf/issue/LON-9/standalone-backend-skeleton-with-compose-postgres-alembic-and-worker) | yes | verified: none (no blockers) |
| DRAFT-10 | Frontend shell with adapted chart components and a minimal run page | 09, 11 | P0 | LON-11 | [LON-11](https://linear.app/twinleaf/issue/LON-11/frontend-shell-with-adapted-chart-components-and-a-minimal-run-page) | yes | verified: LON-9, LON-10 |
| DRAFT-11 | Core schema, migrations, artifact storage and API contracts | 09 | P0 | LON-10 | [LON-10](https://linear.app/twinleaf/issue/LON-10/core-schema-migrations-artifact-storage-and-api-contracts) | yes | verified: LON-9 |
| DRAFT-12 | Early export rehearsal outside Talisman | 10, 13, 14, 15, 20, 24 | P0 | LON-24 | [LON-24](https://linear.app/twinleaf/issue/LON-24/early-export-rehearsal-outside-talisman) | yes | verified: LON-11, LON-12, LON-13, LON-14, LON-19, LON-23 |
| DRAFT-13 | Isolation guard tests and exclusion manifest | 09 | P0 | LON-12 | [LON-12](https://linear.app/twinleaf/issue/LON-12/isolation-guard-tests-and-exclusion-manifest) | yes | verified: LON-9 |
| DRAFT-14 | Manifest-driven collector with caching, hashing and timestamps | 11 | P0 | LON-13 | [LON-13](https://linear.app/twinleaf/issue/LON-13/manifest-driven-collector-with-caching-hashing-and-timestamps) | yes | verified: LON-10 |
| DRAFT-15 | Visa release and 10-Q structured table parser | 02, 14 | P0 | LON-14 | [LON-14](https://linear.app/twinleaf/issue/LON-14/visa-release-and-10-q-structured-table-parser) | yes | verified: LON-2, LON-13 |
| DRAFT-16 | Census MARTS archived-release parser and vintage series | 05, 14 | P1 | LON-15 | [LON-15](https://linear.app/twinleaf/issue/LON-15/census-marts-archived-release-parser-and-vintage-series) | yes | verified: LON-5, LON-13 |
| DRAFT-17 | LLM structured extraction with Pydantic schemas, caching and review persistence | 11, 14 | P0 | LON-16 | [LON-16](https://linear.app/twinleaf/issue/LON-16/llm-structured-extraction-with-pydantic-schemas-caching-and-review) | yes | verified: LON-10, LON-13 |
| DRAFT-18 | Full-text search filtered by company, period and publication cutoff | 11, 14 | P1 | LON-17 | [LON-17](https://linear.app/twinleaf/issue/LON-17/full-text-search-filtered-by-company-period-and-publication-cutoff) | yes | verified: LON-10, LON-13 |
| DRAFT-19 | Extraction evaluation set and scoring | 17 | P1 | LON-18 | [LON-18](https://linear.app/twinleaf/issue/LON-18/extraction-evaluation-set-and-scoring) | yes | verified: LON-16 |
| DRAFT-20 | Visa quarterly engine core with identities and seeded correlated Monte Carlo | 02 | P0 | LON-19 | [LON-19](https://linear.app/twinleaf/issue/LON-19/visa-quarterly-engine-core-with-identities-and-seeded-correlated-monte) | yes | verified: LON-2 |
| DRAFT-21 | Parameter ranges, chronological calibration and ensemble weighting | 03, 15, 20 | P0 | LON-20 | [LON-20](https://linear.app/twinleaf/issue/LON-20/parameter-ranges-chronological-calibration-and-ensemble-weighting) | yes | verified: LON-3, LON-14, LON-19 |
| DRAFT-22 | Mapping-rule registry and observation-to-parameter review | 04, 05, 11, 20 | P0 | LON-21 | [LON-21](https://linear.app/twinleaf/issue/LON-21/mapping-rule-registry-and-observation-to-parameter-review) | yes | verified: LON-4, LON-5, LON-10, LON-19 |
| DRAFT-23 | Paired scenarios, interventions and attribution | 20 | P0 | LON-22 | [LON-22](https://linear.app/twinleaf/issue/LON-22/paired-scenarios-interventions-and-attribution) | yes | verified: LON-19 |
| DRAFT-24 | Run persistence, worker execution and replay without LLM | 11, 20 | P0 | LON-23 | [LON-23](https://linear.app/twinleaf/issue/LON-23/run-persistence-worker-execution-and-replay-without-llm) | yes | verified: LON-10, LON-19 |
| DRAFT-25 | Earnings/multiple valuation bridge | 02, 20 | P1 | LON-25 | [LON-25](https://linear.app/twinleaf/issue/LON-25/earningsmultiple-valuation-bridge) | yes | verified: LON-2, LON-19 |
| DRAFT-26 | Illustrative actions with explicit costs and a predefined decision rule | 25 | P1 | LON-26 | [LON-26](https://linear.app/twinleaf/issue/LON-26/illustrative-actions-with-explicit-costs-and-a-predefined-decision) | yes | verified: LON-25 |
| DRAFT-27 | Benchmark/price ingestion and exploratory portfolio scoring | 06, 26, 28 | P1 | LON-28 | [LON-28](https://linear.app/twinleaf/issue/LON-28/benchmarkprice-ingestion-and-exploratory-portfolio-scoring) | yes | verified: LON-6, LON-26, LON-27 |
| DRAFT-28 | Evaluation harness: origins loop, leakage guard, errors, coverage and scoring | 01, 21, 24 | P0 | LON-27 | [LON-27](https://linear.app/twinleaf/issue/LON-27/evaluation-harness-origins-loop-leakage-guard-errors-coverage-and) | yes | verified: LON-1, LON-20, LON-23 |
| DRAFT-29 | Baselines: seasonal/trend, financial-only driver model, guidance comparison | 07, 28 | P0 | LON-29 | [LON-29](https://linear.app/twinleaf/issue/LON-29/baselines-seasonaltrend-financial-only-driver-model-guidance) | yes | verified: LON-7, LON-27 |
| DRAFT-30 | LLM same-document forecast baseline | 17, 28 | P1 | LON-30 | [LON-30](https://linear.app/twinleaf/issue/LON-30/llm-same-document-forecast-baseline) | yes | verified: LON-16, LON-27 |
| DRAFT-31 | Three ablations rebuilt and rerun across origins | 22, 28 | P0 | LON-31 | [LON-31](https://linear.app/twinleaf/issue/LON-31/three-ablations-rebuilt-and-rerun-across-origins) | yes | verified: LON-21, LON-27 |
| DRAFT-32 | Register the prospective Q4 FY2026 forecast | 21, 22, 24 | P1 | LON-32 | [LON-32](https://linear.app/twinleaf/issue/LON-32/register-the-prospective-q4-fy2026-forecast) | yes | verified: LON-20, LON-21, LON-23 |
| DRAFT-33 | Evaluation report, model specification and failure case | 19, 27, 28, 29, 30, 31, 32 | P0 | LON-33 | [LON-33](https://linear.app/twinleaf/issue/LON-33/evaluation-report-model-specification-and-failure-case) | yes | verified: LON-18, LON-27, LON-28, LON-29, LON-30, LON-31, LON-32 |
| DRAFT-34 | Scenario workspace: state, controls, runs, fan charts, paired comparison, attribution | 10, 23, 24 | P0 | LON-34 | [LON-34](https://linear.app/twinleaf/issue/LON-34/scenario-workspace-state-controls-runs-fan-charts-paired-comparison) | yes | verified: LON-11, LON-22, LON-23 |
| DRAFT-35 | Evidence and review UI with passage spans, decisions and search | 10, 17, 18, 22 | P1 | LON-35 | [LON-35](https://linear.app/twinleaf/issue/LON-35/evidence-and-review-ui-with-passage-spans-decisions-and-search) | yes | verified: LON-11, LON-16, LON-17, LON-21 |
| DRAFT-36 | Valuation, actions, evaluation and replay pages | 10, 25, 26, 27, 28 | P1 | LON-36 | [LON-36](https://linear.app/twinleaf/issue/LON-36/valuation-actions-evaluation-and-replay-pages) | yes | verified: LON-11, LON-25, LON-26, LON-27, LON-28 |
| DRAFT-37 | Demo dataset, saved runs and seed command | 15, 16, 24, 34, 35, 36 | P0 | LON-37 | [LON-37](https://linear.app/twinleaf/issue/LON-37/demo-dataset-saved-runs-and-seed-command) | yes | verified: LON-14, LON-15, LON-23, LON-34, LON-35, LON-36 |
| DRAFT-38 | Final export, clean-environment validation and submission docs | 12, 33, 37 | P0 | LON-38 | [LON-38](https://linear.app/twinleaf/issue/LON-38/final-export-clean-environment-validation-and-submission-docs) | yes | verified: LON-24, LON-33, LON-37 |
| DRAFT-39 | Demo rehearsal and presentation notes | 38 | P2 | LON-39 | [LON-39](https://linear.app/twinleaf/issue/LON-39/demo-rehearsal-and-presentation-notes) | yes | verified: LON-38 |

## Conflicts and failures

- **Destination conflict (resolved):** the authorization named a new team "Longaeva" and a new project "hackathon", but also said "Do not create a project", and the connection cannot create teams. The user created the team and project in the Linear UI and chose the priority mapping; the import only attached issues.
- **Failures:** none. Every create call succeeded on the first attempt.
- **Metadata not carried as Linear fields:** effort hours, requirement IDs, plan priority labels (P0/P1/P2) and inputs are in the issue bodies only. No labels, milestones, cycles, assignees or estimates were created or set.
- **Cosmetic:** Linear auto-linked the text "investor.visa.com" in LON-7. The wording is unchanged.
