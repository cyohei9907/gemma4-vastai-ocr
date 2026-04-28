#!/usr/bin/env bash
# Open an SSH local-port-forward from 127.0.0.1:<SERVE_PORT> on this machine
# to <SERVE_PORT> inside the vast.ai instance. vast.ai does not always expose
# arbitrary container ports externally, so the tunnel is the reliable path
# for the local Flask client to reach vLLM.
#
# After this script prints "tunnel up", set REMOTE_HOST=127.0.0.1 and
# REMOTE_PORT=<SERVE_PORT> in .env, then `make client`.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .instance.json ]]; then
  echo 'no .instance.json — run `make up` first' >&2
  exit 1
fi

SSH_PORT=$(python -c "import json;print(json.load(open('.instance.json'))['ssh_port'])")
SERVE_PORT=$(python -c "import json;print(json.load(open('.instance.json'))['serve_port'])")
KEY="${VAST_SSH_KEY:-$HOME/.ssh/vast_ed25519}"

echo "==> forwarding 127.0.0.1:${SERVE_PORT} -> ssh1.vast.ai:${SSH_PORT} -> instance:${SERVE_PORT}"
exec ssh -N \
    -i "$KEY" \
    -p "$SSH_PORT" \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -L "${SERVE_PORT}:127.0.0.1:${SERVE_PORT}" \
    "root@ssh1.vast.ai"
