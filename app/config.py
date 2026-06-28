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
TRAINING_DIR = BASE_DIR / "training"                      # LoRA datasets: <base>/<name>/dataset
TRAINING_RUNS_DIR = DATA_DIR / "training_runs"            # per-run training logs
STYLE_REFS_DIR = DATA_DIR / "style_refs"                  # cartoon style reference pack (RAG)

for _d in (DATA_DIR, OUTPUTS_DIR, REFS_DIR, PROJECTS_DIR, MODELS_DIR,
           DIFFUSION_DIR, LORAS_DIR, TRAINING_DIR, TRAINING_RUNS_DIR, STYLE_REFS_DIR):
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
    "cartoon-rag": {
        "label": "Cartoon (SDXL + reference RAG · local, no ComfyUI)", "type": "sdxl",
        "repo": "stabilityai/stable-diffusion-xl-base-1.0",
        "ip_adapter": True,          # IP-Adapter style transfer from the reference pack
        "steps": 30, "guidance": 6.0, "width": 1024, "height": 576,
        "gated": False, "size": "~7 GB", "negative": True,
    },
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
# Default to the standalone **cartoon-rag** path (SDXL + IP-Adapter reference RAG):
# fully local, NO ComfyUI. krea2 (ComfyUI) stays selectable as the legacy engine;
# SD 1.5 / FLUX remain available via diffusers too.
DEFAULT_IMAGE_MODEL = "cartoon-rag"

# --- cartoon style via reference RAG (IP-Adapter, no ComfyUI) ----------------
# The reference pack lives in data/style_refs/ (seed it from your krea2 cartoon
# renders). At generation time the top-k references are fed to IP-Adapter in
# *style-transfer* mode so SDXL reproduces the flat-cartoon look without copying
# composition — the standalone replacement for krea2's baked-in style.
IP_ADAPTER = {
    "repo": "h94/IP-Adapter",
    "subfolder": "sdxl_models",
    "weight_name": "ip-adapter_sdxl_vit-h.safetensors",
    "image_encoder_subfolder": "models/image_encoder",
    "default_scale": 0.7,          # overall style strength
    "top_k": 3,                    # how many references to blend per image
    # style-transfer layer targeting (diffusers IP-Adapter trick): only the
    # style block carries the reference, so composition stays prompt-driven.
    "style_only": True,
}
# Flat-cartoon style suffix for the RAG/diffusers path (same intent as KREA2_STYLE).
CARTOON_STYLE = (
    "flat 2D cartoon explainer illustration, Cyanide-and-Happiness style: simple "
    "minimal bodies with thin noodle limbs but expressive detailed faces (clear "
    "eyes, eyebrows, mouth conveying emotion); bold clean uniform black outlines, "
    "flat solid color fills, soft cell-shading, gentle directional lighting, no "
    "gradients, no photorealism, no 3D, clean vector look, simple uncluttered background"
)

# --- ComfyUI backend (drives the local krea2 / Qwen-Image checkpoint) -------
# krea2 is a ComfyUI fp8 checkpoint the in-app diffusers engine can't load, so
# "comfyui"-type models are rendered by talking to ComfyUI's HTTP API. ComfyUI is
# auto-started from this portable install on first use.
COMFY_DIR = BASE_DIR / "ComfyUI_windows_portable"
COMFY_PYTHON = COMFY_DIR / "python_embeded" / "python.exe"
COMFY_MAIN = COMFY_DIR / "ComfyUI" / "main.py"
COMFY_URL = os.environ.get("AAAFLOW_COMFY_URL", "http://127.0.0.1:8188")
COMFY_LOG = DATA_DIR / "comfyui.log"                       # headless ComfyUI stdout/stderr
KREA2_PER_LAYER = "1.0,1.0,1.0,1.0,1.0,1.0,1.0,2.5,5.0,1.1,4.0,1.0"  # ConditioningKrea2Rebalance
# Flat 2D cartoon "history-explainer" style that overrides the storyboard's own
# ink/whiteboard suffix when rendering with krea2.
KREA2_STYLE = (
    "flat 2D cartoon explainer illustration in a Cyanide-and-Happiness style: "
    "simple minimal bodies (rounded torsos with thin noodle/stick limbs and small "
    "simple hands) but expressive, detailed faces with clear eyes, eyebrows and mouth "
    "shapes conveying real emotion; bold clean uniform black outlines, flat solid color "
    "fills, soft cell-shading with simple drop shadows and gentle directional lighting, "
    "no gradients, no photorealism, no 3D, clean vector look, simple uncluttered background"
)

