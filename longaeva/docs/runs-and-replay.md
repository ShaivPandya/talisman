# Runs and replay (LON-23)

Submit a Visa Monte Carlo run, execute it on the Postgres-backed worker, persist
path outputs and hashes, replay without an LLM, and optionally archive immutable
forecasts.

## Lifecycle

1. `POST /runs` with `scenario_id`, `cutoff_ts`, `seed`, `n_paths`, optional
   `n_quarters` and `switches`. Returns **202** and a queued `run` plus `job_id`.
2. The worker claims the `run` job, executes `engine.simulate`, writes
   `runs/<run_id>/paths.npz`, and stores `outputs_hash`, `summary`, `code_version`,
   and `lib_versions`.
3. `GET /runs/{id}` shows status. `GET /runs/{id}/results` returns per-metric
   per-quarter summaries after success (409 until then).
4. `POST /runs/{id}/replay` and `python -m longaeva_app.cli replay RUN_ID`
   re-simulate from pinned inputs and compare hashes. They write nothing.
5. `POST /runs/{id}/forecasts` with `{ "kind": "retrospective" | "prospective" }`
   writes the immutable archive (explicit; never automatic).

CLI helpers (Compose):

```bash
make submit-run ARGS='--origin 2024-07-23 --n-paths 64 --inline'
make replay RUN=<run-uuid>
```

`--inline` executes in the CLI process (claims the job). `--wait S` polls the
worker. With no `--scenario`, an all-assumption uncalibrated baseline is created
and reused by content hash.

## Starting state (decision 1a)

Only the two LON-3 fixtures are runnable:

| Origin date | Cutoff (UTC) | Label |
| --- | --- | --- |
| 2024-07-23 | 2024-07-23T20:05:38Z | FY2024Q3 |
| 2025-10-28 | 2025-10-28T20:06:03Z | FY2025Q4 |

`cutoff_ts` may match the exact cutoff or that UTC date. Committed fixtures take
precedence; other `origins.csv` candidate/prospective cutoffs are built by
`companies/visa/state_builder.py` (LON-27). Unknown cutoffs still return 422.
A scenario may carry interventions (LON-22). Submit parses them, rejects an
unknown type or a `start_quarter` past `n_quarters`, and pins `run.interventions`
plus `run.interventions_hash`. Replay adds `interventions_hash` to the
`inputs_changed` differences when the scenario list no longer matches that pin.

The run stores a copy of the numeric starting state and `starting_state_hash`.
The source manifest lists fixture **input** documents as
`{document_key, content_hash, publication_ts, source_id?}`; `source_id` is linked
when a collected `source` row exists and is **omitted from the hash**.

## Record fields (FR-09)

| Field | Meaning |
| --- | --- |
| `cutoff_ts` | Origin cutoff |
| `source_manifest` / `source_manifest_hash` | Documents eligible at the cutoff |
| `parameter_set_hash` | Hash of the scenario's parameter set (UTC-normalized `cutoff_ts`) |
| `starting_state` / `starting_state_hash` | Numeric origin state |
| `code_version` | `package version` + SHA-256 of `engine/`, `companies/`, `hashing.py` (no git) |
| `seed`, `n_paths`, `n_quarters`, `switches` | Simulation knobs (switches stored after merging defaults) |
| `lib_versions` | Python, NumPy, BLAS, OS/machine, CPU SIMD of the **worker** process |
| `outputs_path` | Relative artifact key `runs/<id>/paths.npz` |
| `outputs_hash` | Canonical path-array hash (not the npz file bytes) |
| `summary` | Per-metric, per-quarter mean / std / MC SE / quantiles |

`code_version` and `lib_versions` are written by the worker. Submit stores
`code_version=pending` until success.

## Outputs hash

Format version 1: SHA-256 of a canonical JSON header (periods, sorted array
names, dtype `float64`, shapes) followed by little-endian float64 bytes of
every metric array then every state array, each prefixed with its name.
Dict order does not matter. The compressed npz is a convenience artifact only.

## Replay statuses (ER-03 / UF-06)

Replay never calls an LLM (`LLM_PROVIDER` may be unset). Statuses:

| Status | Meaning |
| --- | --- |
| `exact_match` | Recomputed outputs hash equals the recorded hash |
| `numerically_equivalent` | Hash differs, but max relative array (or summary) difference ≤ 1e-9. Code-version and library differences are listed. Covers macOS Accelerate vs container OpenBLAS. |
| `mismatch` | Difference exceeds 1e-9 |
| `inputs_changed` | Parameter-set, starting-state, manifest, or interventions hash no longer verifies |

CLI exit codes: 0 for exact or numerically equivalent, 1 for mismatch or
inputs_changed, 2 on error.

Host-vs-container: bit-exact replay is guaranteed only inside the same
numerical environment. Observed 2026-10-03 on this machine: a Compose-created
FY2024Q3 run (`n_paths=64`) replayed inside Compose as `exact_match`. The same
run replayed from the host virtualenv was `numerically_equivalent`
(max relative difference ~1.9e-16) with `lib_versions.blas` differing
(`scipy-openblas` in the container vs macOS `accelerate`).

## Forecast archive (decision 2a / FR-17)

`POST /runs/{id}/forecasts` requires a succeeded run, an empty intervention list
on both the scenario and the pinned run, and a
parameter set with at least one evidence-backed parameter (uncalibrated defaults
cannot be archived). Declared `kind` must match whether the next quarter's
results are already published in `data/fixtures/origins.csv` at archive time:
`prospective` only if unpublished, `retrospective` only if published. Rows are
written for net revenue, operating profit ex special items, and the three
driver growth metrics across the horizon (20 rows for four quarters). A second
archive of the same run returns 409. Forecast rows cannot be updated or deleted.

## Handoffs

- **LON-11:** `GET /runs` and `GET /runs/{id}/results` are the minimal run-page contract.
- **LON-22 (done):** interventions are runnable. Comparison and attribution live
  under `/scenarios`; see [`docs/scenarios.md`](scenarios.md). The archive still
  refuses them.
- **LON-24:** `make submit-run` / `make replay` work from an empty database with
  the two bundled fixtures (no collector required).
- **LON-27 (done):** state builder + evaluation harness reuse `submit_run` /
  `execute_run`; see [`docs/evaluation.md`](evaluation.md).
- **LON-32:** the builder produces the FY2026Q3 prospective starting state at
  2026-07-28.
- **LON-37:** bundle run rows plus `paths.npz`.
