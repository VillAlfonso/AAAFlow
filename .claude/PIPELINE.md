# AAAFlow — the canonical production pipeline (deep reference)

This is the process. CLAUDE.md carries the short version; this file explains
*why* each step sits where it does, so nobody (human or Claude) re-orders it.

## Channels first (multi-channel operation)
Every video belongs to a **channel** (`data/channels.json`, `app/channels.py`)
unless deliberately standalone. Inheritance chain at project creation:
`channel.defaults` → creation-time picks → the storyboard's own fields (each
later layer wins). Defaults cover: image_model, animate_engine, quality,
preset, voice + voice_instruct + language, style_suffix (art direction),
negative_style, music_vibe, authoring (pro|assisted). The channel also carries
the writing brief + topic bank; `GET /api/channels/{cid}/authoring_prompt`
composes storyboard_v3_prompt.md + that brief into one paste-ready prompt.
Projects stamp `project.channel`; channel cards show their videos.
API: GET/POST `/api/channels`, DELETE `/api/channels/{cid}`.
Rule: a channel's look NEVER gets hardcoded into a pipeline stage — edit the
registry instead.

## Why voice-first, one take
Per-scene TTS = 28 independent generations. Each one picks its own energy, so
scene boundaries jump in tone and the video sounds stitched (it is). One take
= a single generation pass over the whole script: prosody arcs across
sentences, paragraph gaps come from stitching rules, tone stays continuous.
The recording becomes the project's **narration track** (`audio/narration.wav`
+ `project.narration`); it is never cut per scene. Scenes are *timed to it*
by Whisper word-timestamps (`voiceover.submit_onetake` → `_align_scenes`).

Practical rules learned in production:
- End narration lines with periods. A trailing comma invited Qwen to invent
  "…and a phone and phone's on time, be happy I can't swim." (scene 6,
  2026-07-02). The QA gate (script vs transcript fuzzy compare) is built into
  the one-take job — check `result.qa.ok`.
- The storyteller `instruct` matters more than the speaker choice.

## Stage order
1. **Script** → storyboard JSON (`storyboard_v2_prompt.md` shape). When
   writing scenes, consult `GET /api/sfx` for available `audio_cue` tags and
   keep on_screen_text empty (it is never rendered).
2. **One-take narration** → alignment sets `planned_start/end` per scene.
   Timeline mode flips to narration-track (see `projects.recompute_timeline`).
3. **Images** (krea2). Composition rule: scene `image_prompt` (+ character
   bible looks for named characters) + project global style, clause-deduped;
   people-clause stripped for people-less scenes. QA a sample; re-render
   individual scenes with `scope: "scene"`.
4. **Music** (ACE-Step sidecar) → set on project with volume ~0.16, duck on.
   Kill the sidecar process (port 8765) before LTX.
