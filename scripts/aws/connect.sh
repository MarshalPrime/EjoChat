#!/usr/bin/env bash
# Open a shell on the trainer. GPU charges continue until the instance is stopped or destroyed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTANCE="$(terraform -chdir="$ROOT/infra" output -raw instance_id)"
REGION="$(terraform -chdir="$ROOT/infra" output -raw aws_region)"

if [[ -z "$INSTANCE" || "$INSTANCE" == "null" ]]; then
  echo "No trainer is running. Launch one with:" >&2
  echo "  terraform -chdir=infra apply -var=launch_trainer=true" >&2
  exit 1
fi

exec aws ssm start-session --region "$REGION" --target "$INSTANCE"
