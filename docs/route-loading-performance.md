# Route startup and navigation (TL-197)

`main.tsx` starts the session check, current page import, and first automatic
route GET before mounting React. AuthProvider, the router, and page queries
reuse those requests. Protected content and actions still wait for auth; only
the navigation shell renders optimistically.

The data router resolves page imports through `lazyPage.preload()` and starts
the existing React Query request from a static loader. Loaders do not wait for
data responses: pages retain their existing data loading and error states.
Sidebar hover and keyboard focus preload chunks. Once a page renders, idle
callbacks preload Dashboard, Workspace, and Risk sequentially, skipping the
current route and connections that request reduced data usage. Prefetching does
not fetch other pages' business data. `useNavigation()` drives an accessible,
indeterminate progress bar while a cold route loads.

`routeData.ts` identifies each route's first automatic GET using the existing
query key and freshness. Routes requiring user input (Chart, Screeners,
Financials, DCF, the empty Explorer, and Signal Aggregator) do not start an
analysis automatically. Explorer deep links start their dossier GET; the chart
POST remains behind auth because it needs the CSRF token. The three forms that
previously loaded defaults in effects join the preloaded query, with five-second
freshness for those defaults. Auth failures and logout clear the query cache.
Speculative 401s cannot trigger document redirects before a session is verified.
Cloudflare Access probes run alongside the session request and preserve password
fallback and Access authentication when the optional session lookup fails.

## Measurements

Measured on October 21, 2026, against baseline `f8550f489`, using production
builds, the same installed Chromium, a single worker, fresh pages, and mocked
successful API responses. Each sample delays `/auth/me` by 400 ms and the route
chunk by 200 ms. No CPU or bandwidth throttle is applied. Baseline and updated
runs execute sequentially; five samples per route are repeated in each run.

The metric is the spread between the earliest and latest Playwright request
events for auth, the page's JS chunk, and its first data request. The tests also
wait for the actual page heading, verify successful data responses, and check
that mounting reuses the initial request. This isolates client scheduling; it is
not a measurement of production API/provider response latency.

| Reload route | Baseline median (range), ms | Updated median (range), ms |
| --- | ---: | ---: |
| Dashboard `/` | 731 (728–752) | 4 (3–9) |
| Workspace `/workspace` | 726 (722–749) | 9 (4–20) |
| Liquidity `/liquidity` | 726 (721–748) | 4 (3–11) |
| Dossier `/dossier/MSFT` | 723 (720–742) | 9 (7–12) |

All 20 updated samples satisfy the 50 ms target. Hover and focus tests verify
the prefetched chunk finishes before clicking and that clicking performs no
second chunk download. A separate network-gated test covers all 37 deep links
with automatic data, including route parameters and query strings. Other
regressions cover the optimistic shell, protected actions, single logged-out
redirect, cold-navigation progress, and browser back/forward navigation.

## Repeating the comparison

Save the baseline production `dist` before changing application code. Serve it
and the updated production build from this worktree on distinct, non-default
ports (the original run used 6197 and 6198). Use an ignored local Playwright
configuration derived from `frontend/playwright.config.ts`, overriding `baseURL`
to the desired preview, disabling `webServer`, selecting one worker, and using
the absolute `frontend/tests/smoke` directory as `testDir`. Do not reuse another
agent's development server.

From `frontend`, execute the following against the respective configurations:

```sh
TL197_BASELINE=1 npm exec playwright -- test --config outputs/tl197/baseline.config.ts \
  route-loading.spec.ts --grep 'starts auth, chunk and data' --repeat-each=5
TL197_MEASURE=1 npm exec playwright -- test --config outputs/tl197/after.config.ts \
  route-loading.spec.ts --grep 'starts auth, chunk and data' --repeat-each=5
```

Each sample emits `TL197_TIMING` JSON. Baseline mode disables only the concurrency
assertions; it still checks that the page renders and its data request succeeds.
Measurement mode also enforces the 50 ms limit. Run the full smoke suite against
the updated preview without these variables for behavioral regression coverage.

The Cloudflare bootstrap tests in `frontend/tests/observability` need a separate
build with `VITE_AUTH_MODE=cloudflare`. The existing Sentry performance tests
need a build with their mock DSN and full trace sampling, as before.
