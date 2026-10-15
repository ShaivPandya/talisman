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
| `generic-api-key` / public metric identifiers | `frontend/src/pages/{PortfolioAnalyzer,YieldCurve,MarketTechnicals,SectorMetrics}.tsx`, `macro/country_dashboard/country_dashboard.py` | Rechecked: frontend field names and public macro data-series identifiers. Exact-token allowlist only. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / synthetic Gemini key | Test fixtures | Rechecked: literal `AIza-test-key-12345678901234567890` is a synthetic credential used only in tests. Exact-token allowlist only. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / `llm.reasoning_effort.frontier_defaults_v2` | `api/llm_settings.py` | Public settings migration marker, read and written through `settings_store`; it is not authentication material. Exact token AND exact path. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / 20 exact financial series identifiers | Historical `longaeva/data/*.json`, Census extractor, test, and gate document | Public evidence keys for earnings metrics and Census series. Each token was reviewed; exact-token matching AND bounded historical paths. No whole-file exclusion. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / `request_key` SHA-256 fingerprints | Historical `longaeva/data/evaluation/visa_llm_baseline.json` and `longaeva/data/fixtures/llm_baseline/{cached,schema-validation-rejected,YYYY-MM-DD}.json` | Deterministic LLM request cache fingerprints, not provider credentials. Require exact field, 64 lowercase hex characters, AND these fixture paths. Other credential fields and other files remain scanned. | @ShaivPandya | 2026-10-14 | 2027-01-12 |
| `generic-api-key` / `anthropic_api_key=` | Historical `longaeva/backend/tests/test_llm_baseline.py` and `scripts/check_gitleaks_allowlists.py` | Scanner misparses adjacent `test-key` literals as a key assignment and captures this public Python argument name. The historical test uses `httpx.MockTransport`; the scanner guard reproduces that fixture. Exact token AND these two test paths; credential values in either file remain detected. | @ShaivPandya | 2026-10-14 | 2027-01-12 |

The TL-161 repair removes the unused `python-jose` runtime dependency (including
its vulnerable `ecdsa` dependency), updates the affected Python pins and both
JavaScript lockfiles, and retains all dependency audit gates without CVE ignores.
The historical secret findings were all `generic-api-key` false positives.
The full-history scan and a synthetic credential detection check must pass before
release. PR #427 records the suppression review required below.

The root Firebase package still pins the affected gRPC client to the 1.9 minor
series. Its `@grpc/grpc-js` override selects the patched 1.x API (at least 1.14.5)
without downgrading Firebase. Both root and frontend lockfiles are audited.

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
