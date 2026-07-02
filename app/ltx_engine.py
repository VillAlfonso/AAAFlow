"""Animate a still into a short clip with LTX-2 (image-to-video), via ComfyUI.

This drives the *same* local ComfyUI as the krea2 image engine (port 8188),
replicating the node graph of ComfyUI's bundled "Image to Video (LTX-2.3)"
blueprint — minus the audio branch, since narration comes from Qwen3-TTS:

    CheckpointLoaderSimple(ltx-2.3 fp8) ─┬─ MODEL ─ LoraLoaderModelOnly(distilled) ─┐
                                         └─ VAE ──────────────┐                    │
    LTXAVTextEncoderLoader(gemma+ckpt) ─ CLIP ─ CLIPTextEncode(pos/neg)            │
        pos,neg ─ LTXVImgToVideo(vae, still) ─ pos,neg,latent                      │
        (transform: EmptyLTXVLatentVideo ─ LTXVConditioning ─ LTXVAddGuide×2)      │
        ─ LTXVConditioning(fps) ─ CFGGuider(model) ◄──────────────────────────────┘
        ─ SamplerCustomAdvanced(RandomNoise, KSamplerSelect, ManualSigmas)
        ─ VAEDecode ─ CreateVideo(fps) ─ SaveVideo(mp4/h264)

The clip is fetched back over HTTP as raw mp4 bytes. Heavy on a 16 GB GPU, so
callers animate only scenes whose storyboard declares motion.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, Optional

from . import config
from .comfy_engine import comfy_engine


def _snap_length(seconds: float, fps: int) -> int:
    """LTX needs length = 8k+1 (>=9). Snap a duration in seconds to a valid frame count."""
    seconds = max(0.4, min(float(seconds), float(config.LTX2["max_seconds"])))
    n = max(9, round(seconds * fps))
    return ((n - 1) // 8) * 8 + 1


class LTXEngine:
    def __init__(self) -> None:
        self._cid = "aaaflow-ltx-" + uuid.uuid4().hex[:8]

    def available(self) -> bool:
        return config.ltx2_ready()

    def status(self) -> Dict:
        m = config.comfy_models_dir()
        cfg = config.LTX2
        return {
            "ready": config.ltx2_ready(),
            "checkpoint": (m / "checkpoints" / cfg["checkpoint"]).exists(),
            "text_encoder": (m / "text_encoders" / cfg["text_encoder"]).exists(),
            "files": {
                "checkpoint": cfg["checkpoint"],
                "text_encoder": cfg["text_encoder"],
            },
        }

    # ---- workflow ---------------------------------------------------------
    # Fused 19B (dev) path: CheckpointLoaderSimple gives MODEL + VAE; the gemma
    # text encoder is loaded via LTXAVTextEncoderLoader (gemma + the same ckpt for
    # the projection). ModelSamplingLTXV patches the model; LTXVScheduler builds the
    # sigma schedule. No distilled LoRA, so real CFG + a moderate step count.
    def _loaders(self, wf: Dict, prompt: str, negative: str):
        """Build the loaders; returns the MODEL ref for the guider. No ModelSamplingLTXV
        (the fused 19B ckpt bakes its own sampling — the official blueprint omits it)."""
        cfg = config.LTX2
        wf["ckpt"] = {"class_type": "CheckpointLoaderSimple",
                      "inputs": {"ckpt_name": cfg["checkpoint"]}}
        model_ref = ["ckpt", 0]
        lora = cfg.get("distilled_lora")
        if lora and (config.comfy_models_dir() / "loras" / lora).exists():
            wf["lora"] = {"class_type": "LoraLoaderModelOnly",
                          "inputs": {"model": ["ckpt", 0], "lora_name": lora,
                                     "strength_model": float(cfg.get("lora_strength", 1.0))}}
            model_ref = ["lora", 0]
        wf["te"] = {"class_type": "LTXAVTextEncoderLoader",
                    "inputs": {"text_encoder": cfg["text_encoder"],
                               "ckpt_name": cfg["checkpoint"], "device": "default"}}
        wf["pos"] = {"class_type": "CLIPTextEncode",
                     "inputs": {"clip": ["te", 0], "text": prompt}}
        wf["neg"] = {"class_type": "CLIPTextEncode",
                     "inputs": {"clip": ["te", 0], "text": negative}}
        return model_ref

    def _sampler_tail(self, wf: Dict, *, model_ref, pos_ref, neg_ref, latent_ref,
                      fps: int, seed: int) -> None:
        """Shared tail: sampler -> VAEDecodeTiled -> CreateVideo -> SaveVideo.

        ``pos_ref``/``neg_ref`` must already be LTXVConditioning-wrapped (frame_rate set).
        """
        cfg = config.LTX2
        wf["noise"] = {"class_type": "RandomNoise",
                       "inputs": {"noise_seed": int(seed) & 0xFFFFFFFFFFFFFF}}
        wf["guider"] = {"class_type": "CFGGuider",
                        "inputs": {"model": model_ref, "positive": pos_ref,
                                   "negative": neg_ref, "cfg": float(cfg["guidance"])}}
        wf["sampler"] = {"class_type": "KSamplerSelect",
                         "inputs": {"sampler_name": cfg["sampler"]}}
        wf["sigmas"] = {"class_type": "LTXVScheduler",
                        "inputs": {"steps": int(cfg["steps"]),
                                   "max_shift": float(cfg["max_shift"]),
                                   "base_shift": float(cfg["base_shift"]),
                                   "stretch": True, "terminal": float(cfg["terminal"]),
                                   "latent": latent_ref}}
        wf["sample"] = {"class_type": "SamplerCustomAdvanced",
                        "inputs": {"noise": ["noise", 0], "guider": ["guider", 0],
                                   "sampler": ["sampler", 0], "sigmas": ["sigmas", 0],
                                   "latent_image": latent_ref}}
        wf["decode"] = {"class_type": "VAEDecodeTiled",
                        "inputs": {"samples": ["sample", 0], "vae": ["ckpt", 2],
                                   "tile_size": 512, "overlap": 64,
                                   "temporal_size": 4096, "temporal_overlap": 8}}
        wf["video"] = {"class_type": "CreateVideo",
                       "inputs": {"images": ["decode", 0], "fps": float(fps)}}
        wf["save"] = {"class_type": "SaveVideo",
                      "inputs": {"video": ["video", 0], "filename_prefix": "AAAFlow/ltx",
                                 "format": "mp4", "codec": "h264"}}

    def _workflow_i2v(self, prompt: str, negative: str, *, width: int, height: int,
                      length: int, fps: int, seed: int) -> Dict:
        """Single-still image-to-video (ambient / generic motion)."""
        wf: Dict = {}
        model_ref = self._loaders(wf, prompt, negative)
        wf["img"] = {"class_type": "LoadImage", "inputs": {"image": "__INPUT__"}}
        wf["i2v"] = {"class_type": "LTXVImgToVideo",
                     "inputs": {"positive": ["pos", 0], "negative": ["neg", 0],
                                "vae": ["ckpt", 2], "image": ["img", 0],
                                "width": int(width), "height": int(height),
                                "length": int(length), "batch_size": 1,
                                "strength": float(config.LTX2["image_strength"])}}
        wf["cond"] = {"class_type": "LTXVConditioning",
                      "inputs": {"positive": ["i2v", 0], "negative": ["i2v", 1],
                                 "frame_rate": float(fps)}}
        self._sampler_tail(wf, model_ref=model_ref, pos_ref=["cond", 0],
                           neg_ref=["cond", 1], latent_ref=["i2v", 2], fps=fps, seed=seed)
        return wf

    def _workflow_t2v(self, prompt: str, negative: str, *, width: int, height: int,
                      length: int, fps: int, seed: int) -> Dict:
        """Text-to-video from scratch (no reference image)."""
        wf: Dict = {}
        model_ref = self._loaders(wf, prompt, negative)
        wf["empty"] = {"class_type": "EmptyLTXVLatentVideo",
                       "inputs": {"width": int(width), "height": int(height),
                                  "length": int(length), "batch_size": 1}}
        wf["cond"] = {"class_type": "LTXVConditioning",
                      "inputs": {"positive": ["pos", 0], "negative": ["neg", 0],
                                 "frame_rate": float(fps)}}
        self._sampler_tail(wf, model_ref=model_ref, pos_ref=["cond", 0],
                           neg_ref=["cond", 1], latent_ref=["empty", 0], fps=fps, seed=seed)
        return wf

    def text2video(self, prompt: str, *, seconds: Optional[float] = None,
                   negative: Optional[str] = None, width: Optional[int] = None,
                   height: Optional[int] = None, fps: Optional[int] = None,
                   seed: int = 0, progress=None) -> bytes:
        """Generate a clip from text only (no reference image)."""
        if not config.ltx2_ready():
            raise RuntimeError("LTX-2 weights are missing.")
        cfg = config.LTX2
        width = int(width or cfg["width"]); height = int(height or cfg["height"])
        fps = int(fps or cfg["fps"])
        length = _snap_length(seconds or cfg["default_seconds"], fps)
        negative = negative if negative is not None else cfg["negative"]
        style = (cfg.get("style") or "").strip()
        full = f"{prompt}, {style}" if style else prompt
        comfy_engine.ensure_running(progress=progress)
        wf = self._workflow_t2v(full, negative, width=width, height=height,
                                length=length, fps=fps, seed=seed)
        infos = comfy_engine.run_workflow(
            wf, want=("images",), client_id=self._cid, timeout=1800,
            progress=progress, prange=(0.15, 0.95), stage="Generating (LTX-2 t2v)")
        return comfy_engine.fetch(infos[0])

    def _workflow_flf(self, prompt: str, negative: str, *, width: int, height: int,
                      length: int, fps: int, seed: int, end_name: str) -> Dict:
        """First+last-frame video (transform scenes with an end_image)."""
        cfg = config.LTX2
        wf: Dict = {}
        model_ref = self._loaders(wf, prompt, negative)
        wf["img"] = {"class_type": "LoadImage", "inputs": {"image": "__INPUT__"}}
        wf["imgEnd"] = {"class_type": "LoadImage", "inputs": {"image": end_name}}
        wf["preStart"] = {"class_type": "LTXVPreprocess",
                          "inputs": {"image": ["img", 0], "img_compression": 25}}
        wf["preEnd"] = {"class_type": "LTXVPreprocess",
                        "inputs": {"image": ["imgEnd", 0], "img_compression": 25}}
        wf["empty"] = {"class_type": "EmptyLTXVLatentVideo",
                       "inputs": {"width": int(width), "height": int(height),
                                  "length": int(length), "batch_size": 1}}
        wf["condFR"] = {"class_type": "LTXVConditioning",
                        "inputs": {"positive": ["pos", 0], "negative": ["neg", 0],
                                   "frame_rate": float(fps)}}
        wf["guideA"] = {"class_type": "LTXVAddGuide",
                        "inputs": {"positive": ["condFR", 0], "negative": ["condFR", 1],
                                   "vae": ["ckpt", 2], "latent": ["empty", 0],
                                   "image": ["preStart", 0], "frame_idx": 0,
                                   "strength": float(cfg["image_strength"])}}
        wf["guideB"] = {"class_type": "LTXVAddGuide",
                        "inputs": {"positive": ["guideA", 0], "negative": ["guideA", 1],
                                   "vae": ["ckpt", 2], "latent": ["guideA", 2],
                                   "image": ["preEnd", 0], "frame_idx": -1,
                                   "strength": float(cfg["end_strength"])}}
        self._sampler_tail(wf, model_ref=model_ref, pos_ref=["guideB", 0],
                           neg_ref=["guideB", 1], latent_ref=["guideB", 2], fps=fps, seed=seed)
        return wf

    # ---- generation -------------------------------------------------------
    def animate(self, image_path: str, prompt: str, *, seconds: Optional[float] = None,
                negative: Optional[str] = None, width: Optional[int] = None,
                height: Optional[int] = None, fps: Optional[int] = None,
                seed: int = 0, end_image_path: Optional[str] = None,
                style_lead: Optional[str] = None, style_tail: Optional[str] = None,
                progress=None) -> bytes:
        """Animate ``image_path`` into an mp4 clip; returns the raw mp4 bytes."""
        if not config.ltx2_ready():
            raise RuntimeError(
                "LTX-2 weights are missing. Run download_ltx23.bat (or the "
                "Download button on the Animate page) to fetch the checkpoint + "
                "distilled LoRA, then retry.")
        cfg = config.LTX2
        width = int(width or cfg["width"]); height = int(height or cfg["height"])
        fps = int(fps or cfg["fps"])
        length = _snap_length(seconds or cfg["default_seconds"], fps)
        negative = negative if negative is not None else cfg["negative"]

        # LTX animation prompt format: style declaration first, then the
        # subject/action, then explicit style-hold negations. Callers pass a
        # project-specific lead/tail (the storyboard's global style); the config
        # flat-cartoon anchors are only the fallback.
        lead = (style_lead if style_lead is not None
                else cfg.get("style_lead") or "").strip()
        tail = (style_tail if style_tail is not None
                else cfg.get("style_tail") or "").strip()
        full_prompt = ". ".join(p.strip().strip(".").strip()
                                for p in (lead, prompt, tail) if p.strip().strip("."))

        comfy_engine.ensure_running(progress=progress)
        in_name = self._upload(image_path)
        if end_image_path:
            end_name = self._upload(end_image_path)
            wf = self._workflow_flf(full_prompt, negative, width=width, height=height,
                                    length=length, fps=fps, seed=seed, end_name=end_name)
        else:
            wf = self._workflow_i2v(full_prompt, negative, width=width, height=height,
                                    length=length, fps=fps, seed=seed)
        wf["img"]["inputs"]["image"] = in_name

        infos = comfy_engine.run_workflow(
            wf, want=("images",), client_id=self._cid, timeout=1800,
            progress=progress, prange=(0.15, 0.95), stage="Animating (LTX-2)")
        return comfy_engine.fetch(infos[0])

    def _upload(self, image_path: str) -> str:
        """Upload a local image into ComfyUI's input dir; return the stored name."""
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
        body += ('Content-Disposition: form-data; name="overwrite"\r\n\r\n'
                 "true\r\n").encode()
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            comfy_engine.url + "/upload/image", data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            import json
            info = json.load(r)
        sub = info.get("subfolder") or ""
        return f"{sub}/{info['name']}" if sub else info["name"]


ltx_engine = LTXEngine()
