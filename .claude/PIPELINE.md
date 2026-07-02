# AAAFlow — the canonical production pipeline (deep reference)

This is the process. CLAUDE.md carries the short version; this file explains
*why* each step sits where it does, so nobody (human or Claude) re-orders it.

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

## Libraries that persist across videos
- `data/effects_presets.json` — editing styles (cinematic / parallax-slides /
  dynamic-slides / simple-slides + any saved custom looks).
- `data/sfx_library/` + `data/sfx_library.json` — stinger wavs, tag-matched
  from each scene's `audio_cue`. Drop packs in (filename → tags) or extend the
  manifest; `riser`-tagged entries end ON the cut instead of starting at it.
- `data/music/` — generated ACE-Step beds, reusable via the Music page.
- Character bibles live per-project in the storyboard (`character_bible`).

## Failure modes catalog (check before debugging something "new")
- TTS: hallucinated continuations (comma endings), slow theatrical stretches.
- krea2: phantom people in people-less scenes (fixed by clause strip); style
  drift to photoreal on famous landmarks; gibberish glyphs on documents —
  avoid close-up readable text in prompts.
- Video models (Wan included): melt under long durations or over-driven
  motion; keep ~3 s / subtle; small moving props smear. Style-hold = project
  style leads the prompt + style_tail + motion-quality negatives.
- moviepy: time-varying resizes report odd t=0 sizes — every transition must
  return a fixed W×H composite (libx264 rejects odd widths).
- VRAM: ACE sidecar + ComfyUI + TTS engine all resident = OOM risk on 16 GB.