# --- LTX-2 video animation (still -> short clip, via ComfyUI) ---------------
# Animates a generated scene still into a short clip when the storyboard scene
# declares motion (its ``motion_prompt`` / ``motion_type``). This drives the same
# ComfyUI instance as krea2, using the model set that ComfyUI's bundled
# "Image to Video (LTX-2.3)" blueprint expects — the gemma text encoder is shared
# with that blueprint (already downloaded). Video-only: the narration still comes
# from Qwen3-TTS, so LTX's own audio branch is skipped. LTX-2 is heavy on a 16 GB
# GPU, so animation is opt-in per scene (animate hero / "transform" scenes only).
LTX2 = {
    # The 19B "dev" fp4 build is a *fused* checkpoint (DiT + VAE + audio_vae +
    # text_embedding_projection) and is the largest LTX-2 that runs on a 16 GB card.
    # It lives in ComfyUI/models/checkpoints/ so CheckpointLoaderSimple (model+VAE) and
    # LTXAVTextEncoderLoader (gemma + this ckpt for the projection/tokenizer) can use it.
    "checkpoint": "ltx-2-19b-dev-fp4.safetensors",             # models/checkpoints (fused)
    "text_encoder": "gemma_3_12B_it_fp4_mixed.safetensors",    # models/text_encoders
    # generation defaults (kept modest to fit 16 GB)
    "width": 768, "height": 512, "fps": 25,
    "default_seconds": 3.0,        # clip length when a scene gives none
    "max_seconds": 6.0,            # cap (LTX cost scales hard with length)
    "steps": 16,                   # dev model (no distilled LoRA) -> moderate steps
    "guidance": 3.0,               # dev model -> real CFG
    "sampler": "euler",
    # LTXVScheduler (sigma schedule for the dev model)
    "max_shift": 2.05, "base_shift": 0.95, "terminal": 0.1,
    "image_strength": 1.0,         # 1.0 = first frame locked to the still
    "end_strength": 0.85,          # last-frame guide strength (transform scenes)
    "negative": ("blurry, out of focus, low quality, jpeg artifacts, distorted, "
                 "deformed, warping, flickering, morphing artifacts, watermark, text"),
}
# Weights the animate stage needs. url -> ComfyUI/models/<subdir>. Both are usually
# already present; the in-app download job skips files that match the HF size.
LTX2_DOWNLOADS = [
    ("checkpoints", "ltx-2-19b-dev-fp4.safetensors",
     "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-dev-fp4.safetensors"),
    ("text_encoders", "gemma_3_12B_it_fp4_mixed.safetensors",
     "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors"),
]


def comfy_models_dir() -> Path:
    return COMFY_DIR / "ComfyUI" / "models"


def _big_enough(path: Path, min_bytes: int) -> bool:
    try:
        return path.exists() and path.stat().st_size >= min_bytes
    except OSError:
        return False


def ltx2_ready() -> bool:
    """True when the fused LTX-2 19B checkpoint + gemma encoder are present (in full)."""
    m = comfy_models_dir()
    return (_big_enough(m / "checkpoints" / LTX2["checkpoint"], 8 * 1024**3)
            and _big_enough(m / "text_encoders" / LTX2["text_encoder"], 1 * 1024**3))

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
        "model": "cartoon-rag",       # key into IMAGE_BASES or an imported checkpoint id
        "style": None,               # optional style preset; None = model/storyboard default
        "use_refs": True,            # cartoon-rag: condition on the style reference pack
        "ip_scale": 0.7,             # IP-Adapter style strength (cartoon-rag)
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
