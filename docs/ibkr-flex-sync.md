# Automated IBKR Flex reconciliation

This integration reads account statements and stages changes for human approval.
It never places orders or applies holdings or NAV changes silently. Yahoo, FRED,
and EDGAR continue to supply research inputs.

## Configure the query

In IBKR Client Portal, create a single-account **Activity Flex Query**, XML format,
for **Last Business Day**. Include:

- Account Information: account/base currency (USD is required for NAV proposals).
- Open Positions: all held asset categories, symbol, underlying symbol, quantity,
  side, multiplier, currency, FX Rate to Base, listing exchange, report date,
  cost basis price/money, position value, mark price, FIFO unrealized P&L.
- Options: expiry, strike and put/call.
- Futures: underlying symbol/root and multiplier, especially for nonstandard contracts.
- Lot detail, if wanted: Level of Detail, Open Date Time, originating transaction ID.
  Summary and lot rows may coexist; the importer counts each holding once.
- Cash Report: per-currency ending cash and ending settled cash.
- Equity Summary in Base: report date and total (net liquidation value).

Unknown nonzero assets, multiple accounts/dates, missing quantities, malformed or
empty positions, inconsistent lot totals and ambiguous NAV are rejected to avoid
proposing a partial book replacement. Cash balances are statement records, not
synthetic investments in the portfolio sizing models. A cash-only statement
requires manual reconciliation because empty securities cannot clear the book.

Enable Flex Web Service and obtain its token and query ID. These are reporting
credentials, not the account password. Never commit them or paste them into logs.
[IBKR Flex setup](https://www.interactivebrokers.com/docs/web-api/flex-web-service/introduction)

## Deployment

1. In ignored `infra/gcp/config.sh`, set `SCHEDULE_IBKR_FLEX_SYNC=1`.
2. Run `infra/gcp/setup-secrets.sh`. It prompts silently for `IBKR_FLEX_TOKEN`
   and `IBKR_FLEX_QUERY_ID`, stores both in Secret Manager, and grants API/worker
   secret access. Existing credentials are preserved.
3. Run `infra/gcp/setup-ibkr-flex-egress.sh` once. It provisions a dedicated
   subnet, Cloud NAT router, and reserved outbound IP in the existing GCP project.
   The reserved IP costs about $3.60/month, plus NAT usage and data transfer.
   It is retained across deploys; do not delete or rotate it during releases.
4. Deploy the backend using the normal release process. When Flex is enabled,
   it also deploys `talisman-ibkr-flex-sync`, a dedicated async executor using
   Direct VPC egress through that NAT. The API routes only `ibkr_flex_sync` jobs
   to this executor through `CLOUD_RUN_JOB_IBKR_FLEX_SYNC`; other job types keep
   their existing dispatch. For a component release, deploy
   `infra/gcp/deploy-ibkr-flex-job.sh` before `infra/gcp/deploy-api.sh`.
5. Run `infra/gcp/setup-scheduler.sh`. It creates `ibkr-flex-sync` with the same
   scheduler/proxy-secret authentication as other maintenance jobs.

The dedicated executor uses the worker service account, Cloud SQL, and the
existing durable async job runner. It binds only the database, Flex, and optional
Sentry credentials. Its deploy script grants the API permission to execute it
with the job-ID override. Egress resource names and subnet range can be overridden
using the `IBKR_FLEX_EGRESS_*` settings in `config.example.sh`.

IBKR can deny Cloud Run's shared outbound IP before validating credentials. An
HTML HTTP 403 page naming the source IP is distinct from the Flex XML error codes.
If a cloud request fails while an identical local request succeeds, inspect a
redacted denial page and the configured NAT route before replacing credentials.
On October 29, 2026, shared IP `34.96.60.179` received HTTP 403 even without a
token; the identical request succeeded through reserved IP `35.223.87.162`.
No alternate broker host, third-party proxy, or TLS verification bypass is used.

[Google's static egress guide](https://docs.cloud.google.com/run/docs/configuring/static-outbound-ip)
and [Cloud NAT pricing](https://cloud.google.com/nat/pricing) describe this setup.

Default: weekdays at **16:35 America/New_York**. Override with
`IBKR_FLEX_SYNC_SCHEDULE` and `IBKR_FLEX_SYNC_TIME_ZONE`. Activity data normally
covers the previous business day: the actual statement date is always visible.
A statement older than the previous market session is treated as stale, including
holiday/weekend handling. Set the enable flag to `0` and rerun scheduler setup to
remove the scheduled trigger. No infrastructure is provisioned by the application.

For local use, supply the two values through `.env`. An authenticated admin can
POST `/api/admin/jobs/enqueue-ibkr-flex-sync`; the normal async job endpoint exposes
completion/failure. The job does not accept arbitrary broker URLs or credentials
from its payload. Fixed IBKR HTTPS endpoints prevent broker-returned URLs from
redirecting credentials. Requests/polling and statement size are bounded.

## Review and failure handling

The portfolio editor shows sync state, report date, broker marks in instrument
currency, unrealized P&L in base currency, cash, NAV and available lot open dates.
Use Workspace to review portfolio/hedge/settings proposals. NAV respects existing
book-size bounds ($10,000–$10,000,000); the $100,000 default remains until a book
size is configured or approved. An out-of-range or non-USD NAV fails validation.

A matching pending proposal is reused. Unchanged holdings generate no new holding
proposal even when marks/date change. New marks remain visible in the statement
panel. Broker-owned hedges missing from a subsequent statement can be removed by
approval; manually managed hedges are retained. Conviction, contrarian and group
metadata carry forward, and research documents are not written.

Failed/empty/stale pulls retain the last successful snapshot and approved book.
The panel and async job show the failure. Expired tokens require replacement in
Secret Manager and a normal service/job restart to load the new version. Manual
XML upload remains available and uses the same parser and approval staging logic.
