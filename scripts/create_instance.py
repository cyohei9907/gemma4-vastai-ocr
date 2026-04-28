"""Provision a vast.ai GPU instance and have it auto-clone this repo + start vLLM.

Flow on the rented box:
    1. vast.ai runs `onstart` (below) once provisioning finishes
    2. onstart clones REPO_URL into /workspace/repo
    3. onstart runs install.sh (deps + weight pre-fetch)
    4. onstart runs serve.sh (launches vLLM)

After this script returns, hit the OCR endpoint via the host:port written
to .instance.json. No further deploy step needed.

Usage:
    python scripts/create_instance.py            # rent + auto-deploy
    python scripts/create_instance.py --dry-run  # just print the offer
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://console.vast.ai/api/v0"
ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k, v in os.environ.items():
        env.setdefault(k, v)
    return env


def search_offers(api_key: str, min_vram_gb: int) -> list[dict]:
    """Find on-demand offers with enough VRAM to host the chosen model.

    For gemma-4-31b-it (fp16) we want >=80GB total VRAM; vLLM will tensor-parallel
    across multiple cards if no single GPU is large enough.
    """
    query = {
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "gpu_total_ram": {"gte": min_vram_gb * 1024},  # MB, summed across GPUs
        # Ampere or newer — Gemma 4 ships in bf16, which Turing (sm_75) lacks.
        # compute_cap is stored x10 (750 = sm_7.5, 800 = sm_8.0).
        "compute_cap": {"gte": 800},
        # vLLM tensor-parallel works best with 1, 2 or 4 GPUs.
        "num_gpus": {"lte": 4},
        "cuda_max_good": {"gte": 12.1},
        "inet_down": {"gte": 200},
        "disk_space": {"gte": 120},
        "rented": {"eq": False},
        "type": "on-demand",
        "order": [["dph_total", "asc"]],
    }
    r = requests.get(
        f"{API}/bundles/",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"q": json.dumps(query)},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("offers", [])


def build_onstart(repo_url: str, repo_branch: str, model_id: str, serve_port: int, hf_token: str) -> str:
    """Compose the script vast.ai runs once on first boot."""
    hf_export = f"export HF_TOKEN={hf_token}\nexport HUGGING_FACE_HUB_TOKEN={hf_token}" if hf_token else ""
    return f"""#!/bin/bash
set -euo pipefail
exec > >(tee -a /workspace/onstart.log) 2>&1

echo "==> onstart.sh @ $(date)"
{hf_export}
export MODEL_ID={model_id}
export SERVE_PORT={serve_port}

apt-get update -qq
apt-get install -y -qq --no-install-recommends git curl ca-certificates

cd /workspace
if [[ ! -d repo/.git ]]; then
    git clone --depth 1 --branch {repo_branch} {repo_url} repo
else
    cd repo && git fetch --depth 1 origin {repo_branch} && git reset --hard origin/{repo_branch} && cd ..
fi
cd repo
chmod +x install.sh serve.sh
bash install.sh
bash serve.sh
echo "==> onstart.sh done"
""".strip()


def rent(
    api_key: str,
    offer_id: int,
    repo_url: str,
    repo_branch: str,
    hf_token: str,
    model_id: str,
    serve_port: int,
) -> int:
    onstart = build_onstart(repo_url, repo_branch, model_id, serve_port, hf_token)
    body = {
        "client_id": "me",
        "image": "vllm/vllm-openai:latest",
        "disk": 120,
        "label": f"gemma4-ocr",
        "onstart": onstart,
        "env": {
            "-p": f"{serve_port}:{serve_port}",
            "MODEL_ID": model_id,
            "SERVE_PORT": str(serve_port),
            **({"HF_TOKEN": hf_token, "HUGGING_FACE_HUB_TOKEN": hf_token} if hf_token else {}),
        },
        "runtype": "ssh",
    }
    r = requests.put(
        f"{API}/asks/{offer_id}/",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise SystemExit(f"vast.ai refused rent: {data}")
    return int(data["new_contract"])


def wait_running(api_key: str, contract_id: int, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(
            f"{API}/instances/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        r.raise_for_status()
        for inst in r.json().get("instances", []):
            if inst.get("id") == contract_id and inst.get("actual_status") == "running":
                return inst
        time.sleep(10)
    raise SystemExit("instance did not reach running state in time")


def write_instance_file(inst: dict, serve_port: int) -> None:
    host = inst.get("public_ipaddr") or inst.get("ssh_host")
    ssh_port = inst.get("ssh_port")
    mapped = None
    for port_info in (inst.get("ports") or {}).get(f"{serve_port}/tcp", []) or []:
        mapped = int(port_info["HostPort"])
        break
    out = {
        "id": inst["id"],
        "ssh_host": host,
        "ssh_port": ssh_port,
        "serve_host": host,
        "serve_port": mapped or serve_port,
    }
    (ROOT / ".instance.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-vram-gb", type=int, default=80,
                   help="minimum total GPU VRAM in GB (default 80 for gemma-4-31b-it)")
    args = p.parse_args()

    env = load_env()
    api_key = env.get("VAST_API_KEY")
    repo_url = env.get("REPO_URL")
    repo_branch = env.get("REPO_BRANCH", "main")
    hf_token = env.get("HF_TOKEN", "")
    model_id = env.get("MODEL_ID", "google/gemma-4-31b-it")
    serve_port = int(env.get("SERVE_PORT", "8000"))

    if not api_key:
        sys.exit("VAST_API_KEY missing — fill .env")
    if not args.dry_run and not repo_url:
        sys.exit("REPO_URL missing — set it to the public clone URL of this repo, e.g. "
                 "https://github.com/<user>/gemma4-vastai-ocr.git")

    offers = search_offers(api_key, min_vram_gb=args.min_vram_gb)
    if not offers:
        sys.exit("no matching offers — relax filters or retry later")
    pick = offers[0]
    print(
        f"picked offer {pick['id']}: {pick['gpu_name']} x{pick['num_gpus']} "
        f"(total {pick['gpu_total_ram']/1024:.0f}GB VRAM) @ ${pick['dph_total']:.3f}/h"
    )
    if args.dry_run:
        return

    contract_id = rent(api_key, pick["id"], repo_url, repo_branch, hf_token, model_id, serve_port)
    print(f"rented contract {contract_id}; waiting for it to come up...")
    inst = wait_running(api_key, contract_id)
    write_instance_file(inst, serve_port)
    print(
        "\ninstance is up. The onstart hook is now installing deps and downloading "
        "the model — this takes 5-20 minutes. Tail progress with:\n"
        f"    ssh -p {inst.get('ssh_port')} root@{inst.get('public_ipaddr')} 'tail -f /workspace/onstart.log'\n"
        "Once /v1/models responds, run `make client`."
    )


if __name__ == "__main__":
    main()
