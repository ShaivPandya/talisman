# Action-item research

Workspace and position dossiers offer **Run with Stan** for open, ticker-specific
research/review items involving a thesis, measurable kill conditions, or valuation.
The manual completion/dismissal flow remains available for work performed outside
Stan. Trading action types do not enter the research runner.

## Flow

1. Starting an item creates a durable execution and reserves its full per-run
   allowance against the owner's daily budget. Repeated starts reuse that execution.
2. Stan snapshots the task and dossier, plans completion requirements, gathers public
   evidence, writes a structured result, and audits the result. Only fixed public
   topics, validated fiscal periods, and a validated ticker go to web search; the private task/dossier are used
   in separate requests with the existing egress controls.
3. Sources must have passages and locations, and their URLs must occur in the
   provider's web trace. Every requirement needs a supported check. Valuation input
   dates and calculations are validated in code; market observations older than seven
   days and consensus observations older than 90 days need review. A separate evidence
   audit checks the report against the original task and retained evidence. These
   automated checks support owner review; they do not establish source truth by themselves.
4. Thesis content and kill conditions are staged through the ontology command service.
   The item stays open. The result view links to the existing approval review flow.
5. After required changes have been approved and applied, **I reviewed the results ·
   Propose Complete** stages a completion proposal containing the execution and
   workflow references. The owner approves that proposal. Research-only valuation
   tasks require report review before this step.

Failures, missing evidence, rejected proposals, and changed task inputs leave the
item open. Cancellation fences further checkpoint/proposal writes. Retry continues
retained work and known provider response IDs, without resetting the budget. For
missing information or requested corrections, the result dialog accepts additional
information and starts a new attempt within the original allowance, retaining the
previous attempt in execution history. A submission with an unknown provider outcome
keeps its full reservation and is not silently resubmitted.

## Runtime and rollout

- Apply Alembic revision `20261029_0001` using the repository's migration process.
  This adds `action_item_executions` with a unique owner/item constraint and an
  owner/time index. Production uses Postgres; isolated tests use SQLite.
- Deploy the API, frontend, and generic async job image together. Jobs register as
  `action_item_execution` and `action_item_automatic`; production uses the existing
  generic Cloud Run job. No new service or agent framework is required.
- `ACTION_ITEM_EXECUTION_ENABLED=false` disables starts and retries. The default is
  `true`; automatic processing defaults to `false` for every owner.
- Research uses the existing `OPENAI_API_KEY` and the company research model,
  currently `COMPANY_RESEARCH_MODEL=gpt-6.1-sol`. Its conservative pricing envelope
  is shared with the company-research provider. Update that envelope when its pricing
  version changes. No external requests occur in the automated test suite.
- Each execution has a 20-minute window, a fenced 120-second lease renewed every
  15 seconds, and persisted response IDs/checkpoints. Polling recovers interrupted
  runs; the generic job timeout also bounds abandoned jobs. Results remain in the
  execution store and workflow artifacts after async-job expiry.
- Research settings control supported categories, concurrent runs (default one),
  the per-run allowance (default $5), and daily reservations (default $15). A full
  run allowance remains reserved for that UTC day. A retry on another day reserves
  its original allowance against that day's cap as well.

## Automatic processing

Enable automatic research in Workspace's research settings. Only eligible items
created after opt-in are selected. **Run eligible backlog** explicitly starts existing
items within the same budget and concurrency limits. Rejected or interrupted runs
require owner intervention rather than repeated automatic execution.

For recurring production dispatch, set `SCHEDULE_ACTION_ITEM_RESEARCH=1` when running
`infra/gcp/setup-scheduler.sh`. The optional `action-item-research` scheduler calls
`POST /api/admin/jobs/enqueue-action-item-research` every five minutes by default.
It uses the existing scheduler/admin authentication. This implementation does not
enable or deploy that production schedule by itself.

The UI reports progress and calls attention to ready, blocked, and failed research.
It does not send email or external notifications. Changes and completion always
retain owner approval.

## Verification

`tests/test_action_item_execution.py` covers the three research types with a fake
provider and durable storage, HTTP contracts, concurrency, cancellation, lost
leases, provider recovery, evidence rejection, valuation checks, budget limits,
and automatic selection. Existing async-job, approval, and workflow tests cover
the reused infrastructure. Browser verification uses a local API with a fake
provider, so it does not spend research credits or change live portfolio records.
