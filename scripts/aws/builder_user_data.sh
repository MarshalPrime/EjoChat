#!/bin/bash
# First boot of the CPU builder. Package install and code sync only.
# The build itself starts over SSM so secrets never land in this file.
set -euo pipefail
exec > >(tee /var/log/ejochat-builder.log) 2>&1
dnf install -y python3.11
mkdir -p /opt/ejochat/logs
echo "EJOCHAT_BUCKET=__BUCKET__" > /etc/ejochat.env
python3.11 - <<'PY'
import json, time
from pathlib import Path
now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
Path("/opt/ejochat/logs/status.json").write_text(json.dumps({
    "stage": "booting",
    "message": "Installing packages and syncing code",
    "started_at": now,
    "updated_at": now,
    "elapsed": "0s",
    "tokens": 0,
    "target": 0,
}, indent=2) + "\n")
PY
aws s3 cp /opt/ejochat/logs/status.json "s3://__BUCKET__/logs/status.json" --region us-east-1
aws s3 sync "s3://__BUCKET__/code/" /opt/ejochat/ --region us-east-1 \
  --exclude "data/mixture/*" --exclude ".cache/*" --exclude "secrets.env"
touch /opt/ejochat/logs/ready
python3.11 - <<'PY'
import json
from pathlib import Path
path = Path("/opt/ejochat/logs/status.json")
payload = json.loads(path.read_text())
payload["stage"] = "ready"
payload["message"] = "Code is on the machine. The mixture build is starting."
path.write_text(json.dumps(payload, indent=2) + "\n")
PY
aws s3 cp /opt/ejochat/logs/status.json "s3://__BUCKET__/logs/status.json" --region us-east-1
