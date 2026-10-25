#!/usr/bin/env bash
# Preview optional credential setup, or use --apply to upload supplied keys.
# Usage: ./infra/gcp/setup-data-source-secrets.sh --env-file .env.data-sources --apply
# Values travel to Secret Manager over stdin, never through command arguments.
set +x
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_var PROJECT_ID
require_var API_SA
require_var WORKER_SA
require_active_project

_repo_root="$(cd "${_here}/../.." && pwd)"
cd "${_repo_root}"
"$(python_bin)" -m infra.gcp.data_source_secrets \
  --project="${PROJECT_ID}" \
  --service-account="${API_SA}" \
  --service-account="${WORKER_SA}" \
  --config-file="${_here}/config.sh" \
  "$@"
