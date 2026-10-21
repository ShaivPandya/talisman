# Source-health cache (TL-194)

Approvals and Workspace share a process-local 60-second cache for source health
and the compact regime/risk inputs used by the Workspace summary. All entries
share one expiry, so caching inputs and their derived result cannot double the
freshness window. Concurrent callers share a fill; invalidation prevents an
older in-flight fill from repopulating the cache. Returned values are isolated
from caller mutation. Other Workspace data retains its existing read path.

Successful computed-snapshot commits, failed-refresh records, deletions, and
portfolio-risk commits invalidate locally. Direct temporal snapshot writes are
covered as well. Other processes observe writes within the TTL; there is no
cross-process notification or persistent cache I/O.

Freshness listings project metadata plus the scalar embedded quality field, so
existing degraded-quality badges survive without transferring full payloads.
Signal reads without raw modules remove `raw_modules` in SQL before decoding.
Request-time history slicing uses the isolated copy already returned by the
snapshot store, eliminating the second deep copy.

## Local fixture measurement

Measured on 2026-10-21 against baseline `8653b613`, using the same Python 3.12
virtual environment and fixture workload for both versions. Each path ran five
batches of one cold call followed by 30 warm calls. No test suite ran during the
comparison. Figures below are the median of the five batch p50/p95 values.

The fixture contained 12 snapshots with 4,000 rows each and one signal snapshot
with a 4,000-row raw module. The measured paths were the Approvals source-health
helper and the Workspace handler, with unrelated portfolio/ontology services
stubbed. SQLite exercised real snapshot SQL and JSON decoding; PostgreSQL
projection shapes are covered separately by tests. These figures demonstrate
local processing/transfer reductions, not production request latency.

| Warm metric | Baseline | TL-194 |
| --- | ---: | ---: |
| Snapshot payload reads per call (both paths) | 14 | 0 |
| Snapshot payload bytes returned per call (both paths) | 10,121,042 | 0 |
| Approvals health p50 | 42.006 ms | 0.268 ms |
| Approvals health p95 | 46.225 ms | 0.274 ms |
| Workspace p50 | 42.584 ms | 0.412 ms |
| Workspace p95 | 43.458 ms | 0.605 ms |

The API regression test warms Approvals, then repeatedly requests approval list,
summary, detail, and Workspace. It asserts zero computed-snapshot, freshness
metadata, and portfolio-risk reads on the warm path, then verifies that a failed
snapshot refresh invalidates both endpoints. Additional tests cover expiry,
concurrent fills, write/commit ordering, deletion, missing sources, embedded
quality, projected signal reads, history slicing, and mutation isolation.
