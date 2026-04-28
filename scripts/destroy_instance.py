"""Destroy the vast.ai instance recorded in .instance.json."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

API = "https://console.vast.ai/api/v0"
ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    inst_file = ROOT / ".instance.json"
    if not inst_file.exists():
        sys.exit(".instance.json not found — nothing to destroy")
    inst = json.loads(inst_file.read_text())

    api_key = os.environ.get("VAST_API_KEY")
    if not api_key:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("VAST_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        sys.exit("VAST_API_KEY missing")

    r = requests.delete(
        f"{API}/instances/{inst['id']}/",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    r.raise_for_status()
    print(f"destroyed instance {inst['id']}")
    inst_file.unlink()


if __name__ == "__main__":
    main()
