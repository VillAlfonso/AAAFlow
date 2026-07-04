"""Wan 2.2 14B image-to-video, via ComfyUI — the best open video model.

MoE: two 14B fp8 experts (high/low noise), each with a 4-step lightx2v LoRA, so it
runs on 16 GB (experts load one at a time; only 4 steps total). Replicates ComfyUI's
bundled "Image to Video (Wan 2.2)" blueprint:

    CLIPLoader(umt5, wan) ─ CLIPTextEncode(pos/neg)
    UNETLoader(high) ─ LoRA(lightx2v high) ─ ModelSamplingSD3(shift 5) ─┐
    UNETLoader(low)  ─ LoRA(lightx2v low)  ─ ModelSamplingSD3(shift 5) ─┤
    WanImageToVideo(pos,neg,vae,start_image,w,h,length) ─ pos,neg,latent │
    KSamplerAdvanced(high, steps 0->2, add_noise, leftover) ─────────────┘
    KSamplerAdvanced(low,  steps 2->4) ─ VAEDecode ─ CreateVideo ─ SaveVideo

Drives the same ComfyUI as krea2/LTX; returns mp4 bytes.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Dict, Optional

from . import config
from .comfy_engine import comfy_engine


def _snap_length(seconds: float, fps: int) -> int:
    """Wan needs length = 4n+1. Snap a duration to a valid frame count."""
    seconds = max(0.5, min(float(seconds), float(config.WAN["max_seconds"])))
    n = max(5, round(seconds * fps))
    return ((n - 1) // 4) * 4 + 1


class WanEngine:
    def __init__(self) -> None:
        self._cid = "aaaflow-wan-" + uuid.uuid4().hex[:8]

    def available(self) -> bool:
        return config.wan_ready()

    def status(self) -> Dict:
        m = config.comfy_models_dir()
        w = config.WAN
        present = {
            "high_noise": (m / "diffusion_models" / w["high_noise"]).exists(),
            "low_noise": (m / "diffusion_models" / w["low_noise"]).exists(),
            "text_encoder": (m / "text_encoders" / w["text_encoder"]).exists(),
            "vae": (m / "vae" / w["vae"]).exists(),
            "lora_high": (m / "loras" / w["lora_high"]).exists(),
            "lora_low": (m / "loras" / w["lora_low"]).exists(),
        }
        return {"ready": config.wan_ready(), **present}

    def _workflow(self, prompt: str, negative: str, *, in_name: str, width: int,
                  height: int, length: int, fps: int, seed: int,
                  profile: Dict) -> Dict:
        w = config.WAN
        s = int(profile["steps"]); b = int(profile["boundary"])
        cfg = float(profile["cfg"]); use_lora = bool(profile.get("use_lora"))
        wf = {
            "clip": {"class_type": "CLIPLoader",
                     "inputs": {"clip_name": w["text_encoder"], "type": "wan", "device": "default"}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": w["vae"]}},
            "unet_h": {"class_type": "UNETLoader",
                       "inputs": {"unet_name": w["high_noise"], "weight_dtype": "default"}},
            "unet_l": {"class_type": "UNETLoader",
                       "inputs": {"unet_name": w["low_noise"], "weight_dtype": "default"}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
            "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": negative}},
            "img": {"class_type": "LoadImage", "inputs": {"image": in_name}},
            "i2v": {"class_type": "WanImageToVideo",
                    "inputs": {"positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0],
                               "width": int(width), "height": int(height), "length": int(length),
                               "batch_size": 1, "start_image": ["img", 0]}},
        }
        src_h, src_l = "unet_h", "unet_l"
        if use_lora:                      # balanced/fast: 4-step lightning distill
            wf["lora_h"] = {"class_type": "LoraLoaderModelOnly",
                            "inputs": {"model": ["unet_h", 0], "lora_name": w["lora_high"],
                                       "strength_model": float(w["lora_strength"])}}
            wf["lora_l"] = {"class_type": "LoraLoaderModelOnly",
                            "inputs": {"model": ["unet_l", 0], "lora_name": w["lora_low"],
                                       "strength_model": float(w["lora_strength"])}}
            src_h, src_l = "lora_h", "lora_l"
        # Optional extra LoRAs (e.g. a HighRes-Fix anti-melt patch): drop the
        # file in ComfyUI models/loras and list it in config.WAN["extra_loras"]
        # as {"file": name, "strength": 1.0, "experts": "both"|"high"|"low"}.
        for i, xl in enumerate(w.get("extra_loras") or []):
            name = xl.get("file")
            if not name:
                continue
            strength = float(xl.get("strength", 1.0))
            experts = xl.get("experts", "both")
            if experts in ("both", "high"):
                wf[f"xlora_h{i}"] = {"class_type": "LoraLoaderModelOnly",
                                     "inputs": {"model": [src_h, 0], "lora_name": name,
                                                "strength_model": strength}}
                src_h = f"xlora_h{i}"
            if experts in ("both", "low"):
                wf[f"xlora_l{i}"] = {"class_type": "LoraLoaderModelOnly",
                                     "inputs": {"model": [src_l, 0], "lora_name": name,
                                                "strength_model": strength}}
                src_l = f"xlora_l{i}"
        wf.update({
            "msm_h": {"class_type": "ModelSamplingSD3",
                      "inputs": {"model": [src_h, 0], "shift": float(w["shift"])}},
            "msm_l": {"class_type": "ModelSamplingSD3",
                      "inputs": {"model": [src_l, 0], "shift": float(w["shift"])}},
            "k1": {"class_type": "KSamplerAdvanced",
                   "inputs": {"model": ["msm_h", 0], "add_noise": "enable",
                              "noise_seed": int(seed) & 0xFFFFFFFFFFFFFF, "steps": s,
                              "cfg": cfg, "sampler_name": w["sampler"],
                              "scheduler": w["scheduler"], "positive": ["i2v", 0],
                              "negative": ["i2v", 1], "latent_image": ["i2v", 2],
                              "start_at_step": 0, "end_at_step": b,
                              "return_with_leftover_noise": "enable"}},
            "k2": {"class_type": "KSamplerAdvanced",
                   "inputs": {"model": ["msm_l", 0], "add_noise": "disable",
                              "noise_seed": int(seed) & 0xFFFFFFFFFFFFFF, "steps": s,
                              "cfg": cfg, "sampler_name": w["sampler"],
                              "scheduler": w["scheduler"], "positive": ["i2v", 0],
                              "negative": ["i2v", 1], "latent_image": ["k1", 0],
                              "start_at_step": b, "end_at_step": s,
                              "return_with_leftover_noise": "disable"}},
        })
        wf.update({
            "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["k2", 0], "vae": ["vae", 0]}},
            "video": {"class_type": "CreateVideo", "inputs": {"images": ["decode", 0], "fps": float(fps)}},
            "save": {"class_type": "SaveVideo",
                     "inputs": {"video": ["video", 0], "filename_prefix": "AAAFlow/wan",
                                "format": "mp4", "codec": "h264"}},
        })
        return wf

    def animate(self, image_path: str, prompt: str, *, seconds: Optional[float] = None,
                negative: Optional[str] = None, width: Optional[int] = None,
                height: Optional[int] = None, fps: Optional[int] = None,
                seed: int = 0, quality: Optional[str] = None, progress=None,
                save_graph: Optional[Path] = None) -> bytes:
        if not config.wan_ready():
            raise RuntimeError("Wan 2.2 weights are missing — use “Download Wan 2.2” "
                               "on the Animate page.")
        w = config.WAN
        profile = dict(w["quality_profiles"].get(quality or w["quality"],
                                                 w["quality_profiles"]["max"]))
        width = int(width or profile["width"]); height = int(height or profile["height"])
        fps = int(fps or w["fps"])
        length = _snap_length(seconds or w["default_seconds"], fps)
        negative = negative if negative is not None else w["negative"]
        comfy_engine.ensure_running(progress=progress)
        in_name = self._upload(image_path)
        wf = self._workflow(prompt, negative, in_name=in_name, width=width, height=height,
                            length=length, fps=fps, seed=seed, profile=profile)
        if save_graph is not None:                 # persist the i2v node graph for inspection
            try:
                p = Path(save_graph); p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(wf, indent=2), encoding="utf-8")
            except Exception:                      # graph-saving must never fail a render
                pass
        infos = comfy_engine.run_workflow(
            wf, want=("images",), client_id=self._cid, timeout=5400,
            progress=progress, prange=(0.15, 0.95),
            stage=f"Animating (Wan 2.2 14B · {quality or w['quality']})")
        return comfy_engine.fetch(infos[0])

    def _upload(self, image_path: str) -> str:
        import json
        import urllib.request
        path = Path(image_path)
        boundary = "----aaaflow" + uuid.uuid4().hex
        name = f"aaaflow_{uuid.uuid4().hex[:10]}{path.suffix or '.png'}"
        body = bytearray()
        body += f"--{boundary}\r\n".encode()
        body += (f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n").encode()
        body += path.read_bytes()
        body += f"\r\n--{boundary}\r\n".encode()
        body += ('Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n').encode()
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            comfy_engine.url + "/upload/image", data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            info = json.load(r)
        sub = info.get("subfolder") or ""
        return f"{sub}/{info['name']}" if sub else info["name"]


wan_engine = WanEngine()
