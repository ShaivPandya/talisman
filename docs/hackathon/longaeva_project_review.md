# Talisman implementation review for the Longaeva AI Hackathon

Reviewed September 16, 2026. Scope: one company, with Visa as the initial model. Proposal: [Longaeva Stage 1 proposal](/Users/shaivpandya/Desktop/talisman/docs/hackathon/longaeva_stage1_proposal.md).

## Recommendation

Build a Visa operating simulation that connects spending mix, transaction activity, revenue timing, client incentives, and operating profit. The strongest reusable idea in the repository is the connection between research claims, evidence, historical state, and decisions. Add a numerical business model to make that connection useful for forward simulation. The external proposal describes the system we are building for the competition; this technical review records the actual repository state for implementation planning.

The current project is a substantial research application, but its existing scenario simulator does not yet fulfill the central challenge. It accepts stock-price scenarios and calculates action outcomes. The missing component is the system that produces those scenarios from payment activity, spending mix, effective revenue yields, incentives, and costs.

This review recommends modifications; it does not implement them. Application code is unchanged. The review is based on the checked-out source at commit `2bc76f6c`, relevant documentation, and focused tests. A running deployment, vendor entitlements, and production data coverage were not audited.

## Fit against the challenge

| Requirement | What exists | Modification needed |
| --- | --- | --- |
| Run a company forward | Financial projections and a deterministic action simulator | Add company state, activity transitions, revenue timing, accounting identities, and a quarterly time loop. |
| Produce probability distributions | Supplied scenario probabilities and weighted outcomes | Sample operating states and correlated shocks; retain complete paths and calibration diagnostics. |
| Use a mosaic of evidence | Financial adapters, PDF/text ingestion, research documents, and evidence records | Extract operating observations from dated disclosures and selected external sources; connect observations to model parameters. |
| Show which signals moved results | Evidence/citation objects, provenance, and change views | Record parameter updates, paired reruns, source ablations, and the resulting distribution changes. |
| Support investment decisions | Valuation, portfolio risk, action comparison, and policy checks | Add an explicit expectations comparison and valuation bridge, with cost-aware evaluation and a no-action outcome. |
| Demonstrate repeatability and scale | Modular backend, jobs, schemas, temporal records, and evaluation infrastructure | Define a company-model contract and a business-forecast evaluation suite. |

