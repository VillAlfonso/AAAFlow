"""Local vision-language client (Ollama): the studio's video eyes.

Feeds gatherer frame sheets (or any image) to a locally pulled VLM and
returns text or structured JSON. Fully local, zero cloud. Models are asked
to unload after a short keep-alive so nothing squats on the 16 GB card;
``unload()`` is wired into gpu.release_all.

Ollama's tray app respawn-loops on this machine; a detached ``ollama serve``
works (see CLAUDE.md). Everything here degrades gracefully when the server
or a vision model is missing: ``available()`` is the cheap gate.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

OLLAMA = "http://127.0.0.1:11434"
# First installed family wins. qwen2.5vl first: qwen3-vl force-thinks on
# structured tasks (ignores think:false AND /no_think, verified 2026-07-13),
# burning the whole token budget before the answer starts.
PREFERRED = ("qwen2.5vl", "qwen3-vl", "minicpm-v", "llava")
KEEP_ALIVE = "3m"


def _post(path: str, payload: Dict, timeout: float = 600) -> Dict:
    req = urllib.request.Request(OLLAMA + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def models() -> List[str]:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=4) as r:
            return [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
    except Exception:  # noqa: BLE001 — server down = no models
        return []


def pick_model() -> Optional[str]:
    have = models()
    for fam in PREFERRED:
        for m in have:
            if m.startswith(fam):
                return m
    return None


def available() -> bool:
    return pick_model() is not None


def describe(image_path, prompt: str, model: Optional[str] = None,
             timeout: float = 600, force_json: bool = False) -> str:
    """One image + one prompt -> the model's text answer."""
    model = model or pick_model()
    if not model:
        raise RuntimeError(
            "No local vision model. Start ollama serve (detached) and "
            "`ollama pull qwen3-vl:8b`.")
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        "stream": False,
        # qwen3 family: without this the answer lands in message.thinking
        # and content comes back empty.
        "think": False,
        "keep_alive": KEEP_ALIVE,
        # num_predict: a 30-tile sheet answer runs ~2-3k tokens; Ollama's
        # default cap truncates it into unparseable JSON.
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 4096},
    }
    if force_json:
        payload["format"] = "json"
    out = _post("/api/chat", payload, timeout=timeout)
    return ((out.get("message") or {}).get("content") or "").strip()


def describe_json(image_path, prompt: str, model: Optional[str] = None,
                  timeout: float = 600) -> Optional[Dict]:
    """describe() with a tolerant JSON parse (fenced/prefixed output ok)."""
    # NOTE: Ollama's format:"json" makes qwen3-vl return EMPTY content
    # (verified 2026-07-13); prompt discipline + tolerant parse instead.
    txt = describe(image_path, prompt, model=model, timeout=timeout)
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001 — dig the first JSON object out
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    return None


def unload() -> None:
    """Ask Ollama to drop any loaded vision model NOW (gpu.release_all)."""
    for m in models():
        if any(m.startswith(f) for f in PREFERRED):
            try:
                _post("/api/generate", {"model": m, "keep_alive": 0},
                      timeout=10)
            except Exception:  # noqa: BLE001
                pass
