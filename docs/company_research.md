# Company research operations

The previous sources phase requested five years of operational evidence in one response capped at 24,000 output tokens. Reasoning and visible output share that limit, so background execution alone cannot prevent `max_output_tokens` failures. The new workflow uses smaller, checkpointed units through the Responses API. ChatGPT Deep Research has its own orchestration; one API request does not reproduce that workflow.

## Run contract

- One run snapshots ticker, requesting actor, as-of date, prompts, model and pricing version. It covers both reports by default. Concurrent starts reuse the active company run.
- Both reports and every attempt share $25 and 55 minutes from creation. Gathering stops admitting requests when 15 minutes or $7 must be reserved for verification, writing and publication. Limits are ceilings, not completion guarantees.
- PostgreSQL transactions protect leases and in-flight reservations. At most two requests are in flight. The SDK has no hidden retries. Unknown submission/cancellation outcomes consume their full reserved liability; known rejected submissions consume zero.
- A resume reuses evidence, response IDs, prompt snapshots, charged costs and the original deadline. It never grants another allowance. Only the original actor can resume. A distinct **Run Company Research** action starts a new allowance after the prior run is no longer active.
- A completed report is independently saved through the existing governed company-sheet action. Incomplete evidence remains available for inspection and never replaces a company sheet. Existing legacy jobs/reports remain readable.

## Quality checks

1. Resolve issuer identity and the last 20 reported fiscal quarters, with dates and primary sources. Assign each overview section to a topic.
2. Research management in five four-quarter packets, splitting a truncated packet into two and then individual quarters. Research overview topics separately. Reuse the verified fiscal-calendar sources.
3. Validate exact quarter coverage, dates, source passages and tool-observed URLs. A documented unsuccessful source search is different from a quarter that was never researched.
4. Group related initiatives for independent source verification. Every original record must be retained or explicitly rejected. Original promises and deadlines cannot be rewritten; concluded outcomes require later dated evidence.
5. Write and audit sections separately, using maximum reasoning for reconciliation, narrative judgments and audits. Permit one repair of an unsupported section or summary. Deduplicate source passages without shortening evidence.
6. Render the 16-column tracker deterministically. Preserve disclosures, uncertainties, exclusions and source links. Validate and audit the company-sheet summary before publishing.

These checks reduce unsupported claims; they do not establish that every public disclosure has been discovered. Evidence gaps remain visible in the report and progress display.

## Pricing and provider limits

Only `gpt-6.1-sol` is accepted until another model has an explicit cost envelope. Requests pin the standard service tier. The current conservative envelope uses $2.50/million input tokens (including possible cache-write pricing), $10/million output tokens, $0.01/web-search call, and a 10% margin. It reserves a 128,000-token search context for each allowed tool turn, the initial turn, and an extra tool result if a batch straddles the call limit. Non-search requests use input and schema bytes plus overhead as a conservative token bound. Output budgets include reasoning tokens. Cached-input discounts are not credited.

The UI reports budget usage with this margin, not an invoice amount. Provider usage settles reservations; missing usage retains the maximum charge. Review rates and context bounds when updating models. Sources: [model limits and pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [tool pricing](https://developers.openai.com/api/docs/pricing), [web search](https://developers.openai.com/api/docs/guides/tools-web-search).

## Validation and recovery

Run `python -m pytest tests/test_company_research.py tests/test_company_research_workflow.py` and `npm run test:smoke -- company-research.spec.ts` from `frontend/` for browser checks. A single real evaluation uses:

```sh
python -m scripts.evaluate_company_research --ticker EL
```

This uses real provider calls and egress governance, isolated local persistence, and `apply=false`. It writes the run ID, response artifacts and result under `tmp/company-research-eval/`. It cannot update company sheets or latest-report pointers. Continue an interrupted evaluation using `--resume RUN_ID` with the same output directory; the original caps remain in effect. Never treat a capped or incomplete evaluation as a successful quality test.

Deploy the additive Alembic migration before the new API/worker. The normal `./infra/gcp/deploy-all.sh` sequence does this. The migration retains legacy state. After rollout, verify the deployed commit and migration health, then exercise authenticated settings/status/report endpoints without starting an unapproved paid run.
