#!/usr/bin/env bash
# Launch continued pre-training. Run this on the GPU machine after the
# mixture is in data/mixture. EjoChat chats are for instruction tuning.
set -euo pipefail

CONFIG="${1:-train/configs/qwen3-8b-kin-cms.yaml}"
if [[ ! -d data/mixture/kin_mono || ! -d data/mixture/kin_synthetic ]]; then
  echo "kin_mono or kin_synthetic is missing from data/mixture." >&2
  exit 1
fi

llamafactory-cli train "$CONFIG"
