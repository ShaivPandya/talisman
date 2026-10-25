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
| EIA petroleum inventories, natural-gas storage, electricity | Existing `EIA_API_KEY`; no additional key |
| NOAA CDO station history | `NOAA_CDO_TOKEN` (free NCEI token) |

Never put these credentials in `VITE_*` variables. Add existing Secret Manager
bindings to the optional `ALTERNATIVE_DATA_SECRETS` array in ignored GCP
`config.sh`; the deploy helpers bind them to both API and workers. For example:

```bash
export ALTERNATIVE_DATA_SECRETS=(
  "FIRMS_MAP_KEY=FIRMS_MAP_KEY:latest"
  "CENSUS_API_KEY=CENSUS_API_KEY:latest"
)
```

To import already-issued credentials, put only the fields you have in an ignored
local `.env.data-sources` file (restrict it with `chmod 600`). Preview, then apply:

```bash
PYTHON=.venv/bin/python ./infra/gcp/setup-data-source-secrets.sh --env-file .env.data-sources
PYTHON=.venv/bin/python ./infra/gcp/setup-data-source-secrets.sh --env-file .env.data-sources --apply
```

This stores values through stdin, preserves existing enabled secrets, skips
empty/placeholder values and incomplete OAuth pairs, grants secret access to
`API_SA` and `WORKER_SA`, and appends references to a managed block in ignored
`config.sh`. No values are printed or written to deploy configuration. A failed
GCP inventory stops setup; reruns are safe after partial completion. Explicit
environment values take precedence over the input file.

The command stages credentials; update the API, generic async job, and agent,
analyzer, and ontology worker pools to load the reported bindings. Use
`gcloud run ... update --update-secrets` to keep their current images/settings,
or the existing component deploy scripts for a normal release. Verify the
authenticated catalog and a bounded provider fetch before deleting the local
handoff file. OpenSky still requires written permission; credential import
never sets license-confirmation flags.

