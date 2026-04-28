#!/usr/bin/env bash
# Tail the onstart log on the rented instance, then probe /v1/models.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .instance.json ]]; then
  echo "no .instance.json — run `make up` first" >&2
  exit 1
fi

SSH_HOST=$(python -c "import json;print(json.load(open('.instance.json'))['ssh_host'])")
SSH_PORT=$(python -c "import json;print(json.load(open('.instance.json'))['ssh_port'])")
SERVE_HOST=$(python -c "import json;print(json.load(open('.instance.json'))['serve_host'])")
SERVE_PORT=$(python -c "import json;print(json.load(open('.instance.json'))['serve_port'])")

echo "==> last 40 lines of onstart.log:"
ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no "root@$SSH_HOST" \
    "tail -n 40 /workspace/onstart.log 2>/dev/null || echo '(log not yet created)'"

echo
echo "==> probing http://${SERVE_HOST}:${SERVE_PORT}/v1/models"
curl -fsS --max-time 5 "http://${SERVE_HOST}:${SERVE_PORT}/v1/models" || echo "(not ready yet)"
echo
