# Early export rehearsal

- Started (UTC): 2026-10-03T21:04:52Z
- Finished (UTC): 2026-10-03T21:09:22Z
- Result: **PASS**
- ZIP: `longaeva-export-20261003T210426Z-63e8ca5.zip`
- SHA-256: `e18751a19cbe6dfc72c149a0ca0228b960ddfbc22248f770e4e50d4391cd9bd2`
- ZIP bytes: 8312838
- Docker: `24.0.2`
- Compose: `2.18.1`
- Host: `Darwin 25.5.0 arm64`
- Compose project: `longaeva-verify-702884`
- Ports: API=18000 WEB=13000 DB=15432
- Work dir: `/tmp/longaeva-verify.9KeZsn`
- Keep: yes (stack and temp dir left in place)

## Steps

| Step | Result | Seconds | Evidence |
| --- | --- | ---: | --- |
| preflight | PASS | 0 | tools, ports 18000/13000/15432, sha256 match |
| unpack | PASS | 1 | 321 entries under longaeva/; exec bits present |
| guard | PASS | 101 | isolation guard --strict: 0 findings |
| git-init | PASS | 0 | fresh git init; 321 files tracked |
| tests | PASS | 126 | make check (ruff, mypy, pytest, frontend) |
| startup | PASS | 15 | make up; api/worker/web/db healthy |
| smoke | PASS | 0 | API /health /openapi.json /runs; web / /runs /api/health |
| scenario | PASS | 6 | run A afb10697-682c-41a4-a67f-1e5e20137410 worker; run B 3a675c79-e791-4944-914c-17ee336c6c7d POST; 68 result rows |
| replay | PASS | 21 | A and B exact_match, llm unset; A exact_match after restart |
| clean-tree | PASS | 0 | git status --porcelain empty |

## Excerpts


### make check (tail)

```
docker run --rm longaeva-verify-702884-web-check sh -c 'npm run lint && npm test'

> longaeva-web@0.1.0 lint
> eslint .


> longaeva-web@0.1.0 test
> vitest run --config vitest.config.ts


 RUN  v3.2.4 /app

 ✓ src/lib/api.test.ts (3 tests) 22ms
 ✓ src/lib/runs.test.ts (4 tests) 8ms
 ✓ src/lib/format.test.ts (3 tests) 21ms

 Test Files  3 passed (3)
      Tests  10 passed (10)
   Start at  21:08:39
   Duration  497ms (transform 250ms, setup 0ms, collect 367ms, tests 52ms, environment 1ms, prepare 294ms)
```

## Notes

- Developer stack on ports 8000/3000/55432 is not used.
- Browser UF-01/UF-03 flows are not automated here (LON-34 / LON-36).
- Replay is expected to be `exact_match` inside Compose (same BLAS).

- Browser spot-check: `http://127.0.0.1:13000/runs/afb10697-682c-41a4-a67f-1e5e20137410` (FY2024Q3, 256 paths). Fan chart and quantile table rendered. No local filesystem paths in the UI. Screenshot: `early-export-2026-10-03-run.png`.
- Teardown after the screenshot: `docker compose down -v --rmi local` for `longaeva-verify-702884`, remove `longaeva-verify-702884-web-check`, delete `/tmp/longaeva-verify.9KeZsn`.
