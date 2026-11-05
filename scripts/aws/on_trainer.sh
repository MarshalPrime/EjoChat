#!/usr/bin/env bash
# Run this on the GPU instance, inside tmux, after connect.sh.
#   tmux new -s cpt
#   export HF_TOKEN=...
#   export EJOCHAT_BUCKET=...    # printed by push_code.sh
#   ./scripts/aws/on_trainer.sh pull
#   ./scripts/aws/on_trainer.sh data
#   ./scripts/aws/on_trainer.sh train
set -euo pipefail

ROOT="/opt/ejochat"
BUCKET="${EJOCHAT_BUCKET:?Set EJOCHAT_BUCKET to the Terraform bucket_name output}"
COMMAND="${1:-pull}"

sync_code() {
  aws s3 sync "s3://${BUCKET}/code/" "$ROOT/" \
    --exclude "data/mixture/*" \
    --exclude "outputs/*" \
    --exclude ".cache/*"
  sudo chown -R ubuntu:ubuntu "$ROOT"
}

sync_outputs() {
  aws s3 sync "$ROOT/outputs/" "s3://${BUCKET}/outputs/"
}

case "$COMMAND" in
  pull)
    sync_code
    ;;
  data)
    sync_code
    cd "$ROOT"
    if [[ -z "${HF_TOKEN:-}" ]]; then
      echo "Export HF_TOKEN first. The Gemma license must be accepted on that account." >&2
      exit 1
    fi
    python3 -m venv .venv
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install -U pip
    pip install -r requirements-data.txt
    if ! aws s3 ls "s3://${BUCKET}/mixture/dataset_info.json" >/dev/null 2>&1; then
      python -m ejochat.data.build_cms --config data/kin_cms.yaml --output data/mixture
      aws s3 sync data/mixture/ "s3://${BUCKET}/mixture/"
    else
      aws s3 sync "s3://${BUCKET}/mixture/" data/mixture/
    fi
    echo "Text mixture is in s3://${BUCKET}/mixture/."
    ;;
  train)
    sync_code
    cd "$ROOT"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install torch --index-url https://download.pytorch.org/whl/cu124
    pip install -r requirements-train.txt
    mkdir -p outputs
    (
      while true; do
        sync_outputs || true
        sleep 600
      done
    ) &
    uploader=$!
    trap 'kill "$uploader" || true; sync_outputs || true' EXIT
    bash train/run_cpt.sh "${2:-train/configs/qwen3-8b-kin-cms.yaml}"
    sync_outputs
    ;;
  *)
    echo "Use: pull, data, or train" >&2
    exit 1
    ;;
esac
