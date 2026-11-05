#!/usr/bin/env bash
# Translate the 12.7M-token Kinyarwanda synthetic set on the CPU builder.
set -euo pipefail
set -a
# shellcheck disable=SC1091
source /etc/ejochat.env
set +a
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$REGION"
export HF_HOME="/opt/ejochat/.cache/huggingface"
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
ROOT="/opt/ejochat"
cd "$ROOT"
export HF_TOKEN
HF_TOKEN="$(aws ssm get-parameter --name /ejochat/hf-token --with-decryption --query Parameter.Value --output text --region "$REGION")"
export GEMINI_API_KEY
GEMINI_API_KEY="$(aws ssm get-parameter --name /ejochat/gemini-api-key --with-decryption --query Parameter.Value --output text --region "$REGION")"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

(
  while true; do
    aws s3 cp "$ROOT/logs/status.json" "s3://${EJOCHAT_BUCKET}/logs/status.json" --region "$REGION" || true
    if [[ -d "$ROOT/data/mixture/kin_synthetic" ]]; then
      aws s3 sync "$ROOT/data/mixture/kin_synthetic/" "s3://${EJOCHAT_BUCKET}/mixture/kin_synthetic/" --region "$REGION" || true
    fi
    sleep 30
  done
) &
uploader=$!

# The sampler can abort while Python is shutting down, after the file is written.
if [[ ! -s data/synthetic/source/all.jsonl ]]; then
  python -m ejochat.data.synthetic prepare \
    --output data/synthetic/source \
    --status logs/status.json || true
fi
if [[ ! -s data/synthetic/source/all.jsonl ]]; then
  echo "English source file is missing." >&2
  exit 1
fi
python -m ejochat.data.synthetic gemini \
  --input data/synthetic/source/all.jsonl \
  --output data/mixture/kin_synthetic \
  --workers 16 \
  --status logs/status.json || true
source_lines="$(wc -l < data/synthetic/source/all.jsonl)"
written_lines=0
if [[ -s data/mixture/kin_synthetic/part-00001.jsonl ]]; then
  written_lines="$(wc -l < data/mixture/kin_synthetic/part-00001.jsonl)"
fi
# The translator stops at the 12.7M token cap, before every English source
# line has been used. That finished cap is a complete run.
tokens=0
if [[ -s logs/status.json ]]; then
  tokens="$(python3.11 -c 'import json; print(int(json.load(open("logs/status.json")).get("tokens") or 0))')"
fi
target="$(python3.11 -c 'import json; print(int(json.load(open("logs/status.json")).get("target") or 12707048))' 2>/dev/null || echo 12707048)"
if [[ "$tokens" -lt "$target" && "$written_lines" -lt "$source_lines" ]]; then
  echo "Translation stopped at ${written_lines} of ${source_lines} lines, ${tokens} of ${target} tokens." >&2
  exit 1
fi

aws s3 cp "s3://${EJOCHAT_BUCKET}/mixture/dataset_info.json" "$ROOT/data/mixture/dataset_info.json" --region "$REGION"
python3.11 - <<'PY'
import json
from pathlib import Path
info_path = Path("/opt/ejochat/data/mixture/dataset_info.json")
info = json.loads(info_path.read_text()) if info_path.exists() else {}
info["kin_synthetic"] = {"file_name": "kin_synthetic/", "columns": {"prompt": "text"}}
info_path.write_text(json.dumps(info, indent=2) + "\n")
status_path = Path("/opt/ejochat/logs/status.json")
status = json.loads(status_path.read_text()) if status_path.exists() else {}
status["stage"] = "finished"
status["message"] = "kin_synthetic is in the mixture."
status_path.write_text(json.dumps(status, indent=2) + "\n")
PY
aws s3 cp "$ROOT/data/mixture/dataset_info.json" "s3://${EJOCHAT_BUCKET}/mixture/dataset_info.json" --region "$REGION"
aws s3 sync "$ROOT/data/mixture/kin_synthetic/" "s3://${EJOCHAT_BUCKET}/mixture/kin_synthetic/" --region "$REGION"
aws s3 cp "$ROOT/logs/status.json" "s3://${EJOCHAT_BUCKET}/logs/status.json" --region "$REGION"
kill "$uploader" >/dev/null 2>&1 || true
unset HF_TOKEN GEMINI_API_KEY HUGGING_FACE_HUB_TOKEN
shutdown -h now || true
