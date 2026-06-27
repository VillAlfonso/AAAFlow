# AAAFlow Studio 🎬

A fully-local web studio that turns a **storyboard JSON** into a finished,
voice-synced video — no cloud, no API keys. It reads the
`{ "video", "scenes" }` format (see `weimar_hyperinflation_scenes.json`) and runs
the whole pipeline on your own machine:

```
import JSON → timed voiceover (Qwen3-TTS) → per-scene images (SD / FLUX) → synced MP4
```

![local](https://img.shields.io/badge/runs-100%25%20local-e6a94b) ![gpu](https://img.shields.io/badge/NVIDIA-CUDA-76b900)

## What it does

- **Projects** — import a storyboard `.json` (drag-drop or paste). Each scene
  becomes a card with its narration, image prompt, timecode and on-screen text.
- **Storyboard** — browse/filter/edit every scene; per-scene re-generate.
- **Voiceover** — narrate each scene with Qwen3-TTS (9 built-in speakers + your
  own designed/cloned voices). **Audio-led sync**: each scene is held for its
  *real* narration length, so images never drift out of sync.
- **Images** — generate a picture per scene with **Stable Diffusion 1.5**
  (default, ~2 GB) or **FLUX** (higher fidelity, ~16 GB). Import your own
  checkpoints / LoRAs; a built-in simple-sketch LoRA gives the stick-figure look.
- **Assemble** — stitch images + timed audio into a 1920×1080 MP4 with subtle
  Ken Burns motion, crossfades, and on-screen text composited in post.
- **Preview** — an in-browser, scrubbable timeline player to check sync before
  rendering.
- **Voice Lab** — design a voice from a text description, or clone one from a
  short sample.
- **History** — every voiceover batch, image batch and assembled video.

## Run it

```powershell
# from C:\AAAFlow
./run.ps1            # or double-click run.bat
```

Then open <http://127.0.0.1:8000>.

## Requirements

- Windows, Python 3.11+, **ffmpeg/ffprobe** on `PATH` (or at `C:\ffmpeg\`).
- An **NVIDIA GPU** with the CUDA build of PyTorch (this machine: **RTX 5060 Ti
  16 GB**, cu128). Falls back to CPU (much slower).
- Disk for model weights, downloaded once into `./models`:
  - Qwen3-TTS ~15 GB (already present)
  - SD 1.5 (DreamShaper 8) ~2 GB, **or** FLUX ~16 GB.

> **First run downloads models.** On a slow connection this can take a while —
> the **Images → "Download / warm model"** button shows progress, and the first
> *Generate* downloads on demand. SD 1.5 is the default precisely because it's
> small; switch to FLUX in **Settings** when you have the bandwidth.

## Image models

| Model | Type | Size | Notes |
|-------|------|------|-------|
| **SD 1.5 · DreamShaper 8** (default) | Stable Diffusion | ~2 GB | what this JSON targets; supports negative prompts; best stick-figure LoRAs |
| FLUX.1 schnell | FLUX (GGUF) | ~16 GB | Apache-2.0, no token; transformer pulled as a GGUF quant |
| FLUX.1 dev | FLUX | ~16 GB | gated — needs an HF token; highest fidelity |
| *imported* | SD or FLUX | — | drop a `.safetensors` checkpoint or LoRA in **Images → Import** |

The built-in **simple-sketch / stick-figure LoRA**
(`Shakker-Labs/FLUX.1-dev-LoRA-Children-Simple-Sketch`) applies on FLUX; on SD
1.5 the storyboard's detailed `global_style_suffix` carries the look (and you can
import an SD line-art LoRA).

## Voices

9 built-in speakers across 10 languages, plus voice **design** (describe a voice)
and voice **clone** (3-second sample) — managed in **Voice Lab**. Your designed
voices in `data/voices_custom.json` are picked up automatically.

## How it works

```
web/  (vanilla-JS SPA, hash-routed)  ──►  FastAPI (app/main.py)
   ├─ scenes.py        parse {video, scenes[]}; build image prompts
   ├─ projects.py      project model + per-scene state + audio-led timeline
   ├─ voiceover.py     per-scene timed TTS  (reuses engine.py / audio.py)
   ├─ image_engine.py  diffusers SD/FLUX manager + LoRA
   ├─ images.py        per-scene image jobs
   ├─ assemble.py      moviepy: images + audio + text -> MP4
   ├─ engine.py        Qwen3-TTS model manager (CUDA/CPU)
   └─ storage.py/jobs.py/config.py  persistence + background jobs + paths
third_party/Qwen3-TTS/   the TTS engine (installed editable)
models/                  downloaded weights (TTS + diffusion + loras)
data/projects/<id>/      per-project audio/, images/, video/, project.json
```

## Troubleshooting

- **"SoX could not be found" / "flash-attn is not installed"** — harmless; ignore.
- **No images generated** — the diffusion model is still downloading; check
  **Images → Download / warm model**, or your connection speed.
- **FLUX out of memory** — in **Settings**, set FLUX offload to `sequential`, or
  use a smaller GGUF quant; or just use SD 1.5.
- **No MP4 / no audio in video** — ensure ffmpeg is installed and on `PATH`.

Built on [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) (Apache-2.0),
🤗 diffusers, and moviepy. For local, personal content creation.
