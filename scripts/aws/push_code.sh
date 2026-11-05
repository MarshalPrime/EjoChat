#!/usr/bin/env bash
# Upload this repo to the CPT bucket. Datasets and checkpoints stay on S3
# under mixture/ and outputs/, so a later code sync does not delete them.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUCKET="$(terraform -chdir="$ROOT/infra" output -raw bucket_name)"
REGION="$(terraform -chdir="$ROOT/infra" output -raw aws_region)"

aws s3 sync "$ROOT/" "s3://${BUCKET}/code/" \
  --region "$REGION" \
  --exclude ".git/*" \
  --exclude ".venv/*" \
  --exclude ".cache/*" \
  --exclude "hf-cache/*" \
  --exclude "secrets.env" \
  --exclude "infra/.terraform/*" \
  --exclude "infra/*.tfstate" \
  --exclude "infra/*.tfstate.*" \
  --exclude "data/mixture/*" \
  --exclude "data/mixture-*/*" \
  --exclude "data/synthetic/*" \
  --exclude "data/Datasets/*" \
  --exclude "outputs/*" \
  --exclude "logs/*" \
  --exclude "__pycache__/*" \
  --exclude "*.pyc"

echo "Code is at s3://${BUCKET}/code/"