The [official competition page](https://www.longaeva.com/hackathon) confirms the working-company-simulation objective and the later-stage data conditions. The supplied organizer message establishes the September 16 proposal deadline. No extra word limit or required proposal format was supplied. The proposal uses prospective language for the planned build and includes a detailed architecture and worked scenario.

## What the code actually supports

**Action simulation is usable downstream.** [The simulator](/Users/shaivpandya/Desktop/talisman/portfolio/scenario_simulator.py:31) implements hold/add/trim/exit mechanics, source references, uncertainty notes, and policy checks. [Scenario normalization](/Users/shaivpandya/Desktop/talisman/portfolio/scenario_simulator.py:226) reads supplied price moves and normalizes supplied probabilities, using equal weights when necessary. This is not an inferred distribution of company outcomes.

**The current interface uses illustrative inputs.** [The scenario tab](/Users/shaivpandya/Desktop/talisman/frontend/src/components/scenario/PositionScenarioSimulatorTab.tsx:31) builds a $100,000 portfolio assumption and -10%, 0%, and +10% price scenarios with fixed weights. Replace these inputs on the hackathon screen with business assumptions and simulation-derived distributions. Keep any demonstration portfolio clearly labeled and editable.

**Document infrastructure exists; general driver extraction does not.** [The extractor registry](/Users/shaivpandya/Desktop/talisman/ontology/extractors/registry.py:11) registers the model document and image extractors as disabled placeholders. [The deterministic text extractor](/Users/shaivpandya/Desktop/talisman/ontology/extractors/deterministic.py:59) creates text-preview observations and evidence, not a calibrated set of company drivers. Existing thesis-generation workflows elsewhere in the application do not close this specific gap.

**The evidence and temporal architecture is the strongest foundation.** [The evidence ledger](/Users/shaivpandya/Desktop/talisman/ontology/evidence_ledger.py), [temporal repository](/Users/shaivpandya/Desktop/talisman/ontology/temporal_repository.py), and [provenance service](/Users/shaivpandya/Desktop/talisman/api/provenance_graph.py) provide useful structures for reproducible research. A provenance edge explains origin; it does not by itself establish a causal effect or validate a probability.

**Historical availability needs explicit work.** [Source upload](/Users/shaivpandya/Desktop/talisman/ontology/source_ingestion.py:194) currently sets `as_of`, `load_time`, and `valid_from` to the upload time. [The EDGAR balance-sheet helper](/Users/shaivpandya/Desktop/talisman/portfolio/momentum/fundamental_momentum/edgar_fetcher.py:156) keeps the latest filing for a period, and shared period helpers also select among filing versions. These are useful current-data paths, but historical forecasts need a publication cutoff before version selection. Temporal storage does not manufacture an authentic historical dataset.

**Costs are partially supported already.** [The simulator](/Users/shaivpandya/Desktop/talisman/portfolio/scenario_simulator.py:390) accepts explicit transaction, slippage, impact, and funding assumptions; defaults can still be zero. Its funding calculation applies to traded notional, so held-position financing would need a separate convention for a leveraged strategy. The existing [aluminum backtest](/Users/shaivpandya/Desktop/talisman/commodities/aluminum/backtest.py) also includes transaction costs. [ADR-009](/Users/shaivpandya/Desktop/talisman/docs/adr/009-simulation-fidelity.md) predates these capabilities and should not be quoted as an exact account of current code.

**Existing evaluations assess a different target.** [TalismanBench](/Users/shaivpandya/Desktop/talisman/docs/talisman_bench/README.md) evaluates agent behavior, schema validity, and decision process. Those checks can inform the new workflow, but they do not measure operating forecast accuracy or investment returns. A company forecast suite is new work.

## Why Visa

Company selection should follow the evidence needed to constrain the important parameters. The repository's infrastructure is broadly company-independent, and the presence of an old investment thesis is not a strong reason to select its subject. Visa offers a practical starting point because reported activity measures connect to identifiable revenue categories, including an explicit lag in service revenue. The hypothesis to test is whether changes in spending composition and timing produce useful information beyond aggregate growth extrapolation.

| Candidate | Public anchors | Important evidence gap | Fit for this build |
| --- | --- | --- | --- |
| Visa | Payment volume, cross-border growth, processed transactions, revenue categories, incentives | Contract-level pricing, incentive schedules, and forward demand responses | Recommended first company; clear aggregate reconciliation and timing. |
| Mastercard | Volume, switched transactions, network assessments, rebates, services revenue | Contract economics and the separate services growth model | Closest alternative and a later architecture test. |
| Meta | Users, ad-impression growth, average ad-price growth, financials | Engagement versus ad load, advertiser returns, auction and budget responses | Attractive if suitable advertiser or usage data become available. |
| Micron | Product revenue, approximate bit and pricing changes, capex, inventory | Product-level allocation, yields, packaging throughput, demand elasticities | A coarse scenario model is feasible, but a detailed factory model relies on weakly observed parameters. |
| Netflix | Financial results, content releases, title viewing | The link from viewing to acquisition, churn, and plan changes | More credible with a subscriber panel; viewing alone is insufficient. |
| Alphabet | Search click and price changes, Cloud revenue and backlog | AI versus traditional Search economics, or Cloud delivery capacity | Narrow to Search or Cloud; a whole-company model exceeds scope. |

Primary comparison sources are [Visa's Q3 results](https://www.sec.gov/Archives/edgar/data/1403161/000140316126000103/q32026earningsrelease.htm), [Mastercard's Q2 filing](https://www.sec.gov/Archives/edgar/data/1141391/000114139126000083/ma-20260630.htm), [Meta's Q2 filing](https://www.sec.gov/Archives/edgar/data/1326801/000162828026050705/meta-20260630.htm), [Micron's Q3 filing](https://www.sec.gov/Archives/edgar/data/723125/000072312526000015/mu-20260528.htm), [Netflix's viewing report](https://about.netflix.com/en/news/what-we-watched-the-first-half-of-2026), and [Alphabet's Q2 filing](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000071/goog-20260630.htm). The fit judgments prioritize observable model inputs, a focused first company, and public data access.

Visa's disclosed outcomes do not identify every causal parameter. Effective yields combine pricing, mix, currency effects, and services; incentives depend on customer agreements. These belong in parameter ranges, with sensitivity analysis and a small number of fitted coefficients. A good fit to historical revenue is not evidence that the underlying contract terms have been recovered.

The initial source audit must preserve the definitions in [Visa's 2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/1403161/000140316125000089/v-20250930.htm) and [Q3 2026 Form 10-Q](https://www.sec.gov/Archives/edgar/data/1403161/000140316126000104/v-20260630.htm). Service revenue primarily follows prior-quarter payment volume; payment volume and processed transactions have different coverage; cross-border volume overlaps total volume; and value-added services are already recognized within reported revenue categories. Visa's network revenue must not be equated to issuer interchange or the full merchant discount rate.

## Required implementation

### First priority is one inspectable business model

Create a small, pure Python package, for example `business_simulation/`, with the following boundaries:

- `models/visa.py`: activity transitions, revenue categories, recognition lags, incentives, and operating costs.
- `engine.py`: reproducible sampling, path generation, and distribution summaries.
- `observations.py`: typed observations, units, dates, source links, and review status.
- `calibration.py`: parameter ranges and constrained ensemble weighting.
- `explain.py`: paired interventions and source-family ablations.
- `evaluation.py`: chronological forecasts, baselines, scores, and saved reports.

The minimum state comprises domestic and international payment-activity indices, processed transactions, cross-border activity, effective revenue yields, incentive intensity, and an operating expense baseline. Represent travel and ecommerce as uncertain drivers of cross-border activity only to the extent that source coverage supports their separation. Begin with roughly six to eight free transition parameters; pool or fix other coefficients rather than fit more detail than the available history can distinguish.

The transition sequence should be explicit: update spending and frequency under common demand and currency conditions; translate those states into payment-volume and transaction paths; apply the correct period and effective yield to each revenue category; subtract client incentives; then subtract modeled expenses. An illustrative seasonal formulation scales last year's category revenue by the relevant activity ratio and a yield-change factor. For service revenue in quarter t, the activity ratio uses payment volume in t-1 versus t-5. Processing uses current-quarter processed transactions; international revenue uses the correctly defined cross-border index plus explicit yield uncertainty. These are aggregate approximations, not recovered fee schedules.

Keep nominal and constant-currency measures separate, preserve fiscal-quarter definitions, and distinguish total cross-border volume from the series excluding intra-Europe. Growth-only disclosures require normalized indices; they do not establish an absolute volume level. Do not divide total payment volume by processed transactions and label the ratio observed average purchase value. A spending-mix intervention must conserve the specified spending total; independent sampling must not accidentally create extra spending. Value-added services will inform category yield or residual assumptions without being added again as a fifth revenue bucket. Gross category revenue less incentives must equal net revenue on every path.

Start with a weighted ensemble and correlated Monte Carlo paths. Use historical residuals to constrain shocks where possible, and clearly label assumed ranges for unobserved contracts and behavioral responses. Apply source updates through an explicit observation-to-parameter rule, then refit or reweight the supported ensemble. Review qualitative update sizes and test them against a financial-only model. A larger simulated sample reduces numerical noise; it does not solve missing information. Net revenue and operating profit are the core financial targets; a detailed cash-flow model is outside the minimum build.

### Second priority is a dated evidence pipeline

Reuse `SourceRecord`, `Observation`, `Evidence`, `Citation`, and `ScenarioAssumption` where their schemas fit. Add narrowly scoped model-definition and simulation-run records only as needed. A run must preserve its model version, source-version identifiers, parameter set, valuation assumptions, random seed, cutoff, and output hash.

Extend ingestion to retain full extracted text with page/character locations, publication time, period described, first observation time where known, and actual retrieval time. Preserve original files and content hashes. Historical reconstruction must filter by externally verifiable publication time while retaining today's ingestion time. Do not backdate transaction timestamps to suggest the system captured a source earlier than it did.

An extracted driver should contain a typed value or range, unit, activity type, geography, period, source span, source family, and review status. Separate reported measurements, management guidance, qualitative statements, analyst assumptions, and intervention settings. A language model's confidence score must not become a business-outcome probability.

For the first build, use a curated source manifest instead of a general-purpose web crawler. Start with Visa's historical disclosures, then selected airline, travel-platform, retailer, and payment-processor statements. Public [I-94 arrivals summaries](https://www.trade.gov/i-94-arrivals-program) can corroborate some travel claims, but their US coverage cannot stand in for global card activity. Preserve the distinction between travel and ecommerce, and between bookings, passenger counts, and spending. Source duplication and copied press releases must not count as independent evidence. Exclude observations from historical tests if their publication vintage cannot be established, including revised government series without recoverable earlier versions.

### Third priority is an explanation and expectations interface

Add one company simulation page alongside the current dossier. Reuse the existing UI controls, charts, evidence panel, and provenance dialog. Its main elements should be operating-driver controls, activity/revenue/operating-profit fan charts, a comparison with dated expectations, and a panel identifying the sources and assumptions responsible for a change. Show how spending composition, recognition lags, yields, and incentives explain differences between paths with similar headline payment growth. Flag material conclusions dominated by weakly supported assumptions.

Use paired runs with identical random seeds for interventions. A source-removal ablation should rebuild the supported parameter ensemble; merely hiding a citation is not an ablation. Label intervention effects as conditional on the model. For interacting changes, show a joint residual or explain order dependence rather than forcing all contributions to add independently.

Add a separate valuation bridge. [The current DCF](/Users/shaivpandya/Desktop/talisman/equities/valuation/dcf.py:841) expects five to eight annual projections and current financial data, so four quarterly paths cannot be passed directly into it. The MVP will translate operating profit to forward earnings with stated tax, net-interest, and diluted share-count assumptions, then apply a valuation-multiple range. Preserve the forward measurement window and price horizon. Document unsupported cases, such as a non-positive earnings denominator, rather than silently producing a misleading value. Valuation assumptions are separate from the operating forecast.

Do not label management guidance as market consensus. Use licensed, dated consensus only when available. Otherwise compare with guidance and show the range of assumptions consistent with the observed price under the chosen valuation convention. Separate potential fundamental surprise from evidence that a trade offers excess return.

### Fourth priority is evaluation before adding breadth

Create a new business-forecast corpus rather than relabeling agent evaluations. Target at least eight eligible one-quarter-ahead origins, with a documented source-availability audit. Report the actual count and any exclusions. Fit at each origin using only prior observations; freeze model choices and decision thresholds before scoring the evaluation window.

Compare against simple seasonal/trend baselines and guidance where its metric and horizon are comparable, using the same eligible dates and accounting basis. Use net-revenue error, operating-profit error, activity-driver error, predictive-interval coverage, and CRPS or a weighted interval score. Point guidance needs a historical residual distribution, estimated using prior data only, before it is compared with probabilistic forecasts. Keep four-quarter scenario scoring separate because fewer completed outcomes will be available. Identify exceptional items rather than treating adjusted and GAAP outcomes as interchangeable.

Run three minimum ablations: financial-only evidence; pooling spending mix into one growth driver; and removal of the service-revenue lag. Inspect whether gains persist across forecast origins and parameter ranges, especially yield and incentive assumptions. Add a small manually labeled extraction set containing numeric facts, qualitative statements, contradictions, and period/units/scope edge cases. Record extraction mistakes separately from business-model errors.

Historical replay is still a retrospective study: current model design may benefit from hindsight, and pretrained language models may know later events. Restrict extraction to supplied passages, reject unsupported claims, and preserve prospective forecasts as a separate test. Do not claim leakage-free live validation from a replay alone.

The optional paper portfolio should use a fixed, simple long/cash rule, an S&P 500 total-return benchmark, and a Visa buy-and-hold comparison. Apply the same risk budget across model variants. Define entry at the first eligible market session after the input cutoff, exit after a fixed holding period, explicit round-trip costs, and handling of dividends and overlapping forecasts. Show excess return, drawdown, and exposure; do not describe a raw benchmark difference as proven risk-adjusted alpha. With a handful of decisions, forecasting and interpretability evidence will carry more weight than a headline Sharpe ratio.

## Proposed implementation architecture

Use a React and TypeScript interface built with Vite, with Recharts for forecast ranges and scenario comparisons. FastAPI will expose requests for observations, reviewed parameter sets, simulation runs, and evaluation results. A Python worker will perform extraction and longer simulations outside the web request, preserving a run identifier and status in PostgreSQL. Source and model versions must be frozen for each run.

Python with HTTPX, Beautiful Soup, and pdfminer.six will collect permitted sources and preserve their original files. A configurable language-model API will return structured JSON observations. Pydantic will validate their fields, units, dates, and allowed values; analyst review will verify the source support and approve material updates. Format validation does not establish factual correctness. PostgreSQL full-text search will retrieve passages after publication-date and company filters. SQLAlchemy will manage the database records, and object storage will hold originals and larger outputs.

The company model will remain a pure Python calculation using pandas for historical data, NumPy for repeated paths, and SciPy where constrained fitting is useful. Its input is an approved parameter set and scenario definition; its output is a reproducible collection of operating and financial paths. It should not need a language-model call to regenerate a saved result. Preserve code version, source versions, cutoff, parameter values, and random seed. Docker can package the service and worker; a permitted Google Cloud deployment can use Cloud Run, Cloud SQL, and Cloud Storage.

The core records are sources, observations, parameter sets, and simulation runs. Each observation points to a source span, each material parameter change points to observations or an explicit analyst assumption, and each forecast points to its exact parameter and code versions. Evaluation must operate on the same numerical engine used by the interface. pytest will verify accounting identities, boundary cases, and publication cutoffs; dated forecast datasets will measure predictive performance.

## Differentiation and comparable work

NLP, retrieval, financial modeling, and Monte Carlo simulation are established methods. [AlphaSense](https://help.alpha-sense.com/hc/en-us/articles/41666587181203-Interacting-with-Generative-Search) combines qualitative and quantitative research with citations. [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) combines AI research, numerical valuation, Monte Carlo analysis, and evidence links. These precedents rule out a credible claim that the broad combination is new. A capable analyst or tool-using AI agent could implement many of the same components.

The intended contribution is a specific, testable model of Visa's spending mix and revenue timing, with a reviewed mapping from dated observations to numerical assumptions and measured forecast consequences. Qualitative observations should remain contextual if their numerical effect cannot be supported. Explanations need to show the update rule, the before-and-after parameter values, and the effect on results. They must not turn citations into claims of causal proof.

Compare the full system with seasonal or trend baselines, a conventional financial-driver model, and a language-model forecast supplied with the same dated documents. The controlled source-removal tests should show whether external observations improve forecasts, not merely change them. A source family that repeatedly worsens results should lose weight or be removed through a documented model revision. Any competitive advantage remains a hypothesis until evaluated.

Preserve a focused Visa model, source traceability, and accounting checks before adding source breadth or additional companies. A second company will require its own operating definitions and validation. Execution systems, custom language-model training, and a full market of simulated agents are outside the core idea.

## Demonstration and acceptance criteria

The demonstration should begin with a saved, dated Visa state. Show the source and uncertainty behind one parameter. Shift spending from cross-border travel to domestic purchases while holding the aggregate payment-volume path fixed, then explain the effects on revenue composition, timing, incentives, and operating profit. Introduce a reviewed source update and show how the forecast changes. Finish with an honest comparison against the baseline, including a failure case and the observable conditions that would invalidate the current interpretation.

The minimum completion criteria are:

- One company runs through four quarterly transitions; financial-only baselines and at least one external evidence family are available for comparison.
- Spending constraints and revenue identities hold on every path; overlapping volume measures and value-added services are not double counted; randomness is seeded and replayable.
- Every displayed material parameter is linked to a dated source or labeled as an assumption; contradictory and missing evidence is visible.
- Forecast distributions, paired scenario changes, and a saved evaluation report are accessible in the UI or exported report.
- Historical source versions and publication cutoffs are auditable; later revisions cannot enter earlier forecasts silently.
- The public-data demo works without Longaeva credentials; restricted inputs and outputs remain within their permitted environment.

## Data access and remaining submission details

Use Longaeva's approved data after the required NDA and compliance approval. Keep provider permissions, permitted processing locations, retention restrictions, and citation requirements in source metadata. Do not send restricted documents to an external model endpoint unless that use is permitted. Ask for historical consensus and original source vintages first if offered; they improve validation more directly than a large collection of extra live feeds. These are implementation constraints arising from the data terms supplied by the user and the official rules.

The proposal presents Talisman as the system being built and explains the idea without staffing or delivery-duration commitments. Add participant names, university details, and required registration fields in the submission form; none have been invented. The proposal describes intended capabilities and does not claim measured predictive performance.

## Verification performed

The following focused command passed during the initial repository assessment; it was not rerun for this document revision:

```text
.venv/bin/python -m pytest tests/test_scenario_simulator.py tests/test_source_ingestion.py tests/test_evidence_ledger.py tests/test_temporal_ontology.py -q --tb=short
30 passed, 1 warning in 3.37s
```

The warning concerns a deprecated FastAPI/Starlette test-client dependency path. These tests verify the selected existing components, primarily with isolated or mocked dependencies. They do not establish live vendor coverage, production readiness, an implemented Visa simulation, or predictive performance. No full application, browser, or deployment test was needed for these document-only deliverables.
