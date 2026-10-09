# Talisman Visa Business Simulation Proposal

Understanding how changes in spending affect a business

Longaeva AI Hackathon | Stage 1 | September 16, 2026

We are building Talisman to help investors answer a practical question: when something changes in a company's business, what should change in our expectations for its results?

Visa will be our first company. Talisman will combine evidence from company disclosures, travel businesses, retailers, and public data with a model of how Visa earns money. Investors will be able to change an assumption, run the business forward through four quarters, and see a range of possible revenue and profit outcomes. Every important change in the forecast will be connected to the evidence and assumptions that produced it.

Our central hypothesis is that the composition of spending can matter as much as its total. Consumers may spend the same amount overall while making fewer international trips, buying different things, or making more frequent small purchases. Those changes can affect a payment network's revenue in different ways. We will test whether identifying them improves forecasts and investment decisions.

## Why Visa

Visa operates a payment network connecting financial institutions, merchants, and consumers. Its revenue depends on several kinds of activity, including payment volumes, transactions processed, and cross-border payments. It also earns money from additional services and pays incentives to clients. Its disclosures provide observable measures of these activities and the resulting revenue. [Visa 2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/1403161/000140316125000089/v-20250930.htm).

Timing also matters. Visa's service revenue primarily follows the previous quarter's payment volume, while other revenue categories reflect current-quarter activity. A change in spending can therefore affect different revenue streams at different times. This gives us a concrete business mechanism to model and test. [Visa fiscal Q3 2026 results](https://www.sec.gov/Archives/edgar/data/1403161/000140316126000103/q32026earningsrelease.htm).

## A simple example

Consider a simplified payment network that earns $1 for every $100 of domestic spending and $3 for every $100 of cross-border spending. These are invented teaching numbers, not Visa's actual fees.

| Measure | Scenario A | Scenario B |
| --- | --- | --- |
| Domestic spending | $800 | $900 |
| Cross-border spending | $200 | $100 |
| Total spending | $1,000 | $1,000 |
| Network revenue | $14 | $12 |

Total spending is unchanged, but revenue falls because the mix changes. A forecast based only on total spending would miss the difference. Talisman will investigate changes like this using Visa's actual revenue categories, available evidence, and explicit uncertainty about the relationships between them.

The investor's question becomes more specific: how much of our forecast depends on international travel, what supports that assumption, and what happens if it is wrong?

## How evidence becomes a forecast

**1. Establish what the business looks like today.** We will assemble Visa's reported activity, revenue, incentives, and expenses. Together, these form the starting state: the set of values from which the simulation begins. Each value will retain its reporting period, units, and source. Growth rates will remain growth rates unless the evidence supports converting them into absolute amounts.

**2. Read new information in context.** AI will extract observations from filings, prepared remarks, and selected airline, travel-platform, retailer, and payment-processor disclosures. Suppose a travel company reports slower international bookings. The system will record who made the statement, which markets it covers, the period described, and the exact supporting passage. It will distinguish a measured result from management's expectation. Publication dates and retrieval dates will be stored separately.

**3. Decide what the observation can change.** A booking statement might affect the expected direction of travel demand. It does not directly measure Visa's global payment volume. We will define a rule connecting each accepted observation to the relevant model assumption. Where sufficient history exists, the relationship can be estimated from earlier observations. Where it does not, an analyst will specify a range and the system will label it as an assumption. A qualitative statement will not become a precise percentage change without additional support.

**4. Run the business forward.** Each quarter will begin with the previous quarter's state. The model will update spending and payment activity, apply the relevant revenue relationships, subtract client incentives, and then subtract operating expenses. It will carry earlier payment volumes forward so revenue delays are handled correctly. The calculations will follow written business rules that can be inspected and tested.

The model will track service revenue, data processing revenue, international transaction revenue, and other revenue separately. Service revenue will follow lagged payment volume; processing revenue will respond to transactions; international revenue will respond to cross-border activity and currency-related effects. Each relationship will allow uncertainty in average revenue earned per unit of activity. This average can change with customer mix, pricing, and services, so it will not be presented as an observed contract fee.

Accounting checks will keep the model consistent. Cross-border payments are already part of total payment volume. Value-added services already appear within Visa's reported revenue categories. Neither will be added a second time. Payment volume and processed transactions cover different sets of activity, so dividing one by the other will not be treated as a measured average purchase value. Expenses will distinguish recurring costs from exceptional items. [Visa fiscal Q3 2026 Form 10-Q](https://www.sec.gov/Archives/edgar/data/1403161/000140316126000104/v-20260630.htm).

**5. Repeat under different possible conditions.** The future is uncertain, and some current assumptions are uncertain too. We will run many possible paths with different combinations of demand, pricing, incentives, and costs. Conditions that tend to move together will be modeled together: weaker consumption, for example, can affect both spending and travel. This repeated sampling is called Monte Carlo simulation. Its output is a range of outcomes, with probabilities conditional on the model's assumptions.

## What makes the approach different

Natural language processing, or NLP, helps computers interpret text. Talisman will use it to identify facts, dates, business conditions, and relationships. A language model can also retrieve documents, summarize an investment thesis, and help write analytical code. Those are useful capabilities, but the question we want to answer requires a maintained model of how the business changes over time.

| Approach | What it contributes | Talisman's intended addition |
| --- | --- | --- |
| NLP and document retrieval | Finds relevant passages and turns language into usable information | Records which operating assumption each accepted observation is allowed to change |
| AI research and financial analysis | Combines sources, calculations, and explanations | Keeps a dated, reproducible connection between evidence, business states, and forecast changes |
| Driver models and simulations | Calculates outcomes under specified assumptions | Updates those assumptions from reviewed evidence and tests whether the updates help predict results |

These boundaries can overlap. A capable analyst with a spreadsheet, or an AI agent with suitable tools, can perform many of the same steps. The contribution we propose is a repeatable system in which those steps are connected and evaluated together.

There are established precedents. AlphaSense combines qualitative and quantitative research with source citations. FinRobot combines AI equity research with numerical valuation, Monte Carlo analysis, and evidence links. We therefore do not claim that combining AI, financial models, and simulation is itself a new invention. [AlphaSense documentation](https://help.alpha-sense.com/hc/en-us/articles/41666587181203-Interacting-with-Generative-Search), [FinRobot project](https://github.com/AI4Finance-Foundation/FinRobot).

Our proposed contribution is narrower and testable: can reviewed evidence about spending composition improve a model of Visa's operating results, and can we show exactly how each useful observation affected the forecast?

A source citation establishes where a statement came from. We will extend that record to show which assumption changed, the size of the change, the rule used to make it, and the resulting movement in revenue or profit. If the observation is too vague to support a numerical update, the system can preserve it as context without changing the forecast.

We will also test the value of the evidence itself. Removing a source family, such as travel-company commentary, and rebuilding the forecast will show whether that information mattered. Historical tests will then show whether it helped or hurt accuracy. Evidence that creates a persuasive explanation but repeatedly worsens forecasts should receive less weight or be excluded.

The hard work lies in selecting the right business relationships, building a reliable history of observations, and learning which updates survive testing. The resulting collection of reviewed mappings and forecast errors could become a defensible asset. Its value would have to be demonstrated through results; familiar software components and an AI-generated narrative would not establish an advantage on their own.

## Technical architecture

Talisman will have three main parts: a browser interface for the investor, a Python service that performs the calculations, and storage that preserves the evidence and results. AI will help read and organize information. The numerical model will calculate business outcomes from approved inputs, so a saved forecast can be reproduced without asking the language model to generate it again.

| Part | Tools and technologies | Purpose |
| --- | --- | --- |
| Source collection | Python, HTTPX, Beautiful Soup, pdfminer.six | Retrieve permitted files and extract text from web pages and PDFs while retaining the originals |
| AI extraction | Language-model API, JSON, Pydantic | Produce structured observations and check required fields, dates, units, and review status |
| Evidence storage | PostgreSQL, SQLAlchemy, object storage | Store linked records in a database and preserve source files and larger simulation outputs separately |
| Business model | Python, pandas, NumPy, SciPy | Align historical data, estimate parameters, and calculate repeated quarterly paths |
| Service and background jobs | FastAPI and a Python worker | Receive requests, run longer tasks outside the web request, and return progress and saved results |
| Investor interface | React, TypeScript, Vite, Recharts | Build scenario controls, evidence views, and charts showing the range of possible outcomes |
| Verification | pytest and dated evaluation datasets | Check business calculations, prevent future information entering historical tests, and measure forecast quality |

The database will contain four core records. A **source** identifies the document, its publication date, and the period it describes. An **observation** records a specific fact or statement and its supporting passage. A **parameter set** records the numbers and ranges used by the business model, together with their evidence or rationale. A **simulation run** records the inputs, model version, and outputs of one calculation. These links allow an investor to move from a chart back to the original statement.

PostgreSQL text search will help locate relevant passages after filtering by company, reporting period, and publication date. The language model will return observations in JSON, a structured format that software can read reliably. Pydantic will check their format and required fields; source review will check whether the statements are supported. Corrections and approval decisions will be saved. An extracted observation will not automatically overwrite an approved model input.

When the investor presses Run, the interface will send the scenario to FastAPI, the service that connects the screen to the model. The service will save the request and return a run identifier. A background worker will load the approved inputs, execute the Python model, and save the results while the interface displays progress. Charts and explanations will refer to that same saved run.

Every run will preserve its information cutoff, document versions, parameter values, code version, and random seed. The seed makes the same set of sampled conditions repeatable. Docker will package the service and worker consistently. A permitted cloud deployment can use Google Cloud Run for computation, Cloud SQL for PostgreSQL, and Cloud Storage for files; data-provider restrictions will govern where processing may occur.

## What the investor will see

The main screen will show the current business assumptions, a range of revenue and profit forecasts, and the evidence behind them. An investor could inspect the share of growth attributed to cross-border activity, see the uncertainty around it, and change the assumption. A chart would show how the expected outcome and the range around it change.

For the spending-mix example, the investor would compare two paths with the same total payment volume but different amounts of cross-border travel. Holding average revenue rates fixed initially would make the mix effect visible. A separate scenario that reduces total spending would show the delayed effect on service revenue. Both comparisons would use the same sampled economic conditions so unrelated random variation does not obscure the effect being examined.

The explanation would connect the change to specific inputs and passages. It would also identify assumptions that matter greatly but have weak support. That helps the investor decide what to research next. These explanations describe consequences within the model; observational documents alone cannot prove its assumed cause-and-effect relationships.

The investment step will remain explicit. We will compare business forecasts with company guidance where the metric and period match, and with historical analyst consensus when licensed data are available. To estimate possible share values, we will translate operating profit into earnings using stated assumptions for taxes, net interest, and share count, then apply a range of valuation multiples. Uncertainty about the business and uncertainty about the price investors might pay for its earnings will be shown separately.

Talisman will compare holding, adding, trimming, or exiting an illustrative position with trading costs included. Our exploratory investment objective is excess return over a fixed S&P 500 total-return benchmark after costs, alongside a comparison with buying and holding Visa. The decision rule and holding period will be fixed before scoring. A favorable business forecast will still need to justify the purchase price and the risk taken.

## How we will test it

We will replay historical forecasting decisions using only information published by each cutoff. The target is at least eight eligible forecasts of the next quarter, with an earlier period used to estimate model relationships. We will report the actual number of usable cases and all exclusions. Forecasts made before future results arrive will be saved and evaluated separately from historical reconstructions.

The full model will be compared with a seasonal or trend forecast, a conventional driver model using financial data alone, and a language-model forecast supplied with the same dated documents. The comparison will ask whether the added structure and evidence improve predictions, with data access, forecast horizon, and scoring kept consistent. Comparable company guidance will provide an additional reference.

We will measure errors in net revenue, operating profit, and the main activity drivers. We will also test the uncertainty ranges. If the model assigns an 80% probability to a range, approximately 80% of outcomes should fall inside such ranges across enough forecasts. A scoring rule will reward useful narrow ranges and penalize both missed outcomes and ranges so wide that they say little.

We will repeat the tests after removing external commentary, combining spending types into one growth assumption, or removing the service-revenue delay. These controlled removals help identify which parts contribute useful information. Separately, a reviewed sample will measure extraction mistakes in facts, units, periods, and geographic scope. This lets us distinguish a reading error from a faulty business assumption.

Historical work can benefit from hindsight, including information present in a pretrained language model. We will restrict extraction to supplied passages, preserve original source versions, and report this limitation. Small samples will not establish durable alpha. Forecast performance, uncertainty calibration, and failure cases will be reported alongside any exploratory portfolio results.

## Evidence limits and expansion

Public disclosures provide stronger evidence for aggregate activity and financial results than for individual contracts or customer behavior. We will use ranges for hidden fee terms, incentive schedules, and uncertain responses to demand. If several parameter combinations explain the same history, the model will retain those alternatives. Thousands of simulated paths will not be presented as a substitute for missing evidence.

External sources will retain their limits. The International Trade Administration's [I-94 Arrivals Program](https://www.trade.gov/i-94-arrivals-program), for example, provides monthly visitor-arrival information for the United States. It can help check some travel claims, but it does not measure global Visa spending or cross-border ecommerce. Repeated versions of one statement will count as one source of evidence. Government data revisions will be handled according to when each version became available.

The demonstration will use sources we are permitted to access and process. Longaeva data will be incorporated only after the required NDA and compliance approval, used only for the competition, and kept within the permitted processing environment. Third-party data will be properly licensed and cited. Paid data can improve coverage, but it will not be required for the core demonstration.

The deliverable will be a working Visa simulation with scenario controls, inspectable evidence, saved forecasts, and an evaluation report. Its model specification will explain each input, the rule connecting it to an outcome, and the evidence supporting that rule. A demonstration will include a changed assumption, its financial consequences, and a case where the model failed.

The architecture will support additional companies through separate business models that use the same formats for observations, scenarios, and results. Mastercard is a natural comparison, although its definitions and revenue relationships will require separate work. Other companies will need their own operating logic. Evidence storage, review tools, simulation orchestration, and forecast testing can be shared while the economics remain company-specific.

## Sources

1. [Visa 2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/1403161/000140316125000089/v-20250930.htm), business model, revenue definitions, and value-added services.
2. [Visa fiscal Q3 2026 earnings release](https://www.sec.gov/Archives/edgar/data/1403161/000140316126000103/q32026earningsrelease.htm), key activity measures, revenue categories, incentives, and recognition timing.
3. [Visa fiscal Q3 2026 Form 10-Q](https://www.sec.gov/Archives/edgar/data/1403161/000140316126000104/v-20260630.htm), operating performance, accounting definitions, and expenses.
4. [International Trade Administration I-94 Arrivals Program](https://www.trade.gov/i-94-arrivals-program), coverage, publication frequency, and revision policies.
5. [AlphaSense Generative Search documentation](https://help.alpha-sense.com/hc/en-us/articles/41666587181203-Interacting-with-Generative-Search), research workflow and source citations.
6. [FinRobot project documentation](https://github.com/AI4Finance-Foundation/FinRobot), equity research, numerical valuation, Monte Carlo analysis, and evidence links.
7. [FinRobot research paper](https://arxiv.org/abs/2411.08804), Zhou and colleagues, 2024, integration of qualitative and quantitative equity research.
