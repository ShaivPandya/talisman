# Reviewer package validation — October 9, 2026

## Acceptance summary

The rebuilt archive passed full Docker export verification and native macOS startup
from a separate, fresh unpacked copy. The archive contains 530 files and matches the
source package and retained standalone repository, including executable permissions.

- ZIP SHA-256: `9598514fadb57dce103b1a06df50072e2cc85159951c5c73c8bae268781d2870`; size: 43,798,010 bytes. The checksum sidecar matches.
- Backend: 561 PostgreSQL tests passed; lint, formatting and mypy passed (206 source files).
- Frontend: lint and production build passed. Docker Vitest passed 43 tests and skipped its data-dependent tour assertion because that image has no package data. Native Vitest ran all 44 tests with exported data present; all passed, with no skips.
- Strict isolation guard: zero findings. All 191 data-license inventory checksums and all 184 frozen demo dependency checksums pass.
- Docker acceptance: seed/reseed preservation, evidence, saved comparisons, valuation, evaluation, paired worker runs and replay passed before and after restart. Three new paired runs replay exactly. Seven bundled runs are numerically equivalent, with maximum relative difference 2.1094237467877974e-15, below the documented 1e-9 tolerance.
- Native acceptance: seven bundled runs and two fresh paired worker runs replay exactly; both fresh runs replay exactly after restart. Original stored outputs and hashes were preserved.
- Both disposable verification stacks are stopped. Existing development stacks and the database on port 55432 were preserved.

## Documentation and archive scope

The README and all 29 documentation Markdown files contain no internal ticket or
requirement IDs. Reader-facing CLI help and source comments were cleaned up. The
limitations document describes model and runtime limits instead of an internal
pre-packaging checklist or parent-repository planning paths. Reuse attribution is
retained in the component-origins document with an explanation of the source project.

Frozen data, configuration, version identifiers and evidence remain byte-for-byte
unchanged from source commit `737777db`. The rule-file comment edit encountered in
an initial native attempt was reverted because the demo manifest hashes the whole
file. Documentation tests were updated to check the revised headings and descriptions
while retaining field-table, source-coverage and invented-fee guards. No numerical
model, database schema or API contract was changed. A database-port option was added
to keep native verification separate from the existing development database.

## Native startup without Docker

- Platform: macOS arm64; Python 3.12.2; Node.js v25.8.0; PostgreSQL 16.10.
- Command from a fresh unpacked copy: `make up-local ARGS='--db-port 55439'`.
- The copy initially contained no virtualenv, node_modules, PostgreSQL binaries or database. Startup installed locked dependencies, downloaded and checksum-verified PostgreSQL, initialized a private database, migrated and seeded it, then started the API, worker and Vite app without Docker or provider credentials.
- API 8000, web 3000 and private database 55439; the existing database on 55432 was not reused.
- Two historical origins, seven saved runs, 40 retrospective forecast rows and 20 prospective forecast rows were present after startup.
- Web routes and `/api/health` proxy returned HTTP 200. Evidence-backed comparisons, valuation and the 16-origin evaluation were available.
- Fresh baseline and mix-shift scenarios used shared seed 923, 5,000 paths and four quarters, completed through the worker, and conserved total payments volume in the mix shift.
- Seven bundled replays plus two new-run replays returned `exact_match` (maximum relative difference 0). Restart preserved all nine runs, reused downloaded dependencies, and both new runs replayed exactly again.
- The exported Git working tree remained clean after startup, runs, replay, restart and frontend tests. Shutdown used `make down-local ARGS='--db-port 55439'`.
- Full replay/runtime evidence: [native validation JSON](reviewer-native-2026-10-09.json).
- Native checks cover HTTP routes, proxy behavior and API/worker flows. Browser rendering was not repeated for this documentation/setup wording update. Windows and Linux native startup were not exercised on this host.

### Native frontend tests

```
> longaeva-web@0.1.0 test
> vitest run --config vitest.config.ts


 RUN  v3.2.4 /private/tmp/longaeva-native-qcsldcai/longaeva/frontend

 ✓ src/lib/runs.test.ts (4 tests) 5ms
 ✓ src/lib/evidence.test.ts (5 tests) 16ms
 ✓ src/lib/scenarios.test.ts (9 tests) 18ms
 ✓ src/lib/tour.test.ts (8 tests) 45ms
 ✓ src/lib/reportDisplay.test.ts (7 tests) 26ms
 ✓ src/lib/llmBaselineDisplay.test.ts (1 test) 25ms
 ✓ src/lib/prospectiveDisplay.test.ts (2 tests) 47ms
 ✓ src/lib/api.test.ts (3 tests) 10ms
 ✓ src/lib/reportApi.test.ts (2 tests) 5ms
 ✓ src/lib/format.test.ts (3 tests) 19ms

 Test Files  10 passed (10)
      Tests  44 passed (44)
   Start at  10:07:23
   Duration  1.01s (transform 420ms, setup 0ms, collect 887ms, tests 215ms, environment 1ms, prepare 634ms)
```

