"""User-supplied default research queries; only company placeholders are templated."""

OVERVIEW_PROMPT = """You are a neutral research compiler. Produce an in-depth research report ONLY from verifiable sources. Do NOT add your own opinions, enthusiasm, investment advice, or qualitative praise/criticism. Focus less on commentary and more on just listing as much raw information.

Create a report on **{ticker}**. Make sure it contains the following information:

1. Overview
 - Stock price
 - One-line sentence of what they do
 - Total revenue in the most recent year
 - Market cap
 - Who the CEO is and how long they've been in charge

2. Financials
 - Revenue trend over the last 3 years (dollar amount and percent change)
 - Revenue breakdown by segment (dollar amount and percent)
 - Revenue breakdown by geographic region (dollar amount and percent)

3. History and expansion
 - What did they start off doing initially?
 - What have they expanded into and how?

4. Industry Overview
 - Who are the big players
 - Porter's five forces
 - Is this industry in a boom (Price affects fundamentals in a reinforcing way, Increasing liquidity, loose policy, favorable industrial policy) or bust (unsustainable, decreasing liquidity, tightening policy, unfavorable industrial policy) or neither?
 - What is the supply for next 6, 12, 18, and 24 months? What is the demand?
 - Is supply out pacing demand, demand outpacing supply, or equal?

5. Competitive Standing and competitive advantage
 - Who are their biggest competitors?
 - What are their competitor's advantages?
 - What is their sustainable competitive advantage (none, narrow, or wide) as measured my intangible assets, cost advantage, efficient scale, network effect, switching costs, and barriers to entry?
 - What is the direction of their competitive advantage (wider, stable, or narrower)? Are they structurally getting better over time?

6. Sensitivity to extrinsic factors
 - What is their sensitivity (low, medium, or high) to extrinsic factors (commodity prices, interest rates, currency fluctuations, tariffs, war/disruption/conflicts, labor costs, inflation)?
 - What is their capacity to deal with each of these?

7. Financials
 - How much debt does (low, medium, or high) does the company have?
 - What are their reinvestment costs (low, medium, or high)? What is their capacity to deal with these?

8. Suppliers and Customers

9. M&A History
 - Dates and outcomes

10. Upcoming catalysts

11. Recent (last 3 months) important news about the company if any

12. Risks
 - What are the risks to the business?
 - What are the risks to the industry?"""

