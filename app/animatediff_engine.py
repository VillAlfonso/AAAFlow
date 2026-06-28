"""AnimateDiff (SDXL) — 2D-native animation that keeps the cartoon style.

Unlike LTX (a realistic-video model that melts flat art), AnimateDiff runs ON TOP of
the SDXL image model, so it animates *in the same 2D style*. We reuse the toon-SDXL
base + IP-Adapter style references (the cartoon-rag setup) and add a motion adapter,
producing a short clip in the C&H look. Generates from prompt + style references
(not locked to an exact still), so it's "cartoon motion in our style".

torch/diffusers imported lazily so the web server starts instantly.
"""
from __future__ import annotations

import threading
from typing import List, Optional

from . import config, style_refs

_lock = threading.RLock()
_infer = threading.Lock()

MOTION_ADAPTER = "guoyww/animatediff-motion-adapter-sdxl-beta"
SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"


class AnimateDiffEngine:
    def __init__(self) -> None:
        self._pipe = None
        self._torch = None
        self._err: Optional[str] = None

    def _device(self):
        return "cuda" if self._torch.cuda.is_available() else "cpu"

    def load(self, progress=None):
        if self._pipe is not None:
            return self._pipe
        with _lock:
            if self._pipe is not None:
                return self._pipe
            import torch
            from diffusers import (AnimateDiffSDXLPipeline, AutoencoderKL,
                                   DDIMScheduler, MotionAdapter)
            from transformers import CLIPVisionModelWithProjection
            self._torch = torch
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            ipc = config.IP_ADAPTER
            if progress:
                progress("Loading motion adapter (first run downloads it)", 0.1)
            adapter = MotionAdapter.from_pretrained(MOTION_ADAPTER, torch_dtype=dtype)
            adapter.to(dtype)                    # force fp16 (torch_dtype is deprecated/ignored here)
            # fp16-safe SDXL VAE — the stock SDXL VAE NaNs/clashes in fp16 (the glitch source)
            vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=dtype)
            # ViT-H image encoder for the *_vit-h IP-Adapter, pre-loaded (Windows-safe path)
            enc = None
            try:
                enc = CLIPVisionModelWithProjection.from_pretrained(
                    ipc["repo"], subfolder=ipc.get("image_encoder_subfolder", "models/image_encoder"),
                    torch_dtype=dtype)
            except Exception as exc:  # noqa: BLE001
                print(f"[animatediff] image encoder load failed: {exc}")
            if progress:
                progress("Loading SDXL + AnimateDiff", 0.35)
            pipe = AnimateDiffSDXLPipeline.from_pretrained(
                SDXL_BASE, motion_adapter=adapter, vae=vae, image_encoder=enc, torch_dtype=dtype)
            pipe.motion_adapter.to(dtype)        # keep the adapter fp16 inside the pipe too
            pipe.scheduler = DDIMScheduler.from_pretrained(
                SDXL_BASE, subfolder="scheduler", clip_sample=False,
                timestep_spacing="linspace", beta_schedule="linear", steps_offset=1)
            try:
                if progress:
                    progress("Loading IP-Adapter (style refs)", 0.6)
                pipe.load_ip_adapter(ipc["repo"], subfolder=ipc["subfolder"],
                                     weight_name=ipc["weight_name"],
                                     image_encoder_folder=None)   # use the pre-loaded encoder
                self._ip = enc is not None
            except Exception as exc:  # noqa: BLE001
                print(f"[animatediff] IP-Adapter load failed: {exc}")
                self._ip = False
            if torch.cuda.is_available():
                pipe.vae.enable_slicing()
                pipe.enable_model_cpu_offload()      # fit 16 GB
            try:
                pipe.set_progress_bar_config(disable=False)
            except Exception:
                pass
            self._pipe = pipe
            if progress:
                progress("Ready", 1.0)
            return pipe

    def generate(self, prompt: str, negative: str = "", *, num_frames: int = 16,
                 steps: int = 22, guidance: float = 7.0, ip_scale: float = 0.7,
                 width: int = 832, height: int = 480, seed: int = 42,
                 progress=None) -> List:
        pipe = self.load(progress=progress)
        torch = self._torch
        refs = style_refs.retrieve({}, k=config.IP_ADAPTER.get("top_k", 3))
        from PIL import Image
        ref_imgs = [Image.open(p).convert("RGB") for p in refs] or None
        with _infer:
            if getattr(self, "_ip", False) and ref_imgs:
                pipe.set_ip_adapter_scale(float(ip_scale))
                ip_kw = {"ip_adapter_image": [ref_imgs]}   # nested: one list per adapter
            else:
                ip_kw = {}
            gen = torch.Generator(device="cpu").manual_seed(int(seed) & 0x7FFFFFFF)
            if progress:
                progress("Animating (AnimateDiff-SDXL)", 0.4)
            out = pipe(prompt=prompt, negative_prompt=(negative or None),
                       num_frames=int(num_frames), num_inference_steps=int(steps),
                       guidance_scale=float(guidance), width=int(width),
                       height=int(height), generator=gen, **ip_kw)
        return out.frames[0]

    @staticmethod
    def to_mp4(frames, path: str, fps: int = 12) -> str:
        from diffusers.utils import export_to_video
        export_to_video(frames, path, fps=int(fps))
        return path


animatediff_engine = AnimateDiffEngine()
