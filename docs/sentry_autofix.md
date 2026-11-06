# Automatic Sentry fixes

Seer creates pull requests for Talisman issues. GitHub runs CI and automatically
merges and deploys only the small changes accepted by `scripts/sentry_autofix.py`.
The controller on `main` makes the decision; pull request code cannot change its
policy or gain deployment credentials before merging.

## Qualification

- The PR must be opened by the verified `sentry[bot]` account, in this repository,
  targeting `main`, and link a Twinleaf Sentry issue.
- At most five files and 200 added plus deleted lines may change.
- Application edits are limited to the explicit UI component, presentation
  utility, and JSON serializer allowlist in the controller. Authentication,
  financial logic, agent execution, database state, migrations, dependencies,
  observability settings, deployment configuration, and workflows are excluded.
- A test file must add an assertion. Existing test lines cannot be removed,
  and skipped or focused tests are rejected. This checks coverage presence;
  the workflow does not independently prove that the test failed before the fix.
- Every existing CI job must succeed for the current PR head. Skipped checks,
  stale runs, a branch behind `main`, and requested changes prevent merging.
- Unshipped application changes on `main` must be deployed separately first.
- A previous failed or unfinished automatic deployment blocks the next one.

Ineligible PRs remain open for normal review. No label can override these rules.
GitHub branch protection must require the CI jobs with the strict up-to-date
branch requirement. The controller never bypasses branch protection.

## Deployment and recovery

The `Sentry autofix` workflow reacts to a completed PR CI run. After qualification
it checks production readiness, verifies the PR again, squash-merges it, and
deploys that exact merged commit in the same workflow. This avoids relying on a
push event from `GITHUB_TOKEN`, which does not trigger downstream push workflows.

Google Cloud authentication uses short-lived GitHub OIDC credentials restricted
to this repository and this workflow on `main`. A separate build identity can
read staged source, write images, and write build logs. The deployment identity
can update the existing Talisman runtimes and Firebase Hosting. No service account
key is stored in GitHub.

The rollout snapshots the existing Cloud Run resource definitions and Firebase
release, builds an image, updates the API, async job, top-50 job, and worker pools,
then runs the viewer smoke checks. It deploys Firebase only after backend smoke
passes. The workflow preserves runtime configuration and does not run migrations.

On a caught rollout failure it attempts to restore the previous Cloud Run
definitions and Firebase version. The GitHub deployment remains failed and
prevents another automatic release even if recovery succeeds. Cancellation,
runner loss, or a failed recovery requires operator investigation. Rollback does
not undo application data writes or revert the merged Git commit.

## Controls and setup

`SENTRY_AUTOFIX_ENABLED=true` enables automatic shipping. Set it to `false` to stop
new merges. This does not interrupt a deployment that already started.

Repository variables:

- `GCP_PROJECT_ID`
- `GCP_AUTOFIX_WIF_PROVIDER`
- `GCP_AUTOFIX_SERVICE_ACCOUNT`
- `AUTOFIX_BUILD_SA`
- `AUTOFIX_BUILD_BUCKET`

Repository secret: `GCP_AUTOFIX_DEPLOY_CONFIG`, containing the existing
`infra/gcp/config.sh`. Runtime secrets stay in Google Secret Manager. Generated
OIDC credentials and local deployment configuration are excluded from images
and source uploads.

Configure Seer for the `talisman` project with automatic issue scans, fixes for
highly actionable issues, and a stopping point of opening a pull request.
Connect the project to `ShaivPandya/talisman`. Seer activation and any subscription
must be completed in Sentry before new fixes can arrive.

Run `Sentry autofix` manually with no CI run ID to check cloud access without
changing production. Supply a successful PR CI run ID with `dry_run=true` to
check its qualification and baseline without merging. Manual runs from branches
other than `main` cannot deploy.

After a failed release, inspect the workflow logs and verify or restore production.
Revert the merged change if appropriate. Only after recovery, mark the failed
GitHub deployment `inactive` to clear the release lock. Do not clear a pending
deployment while its workflow is still running.

References: [Seer](https://docs.sentry.io/product/ai-in-sentry/seer/),
[GitHub workflow triggers](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[Google Cloud OIDC](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).
