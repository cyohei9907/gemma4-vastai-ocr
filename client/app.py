"""Local OCR client.

Serves a tiny web page where you drag-drop an image; the server forwards it
to the remote vLLM endpoint as a chat-completions request with an image part,
and renders the model's text response.

Run:
    pip install flask requests python-dotenv
    python client/app.py
Then open http://127.0.0.1:5000
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()

# Prefer .instance.json (written by create_instance.py) over .env.
inst_file = ROOT / ".instance.json"
if inst_file.exists():
    inst = json.loads(inst_file.read_text())
    REMOTE_HOST = inst.get("serve_host") or os.environ.get("REMOTE_HOST", "")
    REMOTE_PORT = str(inst.get("serve_port") or os.environ.get("REMOTE_PORT", "8000"))
else:
    REMOTE_HOST = os.environ.get("REMOTE_HOST", "")
    REMOTE_PORT = os.environ.get("REMOTE_PORT", "8000")

MODEL_ID = os.environ.get("MODEL_ID", "google/gemma-4-31b-it")

DEFAULT_PROMPT = (
    "Extract all text visible in this image exactly as written, preserving "
    "line breaks and reading order. If the image contains tables, render them "
    "as Markdown tables. Output only the extracted text — no commentary."
)

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))


@app.get("/")
def index():
    backend = f"http://{REMOTE_HOST}:{REMOTE_PORT}" if REMOTE_HOST else "(not configured)"
    return render_template("index.html", backend=backend, model=MODEL_ID, default_prompt=DEFAULT_PROMPT)


@app.post("/api/ocr")
def ocr():
    if not REMOTE_HOST:
        return jsonify({"error": "REMOTE_HOST not set — run `make up` first (or set REMOTE_HOST/REMOTE_PORT in .env)"}), 400

    f = request.files.get("image")
    if not f:
        return jsonify({"error": "no image uploaded"}), 400
    prompt = (request.form.get("prompt") or DEFAULT_PROMPT).strip()

    raw = f.read()
    if not raw:
        return jsonify({"error": "empty file"}), 400
    mime = f.mimetype or "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    body = {
        "model": MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": 2048,
    }

    try:
        r = requests.post(
            f"http://{REMOTE_HOST}:{REMOTE_PORT}/v1/chat/completions",
            json=body,
            timeout=180,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        return jsonify({"error": f"upstream error: {e}"}), 502

    out = r.json()
    text = out["choices"][0]["message"]["content"]
    usage = out.get("usage", {})
    return jsonify({"text": text, "usage": usage})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