## Retained standalone repository

- Destination: `~/Desktop/longaeva-submission`.
- Copied 199 changed files and four added files from this exact ZIP.
- Commit: `e00362fb5fbe27dfce6edb340400d5065413fdde` on `hackathon`; zero remotes; clean working tree.
- All 530 file contents and executable permissions match the archive. Its initial import and previous documentation commit remain in its history; no parent-project history was imported.

## Docker final verification

- Started (UTC): 2026-10-09T14:04:53Z
- Finished (UTC): 2026-10-09T14:10:09Z
- Result: **PASS**
- Final mode: 1; tests skipped: 0; provider credentials cleared
- ZIP: `longaeva-submission.zip`
- SHA-256: `9598514fadb57dce103b1a06df50072e2cc85159951c5c73c8bae268781d2870`
- ZIP bytes: 43798010
- Docker: `24.0.2`
- Compose: `2.18.1`
- Host: `Darwin 25.5.0 arm64`
- Compose project: `longaeva-verify-4f3b3a`
- Ports: API=18000 WEB=13000 DB=15432
- Work dir: `/tmp/longaeva-verify.w4VTWX`
- Keep: no (stack and temp dir removed)

## Steps

| Step | Result | Seconds | Evidence |
| --- | --- | ---: | --- |
| preflight | PASS | 1 | tools, ports 18000/13000/15432, sha256 match |
| unpack | PASS | 0 | 530 entries under longaeva/; exec bits present |
| guard | PASS | 48 | isolation guard --strict: 0 findings |
| git-init | PASS | 2 | fresh git init; 530 files tracked |
| tests | PASS | 198 | make check (ruff, mypy, pytest, frontend) |
| startup | PASS | 19 | make up; api/worker/web/db healthy |
| smoke | PASS | 0 | API /health /openapi.json /runs; web / /runs /api/health |
| final-demo | PASS | 8 | inventory, report, seed/reseed, evidence, evaluation, valuation, paired worker runs and replay |
| scenario | PASS | 5 | run A 6b9dd815-d76e-43a2-88cc-a570ffb2a694 worker; run B 69516540-b159-42aa-96d1-ad6846de8fac POST; 68 result rows |
| replay | PASS | 32 | A and B exact_match, llm unset; A exact_match after restart |
| final-replay-after-restart | PASS | 3 | all bundled runs plus fresh paired runs replay after restart |
| clean-tree | PASS | 0 | git status --porcelain empty |

## Excerpts


### make check

