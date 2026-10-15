# Security Scanning — False-Positive & Allowlist Policy

This directory documents known false positives and bounded exceptions across
all CI security scanners. Every suppression must follow the structured format
below so suppressions are traceable, time-bounded, and reviewable.

## Scanners in CI

| Scanner | Scope | Gate level | Suppress mechanism |
|---------|-------|-----------|-------------------|
| `pip-audit` | Python dependency CVEs | All severities | `--ignore-vuln` flag in CI step |
| `npm audit` | Frontend dependency CVEs | High / Critical | `.npmrc` audit config or `npm audit` overrides |
| `gitleaks` | Secret detection in git history | All findings | `.gitleaks.toml` allowlist rules |
| `bandit` | Python static analysis (SAST) | High / Critical | `# nosec` inline or `.bandit` config |
| `trivy fs` | Dockerfile, IaC, container deps | High / Critical | `.trivyignore` at repo root |

## Adding a Suppression

Before adding any suppression, create a row in the appropriate table below.
All fields are required.

### Allowlist Entry Format

| Field | Description |
|-------|-------------|
| **Vulnerability ID** | CVE, GHSA, or scanner-specific rule ID |
| **Package / Scope** | Affected package name, file, or scan scope |
| **Reason** | Why this is a false positive or accepted risk |
| **Owner** | GitHub handle or email of the person accepting the risk |
| **Added** | ISO-8601 date when the exception was created |
| **Expiry** | ISO-8601 date when this must be re-evaluated (max 90 days) |

### pip-audit Allowlist

There are no active `pip-audit --ignore-vuln` entries.

If a bounded exception is needed, add a row below with the vulnerability ID,
then add the `--ignore-vuln` flag to the CI step.

| Vulnerability ID | Package | Reason | Owner | Added | Expiry |
|-----------------|---------|--------|-------|-------|--------|
| *(none)* | | | | | |

### npm audit Allowlist

No active exceptions.

| Vulnerability ID | Package | Reason | Owner | Added | Expiry |
|-----------------|---------|--------|-------|-------|--------|
| *(none)* | | | | | |

### gitleaks Allowlist

Suppressions go in `.gitleaks.toml` at the repo root.

| Rule ID / Pattern | File / Scope | Reason | Owner | Added | Expiry |
|-------------------|-------------|--------|-------|-------|--------|
| `generic-api-key` / public metric identifiers | `frontend/src/pages/{PortfolioAnalyzer,YieldCurve,MarketTechnicals,SectorMetrics}.tsx`, `macro/country_dashboard/country_dashboard.py` | Re-reviewed public field/data-series identifiers; exact tokens remain unchanged. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / synthetic Gemini key | Tests | Exact nonfunctional fixture key `AIza-test-key-12345678901234567890`; never a live credential. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / `llm.reasoning_effort.frontier_defaults_v2` | `api/llm_settings.py` | Public database setting identifier introduced by the model-default migration; exact token and path must both match. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / 20 exact public metric identifiers | Exact historical files enumerated for each identifier in `.gitleaks.toml` | Public financial observations and Census field names. Each anchored token must match one of its exact reviewed paths; no directory wildcards. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / 17 exact SHA-256 request cache digests | Exact historical fixture files enumerated for each digest in `.gitleaks.toml` | Non-authenticating cache lookups. Only the 17 reviewed digest values at their exact reviewed paths are allowed; no hash-format pattern or directory wildcards. | @ShaivPandya | 2026-10-14 | 2027-01-12 |

The owner reviewed these false positives in PR #423 and requested exact hashes
and file paths on 2026-10-14. The revised rules cover 38 exact public identifiers
and cache hashes across 24 exact historical paths, including the settings key
above. Default detection rules remain enabled.

### bandit Allowlist

No active `# nosec` suppressed findings.

| Issue ID | File:Line | Reason | Owner | Added | Expiry |
|----------|-----------|--------|-------|-------|--------|
| *(none)* | | | | | |

### Trivy Allowlist

No active entries in `.trivyignore`.

| CVE / ID | Component | Reason | Owner | Added | Expiry |
|----------|-----------|--------|-------|-------|--------|
| *(none)* | | | | | |

## Review Process

1. **Before suppressing**: Verify the finding is genuinely a false positive
   or the risk is accepted and bounded.
2. **Add the row** in this document with all required fields.
3. **Add the technical suppression** (ignore flag, `.trivyignore` entry, etc.).
4. **Set an expiry** no more than 90 days out.
5. **PR review**: Suppressions require at least one approving review.
6. **Expiry review**: Expired entries should be re-evaluated in the next PR
   that touches the affected area, or in a scheduled quarterly review.