5. **Animate** (optional; only when the chosen preset uses "clips") —
   **Wan 2.2 14B** i2v (fp8 MoE experts via ComfyUI), ~3 s ambient clips on
   hero scenes flagged `motion_type: ambient`. Quality profiles in
   `config.WAN["quality_profiles"]`: **max** (default — 20 steps, cfg 3.5,
   native 1280x720, no speed LoRAs; slow and that's fine) and **fast**
   (lightx2v 4-step at 832x480, drafts only). Every clip then runs the
   **enhance chain** (`app/enhance.py`): ffmpeg minterpolate to 30 fps +
   Real-ESRGAN `realesr-animevideov3` 2x line sharpening. Stills feeding
   parallax get the same 2x sharpen (cached `*_up2x.png`).
   LTX-2 was fully removed 2026-07-03 (35 GB reclaimed) — do not re-add.
6. **Assemble** — preset-driven (`data/effects_presets.json`):
   - `sources` chain per scene: `clips` → `parallax` → `stills` (first
     available wins; stills always the fallback).
   - **Parallax** = `app/parallax.py`: Depth-Anything-V2-small depth map +
     GPU grid_sample warp; camera moves dolly/pan/tilt/arc picked from shot
     hints else rotated per scene index; clips cached as
     `video/scene_XXXX_plx_{W}x{H}_{dur}.mp4`.
   - Audio is one mix: narration + ducked bed + `audio_cue` stingers
     (library file first, procedural synth fallback) + peak limiter.
   - No caption compositing exists anymore. Do not add it back.
7. **QA the mp4**: `scratchpad/inspect_video.py` pattern — ffprobe + frame
   samples + ebur128 loudness (target around -14 to -20 LUFS, peaks < -1 dB).

## One-call production
`POST /api/projects/{pid}/produce {"plan": {...}}` chains
voice(one-take when no narration) → images(missing) → animate(missing, only
if preset uses clips) → assemble(preset). Status:
`GET /api/projects/{pid}/produce`. Stages are idempotent — re-produce resumes.

## Auto-direction (weak-model proofing)
`app/autodirect.py` runs inside `projects.create_project` on EVERY import (the
report lands in `project.direction_report`) and via `POST /api/storyboard/lint`:
- fixes TTS-unsafe narration endings (trailing comma → period; missing → period)
- clears any `on_screen_text` (the no-burned-text rule is absolute)
- fills empty `transition` from hook/body rotations (hook window = first 30 s
  of estimated narration; punchy set there, varied set after)
- fills empty `audio_cue` by keyword → library-tag mapping (hook cuts always
  carry energy), warns on cues that match nothing
- fills `shot` rotation (drives parallax camera-move variety)
- flags hero scenes (`motion_type: ambient`): scene 1 + the longest scenes,
  budget ≈ scenes/4 capped at 10
- falls back to the flat-cartoon house style when `global_style_suffix` is empty
- lints the viral formula: scene-1 length, hook words/scene, est. runtime
The division of labor: models write narration + picture subjects
(`storyboard_v3_prompt.md`); code directs. Raise output quality by improving
autodirect/the template — that fixes every future video at once.

**Assisted mode** (`settings.authoring == "assisted"`, the "write it with
Haiku" path): `autodirect.direct(..., strict=True)` may additionally REWRITE
weak structure — trims a >14-word cold open at the first safe clause/sentence
boundary, splits >26-word multi-sentence scenes into two cuts near the word
midpoint (scene B gets "different moment, alternate angle" + fresh directing
fields; max 8 splits; scenes renumbered, thumbnail_scene remapped). Pro mode
never touches author text beyond punctuation. Channel default or per-project.

## Publish (step 9: SEO → Shorts → Upload)
**SEO** `POST /api/projects/{pid}/package {thumb_text?}` (`app/packaging.py`):
2-3 title options, keyword-front-loaded description with chapters (every
≥25 s), tags = title phrases + recurring narration bigrams + top words +
channel `seo_keywords` pool (≤470 chars, video-specific terms lead → unique
per video BY CONSTRUCTION), hashtags, thumbnail (hero frame, prefers
`*_up2x.png`, gradient + stroked headline — allowed; only in-video text is
banned). Saved to `project.seo`; `PUT .../seo` persists user edits; the
uploader reads the edited copy. Writes `video/youtube_package.md` too.

**Shorts** `POST /api/projects/{pid}/shorts {count}` (`app/shorts.py`): picks
hook (0 → boundary nearest 30 s) and payoff (last ~30 s from a boundary)
windows and renders them through `assemble._render` with
`{window, 1080x1920, out_name}` — parallax re-renders natively vertical
(size-keyed cache), Wan clips cover-crop, one-mix audio slices the narration
track. Saved to `project.shorts`; upload them with " #Shorts" in the TITLE.

**Upload** (`app/youtube.py`): per-channel Google OAuth (Desktop client;
loopback redirect to `/api/youtube/oauth/callback`; refresh token stored on
the channel). `POST /api/projects/{pid}/upload {file?, privacy?}` = job:
refresh token → resumable chunked upload (8 MB, 308-resume) → thumbnails/set.
Metadata comes from `project.seo`. **Default privacy: private** (also, Google
locks unverified-app uploads to private) — publish manually on YouTube.
videos.insert costs 1600 quota units (~6 uploads/day on the default 10k).
Uploads ledger: `project.uploads`.

**Local writer** (`app/writer.py`): `POST /api/channels/{cid}/write {topic?}`
= channel authoring prompt → Ollama (if reachable) else in-process
Qwen3-4B-Instruct (auto-downloads ~8 GB, CUDA→CPU fallback, freed after) →
balanced-JSON extraction (one retry with the parse error fed back; raw draft
kept at `data/outputs/writer_last.json`) → `create_project(channel=cid)` so
the auto-director (assisted when the channel says so) directs it. The writer
job serializes on the single job queue, so it never fights a render for VRAM.

**Auto-music**: `produce` inserts a `music` stage (before animate) when the
project has a channel `music_vibe`, no bed yet, and ACE is installed —
generates a 75 s bed, attaches it (vol 0.16, duck, fade 1.5), then kills the
ACE sidecar (port 8765) to free VRAM before Wan.

## Libraries that persist across videos
- `data/effects_presets.json` — editing styles (cinematic / parallax-slides /
  dynamic-slides / simple-slides + any saved custom looks).
- `data/sfx_library/` + `data/sfx_library.json` — stinger wavs, tag-matched
  from each scene's `audio_cue`. Drop packs in (filename → tags) or extend the
  manifest; `riser`-tagged entries end ON the cut instead of starting at it.
- `data/music/` — generated ACE-Step beds, reusable via the Music page.
- Character bibles live per-project in the storyboard (`character_bible`).

## Storage discipline
Disk janitor: `GET /api/storage` (free space, per-dir sizes, reclaimables) +
`POST /api/storage/clean {actions}` (UI: Settings · Storage). Safe actions:
old_renders (keeps newest final per project), parallax_cache, upscale_cache,
comfy_io, moviepy_temp, hf_incomplete, pycache, logs (truncate). 2026-07-03
purge ledger (~100 GB): ltx-2.3-22b fp8 29 GB (last LTX remnant), training-only
raw weights 33 GB (`trainers/weights/README.md` has re-download pointers),
SDXL 14 GB + IP-Adapter 6.5 GB + SD1.5 x2 8.5 GB + safety-checker/0.6B-TTS/
AnimateDiff/dreamshaper/vae-fix ~6.5 GB (all HF-cached → auto-re-download on
use), krea2 LoRA epochs 1-5. `DEFAULT_IMAGE_MODEL` is now **krea2**.
Legacy code deleted the same day: animatediff_engine.py, LTX/AnimateDiff
trainer scripts, Wan2.2 repo clone, stale QwenTTS/.git.

## Failure modes catalog (check before debugging something "new")
- TTS: hallucinated continuations (comma endings), slow theatrical stretches.
- krea2: phantom people in people-less scenes (fixed by clause strip); style
  drift to photoreal on famous landmarks; gibberish glyphs on documents —
  avoid close-up readable text in prompts.
- Video models (Wan included): melt under long durations or over-driven
  motion; keep ~3 s / subtle; small moving props smear. Style-hold = project
  style leads the prompt + style_tail + motion-quality negatives.
- **ffmpeg minterpolate on flat art = ghosting/glitching** (2026-07-03: birds
  grew ghost doubles, lattices tore; user: "glitchy and kinda melty"; single
  frames looked FINE — always QA consecutive frames at 1:1, not lone stills).
  Interpolation is now OFF (ENHANCE.interpolate); clips stay native 16 fps and
  the timeline duplicates frames (cartoon-on-twos). If interpolation is ever
  truly needed, use RIFE, never minterpolate.
- A clip freezing on its last frame mid-scene reads as a glitch — the
  assembler drifts the held frame (slow zoom) instead (_fit_clip).
- moviepy: time-varying resizes report odd t=0 sizes — every transition must
  return a fixed W×H composite (libx264 rejects odd widths).
- VRAM: ACE sidecar + ComfyUI + TTS engine all resident = OOM risk on 16 GB.
