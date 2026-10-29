#!/usr/bin/env bash
# Idempotently provision static egress for the Flex worker only.
# This reserves a billable external IP and configures a small dedicated subnet.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [[ "${SCHEDULE_IBKR_FLEX_SYNC:-0}" != "1" ]]; then
  echo "Enable SCHEDULE_IBKR_FLEX_SYNC=1 before setting up Flex egress." >&2
  exit 1
fi
require_var PROJECT_ID
require_var REGION
require_active_project

if gcloud compute networks subnets describe "${IBKR_FLEX_EGRESS_SUBNET}" \
    --project="${PROJECT_ID}" --region="${REGION}" >/dev/null 2>&1; then
  current_network="$(gcloud compute networks subnets describe "${IBKR_FLEX_EGRESS_SUBNET}" \
    --project="${PROJECT_ID}" --region="${REGION}" --format='value(network)')"
  current_cidr="$(gcloud compute networks subnets describe "${IBKR_FLEX_EGRESS_SUBNET}" \
    --project="${PROJECT_ID}" --region="${REGION}" --format='value(ipCidrRange)')"
  if [[ "${current_network##*/}" != "${IBKR_FLEX_EGRESS_NETWORK}" || "${current_cidr}" != "${IBKR_FLEX_EGRESS_CIDR}" ]]; then
    echo "Existing Flex subnet differs from configured network/CIDR; refusing to change it." >&2
    exit 1
  fi
else
  gcloud compute networks subnets create "${IBKR_FLEX_EGRESS_SUBNET}" \
    --project="${PROJECT_ID}" --region="${REGION}" \
    --network="${IBKR_FLEX_EGRESS_NETWORK}" --range="${IBKR_FLEX_EGRESS_CIDR}" \
    --enable-private-ip-google-access --quiet
fi

if gcloud compute routers describe "${IBKR_FLEX_EGRESS_ROUTER}" \
    --project="${PROJECT_ID}" --region="${REGION}" >/dev/null 2>&1; then
  current_network="$(gcloud compute routers describe "${IBKR_FLEX_EGRESS_ROUTER}" \
    --project="${PROJECT_ID}" --region="${REGION}" --format='value(network)')"
  if [[ "${current_network##*/}" != "${IBKR_FLEX_EGRESS_NETWORK}" ]]; then
    echo "Existing Flex router uses a different network; refusing to change it." >&2
    exit 1
  fi
else
  gcloud compute routers create "${IBKR_FLEX_EGRESS_ROUTER}" \
    --project="${PROJECT_ID}" --region="${REGION}" \
    --network="${IBKR_FLEX_EGRESS_NETWORK}" --quiet
fi

if ! gcloud compute addresses describe "${IBKR_FLEX_EGRESS_IP}" \
    --project="${PROJECT_ID}" --region="${REGION}" >/dev/null 2>&1; then
  gcloud compute addresses create "${IBKR_FLEX_EGRESS_IP}" \
    --project="${PROJECT_ID}" --region="${REGION}" --quiet
fi

nat_action=create
if gcloud compute routers nats describe "${IBKR_FLEX_EGRESS_NAT}" \
    --router="${IBKR_FLEX_EGRESS_ROUTER}" --project="${PROJECT_ID}" \
    --region="${REGION}" >/dev/null 2>&1; then
  nat_action=update
fi
gcloud compute routers nats "${nat_action}" "${IBKR_FLEX_EGRESS_NAT}" \
  --router="${IBKR_FLEX_EGRESS_ROUTER}" --project="${PROJECT_ID}" \
  --region="${REGION}" --nat-custom-subnet-ip-ranges="${IBKR_FLEX_EGRESS_SUBNET}" \
  --nat-external-ip-pool="${IBKR_FLEX_EGRESS_IP}" --quiet

gcloud compute addresses describe "${IBKR_FLEX_EGRESS_IP}" \
  --project="${PROJECT_ID}" --region="${REGION}" --format='value(address)'
