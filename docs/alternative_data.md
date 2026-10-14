# Shared alternative-data catalog

The Alternative Data page (`/alternative-data`), Stan's two alternative-data
tools, company research workflows, and the analyzer's enriched AI brief use the
same source registry and fetch service. Adding a source requires a catalog
registration and adapter; navigation and workflow source lists do not change.

## Access and configuration

All application endpoints require authentication. Browser writes also require
the normal CSRF and request-schema headers. Alternative-data sources are optional:
missing credentials or written permission never prevent the application starting.

| Capability | Server environment / Secret Manager bindings |
| --- | --- |
| NASA FIRMS | `FIRMS_MAP_KEY` (free NASA map key) |
| Census international trade | `CENSUS_API_KEY` (free Census data key) |
| Sentinel-2 derived indices | `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET` (CDSE OAuth client) |
| AISHub aggregates | `AISHUB_USERNAME` (qualifying contributor account) |
| OpenSky aggregates | `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`, and `ALTERNATIVE_DATA_OPENSKY_LICENSE_CONFIRMED=true` after written operational permission |
| IMF PortWatch | `ALTERNATIVE_DATA_PORTWATCH_PERMISSION_CONFIRMED=true` after confirming applicable dataset reuse permission |

Never put these credentials in `VITE_*` variables. Add existing Secret Manager
bindings to the optional `ALTERNATIVE_DATA_SECRETS` array in ignored GCP
`config.sh`; the deploy helpers bind them to both API and workers. For example:

```bash
export ALTERNATIVE_DATA_SECRETS=(
  "FIRMS_MAP_KEY=FIRMS_MAP_KEY:latest"
  "CENSUS_API_KEY=CENSUS_API_KEY:latest"
)
```

No paid provider is purchased or provisioned. SONAR charts remain reference-only.
NOAA AIS provides archive discovery, with historical track analysis labeled
bulk-only. An unavailable provider/export remains visible with its last attempt
and error. The catalog permits manual retries, and temporarily failed sources
are omitted from automatic evidence selection for one hour.

## Contracts and persistence

- `GET /api/alternative-data/catalog`: grouped source descriptions, parameter
  schemas, availability, licenses, latest successful observation dates, and
  confirmed/proposed company sites when `ticker` is supplied.
- `POST /api/alternative-data/fetch`: `source_id`, `parameters`, optional `ticker`
  and `force_refresh`; returns cached data, a setup/access state, or a durable job.
- `GET /api/alternative-data/jobs/{job_id}`: job status and final result. Source
  fetch, site discovery, and enriched analyzer jobs share this polling endpoint.
- `POST /api/alternative-data/sites/suggest`: grounded, cited candidate sites.
- `POST /api/alternative-data/sites/confirm`: person-confirmed company geometry.
- `DELETE /api/alternative-data/sites/{site_id}`: deactivate a site, preserving
  its temporal history and preventing further company queries using it.
- `POST /api/portfolio-analyzer/course-of-action/brief/async`: enriched brief.
  The existing synchronous brief and all numerical scoring remain compatible.

Agents discover sources with `search_alternative_data_catalog`, then call
`fetch_alternative_data` with parameters from that source's schema. The latter
also accepts its `job_id` to poll. Research/evaluation code can call
`build_company_evidence(ticker, question, context, actor=...)`; selection is
limited to three relevant, available sources and validated parameters.

Results include observations or a snapshot, units, citations, attribution,
observation and retrieval timestamps, freshness, coverage warnings, and a link
to the same source in the app. Sector, geographic, exact-employer and confirmed
site evidence have explicit relevance labels. Missing data never become zero.

Production results use existing `source_record_versions` and
`computed_snapshot_versions`; confirmed sites use `SourceManifest` records with
dataset `alternative_data_sites`. Site proposals use `WorkflowArtifact` records.
These existing canonical types require no new database tables or migrations.
Source refresh failures retain the prior payload and its successful observation
and retrieval timestamps. API keys, OAuth tokens, and raw restricted AIS data
are excluded from results and provenance payloads.

## Imagery calculations

Sentinel-2 uses the free CDSE Statistical API with a fixed, versioned evalscript:
NDVI = (NIR − red)/(NIR + red), NDWI = (green − NIR)/(green + NIR),
NDBI = (SWIR − NIR)/(SWIR + NIR). Coordinates are projected to a local UTM grid
for 20m sampling. Clear vegetation, bare-surface and water classes are accepted;
cloud, shadow, snow, saturated and invalid pixels are masked.

The defaults are 90 days, daily intervals, and latest versus preceding 30-day
means. Intervals below 30% valid coverage are suppressed. Site area is capped at
25 km², history at one year, and confirmed sites at five per company. These are
spectral proxies, not verified construction progress, parking occupancy,
industrial output, or revenue. Sentinel-1 and Landsat initially provide scene
discovery and previews.

## Verification

Run the alternative-data Python tests, the existing source/governance/workflow
regressions, frontend lint/build, and Playwright smoke tests. Release verification
must also check authenticated production catalog discovery, a successful public
source fetch and cache read, setup states, job polling, and analyzer evidence.
Credential-gated imagery is validated with fixtures until credentials are added.

LCA disclosures are streamed to temporary storage, with a disk-backed string
index and exact employer aggregates. Downloads are limited to 300 MB compressed
and 4 GB expanded; the durable fetch job has a 20-minute execution budget.