Credential registration: [NASA FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/),
[Census API key](https://api.census.gov/data/key_signup.html),
[NOAA NCEI token](https://www.ncei.noaa.gov/cdo-web/token), and
[Copernicus Sentinel Hub OAuth client](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html).
FIRMS requires its own MAP_KEY; a general `api.nasa.gov` key does not replace it.

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
The helper skips unresolved employer legal names and labels unresolved product
relationships as sector proxies. Callers with reviewed mappings may supply
`context.alternative_data_mappings` with an `employer` legal name and `products`
codes; a model's proposed name alone never establishes a company relationship.

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

## Company and sector public datasets

The catalog additionally registers SEC Form 4 transactions, query passages from
recent SEC 10-K/10-Q/8-K filings, USAspending recipient awards, Federal Register
documents, USPTO patent search availability, ClinicalTrials.gov API v2,
openFDA drug events, Drugs@FDA approvals, Wikimedia article pageviews, EIA energy
series, USDA WASDE crop production/ending stocks, Baker Hughes rig counts, and
NOAA CDO station history. These use the same two tools and the three-source
company-evidence limit. There are no additional navigation entries.

On the Alternative Data page, enter a ticker and choose a name-matched source.
A person must confirm the exact recipient, assignee, sponsor, applicant, drug,
company name, or article title and cite its company relationship. Confirmation
uses `POST /api/alternative-data/mappings/confirm`; removal uses
`DELETE /api/alternative-data/mappings/{mapping_id}`. Reviewed mappings are
existing `SourceManifest` objects with dataset `alternative_data_mappings`.
Agents cannot confirm or remove them. A fetch must supply the active mapping ID;
the server checks its source, ticker, and exact value before cache lookup or
provider access. Model-proposed names and revoked mappings are rejected.
Federal Register agency-only queries may run without a company mapping and
remain agency context. A company search hit is retained only if the document
text names the exact reviewed company; a mention does not establish subject matter.

SEC queries resolve and verify issuer CIKs through `edgar_fetcher`, including its
shared SEC request pacing. Form 4 reads at most ten primary documents (1 MB each)
and reports acquisition/disposition and transaction codes without scoring them.
Filing passage search reads at most three recent primary documents (3 MB each),
returning up to six literal, cited passages per document. Oversized or blocked
documents return an explicit failure, never an invented empty match.

Awards are obligations rather than revenue; their start dates are not freshness
dates. Trials do not establish efficacy, and adverse-event reports do not establish
causality or incidence. Article attention, energy aggregates, crop projections,
rig counts, and station weather are proxies. No company facility, store traffic,
production, or revenue relationship is inferred.

Access checked 2026-10-24: the legacy PatentsView APIs paused during USPTO's ODP
migration. Until a bounded, documented exact-assignee replacement is verified,
the catalog entry is unavailable and cannot fetch or store data. No bulk patent
corpus or paid replacement is used. Baker Hughes downloads can return HTTP 403;
these stay unavailable without an access bypass. Its FAQ permits attributed use
of rig-count downloads subject to its terms. WASDE downloads are bounded current
monthly workbooks, with marketing year, publisher units, and report release date.

## Economic activity and published forecasts

Economic Growth retains its cross-asset return panel and adds an independent,
snapshot-backed `/api/economic-growth/backdrop` read. The existing
`get_economic_growth` tool accepts `section="backdrop"`; its default remains
market returns. The scheduled macro refresh includes the backdrop snapshot.
Nothing in this read changes signal-aggregator weights or regime thresholds.

FRED observations include PAYEMS, UNRATE, RSAFS, PCEC96, INDPRO, CSUSHPISA,
USSTHPI, TOTALSL, and SLOOS DRTSCILM (net percentage of domestic banks tightening
C&I standards for large and middle-market firms). Payrolls and unemployment
also appear on Labor; the two house-price indexes appear on Housing. FRED marks
CSUSHPISA **copyrighted, pre-approval required**. It is not fetched unless
`ALTERNATIVE_DATA_CASE_SHILLER_PERMISSION_CONFIRMED=true` after written permission.
No browser environment variable grants permission.

GSCPI uses the NY Fed's official CSV and its latest vintage column. The NY Fed
Staff Nowcast uses the publisher's landing-quarter metadata, quarter CSV, and
release-schedule note. Cleveland inflation nowcasts use the publisher's dated
JSON feed; blanks remain missing even where an earlier daily value exists.
IMF WEO NGDP_RPCH and PCPIPCH reuse the existing DataMapper client for every
country on the country dashboard, for the current and next year. The edition
and metadata last-modified date come from IMF, with that date explicitly labeled
as a metadata update rather than an invented release date. Next-release notes
report the publisher cadence and disclose when no exact date is supplied.

Each reading carries its unit, observation/as-of date, official source link,
and availability. Forecast target periods, publisher vintages, and retrieval
timestamps are separate fields. Missing values are never replaced with zero.

Primary documentation: [SEC](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[USAspending](https://api.usaspending.gov/docs/intro-tutorial),
[Federal Register](https://www.federalregister.gov/developers/documentation/api/v1),
[ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api),
[openFDA](https://open.fda.gov/apis/), [Wikimedia](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html),
[EIA](https://www.eia.gov/opendata/documentation.php), [WASDE](https://www.usda.gov/oce/commodity/wasde),
[Baker Hughes reuse](https://bakerhughesrigcount.gcs-web.com/rig-count-faqs/),
[NOAA CDO](https://www.ncei.noaa.gov/cdo-web/webservices/v2),
[NY Fed Staff Nowcast](https://www.newyorkfed.org/research/policy/nowcast),
[Cleveland Fed](https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting),
[IMF DataMapper](https://www.imf.org/external/datamapper/api/help),
[Case-Shiller access](https://fred.stlouisfed.org/series/CSUSHPISA),
[USPTO migration notice](https://content.govdelivery.com/accounts/USPTO/bulletins/40e8c67).

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