MANAGEMENT_QUALITY_PROMPT = """You are a neutral research compiler. Use only verifiable public sources. Do not provide investment advice, personal opinions, enthusiasm, or unsupported qualitative judgment.

Company: {ticker}

"Conference call transcripts are publicly available. It's kind of very helpful to go back five years and kinda learn the story. You know here's how management describes their business, here's what they say they're gonna do, and you can follow along to see what they do. It's like a historical record of how competent and truthful they are. It's a very useful device" - Bill Ackman

Fundamentally we are trying to answer three questions:
1. Do the managers think and act like owners?
2. Do the managers understand what drives business value?
3. Did they do what they say they were gonna do?

Objective:
Evaluate management quality over the last 20 fiscal quarters by testing operational execution: what management said they would build, launch, open, fix, integrate, reduce, expand, or improve — and what actually happened.

Do not focus on whether the company met revenue, EPS, EBITDA, or income guidance. Financial results matter only when they verify or contradict an operational claim, such as cost reductions, unit economics, capacity utilization, production volumes, capex budgets, working capital improvements, inventory normalization, or margin impact from a specific operational initiative.

Primary sources:
- Earnings call transcripts
- 10-Q and 10-K filings
- Earnings releases
- Investor presentations
- Company press releases
- Proxy statements where relevant
- Regulatory filings, permits, production reports, or technical reports where relevant
- Segment/KPI disclosures

Core task:
For each of the last 20 quarters, identify specific operational claims, targets, timelines, projects, or initiatives stated by management. Then determine whether each was achieved, delayed, missed, over budget, under budget, changed, abandoned, or insufficiently disclosed.

Prioritize concrete operational execution, including:

1. Product and service launches
- Did new products, services, features, platforms, models, stores, facilities, mines, factories, wells, plants, routes, data centers, or projects launch when management said they would?
- Were launches commercial, pilot, beta, limited-release, or fully scaled?
- Did management redefine the launch after the fact?

2. Capacity and production
- Did capacity additions happen on time?
- Did production ramp as expected?
- Were utilization, throughput, yield, uptime, recovery rates, grade, volume, or efficiency targets achieved?
- Were bottlenecks identified and fixed?

3. Construction and project execution
- Were factories, mines, plants, warehouses, stores, distribution centers, pipelines, facilities, or other assets completed on schedule?
- Were they commissioned, permitted, producing, staffed, and commercially useful when promised?
- Did capex stay within budget?
- Were delays caused by management execution, permitting, suppliers, weather, labor, financing, technical issues, or other factors?

4. Cost reduction and efficiency programs
- Did stated cost savings occur?
- Were savings gross or net of reinvestment?
- Were savings one-time or structural?
- Did unit costs, cash costs, COGS per unit, SG&A efficiency, freight, procurement, labor, input costs, or manufacturing costs move as management said they would?
- Did cost programs create service, quality, employee, safety, or customer problems?

5. Operational fixes
- When management identified a problem, how quickly did they act?
- Did they replace personnel, change processes, close facilities, alter suppliers, restructure, change incentives, revise quality controls, or adjust strategy?
- Did the fix work?
- Was the same issue repeated in later quarters?

6. Supply chain and procurement
- Did management execute sourcing, vendor diversification, inventory normalization, logistics improvements, or input-cost reduction plans?
- Were shortages, delays, or working-capital problems resolved on the timeline management gave?

7. Integration and M&A execution
- If the company acquired a business, did integration proceed as described?
- Were synergies operationally realized?
- Were systems, facilities, customers, teams, or product lines integrated on time?
- Did the acquisition later require impairment, restructuring, or strategic reversal?

8. Quality, safety, reliability, and customer outcomes
- Did management disclose quality issues, recalls, downtime, outages, churn, service problems, regulatory problems, safety incidents, or customer losses?
- How quickly did they respond?
- Did operational KPIs improve afterward?

9. Personnel and organizational execution
- When leadership, salesforce, engineering, operations, or plant-level problems appeared, did management act quickly?
- Were changes cosmetic or substantive?
- Did execution improve after personnel changes?

10. Accounting and disclosure quality
Analyze accounting only where it affects operational interpretation:
- Capitalized vs. expensed project costs
- Inventory write-downs or build-ups
- Impairments
- Warranty reserves
- Restructuring charges
- Capitalized software or development costs
- Depreciation lives
- Asset retirement obligations
- Mine/factory/project commissioning treatment
- Changes in segment reporting or KPI definitions
- Recurring “one-time” adjustments
- Non-GAAP metrics used to obscure operational problems

For each quarter, produce a detailed table with these columns:
1. Fiscal quarter
2. Source and date
3. Management’s operational claim or commitment
4. Category:
   - Product launch
   - Capacity expansion
   - Construction/project execution
   - Production ramp
   - Cost reduction
   - Supply chain
   - Quality/reliability
   - Integration/M&A
   - Personnel/organization
   - Regulatory/permitting
   - Other operational initiative
5. Original timeline, budget, or measurable target
6. Later evidence of what actually happened
7. Outcome:
   - Achieved on time
   - Achieved late
   - Partially achieved
   - Missed
   - Over budget
   - Under budget
   - Re-scoped
   - Abandoned
   - Not yet measurable
   - Insufficient disclosure
8. Delay or variance versus original statement
9. Management’s explanation
10. Independent verification from filings or later disclosures
11. Was the issue management-controlled, externally driven, or mixed?
12. Did management acknowledge the variance clearly?
13. Did management propose a fix?
14. Time from problem visibility to management action
15. Evidence that the fix worked or failed
16. Citations

Important exclusions:
- Do not make meeting revenue, EPS, EBITDA, or margin guidance the center of the analysis.
- Do not treat beating or missing quarterly financial guidance as evidence of management quality unless tied to a specific operational promise.
- Do not use stock price performance as evidence of management quality.
- Do not infer motives.
- Do not praise or criticize management without specific evidence.

Final output structure:
1. Operational execution summary
Summarize the major operational promises and whether management delivered.

2. Quarter-by-quarter operational commitment tracker
Provide a detailed table covering the last 20 quarters.

3. Project and initiative scorecard
Group major projects or initiatives across quarters and assess:
- Original promise
- Actual result
- Timeliness
- Budget discipline
- Management explanation
- Final status

4. Recurring execution patterns
Identify whether management repeatedly:
- Launches on time
- Misses timelines
- Revises targets
- Changes definitions
- Underestimates costs
- Overpromises ramp speed
- Acts quickly when problems appear
- Allows problems to persist
- Stops discussing prior commitments

5. Accountability and speed of response
For each major operational problem, show:
- First sign of issue
- First acknowledgement
- Corrective action
- Time elapsed
- Evidence of improvement or continued failure

6. Capital allocation as operational evidence
Analyze capital allocation only as it relates to execution:
- Was capex spent on time and within budget?
- Did projects produce the capacity or returns management expected?
- Were buybacks prioritized despite operational underinvestment?
- Did acquisitions create operational complexity or improve capability?
- Did stock-based compensation, dilution, or executive incentives reward execution or merely financial optics?

7. Accounting considerations
Identify whether accounting treatment made operational performance look better, worse, or harder to evaluate.

8. Evidence-based management quality assessment
Use this rating scale:
- Strong operational execution
- Mixed operational execution
- Weak operational execution
- Insufficient evidence

Assess only:
- Operational follow-through
- Timeliness
- Budget discipline
- Problem recognition
- Corrective action speed
- Transparency
- Consistency between stated plans and later actions"""
