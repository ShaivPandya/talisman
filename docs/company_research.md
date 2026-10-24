# Company research operations

The previous sources phase requested five years of operational evidence in one response capped at 24,000 output tokens. Reasoning and visible output share that limit, so background execution alone cannot prevent `max_output_tokens` failures. The new workflow uses smaller, checkpointed units through the Responses API. ChatGPT Deep Research has its own orchestration; one API request does not reproduce that workflow.

## Run contract

- One run snapshots ticker, requesting actor, as-of date, prompts, model and pricing version. It covers both reports by default. Concurrent starts reuse the active company run.
- Both reports and every attempt share $25 and 55 minutes from creation. Gathering stops admitting requests when 15 minutes or $7 must be reserved for verification, writing and publication. Limits are ceilings, not completion guarantees.
- PostgreSQL transactions protect leases and in-flight reservations. At most three requests are in flight; reservations can reduce this further. The SDK has no hidden retries. Unknown submission/cancellation outcomes consume their full reserved liability; known rejected submissions consume zero.
- A resume reuses evidence, response IDs, prompt snapshots, charged costs and the original deadline. It never grants another allowance. Only the original actor can resume. A distinct **Run Company Research** action starts a new allowance after the prior run is no longer active.
- A completed report is independently saved through the existing governed company-sheet action. Incomplete evidence remains available for inspection and never replaces a company sheet. Existing legacy jobs/reports remain readable.
- After public issuer/calendar planning, research can select relevant Talisman data through the existing governed chat read tools. Two selection rounds allow at most six reads and 80 KB of context. The reads use the requesting actor, prohibit writes, refreshes and site suggestions, and scope company-private reads to the run's ticker. Industry/macro datasets can supply relevant broader context. Alternative-data catalog discovery is available; it does not automatically launch fetch jobs or provision new sources.
- Read results, arguments, relevance reasons, capture timestamps and freshness metadata are snapshotted in the existing report artifact storage. A resume reuses those snapshots. Unavailable, denied or oversized reads are reported as evidence gaps; public-web research continues. A snapshot's capture time is not a historical observation date.
- Private evidence is extracted and verified without web-search tools, alongside the independently gathered public evidence. Prior internal analysis remains analysis, not independent proof. Each private citation must identify a registered snapshot and contain an exact supporting excerpt. Public search cannot introduce a private source. Private-data model requests still pass through existing egress governance and secret redaction.
- Private Talisman citations link to authenticated `GET /api/company-research/{ticker}/runs/{run_id}/sources/{source_id}` snapshots. Only the original requesting actor can retrieve them; responses are not cacheable. Reports retain source provenance and data limitations.
- The **Source files** panel on dossiers, watchlist names, and Company Explorer stores readable PDF, text, Markdown, and CSV files independently of holdings and chat messages. Each file is limited to 20 MiB, 500 PDF pages, and two million extracted characters; scanned PDFs require OCR. Attaching a file to another name preserves an independent copy, so removing it from one name leaves other names and files intact. Workspace members can read files; administrators can upload, attach, and remove them. The **Source Library** page (`/source-files`) lists every uploaded file once, with the names it is attached to; files with identical content are one entry, and deleting an entry removes that content from every name, so later research and Stan no longer read it.
- Research snapshots attached file identities at dispatch. Selected excerpts use at most 36 KB of the existing 80 KB private-context allowance; omitted or partial files are identified as gaps. Uploads enter extraction and verification through the private-only pipeline and never enter public search requests. Their citations retain **Private upload: filename** attribution and link to authenticated original-file downloads. Existing run checkpoints retain captured evidence; new runs and agent reads use the files currently attached to the name. Stan can list and page through these sources in a new chat without reattachment.
- When source gathering stops early, the finishing reserve can verify the evidence already collected. Its draft lists unresearched quarters or sections explicitly and remains incomplete; it cannot publish a company-sheet summary.

## Quality checks

1. Resolve issuer identity and the last 20 reported fiscal quarters, with dates and primary sources. Assign each overview section to a topic.
2. Research management in five four-quarter packets, splitting a truncated packet into two and then individual quarters. Research overview topics separately. Reuse the verified fiscal-calendar sources.
3. Validate exact quarter coverage, dates, source passages and tool-observed URLs. Ignore URL tracking parameters without removing document-identifying query parameters, and resolve genuinely new citations with a focused source check. A documented unsuccessful source search is different from a quarter that was never researched.
4. Group related initiatives for independent source verification. Every original record must be retained or explicitly rejected. Original promises and deadlines cannot be rewritten; concluded outcomes require later dated evidence.
5. Extract source evidence with medium reasoning, then use maximum reasoning for reconciliation, narrative judgments and audits. Verification returns compact decisions and corrections without regenerating the ledger; writing/auditing uses packets of up to two sections. Permit one repair of an unsupported section or summary. Deduplicate source passages without shortening evidence.
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

The October 17, 2026 EL pilot did not complete either report within its source-gathering allowance. It retained 19 management commitments across four fiscal quarters. The pilot exposed equivalent quarter-label formatting, citation tracking parameters and repeated evidence payloads; these led to parser normalization, focused citation checks and compact verification decisions. In-flight requests retained their initial, slower reasoning settings, so this pilot does not establish the final configuration's full-report completion rate or equivalence to ChatGPT Deep Research. Keep incomplete reports clearly labeled and evaluate completion quality on subsequent explicitly authorized runs.

Deploy the additive Alembic migration before the new API/worker. The normal `./infra/gcp/deploy-all.sh` sequence does this. The migration retains legacy state. After rollout, verify the deployed commit and migration health, then exercise authenticated settings/status/report endpoints without starting an unapproved paid run.
