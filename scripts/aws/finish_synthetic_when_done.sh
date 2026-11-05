#!/usr/bin/env bash
# Wait until the running translation stops at its token cap, upload the
# finished file, and shut the machine down. Training is not started.
set -euo pipefail
set -a
# shellcheck disable=SC1091
source /etc/ejochat.env
set +a
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$REGION"
ROOT="/opt/ejochat"
cd "$ROOT"
LOG="$ROOT/logs/finish_synthetic.log"
exec >>"$LOG" 2>&1
echo "watcher started $(date -u +%Y-%m-%dT%H:%M:%SZ)"

while pgrep -f 'ejochat.data.synthetic gemini' >/dev/null; do
  sleep 30
done
sleep 15

python3.11 - <<'PY'
import json
from pathlib import Path
status = json.loads(Path("/opt/ejochat/logs/status.json").read_text())
tokens = int(status.get("tokens") or 0)
target = int(status.get("target") or 12707048)
print(f"translation process ended at {tokens} of {target} tokens")
if tokens < target:
    raise SystemExit("token target was not reached; leaving the machine on")
PY

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
aws s3 cp "$LOG" "s3://${EJOCHAT_BUCKET}/logs/finish_synthetic.log" --region "$REGION"
echo "shutting down $(date -u +%Y-%m-%dT%H:%M:%SZ)"
aws s3 cp "$LOG" "s3://${EJOCHAT_BUCKET}/logs/finish_synthetic.log" --region "$REGION" || true
shutdown -h now || true
