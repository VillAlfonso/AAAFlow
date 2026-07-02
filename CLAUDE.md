# AAAFlow Studio

## Mission
**Type a script in → a finished YouTube video comes out.** Fully local, one machine
(RTX 5060 Ti 16 GB), zero cloud. The output must look like it was made by a human
creator — writing, pacing, art direction, editing, sound. If a viewer (or a
platform) can tell it's AI-generated, that's a failure. "Good enough for AI" is
not the bar; *indistinguishable from a skilled human editor* is the bar.

## What "human-made" means here
- **Hook discipline:** the first 30 seconds carry the densest editing — fast cuts,
  punch-ins, motion, on-screen text that pays off the thumbnail. Never open slow.
- **Editing variety:** no metronome pacing. Mix cut lengths, transitions, zoom
  directions; let big lines breathe, rush the montages.
- **One art direction per video:** a single global style drives stills, end frames
  and animation (never hardcode a look into a pipeline stage — source it from the
  project's `video.global_style_suffix`).
- **Sound design:** music matched to the story's emotion, ducked under narration;
  scene-appropriate pacing in the voice (instruct prompts), not TTS monotone.
- **No AI tells:** no melted hands/faces (regenerate or reframe), no watermark-ish
  artifacts, no uncanny drift in animated clips (keep clips short, motion subtle).

## Pipeline (all local)
1. **Script → JSON** — storyboard JSON (see `storyboard_v2_prompt.md`, parser in
   `app/scenes.py`). Scenes carry narration, image_prompt, motion, transitions.
2. **Voiceover** — Qwen3-TTS (`app/voiceover.py`, engine in `app/engine.py`).
   Voiceover-first flow: master narration can drive scene timing.
3. **Images** — Krea-2 Turbo via ComfyUI (`app/comfy_engine.py`) or SDXL/FLUX via
   diffusers (`app/image_engine.py`). Prompt = scene image_prompt + editable
   global style (clause-deduped in `scenes.build_image_prompt`).
4. **Music / SFX** — ACE-Step 1.5 sidecar (`app/music_engine.py`, isolated venv).
5. **Animate** — LTX-2 19B fp4 i2v via ComfyUI (`app/ltx_engine.py`), short
   (~1.5 s) subtle-motion clips on hero scenes only; Wan 2.2 as alternative.
6. **Assemble** — ffmpeg (`app/assemble.py`): timeline from real narration audio,
   Ken Burns, transitions, burned on-screen text, music bed, loudness-normalized.

## Hard-won operational rules
- Backend (`app/*.py`) edits need a **full server restart** (no hot-reload):
  `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
  from repo root, log to `data/server.log`. Bump the `app.js?v=` cache-bust in
  `web/index.html` on frontend changes. **Never restart while a job runs** —
  jobs live in the server process.
- One GPU: krea2 renders, LTX clips and TTS contend — the app serializes ComfyUI
  work on one lock; run heavy stages sequentially, not in parallel.
- ComfyUI auto-starts from `ComfyUI_windows_portable/` on first image/animate use.
- Don't auto-open rendered media or the browser on the user's machine.
- Projects live in `data/projects/<pid>/` (`project.json` + audio/ images/ video/).

## Quality checklist before calling a video done
- [ ] Watch (or frame-sample) the actual output mp4 — never ship unviewed.
- [ ] First 30 s: hook lands, effects dense, thumbnail promise paid off.
- [ ] Audio: narration clear over music, no clipping, no dead air > 1 s.
- [ ] No scene shows an AI artifact (hands, faces, melted text, style drift).
- [ ] Text overlays are readable on every background they sit on.
