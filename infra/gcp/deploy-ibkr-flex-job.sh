#!/usr/bin/env bash
# Deploy the Flex-only async executor with dedicated static outbound IP routing.
# Prerequisite: setup-ibkr-flex-egress.sh has provisioned the subnet and NAT.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [[ "${SCHEDULE_IBKR_FLEX_SYNC:-0}" != "1" ]]; then
  echo "IBKR Flex sync is disabled; skipping its worker."
  exit 0
fi

for variable in PROJECT_ID REGION WORKER_SA API_SA CLOUDSQL_INSTANCE GCS_STATE_BUCKET; do
  require_var "${variable}"
done
require_active_project
require_image_exists

gcloud compute networks subnets describe "${IBKR_FLEX_EGRESS_SUBNET}" \
  --project="${PROJECT_ID}" --region="${REGION}" >/dev/null

# Direct VPC egress can take tens of seconds to become usable at cold start.
# Give the initial database claim time to connect without widening API deadlines.
POSTGRES_POOL_TIMEOUT_SECONDS=60
mapfile -t FLEX_ENV < <(common_env_vars)
FLEX_ENV+=(
  "ASYNC_JOB_BACKEND=cloud_run_jobs"
  "ASYNC_CLOUD_RUN_JOB=${IBKR_FLEX_SYNC_JOB}"
  "POSTGRES_POOL_MAX_SIZE=${POSTGRES_POOL_MAX_SIZE:-2}"
  "SENTRY_ENVIRONMENT=production"
)

# Flex stages broker statements; it does not need model-provider credentials.
FLEX_SECRETS=()
for binding in "${WORKER_SECRETS[@]}"; do
  case "${binding%%=*}" in
    DATABASE_URL|IBKR_FLEX_TOKEN|IBKR_FLEX_QUERY_ID|SENTRY_DSN)
      FLEX_SECRETS+=("${binding}") ;;
  esac
done

gcloud run jobs deploy "${IBKR_FLEX_SYNC_JOB}" \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --image="$(image_uri)" --service-account="${WORKER_SA}" \
  --set-cloudsql-instances="${CLOUDSQL_INSTANCE}" \
  --command=python --args=-m,api.async_job_runner,run \
  --set-env-vars="$(join_kv "${FLEX_ENV[@]}")" \
  --set-secrets="$(join_kv "${FLEX_SECRETS[@]}")" \
  --network="${IBKR_FLEX_EGRESS_NETWORK}" \
  --subnet="${IBKR_FLEX_EGRESS_SUBNET}" --vpc-egress=all-traffic \
  --cpu=1 --memory=1Gi --max-retries=0 --task-timeout=900

# The API passes the durable async job ID through an execution override.
gcloud run jobs add-iam-policy-binding "${IBKR_FLEX_SYNC_JOB}" \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --member="serviceAccount:${API_SA}" \
  --role=roles/run.jobsExecutorWithOverrides --quiet >/dev/null
