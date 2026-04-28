#!/usr/bin/env bash
# Runs ON THE vast.ai INSTANCE.
# Installs vLLM + deps so `serve.sh` can launch a Gemma 4 OpenAI-compatible server.
#
# Idempotent: re-running is safe and skips already-done work.
set -euo pipefail

MODEL_ID="${MODEL_ID:-google/gemma-4-31b-it}"
SERVE_PORT="${SERVE_PORT:-8000}"

echo "==> install.sh starting (model=$MODEL_ID)"
echo "==> python3: $(python3 --version 2>&1)"
echo "==> nvidia-smi:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends git curl ca-certificates

# Use a HF cache on the data disk so it survives `serve.sh` restarts and is
# big enough for a 31B model (~60GB in fp16). /workspace may not exist on
# minimal images, so create it defensively.
export HF_HOME=/workspace/.hf
export HF_HUB_ENABLE_HF_TRANSFER=1
mkdir -p /workspace "$HF_HOME"

# Persist env vars for any future SSH login (overwrite, don't append, so
# re-running install.sh doesn't accumulate duplicate lines).
cat > /etc/profile.d/gemma4.sh <<'PROF'
export HF_HOME=/workspace/.hf
export HF_HUB_ENABLE_HF_TRANSFER=1
PROF

# vllm/vllm-openai images already ship vllm; for a plain CUDA image we install it.
if ! python3 -c "import vllm" 2>/dev/null; then
  echo "==> installing vllm + transformers"
  pip install --upgrade pip
  # Gemma 4 requires recent transformers + vllm
  pip install "vllm>=0.8.0" "transformers>=4.55.0" "pillow" "huggingface_hub[hf_transfer]"
fi

# Optional: log into HF (Gemma 4 is Apache 2.0 — no token strictly required,
# but a token avoids unauthenticated rate limits on large downloads).
if [[ -n "${HF_TOKEN:-}" ]]; then
  echo "==> logging into Hugging Face"
  python3 -c "from huggingface_hub import login; login('$HF_TOKEN')"
fi

# Pre-fetch weights so the first request to /v1/chat/completions doesn't time out.
echo "==> pre-fetching $MODEL_ID weights (this is the slow part — 5 to 20 min)"
python3 - <<PY
import os
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id=os.environ["MODEL_ID"],
    cache_dir=os.environ["HF_HOME"],
    max_workers=8,
)
print("download complete")
PY

echo "==> install.sh done. Run ./serve.sh next."
