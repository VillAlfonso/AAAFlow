"""Local image engine (diffusers) — Stable Diffusion *or* FLUX.

Two families, selected by the model's ``type``:

* **sd**  — Stable Diffusion 1.5 (default: DreamShaper 8). ~2 GB, what this
  storyboard JSON targets, supports negative prompts. Loaded with
  ``AutoPipelineForText2Image`` and kept resident (small enough for 16 GB).
* **flux** — FLUX.1 (schnell ungated / dev gated). The transformer is loaded
  from a **GGUF** quant (city96) so the download is ~7 GB instead of 24 GB; text
  encoders + VAE come from the ungated schnell repo; ``enable_model_cpu_offload``
  keeps peak VRAM under 16 GB. The built-in simple-sketch LoRA adds the
  stick-figure look (FLUX only).

torch / diffusers are imported lazily so the web server starts instantly.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, storage

_lock = threading.RLock()      # guards load
_infer = threading.Lock()      # serialize generate()

# --- FLUX GGUF sources -----------------------------------------------------
GGUF_REPO = "city96/FLUX.1-schnell-gguf"
GGUF_FILES = {"Q4_K_S": "flux1-schnell-Q4_K_S.gguf",
              "Q5_K_S": "flux1-schnell-Q5_K_S.gguf",
              "Q8_0": "flux1-schnell-Q8_0.gguf"}
SCHNELL_REPO = "black-forest-labs/FLUX.1-schnell"   # ungated; supplies T5/CLIP/VAE

# Built-in stick-figure / simple-sketch LoRA (HF-hosted, no token) — FLUX only.
DEFAULT_LORA = {
    "id": "builtin-simple-sketch",
    "label": "Simple sketch / stick-figure (built-in, FLUX)",
    "repo": "Shakker-Labs/FLUX.1-dev-LoRA-Children-Simple-Sketch",
    "filename": "FLUX-dev-lora-children-simple-sketch.safetensors",
    "trigger": "sketched", "weight": 0.95, "builtin": True, "for": "flux",
}


class ImageEngine:
    def __init__(self) -> None:
        self._torch = None
        self._pipe = None
        self._pipe_key: Optional[Tuple] = None
        self._pipe_type: Optional[str] = None
        self._loaded_adapters: List[str] = []
        self._import_error: Optional[str] = None
        self._lora_supported = True
        self._ip_loaded = False

    # ---- imports / device -------------------------------------------------
    def ensure_imports(self):
        if self._torch is not None:
            return
        with _lock:
            if self._torch is not None:
                return
            try:
                import torch  # noqa
                self._torch = torch
            except Exception as exc:  # noqa: BLE001
                self._import_error = f"{type(exc).__name__}: {exc}"
                raise

    def _device(self) -> str:
        self.ensure_imports()
        return "cuda" if self._torch.cuda.is_available() else "cpu"

    # ---- model resolution -------------------------------------------------
    def _model_def(self, model_key: str) -> Dict:
        if model_key in config.IMAGE_BASES:
            return {"key": model_key, **config.IMAGE_BASES[model_key], "imported": False}
        m = storage.get_image_model(model_key)
        if m and m.get("kind") == "checkpoint":
            return {"key": model_key, "label": m.get("label"), "path": m.get("path"),
                    "imported": True, "type": m.get("base_type", "sd"),
                    "steps": m.get("steps", 26), "guidance": m.get("guidance", 7.0),
                    "width": m.get("width", 896), "height": m.get("height", 512)}
        d = config.DEFAULT_IMAGE_MODEL
        return {"key": d, **config.IMAGE_BASES[d], "imported": False}

    # ---- pipeline loading -------------------------------------------------
    def get_pipeline(self, progress=None):
        settings = storage.get_settings()
        img = settings.get("image", {})
        model_key = img.get("model", config.DEFAULT_IMAGE_MODEL)
        mdef = self._model_def(model_key)
        mtype = mdef.get("type", "sd")
        quant = img.get("quantize", "gguf")
        gguf_q = img.get("gguf_quant", "Q4_K_S")
        offload = img.get("offload", "model")
        # IP-Adapter (cartoon-rag): only wire it up when SDXL + refs are requested
        # and the style pack is non-empty; the count is in the key so 0->N reloads.
        from . import style_refs
        n_refs = style_refs.count()
        want_ip = (bool(mdef.get("ip_adapter")) and mtype == "sdxl"
                   and img.get("use_refs", True) and n_refs > 0)
        key = (model_key, mtype, quant, gguf_q, offload, want_ip, n_refs > 0)

        with _lock:
            if self._pipe is not None and self._pipe_key == key:
                return self._pipe
            self.ensure_imports()
            if self._pipe is not None:
                del self._pipe
                self._pipe = None
                self._free()
            self._ip_loaded = False
            if mtype == "flux":
                pipe = self._load_flux(mdef, quant, gguf_q, offload, progress)
            else:
                pipe = self._load_sd(mdef, progress)
            if want_ip:
                self._load_ip(pipe, progress)
            self._pipe = pipe
            self._pipe_key = key
            self._pipe_type = mtype
            self._loaded_adapters = []
            if progress:
                progress("Ready", 1.0)
            return pipe

    def _load_sd(self, mdef, progress=None):
        from diffusers import AutoPipelineForText2Image
        torch = self._torch
        dtype = torch.float16 if self._device() == "cuda" else torch.float32
        if progress:
            progress(f"Loading {mdef.get('label', 'SD')}", 0.3)
        if mdef.get("imported") and mdef.get("path"):
            # single-file checkpoints load via the concrete pipeline class
            # (AutoPipeline has no from_single_file)
            if str(mdef.get("type")) == "sdxl":
                from diffusers import StableDiffusionXLPipeline as _SDPipe
            else:
                from diffusers import StableDiffusionPipeline as _SDPipe
            pipe = _SDPipe.from_single_file(
                mdef["path"], torch_dtype=dtype, safety_checker=None,
                load_safety_checker=False)
        elif str(mdef.get("type")) == "sdxl":
            # SDXL has no safety_checker component; don't pass the kwarg.
            pipe = AutoPipelineForText2Image.from_pretrained(mdef["repo"], torch_dtype=dtype)
        else:
            pipe = AutoPipelineForText2Image.from_pretrained(
                mdef["repo"], torch_dtype=dtype, safety_checker=None)
        try:
            pipe.safety_checker = None
            pipe.set_progress_bar_config(disable=True)
        except Exception:
            pass
        if self._device() == "cuda":
            pipe.to("cuda")
        return pipe

    def _load_flux(self, mdef, quant, gguf_q, offload, progress=None):
        from diffusers import FluxPipeline, FluxTransformer2DModel, GGUFQuantizationConfig
        torch = self._torch
        dtype = torch.bfloat16 if self._device() == "cuda" else torch.float32

        def say(s, f=0.3):
            if progress:
                progress(s, f)

        if mdef.get("imported") and mdef.get("path"):
            p = mdef["path"]
            say(f"Loading checkpoint {Path(p).name}", 0.2)
            if str(p).lower().endswith(".gguf"):
                transformer = FluxTransformer2DModel.from_single_file(
                    p, quantization_config=GGUFQuantizationConfig(compute_dtype=dtype),
                    torch_dtype=dtype)
            else:
                transformer = FluxTransformer2DModel.from_single_file(p, torch_dtype=dtype)
            pipe = FluxPipeline.from_pretrained(SCHNELL_REPO, transformer=transformer,
                                                torch_dtype=dtype)
        elif quant == "gguf":
            from huggingface_hub import hf_hub_download
            fname = GGUF_FILES.get(gguf_q, GGUF_FILES["Q4_K_S"])
            say(f"Downloading transformer ({gguf_q})", 0.1)
            gguf_path = hf_hub_download(GGUF_REPO, fname)
            say("Loading FLUX transformer", 0.35)
            transformer = FluxTransformer2DModel.from_single_file(
                gguf_path, quantization_config=GGUFQuantizationConfig(compute_dtype=dtype),
                torch_dtype=dtype)
            say("Loading text encoders + VAE", 0.55)
            pipe = FluxPipeline.from_pretrained(SCHNELL_REPO, transformer=transformer,
                                                torch_dtype=dtype)
        else:
            say("Loading FLUX pipeline", 0.2)
            pipe = FluxPipeline.from_pretrained(mdef.get("repo", SCHNELL_REPO), torch_dtype=dtype)
            if quant == "fp8" and self._device() == "cuda":
                try:
                    from optimum.quanto import freeze, qfloat8, quantize
                    say("Quantizing to fp8", 0.6)
                    quantize(pipe.transformer, weights=qfloat8); freeze(pipe.transformer)
                    quantize(pipe.text_encoder_2, weights=qfloat8); freeze(pipe.text_encoder_2)
                except Exception:  # noqa: BLE001
                    pass

        say("Optimizing memory", 0.8)
        try:
            pipe.set_progress_bar_config(disable=True)
        except Exception:
            pass
        if self._device() == "cuda":
            if offload == "sequential":
                pipe.enable_sequential_cpu_offload()
            elif offload == "none":
                pipe.to("cuda")
            else:
                pipe.enable_model_cpu_offload()
        return pipe

    def _free(self):
        import gc
        gc.collect()
        try:
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
        except Exception:
            pass

    # ---- IP-Adapter (cartoon style RAG) -----------------------------------
    def _load_ip(self, pipe, progress=None):
        """Attach IP-Adapter so retrieved reference images steer the cartoon style."""
        ipc = config.IP_ADAPTER
        try:
            if progress:
                progress("Loading IP-Adapter (style RAG)", 0.85)
            from transformers import CLIPVisionModelWithProjection
            dtype = self._torch.float16 if self._device() == "cuda" else self._torch.float32
            enc = CLIPVisionModelWithProjection.from_pretrained(
                ipc["repo"], subfolder=ipc.get("image_encoder_subfolder", "models/image_encoder"),
                torch_dtype=dtype)
            if self._device() == "cuda":
                enc = enc.to("cuda")
            pipe.image_encoder = enc
            pipe.load_ip_adapter(
                ipc["repo"], subfolder=ipc["subfolder"], weight_name=ipc["weight_name"],
                image_encoder_folder=None)       # use the pre-loaded encoder (Windows-safe)
            self._ip_loaded = True
        except Exception as exc:  # noqa: BLE001 - degrade to base SDXL + style prompt
            print(f"[image] IP-Adapter load failed ({exc}); using base SDXL + prompt only")
            self._ip_loaded = False

    def _ip_scale(self, scale: float):
        """Style-transfer scale: route the reference only through the style block so
        composition stays prompt-driven (diffusers IP-Adapter style/layout trick)."""
        if config.IP_ADAPTER.get("style_only"):
            return {"up": {"block_0": [0.0, float(scale), 0.0]}}
        return float(scale)

    # ---- LoRA -------------------------------------------------------------
    def _resolve_loras(self, img: Dict) -> List[Dict]:
        out: List[Dict] = []
        if img.get("use_default_lora", True) and self._pipe_type == "flux":
            out.append({"name": "builtin", "repo": DEFAULT_LORA["repo"],
                        "filename": DEFAULT_LORA["filename"],
                        "weight": float(img.get("default_lora_weight", DEFAULT_LORA["weight"]))})
        for spec in (img.get("loras") or []):
            m = storage.get_image_model(spec.get("id"))
            if m and m.get("kind") == "lora":
                out.append({"name": m["id"].replace("-", "")[:24], "path": m.get("path"),
                            "trigger": m.get("trigger", ""),
                            "weight": float(spec.get("weight", m.get("weight", 1.0)))})
        return out

    def apply_loras(self, pipe, img: Dict) -> List[str]:
        specs = self._resolve_loras(img)
        wanted = [s["name"] for s in specs]
        if wanted == self._loaded_adapters:
            return self._trigger_words(specs)
        try:
            pipe.unload_lora_weights()
        except Exception:
            pass
        self._loaded_adapters = []
        if not specs or not self._lora_supported:
            return []
        names, weights = [], []
        for s in specs:
            try:
                if s.get("path"):
                    pipe.load_lora_weights(s["path"], adapter_name=s["name"])
                else:
                    pipe.load_lora_weights(s["repo"], weight_name=s.get("filename"),
                                           adapter_name=s["name"])
                names.append(s["name"]); weights.append(s["weight"])
            except Exception as exc:  # noqa: BLE001 - degrade to prompt-only
                print(f"[image] LoRA load failed ({s.get('name')}): {exc}")
        if names:
            try:
                pipe.set_adapters(names, adapter_weights=weights)
                self._loaded_adapters = names
            except Exception as exc:  # noqa: BLE001
                print(f"[image] set_adapters failed: {exc}")
        return self._trigger_words(specs)

    def _trigger_words(self, specs) -> List[str]:
        words = []
        for s in specs:
            if s["name"] not in self._loaded_adapters:
                continue
            if s["name"] == "builtin":
                words.append(DEFAULT_LORA["trigger"])
            elif s.get("trigger"):
                words.append(s["trigger"])
        return [w for w in words if w]

    # ---- generation -------------------------------------------------------
    def generate(self, prompt: str, negative: str = "", *, width: int, height: int,
                 steps: int, guidance: float, seed: int, ref_images=None,
                 ip_scale=None, progress=None):
        pipe = self.get_pipeline(progress=progress)
        img = storage.get_settings().get("image", {})
        triggers = self.apply_loras(pipe, img)
        if triggers:
            prompt = f"{', '.join(triggers)}. {prompt}"
        torch = self._torch
        with _infer:
            if self._pipe_type == "flux":
                gen = torch.Generator(device="cpu").manual_seed(int(seed) & 0x7FFFFFFF)
                mseq = 512 if "dev" in str(img.get("model", "")) else 256
                out = pipe(prompt=prompt, width=int(width), height=int(height),
                           num_inference_steps=int(steps), guidance_scale=float(guidance),
                           generator=gen, max_sequence_length=mseq)
            else:
                gen = torch.Generator(device=self._device()).manual_seed(int(seed) & 0x7FFFFFFF)
                kwargs = dict(prompt=prompt, negative_prompt=(negative or None),
                              width=int(width), height=int(height),
                              num_inference_steps=int(steps),
                              guidance_scale=float(guidance), generator=gen)
                if self._ip_loaded:
                    kwargs["ip_adapter_image"] = [self._prep_refs(ref_images)]  # one list per adapter
                    scale = ip_scale if ip_scale is not None else config.IP_ADAPTER["default_scale"]
                    # no usable refs -> neutralize the adapter (still must pass an image)
                    pipe.set_ip_adapter_scale(self._ip_scale(scale if ref_images else 0.0))
                out = pipe(**kwargs)
        return out.images[0]

    def _prep_refs(self, ref_images):
        """Open reference image paths as PIL (or a blank when the pack is empty)."""
        import os
        from PIL import Image
        imgs = []
        for p in (ref_images or []):
            try:
                if os.path.exists(p):
                    imgs.append(Image.open(p).convert("RGB"))
            except Exception:  # noqa: BLE001
                pass
        return imgs or [Image.new("RGB", (224, 224), (255, 255, 255))]

    # ---- status -----------------------------------------------------------
    def status(self) -> Dict:
        return {
            "loaded": self._pipe is not None,
            "model": (self._pipe_key[0] if self._pipe_key else None),
            "type": self._pipe_type,
            "lora_supported": self._lora_supported,
            "ip_loaded": self._ip_loaded,
            "adapters": list(self._loaded_adapters),
            "torch_ready": self._torch is not None,
            "import_error": self._import_error,
        }


image_engine = ImageEngine()
