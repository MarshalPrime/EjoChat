#!/usr/bin/env bash
# Runs on the CPU builder. Reads tokens from Parameter Store, builds the
# mixture, translates with Gemini, uploads to S3, then shuts the machine down.
set -euo pipefail
set -a
# shellcheck disable=SC1091
source /etc/ejochat.env
set +a
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$REGION"
export HF_HOME="/opt/ejochat/.cache/huggingface"
export HF_HUB_DISABLE_TELEMETRY=1
export PYTHONUNBUFFERED=1
ROOT="/opt/ejochat"
cd "$ROOT"
mkdir -p "$ROOT/logs" "$ROOT/data/mixture" "$ROOT/data/synthetic/source"

for _ in $(seq 1 60); do
  [[ -f "$ROOT/logs/ready" ]] && break
  sleep 10
done
if [[ ! -f "$ROOT/logs/ready" ]]; then
  echo "Code sync did not finish" >&2
  exit 1
fi

export HF_TOKEN
HF_TOKEN="$(aws ssm get-parameter --name /ejochat/hf-token --with-decryption --query Parameter.Value --output text --region "$REGION")"
export GEMINI_API_KEY
GEMINI_API_KEY="$(aws ssm get-parameter --name /ejochat/gemini-api-key --with-decryption --query Parameter.Value --output text --region "$REGION")"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

python3.11 -m venv "$ROOT/.venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip
python -m pip install -r requirements-data.txt

(
  while true; do
    aws s3 cp "$ROOT/logs/status.json" "s3://${EJOCHAT_BUCKET}/logs/status.json" --region "$REGION" || true
    aws s3 sync "$ROOT/data/mixture/" "s3://${EJOCHAT_BUCKET}/mixture-full/" --region "$REGION" || true
    sleep 30
  done
) &
uploader=$!

finish() {
  local code=$?
  kill "$uploader" >/dev/null 2>&1 || true
  wait "$uploader" 2>/dev/null || true
  if [[ ! -f "$ROOT/logs/success" ]]; then
    python3.11 - "$code" <<'PY' || true
import json, sys
from pathlib import Path
path = Path("/opt/ejochat/logs/status.json")
payload = json.loads(path.read_text()) if path.exists() else {}
payload["stage"] = "failed"
payload["message"] = f"Build stopped with exit code {sys.argv[1]}. Partial output is in mixture-full/."
path.write_text(json.dumps(payload, indent=2) + "\n")
PY
  fi
  aws s3 cp "$ROOT/logs/status.json" "s3://${EJOCHAT_BUCKET}/logs/status.json" --region "$REGION" || true
  aws s3 sync "$ROOT/data/mixture/" "s3://${EJOCHAT_BUCKET}/mixture-full/" --region "$REGION" || true
  if [[ -f "$ROOT/logs/success" ]]; then
    aws ssm delete-parameter --name /ejochat/hf-token --region "$REGION" || true
    aws ssm delete-parameter --name /ejochat/gemini-api-key --region "$REGION" || true
  fi
  unset HF_TOKEN GEMINI_API_KEY HUGGING_FACE_HUB_TOKEN
  shutdown -h now || true
  exit "$code"
}
trap finish EXIT

python -m ejochat.data.build_cms \
  --config data/kin_cms.yaml \
  --output data/mixture \
  --cache-dir .cache/ejochat \
  --status logs/status.json

python -m ejochat.data.add_written_kin
mkdir -p data/mixture/kin_gazette data/mixture/kin_health
cp -R data/mixture-written/kin_gazette/. data/mixture/kin_gazette/
cp -R data/mixture-written/kin_health/. data/mixture/kin_health/
python3.11 - <<'PY'
import json
from pathlib import Path
info_path = Path("data/mixture/dataset_info.json")
info = json.loads(info_path.read_text()) if info_path.exists() else {}
extra = json.loads(Path("data/mixture-written/dataset_info.json").read_text())
info.update(extra)
info.pop("kin_synthetic", None)
info_path.write_text(json.dumps(info, indent=2) + "\n")
PY

aws s3 sync "$ROOT/data/mixture/" "s3://${EJOCHAT_BUCKET}/mixture/" --region "$REGION" --delete
python3.11 - <<PY
import json
from pathlib import Path
path = Path("/opt/ejochat/logs/status.json")
payload = json.loads(path.read_text())
payload["stage"] = "finished"
payload["message"] = "Full mixture is in s3://${EJOCHAT_BUCKET}/mixture/"
path.write_text(json.dumps(payload, indent=2) + "\n")
PY
touch "$ROOT/logs/success"
