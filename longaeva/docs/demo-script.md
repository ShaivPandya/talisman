# Offline demo (LON-37)

Start Docker Desktop, then run `make up` from the package directory. Migrations and the validated seed finish before API health becomes ready. No provider credentials or collection command are needed. `make seed` explicitly repeats the same import.

The demo contains two historical origins, six completed historical runs (baseline, mix shift and spending reduction for each), 40 retrospective forecast rows, and the original 20-row prospective archive. Historical examples use 5,000 paths, four quarters and seed 22. Mix shift changes cross-border share by −10%; spending reduction is 5%, both from quarter 1. These are illustrative interventions.

## Walkthrough

For the in-app version, open [How to use](http://127.0.0.1:3000/guide) and select
**Start product tour**. The docked instructions highlight the real page and follow
the July 23, 2024 starting state, Evidence & Review, scenario controls, the saved
−10% cross-border mix-shift comparison, baseline valuation, historical evaluation,
the unscored prospective registration, and baseline replay. Optional actions use
the regular page controls; Next never submits a simulation, review, rule application,
or replay. The static guide also links directly to methodology, model specification,
the failure case, and limitations.

**Product tour** is available on every page. Exit leaves the current page and inputs
intact. A later launch offers Resume or Restart; progress uses versioned local browser
storage with an in-memory fallback when storage is disabled. Reload does not reopen
the tour. Manual navigation pauses it and offers Return to tour step. Tour navigation
warns before discarding unsaved scenario, observation-review, or mapping-rule edits.
Unavailable content offers retry, skip, and exit. Source dialogs include Exit tour;
Escape closes the dialog first, or exits the tour when no dialog is open.

1. Open [State & Evidence](http://127.0.0.1:3000/state?origin=2024-07-23). Inspect period, units, accounting basis and the source excerpt for net revenue. Repeat with October 28, 2025. Post-cutoff checks are labeled separately.
2. Open the Evidence & Review tab. Search for “Room nights”, select a Booking observation, and inspect its exact retained quote and review history. Existing gate/parser acceptance rationales are preserved; they are not newly claimed human labels. Accept, adjust or reject with a rationale; reload to confirm the new decision survives.
3. Open a saved comparison below. Inspect net-revenue and operating-profit fan charts, path-wise differences, paired conditions, and conditional attribution. The mix-shift example conserves total payments volume on every path.

- [2024-07-23: mix shift](http://127.0.0.1:3000/scenarios?origin=2024-07-23&baseline_run_id=cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d&run_id=3752b7df-c114-5fa4-b312-efe5a5908c38)
- [2024-07-23: spending reduction](http://127.0.0.1:3000/scenarios?origin=2024-07-23&baseline_run_id=cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d&run_id=ab595be3-2964-5845-b6f3-4d8d4fce6bf3)
- [2025-10-28: mix shift](http://127.0.0.1:3000/scenarios?origin=2025-10-28&baseline_run_id=846c4e0b-a634-5bed-996d-3785bb899846&run_id=20673695-fcda-54a8-8020-3d670ee80847)
- [2025-10-28: spending reduction](http://127.0.0.1:3000/scenarios?origin=2025-10-28&baseline_run_id=846c4e0b-a634-5bed-996d-3785bb899846&run_id=db0ff361-957b-5148-8299-6c71d0313f57)

4. Open [Runs](http://127.0.0.1:3000/runs), select a historical baseline, then follow Valuation & Actions. Inspect separate earnings/multiple uncertainty, the illustrative position and each cost component. The reference price remains a quarterly buyback average.
5. Open [Evaluation](http://127.0.0.1:3000/evaluation). Inspect 16 scored origins and two exclusions, matched baselines, ablations, extraction scores, benchmark labels and the failure case under Report & model. These are saved evaluation snapshots; the six demonstration paths are separate illustrative runs and do not replace their original evaluation run IDs.
6. Open [Replay](http://127.0.0.1:3000/replay), select any of the seven seeded runs, and click Replay. Expect `exact_match` with matching hashes in the recorded runtime. Across platforms, the existing engine may report `numerically_equivalent` within its 1e-9 tolerance; both hashes and runtime differences remain visible. Replay uses no LLM provider. The prospective Q4 FY2026 registration remains unscored with its original creation time.

CLI replay example:

```bash
make replay RUN=cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d
make replay-prospective
```

## Safe repeat and recovery

Restarting with `make up` or running `make seed` again reports reused rows. Later review decisions, user scenarios and unrelated data are preserved. Missing matching artifact files are restored. An interrupted transaction commits no demo records; matching files copied before interruption can be reused. Corrupt files or conflicting immutable rows stop startup with an error; preserve the local database and investigate the reported record rather than resetting it.

The seed is offline even if a provider is configured. It never queues jobs, recalibrates, captures model responses, scores outcomes or re-registers the prospective forecast. Completed runs have no active job reference.

## Curator rebuild

The packaged `data/demo/prospective-records.json` is the dependency closure captured from the original LON-32 archive. Its frozen run and forecast IDs/timestamps are checked against the unchanged registration. To rebuild historical examples, use an empty, migrated disposable PostgreSQL database and a separate artifact directory:

```bash
cd backend
DATABASE_URL=postgresql://longaeva:longaeva@127.0.0.1:55437/longaeva \
ARTIFACT_DIR=/tmp/longaeva-demo-build LLM_PROVIDER= \
  .venv/bin/python -m longaeva_app.cli build-demo
```

Generation refuses a nonempty database. It reads retained fixtures and saved reports; Census PDFs needed by the two origins and the prospective dependency closure are retained in `data/demo/originals/`. It requires exact replay for the six newly generated runs and accepts the existing cross-platform tolerance for the original prospective archive. Generation timestamps and review times are actual build times; deterministic UUIDs make historical run links stable. Use the recorded runtime when exact hash equality matters; the bundled runs retain their original runtime fingerprints.

Per-file input inventory: [data-license-inventory.csv](data-license-inventory.csv).
