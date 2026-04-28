#!/usr/bin/env bash
# Runs ON THE vast.ai INSTANCE.
# Starts (or restarts) a vLLM OpenAI-compatible server hosting Gemma 4.
set -euo pipefail

MODEL_ID="${MODEL_ID:-google/gemma-4-31b-it}"
SERVE_PORT="${SERVE_PORT:-8000}"
export HF_HOME="${HF_HOME:-/workspace/.hf}"
export HF_HUB_ENABLE_HF_TRANSFER=1

mkdir -p /workspace
LOG=/workspace/vllm.log

# Detect GPU count to set tensor parallelism. 31B in fp16 needs >=80GB VRAM,
# which usually means 1xH100/A100-80G or 2-4xRTX 4090.
GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
if [[ -z "$GPU_COUNT" || "$GPU_COUNT" -lt 1 ]]; then
  echo "ERROR: nvidia-smi reported no GPUs — abort" >&2
  exit 1
fi
TP=$GPU_COUNT
echo "==> detected $GPU_COUNT GPU(s) — using tensor-parallel=$TP"

# Kill any previous vLLM on the same port before restarting.
if pgrep -f "vllm.entrypoints.openai.api_server" >/dev/null; then
  echo "==> stopping previous vllm server"
  pkill -f "vllm.entrypoints.openai.api_server" || true
  sleep 3
fi

echo "==> launching vLLM serving $MODEL_ID on :$SERVE_PORT (logs: $LOG)"
nohup python3 -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_ID" \
  --host 0.0.0.0 \
  --port "$SERVE_PORT" \
  --tensor-parallel-size "$TP" \
  --max-model-len 8192 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.92 \
  --trust-remote-code \
  > "$LOG" 2>&1 &

echo "==> waiting for /v1/models to respond (up to 15 min)..."
for i in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${SERVE_PORT}/v1/models" >/dev/null 2>&1; then
    echo "==> server is up:"
    curl -fsS "http://127.0.0.1:${SERVE_PORT}/v1/models"
    echo
    exit 0
  fi
  sleep 10
done

echo "ERROR: vllm did not become ready in 15 min — last 80 lines of $LOG:" >&2
tail -n 80 "$LOG" >&2
exit 1
