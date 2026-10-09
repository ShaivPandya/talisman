# Longaeva

Longaeva simulates how changes in spending, travel and pricing affect Visa’s
revenue, profit and valuation. Start with published financial evidence, change
business assumptions, and compare a range of possible outcomes over the next four
quarters.

Every starting figure links back to its source. Saved runs preserve their inputs
and results, so you can inspect an assumption, understand its effect, and replay
the calculation.

## What you can do

- **Trace the evidence.** Explore Visa disclosures and related economic and
  company data, with publication dates, source excerpts and original links.
  Review AI-extracted observations before applying them to model assumptions.
- **Test a scenario.** Shift spending between domestic and cross-border payments,
  reduce total spending, or adjust other business drivers. Compare a baseline
  and a variant using shared random draws to make their differences easier to
  interpret.
- **Explore uncertainty.** Run thousands of simulated paths and inspect revenue
  and operating-profit ranges, sensitivities and the drivers of each change.
- **Connect operations to valuation.** Separate earnings uncertainty from
  valuation-multiple uncertainty and compare illustrative hold, add, trim and
  exit decisions with transaction costs.
- **Check the model.** Compare historical forecasts with observed outcomes and
  simpler baselines. Inspect forecast errors, interval coverage and a documented
  failure case.
- **Reproduce a result.** Reopen saved comparisons and replay runs from their
  recorded inputs, seeds and runtime information.

## Run locally

The app binds to localhost and has no login. After either startup below, open
**http://127.0.0.1:3000**. Start with **How to use**, or launch the
five-to-seven-minute **Product tour**.

Startup loads two historical starting states, seven saved runs, historical
evaluations, and a saved forecast awaiting results. You can explore them
immediately or run new scenarios. No API keys are required.

### With Docker

Install Docker Desktop with Docker Compose and start Docker. From this directory:

```bash
make up
```

The first build downloads dependencies. After that, the demo does not download data.

To stop:

```bash
make down
```

Saved data remains in Docker volumes. Run `make up` to resume; startup preserves
existing records and reviews. Use `make logs` to inspect a startup or worker error.

### Without Docker

Install Python 3.12 or newer and Node.js 20.19 or newer. From this directory on
macOS or Linux:

```bash
make up-local
```

On Windows PowerShell:

```powershell
.\scripts\up-local.ps1
```

The command creates a virtualenv, installs the locked Python packages and web
dependencies, and on first run downloads PostgreSQL 16 into `var/`. That download
needs a network connection. Later runs reuse the virtualenv, `node_modules`, and
the downloaded database server.

If port 55432 is occupied, choose another database port with
`make up-local ARGS='--db-port 55439'`.

To stop:

```bash
make down-local
```

On Windows: `.\scripts\up-local.ps1 -Down`

`make down` stops only the Docker stack. `make down-local` stops only the
no-Docker stack. Windows on ARM and Alpine Linux are not supported for this path;
use Docker there.

## Try a comparison

1. In **State & Evidence**, select the July 23, 2024 starting state and open a
   financial figure to see its supporting disclosure.
2. In **Scenarios**, open the saved cross-border mix-shift comparison. Inspect
   how the variant changes revenue and profit while holding total payments
   volume constant.
3. Change an assumption and submit a new paired run. Compare the outcome ranges
   and the model’s attribution of the difference.
4. Open **Valuation & Actions** to see how the operating results translate into
   valuation ranges and illustrative decisions.
5. Visit **Evaluation** to examine historical accuracy and the failure case,
   then **Replay** to reproduce a saved run.

The [walkthrough](docs/demo-script.md) and [workspace guide](docs/workspace.md)
explain the controls and examples in more detail.

## Reading the results

Outputs are conditional on the model and its assumptions. The simulated profit
measure excludes special items. Scenario attribution describes relationships
inside the model; it does not establish real-world causality.

The historical evaluation covers 16 scored origins, with sample counts reported
for each metric. Historical cutoffs do not remove retrospective model-design or
pretrained-model knowledge. The saved Q4 FY2026 forecast is unscored; its evidence
cutoff and actual registration time are shown separately. Valuation examples use
a disclosed quarterly buyback-price reference, not a live share price.

Replay is exact in the same numerical environment. Across numerical libraries,
bundled runs may be reported as numerically equivalent within the documented
1e-9 tolerance. See the [evaluation report](docs/evaluation-report.md),
[model specification](docs/model-spec.md) and [limitations](docs/limitations.md)
for methods, measured results and caveats.

## Development and configuration

The application uses FastAPI, PostgreSQL and a Python/NumPy simulation worker,
with a React frontend. Interactive API documentation is available at
http://127.0.0.1:8000/docs while the app is running.

```bash
make check   # Backend and frontend checks, tests and production build
```

For live source collection or fresh AI extraction, copy `.env.example` to `.env`
and configure the relevant provider. See [extraction](docs/extraction.md) and
[passage search](docs/search.md). Credentials are optional for the included demo.

## Packaging and source data

```bash
make export  # Creates a ZIP and SHA-256 sidecar under dist/
make verify-export ZIP=dist/<archive>.zip LOG=/tmp/longaeva-validation.md ARGS=--final
```

Final verification checks the archive and starts a separate, temporary stack to
run tests, exercise application flows and verify replay. A failed check stops
verification; correct the source and rebuild the archive before trying again.

[Data provenance and terms](docs/data-licenses.md), the
[per-file inventory](docs/data-license-inventory.csv) and
[component reuse notes](docs/reuse-notes.md) document the included sources and
adapted components.
