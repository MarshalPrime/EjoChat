#!/usr/bin/env bash
# Print the CPU builder's progress. Pass --watch to refresh every 20 seconds.
# Requires an active aws login in this account.
set -euo pipefail
BUCKET="${EJOCHAT_BUCKET:-ejochat-cpt-682975283852}"
REGION="${AWS_REGION:-us-east-1}"

show() {
  echo "---- $(date -u +%Y-%m-%dT%H:%M:%SZ) ----"
  aws s3 cp "s3://${BUCKET}/logs/status.json" - --region "$REGION" \
    || echo "Status is not in the bucket yet."
  echo
}

if [[ "${1:-}" == "--watch" ]]; then
  while true; do
    show
    sleep 20
  done
else
  show
fi