```
docker compose build 
#1 [api internal] load build definition from Dockerfile
#1 transferring dockerfile: 1.19kB done
#1 DONE 0.0s

#2 [api internal] load .dockerignore
#2 transferring context: 197B done
#2 DONE 0.0s

#3 [api internal] load metadata for docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#3 DONE 0.0s

#4 [api 1/7] FROM docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#4 DONE 0.0s

#5 [api internal] load build context
#5 transferring context: 21.32kB 0.0s done
#5 DONE 0.0s

#6 [api 4/7] COPY requirements.txt requirements-dev.txt requirements.lock ./
#6 CACHED

#7 [api 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#7 CACHED

#8 [api 2/7] WORKDIR /srv/longaeva/backend
#8 CACHED

#9 [api 3/7] RUN useradd --create-home --uid 10001 appuser     && mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config /srv/longaeva/var/artifacts /tmp     && chown -R appuser:appuser /srv/longaeva /tmp
#9 CACHED

#10 [api 6/7] COPY --chown=appuser:appuser . /srv/longaeva/backend
#10 CACHED

#11 [api 7/7] RUN mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config     && chown -R appuser:appuser /srv/longaeva
#11 CACHED

#12 [api] exporting to image
#12 exporting layers done
#12 writing image sha256:f00d7414fd7c3a50667d8d20de34c031591a623454981ea4cc7c405b9985da4f done
#12 naming to docker.io/library/longaeva-verify-4f3b3a-api done
#12 DONE 0.0s

#13 [worker internal] load .dockerignore
#13 transferring context: 197B done
#13 DONE 0.0s

#14 [worker internal] load build definition from Dockerfile
#14 transferring dockerfile: 1.19kB done
#14 DONE 0.0s

#3 [worker internal] load metadata for docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#3 DONE 0.0s

#4 [worker 1/7] FROM docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#4 DONE 0.0s

#15 [worker internal] load build context
#15 transferring context: 21.32kB 0.0s done
#15 DONE 0.0s

#16 [worker 6/7] COPY --chown=appuser:appuser . /srv/longaeva/backend
#16 CACHED

#17 [worker 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#17 CACHED

#18 [worker 4/7] COPY requirements.txt requirements-dev.txt requirements.lock ./
#18 CACHED

#8 [worker 2/7] WORKDIR /srv/longaeva/backend
#8 CACHED

#9 [worker 3/7] RUN useradd --create-home --uid 10001 appuser     && mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config /srv/longaeva/var/artifacts /tmp     && chown -R appuser:appuser /srv/longaeva /tmp
#9 CACHED

#19 [worker 7/7] RUN mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config     && chown -R appuser:appuser /srv/longaeva
#19 CACHED

#20 [web internal] load build definition from Dockerfile
#20 transferring dockerfile: 547B done
#20 DONE 0.0s

#21 [worker] exporting to image
#21 exporting layers done
#21 writing image sha256:5c891caf122c418f46c19edce80a5df7b68a42f9f25d39098e4bebf65b273a3d done
#21 naming to docker.io/library/longaeva-verify-4f3b3a-worker done
#21 DONE 0.0s

#22 [web internal] load .dockerignore
#22 transferring context: 143B done
#22 DONE 0.0s

#23 [web internal] load metadata for docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#23 DONE 0.0s

#24 [web internal] load metadata for docker.io/library/nginx:1.27-alpine
#24 DONE 0.0s

#25 [web frontend-src 1/5] FROM docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#25 DONE 0.0s

#26 [web stage-3 1/3] FROM docker.io/library/nginx:1.27-alpine
#26 DONE 0.0s

#27 [web internal] load build context
#27 transferring context: 6.84kB done
#27 DONE 0.0s

#28 [web build 1/1] RUN npm run build
#28 CACHED

#29 [web stage-3 2/3] COPY nginx.conf /etc/nginx/conf.d/default.conf
#29 CACHED

#30 [web frontend-src 2/5] WORKDIR /app
#30 CACHED

#31 [web frontend-src 5/5] COPY . .
#31 CACHED

#32 [web frontend-src 4/5] RUN npm ci
#32 CACHED

#33 [web frontend-src 3/5] COPY package.json package-lock.json ./
#33 CACHED

#34 [web stage-3 3/3] COPY --from=build /app/dist /usr/share/nginx/html
#34 CACHED

#35 [web] exporting to image
#35 exporting layers done
#35 writing image sha256:6fe8c2c092574f2f28583a1c51f67ab38a99655282be7b36d4d0b1a6c5eac53e done
#35 naming to docker.io/library/longaeva-verify-4f3b3a-web done
#35 DONE 0.0s
docker compose up -d --wait db
 Container longaeva-verify-4f3b3a-db-1  Creating
 Container longaeva-verify-4f3b3a-db-1  Created
 Container longaeva-verify-4f3b3a-db-1  Starting
 Container longaeva-verify-4f3b3a-db-1  Started
 Container longaeva-verify-4f3b3a-db-1  Waiting
 Container longaeva-verify-4f3b3a-db-1  Healthy
docker compose run --rm --no-deps \
		-v "/private/tmp/longaeva-verify.w4VTWX/longaeva:/srv/longaeva-src:ro" -e LONGAEVA_GUARD_ROOT=/srv/longaeva-src \
		-e DATABASE_URL=postgresql://longaeva:longaeva@db:5432/longaeva \
		-e LONGAEVA_REQUIRE_DB=1 \
		-e LONGAEVA_TEST_DB=longaeva_test \
		api sh -c 'scripts/check.sh'
== ruff check ==
All checks passed!
== ruff format --check ==
214 files already formatted
== mypy ==
Success: no issues found in 206 source files
== pytest ==
........................................................................ [ 12%]
........................................................................ [ 25%]
........................................................................ [ 38%]
........................................................................ [ 51%]
........................................................................ [ 64%]
........................................................................ [ 77%]
........................................................................ [ 89%]
.........................................................                [100%]
=============================== warnings summary ===============================
../../../usr/local/lib/python3.12/site-packages/fastapi/testclient.py:1
  /usr/local/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_ablations.py::test_matched_variants_numerical_removal_replay_and_idempotency
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
  /usr/local/lib/python3.12/site-packages/alembic/config.py:604: DeprecationWarning: No path_separator found in configuration; falling back to legacy splitting on spaces, commas, and colons for prepend_sys_path.  Consider adding path_separator=os to Alembic config.
    util.warn_deprecated(

tests/test_extract_api.py::test_extraction_is_disabled_until_a_provider_is_configured
tests/test_search.py::test_invalid_queries_return_422
  /usr/local/lib/python3.12/site-packages/fastapi/telemetry/_api.py:240: StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.
    return function(**arguments)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
561 passed, 8 warnings in 157.06s (0:02:37)
/Library/Developer/CommandLineTools/usr/bin/make check-web
docker build  --target check -t longaeva-verify-4f3b3a-web-check ./frontend
#1 [internal] load build definition from Dockerfile
#1 transferring dockerfile: 547B done
#1 DONE 0.0s

#2 [internal] load .dockerignore
#2 transferring context: 143B done
#2 DONE 0.0s

#3 [internal] load metadata for docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#3 DONE 0.0s

#4 [frontend-src 1/5] FROM docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#4 DONE 0.0s

#5 [internal] load build context
#5 transferring context: 13.59kB done
#5 DONE 0.0s

#6 [frontend-src 2/5] WORKDIR /app
#6 CACHED

#7 [frontend-src 3/5] COPY package.json package-lock.json ./
#7 CACHED

#8 [frontend-src 4/5] RUN npm ci
#8 CACHED

#9 [frontend-src 5/5] COPY . .
#9 DONE 0.1s

#10 exporting to image
#10 exporting layers 0.0s done
#10 writing image sha256:d9b82094514174074a7069728c6a221227efab477b02aa30ce51c1bd7b3be021 done
#10 naming to docker.io/library/longaeva-verify-4f3b3a-web-check done
#10 DONE 0.0s
docker run --rm longaeva-verify-4f3b3a-web-check sh -c 'npm run lint && npm test'

> longaeva-web@0.1.0 lint
> eslint .


> longaeva-web@0.1.0 test
> vitest run --config vitest.config.ts


 RUN  v3.2.4 /app

 ✓ src/lib/scenarios.test.ts (9 tests) 14ms
 ✓ src/lib/tour.test.ts (8 tests | 1 skipped) 6ms
 ✓ src/lib/reportDisplay.test.ts (7 tests) 34ms
 ✓ src/lib/runs.test.ts (4 tests) 7ms
 ✓ src/lib/evidence.test.ts (5 tests) 21ms
 ✓ src/lib/prospectiveDisplay.test.ts (2 tests) 114ms
 ✓ src/lib/api.test.ts (3 tests) 15ms
 ✓ src/lib/reportApi.test.ts (2 tests) 9ms
 ✓ src/lib/llmBaselineDisplay.test.ts (1 test) 30ms
 ✓ src/lib/format.test.ts (3 tests) 27ms

 Test Files  10 passed (10)
      Tests  43 passed | 1 skipped (44)
   Start at  14:08:59
   Duration  2.54s (transform 584ms, setup 0ms, collect 1.37s, tests 279ms, environment 3ms, prepare 1.61s)
```

