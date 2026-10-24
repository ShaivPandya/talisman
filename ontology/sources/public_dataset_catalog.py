"""Public dataset registrations added by TL-176; no provider calls at import time."""

from __future__ import annotations

from typing import Any


def public_dataset_specs(source: Any, string: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(
        key: str,
        name: str,
        group: str,
        question: str,
        coverage: str,
        cadence: str,
        url: str,
        hosts: list[str],
        *,
        reviewed: str | None = None,
        **kwargs: Any,
    ) -> None:
        fields = kwargs.pop("fields", {})
        if reviewed:
            fields["mapping_id"] = string("Human-reviewed company mapping ID; never infer a name from a ticker")
            fields[reviewed] = string("Exact reviewed name/title; supplied from mapping_id")
        spec = source(
            key, name, group, question, coverage, cadence, url, "public:" + key, hosts, fields=fields, **kwargs
        )
        spec.update(access_checked_at="2026-10-24", reviewed_field=reviewed)
        rows.append(spec)

    sec_fields = {"cik": string("Resolved SEC CIK; ticker queries resolve and verify it", pattern=r"\d{1,10}")}
    add(
        "sec_form4",
        "SEC Form 4 insider transactions",
        "company",
        "What insider transactions were disclosed?",
        "Resolved issuer CIK; disclosed transactions, never a buy/sell recommendation",
        "As filed",
        "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        ["data.sec.gov", "www.sec.gov"],
        fields=sec_fields,
        notes="At most ten recent Form 4 filings. Transaction codes and acquisition/disposition are disclosures, not trading signals.",
    )
    add(
        "sec_filings",
        "SEC filing passages",
        "company",
        "What do recent 10-K, 10-Q, and 8-K filings say about a question?",
        "Query-matched passages from at most three recent primary filing documents",
        "As filed",
        "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        ["data.sec.gov", "www.sec.gov"],
        fields={**sec_fields, "query": string("Literal passage search, bounded to recent filings", maxLength=160)},
        required=["query"],
        notes="Bounded primary documents from submissions; no corpus download or inferred sentiment.",
    )
    add(
        "usaspending",
        "USAspending recipient awards",
        "company",
        "What federal awards name the reviewed recipient?",
        "Exact reviewed recipient; award obligations are not recognized company revenue",
        "Daily with reporting lag",
        "https://api.usaspending.gov/docs/intro-tutorial",
        ["api.usaspending.gov"],
        reviewed="recipient",
        license_url="https://www.usaspending.gov/about",
        notes="Exact recipient post-filter; no inferred subsidiaries or ticker-to-name matching.",
    )
    add(
        "federal_register",
        "Federal Register documents",
        "company",
        "What published rules or notices name an agency or company?",
        "Exact agency or reviewed company phrase; hits alone do not establish company subject matter",
        "Daily",
        "https://www.federalregister.gov/developers/documentation/api/v1",
        ["www.federalregister.gov"],
        reviewed="company",
        fields={"agency": string("Exact agency slug from the Federal Register agencies endpoint")},
        notes="Agency-only results are regulatory context. Company attribution requires the exact name in document text.",
    )
    add(
        "uspto",
        "USPTO patent applications",
        "company",
        "What patent applications identify the reviewed assignee?",
        "Exact reviewed assignee, using the current USPTO Open Data Portal",
        "Publisher updates",
        "https://data.uspto.gov/apis/patent-file-wrapper/search",
        ["api.uspto.gov"],
        reviewed="assignee",
        access="unavailable",
        license_url="https://www.uspto.gov/ip-policy/economic-research/patentsview",
        notes="PatentsView search APIs paused during ODP migration. No verified bounded exact-assignee replacement; no bulk corpus or unofficial replacement.",
    )
    rows[-1]["storage_allowed"] = False
    add(
        "clinical_trials",
        "ClinicalTrials.gov studies",
        "healthcare",
        "What studies list the reviewed lead sponsor?",
        "Exact reviewed lead sponsor; registry status is not evidence of efficacy or approval",
        "Weekdays",
        "https://clinicaltrials.gov/data-api/api",
        ["clinicaltrials.gov"],
        reviewed="sponsor",
        license_url="https://clinicaltrials.gov/about-site/terms-conditions",
        notes="API v2; exact lead-sponsor post-filter; no patient data.",
    )
    add(
        "openfda_events",
        "openFDA drug adverse event reports",
        "healthcare",
        "What adverse event reports mention a reviewed drug?",
        "Reviewed drug name; reports do not establish causation, incidence, or comparative safety",
        "Quarterly, often delayed",
        "https://open.fda.gov/apis/drug/event/",
        ["api.fda.gov"],
        reviewed="drug",
        freshness_days=150,
        license_url="https://open.fda.gov/license/",
        notes="Exact drug mapping required. Reporting biases, duplicates and exposure denominators prevent incidence calculations.",
    )
    add(
        "openfda_approvals",
        "Drugs@FDA approvals",
        "healthcare",
        "What approvals name the reviewed applicant?",
        "Exact reviewed applicant; approval records, not sales forecasts",
        "Weekdays",
        "https://open.fda.gov/apis/drug/drugsfda/",
        ["api.fda.gov"],
        reviewed="applicant",
        license_url="https://open.fda.gov/license/",
        notes="Exact sponsor_name post-filter; retain submission dates and application identifiers.",
    )
    add(
        "wikimedia",
        "Wikimedia article pageviews",
        "demand",
        "Is attention to an exact reviewed article changing?",
        "Exact article and project; attention proxy, not company demand or revenue",
        "Daily",
        "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html",
        ["wikimedia.org"],
        reviewed="article",
        fields={"project": string("Wikimedia project", default="en.wikipedia.org", pattern=r"[a-z-]+\.wikipedia\.org")},
        license_url="https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/access-policy.html",
        notes="No ticker-to-article guessing. Human pageviews only; spelling and redirects affect coverage.",
    )
    add(
        "eia",
        "EIA energy inventories and electricity",
        "resources",
        "What are petroleum stocks, gas storage, or electricity conditions?",
        "US sector/geographic proxy; never company production or revenue",
        "Weekly inventories; monthly electricity",
        "https://www.eia.gov/opendata/documentation.php",
        ["api.eia.gov"],
        keys=["EIA_API_KEY"],
        fields={
            "series": string(
                "Official EIA series",
                enum=["petroleum_stocks", "natural_gas_storage", "electricity_sales"],
                default="petroleum_stocks",
            )
        },
        freshness_days=75,
        license_url="https://www.eia.gov/about/copyrights_reuse.php",
        notes="Reuses EIA_API_KEY. National aggregates; no company facility mapping is inferred.",
    )
    add(
        "wasde",
        "USDA WASDE crop supply and stocks",
        "resources",
        "What are published crop production and ending stocks estimates?",
        "US and world commodity context; USDA marketing-year estimates, not company revenue",
        "Monthly",
        "https://www.usda.gov/oce/commodity/wasde",
        ["www.usda.gov"],
        fields={"commodity": string("Crop", enum=["Wheat", "Corn", "Soybeans", "Rice", "Cotton"], default="Corn")},
        freshness_days=45,
        license_url="https://www.usda.gov/policies-and-links",
        notes="Bounded current monthly workbook. Retain report vintage, marketing year and publisher units.",
    )
    add(
        "rig_count",
        "Baker Hughes weekly rig count",
        "resources",
        "Is North American drilling activity changing?",
        "US/Canada active rigs; energy-activity proxy, not production or company revenue",
        "Weekly on Friday",
        "https://bakerhughesrigcount.gcs-web.com/na-rig-count",
        ["bakerhughesrigcount.gcs-web.com", "rigcount.bakerhughes.com"],
        license_url="https://bakerhughesrigcount.gcs-web.com/rig-count-faqs/",
        citation="Baker Hughes Rig Count",
        notes="Baker Hughes permits attributed use of rig-count downloads subject to its terms. No inference of individual company activity.",
    )
    add(
        "noaa_cdo",
        "NOAA Climate Data Online station history",
        "resources",
        "What were weather conditions at a selected station?",
        "Exact station observations; geographic proxy, not store traffic or revenue",
        "Daily with station reporting lag",
        "https://www.ncei.noaa.gov/cdo-web/webservices/v2",
        ["www.ncei.noaa.gov"],
        keys=["NOAA_CDO_TOKEN"],
        fields={
            "station": string("Exact GHCND station ID", pattern=r"GHCND:[A-Z0-9]{11}"),
            "metric": string("Daily station measurement", enum=["TMAX", "TMIN", "PRCP"], default="TMAX"),
        },
        required=["station"],
        license_url="https://www.noaa.gov/information-technology/open-data-dissemination",
        notes="Free NCEI token required. Metric units from CDO; missing observations stay missing.",
    )
    return rows
