"""Drive the isolated ACE-Step 1.5 sidecar to generate background music / SFX.

ACE-Step needs torch 2.7.1 + numba/torchcodec/torchao, which clash with this
app's torch-2.11 stack — so it lives in its own venv (``ACE-Step-1.5/.venv``) and
runs as a tiny HTTP server (``aaaflow_music_server.py``). This module starts that
server on demand and talks to it over HTTP, exactly like ``comfy_engine`` drives
ComfyUI. The 4B XL DiT is CPU-offloaded to fit 16 GB, so generation is slow-ish;
callers run it inside a background job.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from . import config

_lock = threading.RLock()       # guards startup
_infer = threading.Lock()       # one generation at a time (single GPU)


class MusicEngine:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._started_here = False

    @property
    def url(self) -> str:
        return config.ACE_URL.rstrip("/")

    # ---- HTTP helpers -----------------------------------------------------
    def _get(self, path: str, timeout: float = 10):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return json.load(r)

    def _post(self, path: str, payload: Dict, timeout: float = 900):
        req = urllib.request.Request(
            self.url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def available(self) -> bool:
        return config.music_env_ready()

    def model_ready(self) -> bool:
        return config.music_model_ready()

    def alive(self) -> bool:
        try:
            self._get("/health", timeout=3)
            return True
        except Exception:
            return False

    def health(self) -> Dict:
        try:
            return self._get("/health", timeout=3)
        except Exception:
            return {}

    # ---- lifecycle --------------------------------------------------------
    def ensure_running(self, progress=None, wait: int = 120) -> None:
        if self.alive():
            return
        with _lock:
            if self.alive():
                return
            if not self.available():
                raise RuntimeError(
                    "ACE-Step isn't installed yet. Its isolated venv "
                    f"({config.ACE_VENV_PYTHON}) or server is missing.")
            if progress:
                progress("Starting music engine…", 0.03)
            port = urllib.parse.urlparse(self.url).port or 8765
            log = open(config.ACE_LOG, "ab", buffering=0)
            self._proc = subprocess.Popen(
                [str(config.ACE_VENV_PYTHON), str(config.ACE_SERVER),
                 "--host", "127.0.0.1", "--port", str(port), "--preload"],
                cwd=str(config.ACE_DIR), stdin=subprocess.DEVNULL,
                stdout=log, stderr=log)
            self._started_here = True
            t0 = time.time()
            while time.time() - t0 < wait:
                if self.alive():
                    if progress:
                        progress("Music engine ready", 0.08)
                    return
                time.sleep(1.5)
            raise RuntimeError("Music engine did not start in time (see data/acestep.log).")

    def _wait_model(self, progress=None, wait: int = 3600) -> None:
        """Block until the model finishes loading (incl. first-time ~9 GB download)."""
        t0 = time.time()
        while time.time() - t0 < wait:
            h = self.health()
            if h.get("ready"):
                return
            if h.get("error"):
                raise RuntimeError(f"Music model failed to load: {h['error']}")
            if progress:
                msg = ("Downloading / loading music model (first run, ~9 GB)…"
                       if not self.model_ready() else "Loading music model…")
                progress(msg, 0.12)
            time.sleep(3)
        raise RuntimeError("Music model did not become ready in time.")

    def warm(self, progress=None) -> None:
        """Start the sidecar and load the model (downloads ~9 GB on first run)."""
        self.ensure_running(progress=progress)
        self._wait_model(progress=progress)

    # ---- generation -------------------------------------------------------
    def generate(self, caption: str, *, seconds: float = 30.0, seed: int = -1,
                 steps: int = 8, instrumental: bool = True,
                 out_dir: Optional[str] = None, progress=None) -> bytes:
        """Generate a clip; returns the raw audio bytes (wav)."""
        self.ensure_running(progress=progress)
        self._wait_model(progress=progress)
        with _infer:
            if progress:
                progress("Composing music…", 0.3)
            res = self._post("/generate", {
                "caption": caption, "seconds": float(seconds), "seed": int(seed),
                "steps": int(steps), "instrumental": bool(instrumental),
                "format": "wav", "out_dir": out_dir or str(config.ACE_DIR / "outputs"),
            }, timeout=1800)
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "music generation failed")
        path = Path(res["file"])
        if not path.exists():
            raise RuntimeError(f"music server reported a file that's missing: {path}")
        if progress:
            progress("Music ready", 0.95)
        return path.read_bytes()

    # ---- status -----------------------------------------------------------
    def status(self) -> Dict:
        h = self.health()
        return {
            "available": self.available(),          # isolated venv installed
            "model_ready": self.model_ready(),       # checkpoint downloaded
            "alive": bool(h) or self.alive(),        # server process up
            "loaded": bool(h.get("ready")),          # model warm in VRAM
            "loading": bool(h.get("loading")),
            "model": config.ACE_MODEL,
            "url": self.url,
            "error": h.get("error"),
        }


music_engine = MusicEngine()
