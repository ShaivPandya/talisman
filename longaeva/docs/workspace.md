# Scenario workspace (LON-34)

Start with `make up`, then open the web app on port 3000. State & Evidence and
Scenarios work on an empty database, without collector commands, internet data
access, or LLM credentials. The workspace uses the two bundled calibrated origins:
2024-07-23 (FY2024Q3) and 2025-10-28 (FY2025Q4).

## Inspect the starting state

Open **State & Evidence**, choose an origin, and inspect the values grouped into
activity/yields, revenue/profit, and valuation inputs. Each row shows its fiscal
period, unit, basis and measured/derived/unavailable status. Derived rows expose
the formula and inputs; supporting levels have their own source links.

**View source** opens a read-only passage panel. The server slices at stored
Python character offsets before converting retained HTML to display text. The
panel shows the quote, context, source ID, timestamp and original-document link.
Later reconciliation documents are listed separately and never become eligible
inputs. Missing evidence, out-of-bounds spans and mismatched quotes are explicit.
Some image-era calibration references inherited from the parser have mismatched
offsets; they retain their source links but do not display a fabricated highlight.
The saved calibration, model values and evidence IDs are unchanged.

## Define and run a pair

**Build a scenario** carries the origin into Scenarios. Enter a variant name,
select either or both interventions, and edit their magnitude/start quarter.
The default mix shift is −10%, conserving total spending. Spending reduction is
5% when enabled, with processed transactions unchanged and lagged service revenue.
Both persist from their start quarter; cross-border share must remain feasible.

The eight free business drivers appear first. Advanced contains seasonality,
shock scales, correlations and model assumptions. Controls display percentage
values for growth, drift, volatility and share parameters; seasonal ratios,
correlations and international FX sensitivity remain raw ratios. Baseline values,
calibrated ranges, hard model bounds and evidence/rationale links are visible.
Ranges are read-only. Every overridden value requires a rationale and is persisted
as an assumption in a child parameter set, retaining the original evidence links.

**Run paired scenarios** creates fresh grouped baseline/variant definitions and
submits both through the existing worker. Defaults are four quarters, seed 22,
and 5,000 paths. Seed and path count are editable in Advanced. Status refreshes
every two seconds while either run is active and stops once both are terminal.
Validation errors preserve the draft. A failed submission is never automatically
retried; check Runs before retrying an ambiguous connection failure.

The saved comparison URL contains both run IDs and the origin. Reload it, or use
**Compare pair** in Runs, to read the saved results. Editing a draft does not alter
previously saved outputs. Charts offer net revenue, operating profit excluding
special items, payments volume, cross-border volume, transactions and service
revenue. Difference intervals are variant minus baseline from saved paths,
including negative/cross-zero bands; they are not differences of marginal quantiles.

Attribution loads separately, verifies the pair, and shows contributions,
sequential order, joint residual, rule/source IDs and sensitivity/support flags.
Every effect is conditional on the model. Source drilldowns work for database
observations and bundled calibration evidence. A manual intervention or override
has no mapping-rule ID; the UI says so explicitly. The sensitivity ranking is for
horizon net revenue, including when operating-profit contributions are inspected.

## API additions

| Method | Path | Result |
| --- | --- | --- |
| GET | `/workspace/origins` | Bundled calibrated origin dates, labels and cutoffs |
| GET | `/workspace/origins/{origin_date}` | State, supporting levels, excerpts, input/later sources, parameter specs |
| POST | `/workspace/origins/{origin_date}/prepare` | Persist/reuse bundled calibrated parameter set; repeated and concurrent requests are idempotent |
| GET | `/parameter-sets/{id}/evidence?parameter=...` | Evidence/assumption metadata, resolved excerpts and parameter updates/rules |

Preparation uses a transaction-scoped PostgreSQL advisory lock and the existing
content hash; it does not recalibrate or change existing scenario pair groups.
The existing scenario, paired-run, comparison and attribution contracts remain
in use. Full demo seeding is LON-37; review editing is LON-35.

## Validation record

LON-34 was checked from a standalone ZIP extracted outside the parent repository,
using a separate PostgreSQL database and worker with no collector or LLM setup.

- Backend lint, formatting, mypy and PostgreSQL suite: 434 tests passed.
- Frontend lint, TypeScript/production build and Vitest: 19 tests passed.
- Strict isolation guard: zero findings.
- Playwright UF-01/UF-03: both origins, retained source highlights, explicit
  unavailable evidence, required override rationale, queued-to-succeeded pairs,
  saved chart/attribution reload, and parameter rationale drilldown passed.
- Submitted mix-only, spend-only, and combined interventions with a parameter
  override. All three pairs used 5,000 paths and reported exact verification.
- Saved-path assertions confirmed that mix shift preserves payments volume on
  all paths and quarters. Spending reduction preserves first-quarter service
  revenue and processed transactions, with lower service revenue thereafter.
- Inspected desktop and 390-pixel layouts, negative difference bands, and mobile
  tables; no page-level horizontal overflow or browser console errors occurred.

The container registry stalled while resolving the nginx runtime image. The
exported frontend was therefore built and served with the already installed
nginx image as its build context; application sources, checks and assets came
from the export. No container configuration was changed for this workaround.
