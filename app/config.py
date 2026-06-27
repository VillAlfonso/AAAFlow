"""Central configuration: paths, model repos, and default settings.

Importing this module sets HF_HOME so every model weight is downloaded *inside*
the project (./models) instead of the user profile. Import it before
`qwen_tts` / `transformers` / `diffusers` anywhere in the app.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# --- paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # project root (C:\AAAFlow)
APP_DIR = BASE_DIR / "app"
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = DATA_DIR / "outputs"                          # generated audio
REFS_DIR = DATA_DIR / "refs"                               # uploaded clone samples
PROJECTS_DIR = DATA_DIR / "projects"                       # one folder per imported storyboard
MODELS_DIR = BASE_DIR / "models"                          # HF weight cache (TTS + diffusion)
DIFFUSION_DIR = MODELS_DIR / "diffusion"                  # imported image checkpoints (.safetensors)
LORAS_DIR = MODELS_DIR / "loras"                          # imported / downloaded LoRAs

for _d in (DATA_DIR, OUTPUTS_DIR, REFS_DIR, PROJECTS_DIR, MODELS_DIR,
           DIFFUSION_DIR, LORAS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Keep model weights local to the project and use the fast downloader.
os.environ.setdefault("HF_HOME", str(MODELS_DIR))
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")  # hf_transfer stalls on this machine; classic downloader is reliable
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")         # Xet backend hangs here; use the plain LFS CDN
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"
CUSTOM_VOICES_FILE = DATA_DIR / "voices_custom.json"
IMAGE_MODELS_FILE = DATA_DIR / "image_models.json"         # registry of imported checkpoints/LoRAs

# --- models ----------------------------------------------------------------
# Each "size" maps a task -> Hugging Face repo id. The model bundles its own
# 12Hz codec under speech_tokenizer/, so one download per task is self-contained.
MODEL_REPOS = {
    "1.7B": {
        "custom_voice": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "voice_design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    },
    "0.6B": {
        "custom_voice": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        # 0.6B has no VoiceDesign checkpoint and no instruction control.
        "base": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    },
}

# --- image models (local via diffusers) ------------------------------------
# Built-in bases span two families:
#   "sd"   — Stable Diffusion (1.5): small (~2 GB), what this storyboard JSON was
#            authored for, supports negative prompts, best stick-figure LoRAs.
#   "flux" — FLUX.1 (schnell ungated / dev gated): higher fidelity but ~16 GB to
#            download (transformer GGUF + T5), heavier on a slow connection.
# Imported .safetensors checkpoints are added to this set at runtime.
IMAGE_BASES = {
    "krea2": {
        "label": "Krea-2 Turbo · flat cartoon (local · ComfyUI)", "type": "comfyui",
        "unet": "krea2_turbo_fp8_scaled.safetensors",
        "clip": "qwen3vl_4b_fp8_scaled.safetensors", "clip_type": "krea2",
        "vae": "qwen_image_vae.safetensors",
        "steps": 8, "guidance": 1.0, "width": 1280, "height": 720,
        "gated": False, "size": "local", "negative": False,
    },
    "sd15-dreamshaper": {
        "label": "SD 1.5 · DreamShaper 8", "type": "sd",
        "repo": "Lykon/dreamshaper-8",
        "steps": 26, "guidance": 7.0, "width": 896, "height": 512,
        "gated": False, "size": "~2 GB", "negative": True,
    },
    "flux-schnell": {
        "label": "FLUX.1 schnell (GGUF)", "type": "flux",
        "repo": "black-forest-labs/FLUX.1-schnell",
        "steps": 4, "guidance": 0.0, "width": 1344, "height": 768,
        "gated": False, "size": "~16 GB", "negative": False,
    },
    "flux-dev": {
        "label": "FLUX.1 dev (gated — needs HF token)", "type": "flux",
        "repo": "black-forest-labs/FLUX.1-dev",
        "steps": 24, "guidance": 3.5, "width": 1344, "height": 768,
        "gated": True, "size": "~16 GB", "negative": False,
    },
}
# Default to the local krea2 (flat-cartoon, Qwen-Image-class) via ComfyUI — best
# quality with no download. SD 1.5 / FLUX remain selectable for the diffusers path.
DEFAULT_IMAGE_MODEL = "krea2"

# --- ComfyUI backend (drives the local krea2 / Qwen-Image checkpoint) -------
# krea2 is a ComfyUI fp8 checkpoint the in-app diffusers engine can't load, so
# "comfyui"-type models are rendered by talking to ComfyUI's HTTP API. ComfyUI is
# auto-started from this portable install on first use.
COMFY_DIR = BASE_DIR / "ComfyUI_windows_portable"
COMFY_PYTHON = COMFY_DIR / "python_embeded" / "python.exe"
COMFY_MAIN = COMFY_DIR / "ComfyUI" / "main.py"
COMFY_URL = os.environ.get("AAAFLOW_COMFY_URL", "http://127.0.0.1:8188")
KREA2_PER_LAYER = "1.0,1.0,1.0,1.0,1.0,1.0,1.0,2.5,5.0,1.1,4.0,1.0"  # ConditioningKrea2Rebalance
# Flat 2D cartoon "history-explainer" style that overrides the storyboard's own
# ink/whiteboard suffix when rendering with krea2.
KREA2_STYLE = (
    "flat 2D cartoon illustration, YouTube history-explainer animation style, "
    "bold clean black outlines, flat solid colors, simple cartoon shapes, minimal "
    "flat shading, no gradients, no photorealism, clean vector art look, characters "
    "with simple rounded bodies, plain dot eyes and thin stick-like limbs"
)

# --- defaults --------------------------------------------------------------
DEFAULT_SETTINGS = {
    "model_size": "1.7B",        # "1.7B" (quality) | "0.6B" (faster, no instruct/design)
    "device": "cuda",           # "cuda" (NVIDIA GPU, auto-falls back to CPU) | "cpu"
    "default_speaker": "Ryan",
    "default_language": "Auto",
    "output_format": "mp3",      # "mp3" | "wav" | "both"
    "loudnorm": True,            # normalize loudness to a YouTube-friendly target
    "loudnorm_i": -16.0,         # integrated loudness target (LUFS)
    "gap_ms": 180,               # silence inserted between sentence chunks
    "paragraph_gap_ms": 480,     # silence inserted between paragraphs
    "trim_silence": True,        # trim dead air at the head/tail of each chunk
    "max_chars": 240,            # max characters per synthesis chunk
    "max_loaded_models": 2,      # how many task-models kept resident in RAM (LRU)
    "sampling": {
        "temperature": 0.9,
        "top_p": 1.0,
        "top_k": 50,
        "repetition_penalty": 1.05,
        "max_new_tokens": 4096,
    },
    # --- image generation (SD 1.5 default / FLUX optional) ----------------
    "image": {
        "model": "krea2",             # key into IMAGE_BASES or an imported checkpoint id
        "style": None,               # optional style preset; None = model/storyboard default
        "offload": "model",          # FLUX only: "model" | "sequential" | "none"
        "quantize": "gguf",          # FLUX only: "gguf" (small) | "fp8" | "none"
        "gguf_quant": "Q4_K_S",      # FLUX GGUF level: Q4_K_S | Q5_K_S | Q8_0
        "steps": None,               # None = use the model's default
        "guidance": None,
        "width": None,
        "height": None,
        "seed": -1,                  # -1 = random per image; >=0 = reproducible seed family
        "use_default_lora": True,    # apply the built-in stick-figure LoRA (FLUX only)
        "default_lora_weight": 0.95,
        "loras": [],                 # [{"id":..,"weight":..}] extra imported LoRAs
        "civitai_token": "",         # optional, only if pulling a LoRA from Civitai
    },
    # --- voiceover <-> timeline sync --------------------------------------
    "sync": {
        "mode": "audio-led",         # each scene holds for its real narration length
        "min_hold_sec": 1.2,         # never show a scene shorter than this
        "lead_in_ms": 120,           # tiny silence before each line
        "tail_ms": 250,              # tiny silence after each line
    },
    # --- final video assembly ---------------------------------------------
    "assemble": {
        "width": 1920, "height": 1080, "fps": 30,
        "ken_burns": True,           # subtle pan/zoom on stills
        "transitions": True,         # honor per-scene transition (cut/fade/whip)
        "burn_text": True,           # composite on_screen_text in post
        "crossfade_ms": 220,
    },
}


def resolve_ffmpeg() -> str:
    """Return a usable ffmpeg binary path."""
    hint = os.environ.get("FFMPEG_BIN") or r"C:\ffmpeg\ffmpeg.exe"
    if Path(hint).exists():
        return hint
    return shutil.which("ffmpeg") or "ffmpeg"


def resolve_ffprobe() -> str:
    hint = os.environ.get("FFPROBE_BIN") or r"C:\ffmpeg\ffprobe.exe"
    if Path(hint).exists():
        return hint
    return shutil.which("ffprobe") or "ffprobe"


FFMPEG = resolve_ffmpeg()
FFPROBE = resolve_ffprobe()