### final demo

```json
{
  "forecast_counts": {
    "prospective": 20,
    "retrospective": 40
  },
  "inventory_files": 191,
  "n_scored": 16,
  "new_run_ids": [
    "fecf5709-991b-4042-a5ee-55748313c68c",
    "3985b438-cdcd-4027-ac41-c0e3b1d7caff",
    "c6097a19-4e73-40ad-a412-8a45940e7ab1"
  ],
  "origins": [
    "2024-07-23",
    "2025-10-28"
  ],
  "replays": [
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "1259b6e2c777488cb487f105cd403eb3697e1c0fea9f5fb19a3e8801e27eff61",
      "run_id": "cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "27ab77ba607d6b306ff663640f26c75328d18efd72d86f3e474099602ffe833b",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7d1a0038211fe48e5baaca8f478163fc4f189248db80dc8460f624f681b52bc7",
      "run_id": "846c4e0b-a634-5bed-996d-3785bb899846",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "4b25be2523ca4d10556ad31fcb3eeaf7aee8b24fc0fe569e5703f8a235097b10",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "88105420099244c4504aab3641ec9ecaca8c2c6090cb8a8cce42172a72c6448a",
      "run_id": "fbbad1df-6531-4a41-86e0-32dda8a482c2",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "361799585560f720b65f7108b1d0bc4c04fd94ca7ab78ce6965a39d032ddc15f",
      "run_id": "3752b7df-c114-5fa4-b312-efe5a5908c38",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "fa1c7bd0d747eef14b1e68ad3f8db9c5b8e789a3e86432d8dd2298361c54faea",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "98dba6f33fb6603e8f4561aeeae34ff6583af5963d2aca77099fffa82bbe075c",
      "run_id": "db0ff361-957b-5148-8299-6c71d0313f57",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.5543122344752192e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "5dabe0961f0d9e5d21f28647be5e6edf49246a40ef0cf44f26438cf00ef12b24",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "a9663464147616255f391896b450513809a174744df5ef360bb83aa0542bacf7",
      "run_id": "20673695-fcda-54a8-8020-3d670ee80847",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 2.1094237467877974e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "04a0ff13875572e677cd36a0694a6d616aadfe79e2b06b19e1c9b63862d13c1f",
      "run_id": "ab595be3-2964-5845-b6f3-4d8d4fce6bf3",
      "status": "numerically_equivalent"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+9a009e5f7519b7f6",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "run_id": "fecf5709-991b-4042-a5ee-55748313c68c",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+9a009e5f7519b7f6",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "run_id": "3985b438-cdcd-4027-ac41-c0e3b1d7caff",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+9a009e5f7519b7f6",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "run_id": "c6097a19-4e73-40ad-a412-8a45940e7ab1",
      "status": "exact_match"
    }
  ],
  "report_current": true,
  "reseed_preserved_review": true,
  "seed_counts": {
    "document_text": 10777,
    "evaluation_result": 554,
    "forecast": 60,
    "mapping_rule": 6,
    "observation": 37,
    "parameter_set": 6,
    "parameter_set_context": 81,
    "parameter_update": 6,
    "parameter_update_observation": 6,
    "review_decision": 37,
    "run": 7,
    "scenario": 11,
    "source": 30
  }
}
```

