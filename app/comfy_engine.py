"""Local image generation by driving the user's ComfyUI (krea2 / Qwen-Image).

The in-app diffusers engine can't load krea2's ComfyUI ``fp8_scaled`` checkpoint
(non-diffusers keys, custom ``krea2`` CLIP type, ``ConditioningKrea2Rebalance``),
so for the flat-cartoon look we talk to ComfyUI's HTTP API directly. ComfyUI is
auto-started from ``C:\\AAAFlow\\ComfyUI_windows_portable`` on first use.

Mirrors the diffusers ImageEngine surface (``generate`` -> PIL.Image) so the
images pipeline can use either backend interchangeably.
"""
from __future__ import annotations

import io
import json
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from typing import Dict, Optional

from . import config

_lock = threading.RLock()       # guards startup
_infer = threading.Lock()       # serialize one generation at a time


class ComfyEngine:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._cid = uuid.uuid4().hex
        self._started_here = False

    @property
    def url(self) -> str:
        return config.COMFY_URL.rstrip("/")

    # ---- HTTP helpers -----------------------------------------------------
    def _get(self, path: str, timeout: float = 10):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return json.load(r)

    def _post(self, path: str, payload: Dict, timeout: float = 30):
        req = urllib.request.Request(
            self.url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def alive(self) -> bool:
        try:
            self._get("/system_stats", timeout=3)
            return True
        except Exception:
            return False

    # ---- lifecycle --------------------------------------------------------
    def ensure_running(self, progress=None, wait: int = 240) -> None:
        if self.alive():
            return
        with _lock:
            if self.alive():
                return
            if not config.COMFY_PYTHON.exists() or not config.COMFY_MAIN.exists():
                raise RuntimeError(
                    f"ComfyUI not found at {config.COMFY_DIR}. Set AAAFLOW_COMFY_URL "
                    "to a running ComfyUI, or place the portable build there.")
            if progress:
                progress("Starting ComfyUI…", 0.03)
            port = urllib.parse.urlparse(self.url).port or 8188
            self._proc = subprocess.Popen(
                [str(config.COMFY_PYTHON), "-s", str(config.COMFY_MAIN),
                 "--windows-standalone-build", "--port", str(port)],
                cwd=str(config.COMFY_DIR),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._started_here = True
            t0 = time.time()
            while time.time() - t0 < wait:
                if self.alive():
                    if progress:
                        progress("ComfyUI ready", 0.1)
                    return
                time.sleep(2)
            raise RuntimeError("ComfyUI did not become ready in time.")

    # ---- workflow ---------------------------------------------------------
    def _workflow(self, mdef: Dict, prompt: str, width: int, height: int,
                  steps: int, cfg: float, seed: int, lora: Optional[Dict]) -> Dict:
        wf = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": mdef["unet"], "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": mdef["clip"],
                             "type": mdef.get("clip_type", "krea2"), "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": mdef["vae"]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
            "5": {"class_type": "ConditioningKrea2Rebalance",
                  "inputs": {"conditioning": ["4", 0], "multiplier": 4.0,
                             "per_layer_weights": config.KREA2_PER_LAYER}},
            "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
            "7": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": int(width), "height": int(height), "batch_size": 1}},
            "8": {"class_type": "KSampler",
                  "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["6", 0],
                             "latent_image": ["7", 0], "seed": int(seed) & 0xFFFFFFFFFFFFFF,
                             "steps": int(steps), "cfg": float(cfg),
                             "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
            "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
            "10": {"class_type": "SaveImage",
                   "inputs": {"images": ["9", 0], "filename_prefix": "AAAFlow"}},
        }
        if lora and lora.get("name"):
            wf["11"] = {"class_type": "LoraLoaderModelOnly",
                        "inputs": {"model": ["1", 0], "lora_name": lora["name"],
                                   "strength_model": float(lora.get("strength", 0.8))}}
            wf["8"]["inputs"]["model"] = ["11", 0]
        return wf

    # ---- generation -------------------------------------------------------
    def generate(self, prompt: str, negative: str = "", *, width: int, height: int,
                 steps: int, guidance: float, seed: int, mdef: Dict,
                 lora: Optional[Dict] = None, progress=None):
        from PIL import Image
        self.ensure_running(progress=progress)
        wf = self._workflow(mdef, prompt, width, height, steps, guidance, seed, lora)
        with _infer:
            r = self._post("/prompt", {"prompt": wf, "client_id": self._cid})
            if "error" in r:
                detail = r.get("node_errors") or r.get("error")
                raise RuntimeError(f"ComfyUI rejected the prompt: {json.dumps(detail)[:400]}")
            pid = r["prompt_id"]
            if progress:
                progress("Rendering (krea2)…", 0.4)
            t0 = time.time()
            info = None
            err = None
            while time.time() - t0 < 600:
                hist = self._get(f"/history/{pid}", timeout=10)
                if pid in hist:
                    entry = hist[pid]
                    st = entry.get("status", {})
                    for _nid, out in (entry.get("outputs") or {}).items():
                        if out.get("images"):
                            info = out["images"][0]
                            break
                    if info:
                        break
                    if st.get("status_str") == "error":
                        err = json.dumps(st.get("messages"))[:400]
                        break
                time.sleep(1.2)
            if not info:
                raise RuntimeError(f"ComfyUI produced no image ({err or 'timeout'}).")
            q = urllib.parse.urlencode({
                "filename": info["filename"], "subfolder": info.get("subfolder", ""),
                "type": info.get("type", "output")})
            with urllib.request.urlopen(self.url + "/view?" + q, timeout=120) as resp:
                data = resp.read()
        return Image.open(io.BytesIO(data)).convert("RGB")

    # ---- status -----------------------------------------------------------
    def status(self) -> Dict:
        return {"alive": self.alive(), "url": self.url,
                "dir": str(config.COMFY_DIR),
                "available": config.COMFY_PYTHON.exists() and config.COMFY_MAIN.exists(),
                "started_by_app": self._started_here}


comfy_engine = ComfyEngine()