### final replay after restart

```json
{
  "replays": [
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "1259b6e2c777488cb487f105cd403eb3697e1c0fea9f5fb19a3e8801e27eff61",
      "run_id": "cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "27ab77ba607d6b306ff663640f26c75328d18efd72d86f3e474099602ffe833b",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7d1a0038211fe48e5baaca8f478163fc4f189248db80dc8460f624f681b52bc7",
      "run_id": "846c4e0b-a634-5bed-996d-3785bb899846",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "4b25be2523ca4d10556ad31fcb3eeaf7aee8b24fc0fe569e5703f8a235097b10",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "88105420099244c4504aab3641ec9ecaca8c2c6090cb8a8cce42172a72c6448a",
      "run_id": "fbbad1df-6531-4a41-86e0-32dda8a482c2",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "361799585560f720b65f7108b1d0bc4c04fd94ca7ab78ce6965a39d032ddc15f",
      "run_id": "3752b7df-c114-5fa4-b312-efe5a5908c38",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "fa1c7bd0d747eef14b1e68ad3f8db9c5b8e789a3e86432d8dd2298361c54faea",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "98dba6f33fb6603e8f4561aeeae34ff6583af5963d2aca77099fffa82bbe075c",
      "run_id": "db0ff361-957b-5148-8299-6c71d0313f57",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.5543122344752192e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "5dabe0961f0d9e5d21f28647be5e6edf49246a40ef0cf44f26438cf00ef12b24",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "a9663464147616255f391896b450513809a174744df5ef360bb83aa0542bacf7",
      "run_id": "20673695-fcda-54a8-8020-3d670ee80847",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "code_version: 0.1.0+cf93263a1d638ffa -> 0.1.0+9a009e5f7519b7f6",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 2.1094237467877974e-15,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "04a0ff13875572e677cd36a0694a6d616aadfe79e2b06b19e1c9b63862d13c1f",
      "run_id": "ab595be3-2964-5845-b6f3-4d8d4fce6bf3",
      "status": "numerically_equivalent"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+9a009e5f7519b7f6",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "run_id": "fecf5709-991b-4042-a5ee-55748313c68c",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+9a009e5f7519b7f6",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "run_id": "3985b438-cdcd-4027-ac41-c0e3b1d7caff",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+9a009e5f7519b7f6",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+9a009e5f7519b7f6",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "run_id": "c6097a19-4e73-40ad-a412-8a45940e7ab1",
      "status": "exact_match"
    }
  ]
}
```

## Notes

- Developer stack on ports 8000/3000/55432 is not used.
- Browser evidence is recorded separately; this script verifies API flows.
- New runs require exact replay; bundled runs retain the documented 1e-9 cross-runtime tolerance.
