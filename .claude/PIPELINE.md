# AAAFlow — the canonical production pipeline (deep reference)

This is the process. CLAUDE.md carries the short version; this file explains
*why* each step sits where it does, so nobody (human or Claude) re-orders it.

## Channels first (multi-channel operation; channel-first UI 2026-07-03)
The app OPENS on a hub of channel cards; entering one scopes the whole studio
UI to it (`#/hub` → `#/ch/<cid>` → `#/p/<pid>/<step>`). Every video belongs
to a **channel**; each channel is a FOLDER `data/channels/<cid>/` with
`channel.json`, `projects/<pid>/` (its videos physically live inside), and
`ui/` for per-channel vibe-coded UIs: `ui.json` {"accent":"#hex"} tint,
`theme.css` restyle, `index.html` full replacement served at `/ch/<cid>/`
(same REST API). `projects.project_dir(pid)` resolves any pid across all
channel folders (+ legacy `data/projects/`) — never hand-build project paths.
Channel delete moves the folder to `data/trash/`. Migration 2026-07-03 merged
the five seeds into channel "main" (originals in `merged_from` +
`data/channels.legacy.json`).
Inheritance chain at project creation:
`channel.defaults` → creation-time picks → the storyboard's own fields (each
later layer wins). Defaults cover: image_model, animate_engine, quality,
preset, coverage, voice + voice_instruct + language, style_suffix (art
direction), negative_style, music_vibe, authoring (pro|assisted). The channel
also carries the writing brief + topic bank;
`GET /api/channels/{cid}/authoring_prompt` composes storyboard_v3_prompt.md +
that brief into one paste-ready prompt. Projects stamp `project.channel`.
API: GET/POST `/api/channels`, GET/DELETE `/api/channels/{cid}`,
`GET /api/projects?channel=<cid>`.
Rule: a channel's look NEVER gets hardcoded into a pipeline stage — edit the
channel's folder instead.

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
- The storyteller `instruct` matters more than the speaker choice — and ask
  for IMPERFECTIONS (breaths, hesitations, uneven gaps); "calm and even"
  alone reads synthetic (Menagerie lesson, 2026-07-05).
- The take is auto-humanized before alignment (`humanize.polish_wav`,
  "natural": tempo jitter, mic EQ/de-ess, tanh saturation, wow, room-tone bed
  — WAV out, no MP3 step). Order matters: humanize → THEN Whisper, so word
  times (`audio/words.json`, feeds emphasis) match the shipped audio. Config:
  `voice.humanize` > channel `defaults.voice_humanize` > `settings.audio.
  voice_humanize` > "natural"; "off" disables.

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
4. **Score audio** (`app/score.py`, auto on every produce) — mood from channel
   `music_vibe` + narration tone; fit ONE mood-matched instrumental bed (vol
   ~0.16, duck on) + a real stinger on every beat. Bed sources: Jamendo library
   (`app/audiolib.py`, commercial-safe CC) → ACE-Step generation → existing.
   SFX: Freesound (CC0) fetched into `data/sfx_library/` → procedural synth.
   Keys in `settings.audio` (Settings·Audio); keyless ⇒ ACE + procedural, never
   blocks. Ledger `data/audio_library/ledger.json`; attribution auto-appended to
   the SEO description. Kill the ACE sidecar (port 8765) after, before Wan.
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

## The effects grammar (one dictionary, shared)
`app/grammar.py` ↔ `data/effects_dictionary.json` (seeded on first load,
`GET/PUT /api/effects_dictionary`, reset via `POST .../reset`; UI: Settings ·
Effects grammar). The single source of truth for WHICH effect WHEN:
`sfx_cues` (beat→keywords→cue), `transitions` (hook/body rotations +
`by_beat` overrides: reveal→flash, impact→smash, money→punch-in, motion→whip),
`shots` rotation, `music_moods` (tone→query). `beat_of`/`pick_cue`/`mood_for`/
`transitions`/`shots`/`hero_beats` are the lookups. `autodirect` AND `score`
both read it, so a new reflex = one JSON edit (or the `/add-effect` skill), no
code. Every rule keeps a `why`.

2026-07-05 sections: **catalog** (every executable effect name + why — new
transitions: crash zoom, real glitch RGB-tear, drop-in, black flash; all in
`app/transitions.py`), **scene_fx** (beat→letterbox/vignette overlays,
hero-only, `transitions.apply_scene_fx`), **emphasis** (word-level punches:
`autodirect` stores ≤1 phrase/scene — writer `*markup*` beats
number/absolute-word detectors, never two auto-picks back-to-back; one-take
voiceover persists Whisper word times to `audio/words.json`; `assemble`
matches phrase→word time and applies `transitions.apply_emphasis`
zoom_bump/flash_soft/shake_micro + a low tick at the exact spoken word;
`emphasis.sfx` sets cue/volume). Lookups: `emphasis_cfg`/`scene_fx_for`/
`scene_fx_hero_only`.

## Auto-direction (weak-model proofing)
`app/autodirect.py` runs inside `projects.create_project` on EVERY import (the
report lands in `project.direction_report`) and via `POST /api/storyboard/lint`:
- fixes TTS-unsafe narration endings (trailing comma → period; missing → period)
- clears any `on_screen_text` (the no-burned-text rule is absolute)
- fills empty `transition` — a detected beat picks its signature cut
  (`grammar.transition_for_beat`), else the hook/body rotation (hook window =
  first 30 s of estimated narration), never repeating
- fills empty `audio_cue` via `grammar.pick_cue` (hook cuts always carry
  energy), warns on cues that match nothing
- fills `shot` from `grammar.shots()` (drives parallax camera-move variety)
- flags hero scenes (`motion_type: ambient`): scene 1 + the longest scenes,
  budget ≈ scenes/4 capped at 10
- falls back to the flat-cartoon house style when `global_style_suffix` is empty
- lints the viral formula: scene-1 length, hook words/scene, est. runtime
- STORY-FIRST visuals (2026-07-05): warns when a scene's image_prompt shares no
  content word with its narration (stem/compound-aware — "visuals drift" =
  slideshow risk; assisted mode appends "clearly showing <subject>"), auto-fills
  scene `characters` from bible names in the line (continuity via the existing
  prompt-builder), warns when a recurring name has no bible entry
- extracts `*emphasis*` markup (TTS never hears asterisks) / auto-detects one
  punchable phrase; fills `fx` (scene_fx) on hero beat scenes
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
Research-driven since 2026-07-05: `PUT /api/projects/{pid}/research` first
(summary/facts/sources/keywords). `packaging.build` quotes the script's most
specific lines (`_specific_lines`, specificity = numbers+dates+proper nouns),
leads tags with `_entities` (proper-noun phrases + years) + research keywords,
appends a Sources block, and writes `video/recipe.md` (`app/recipe.py`,
`GET /api/projects/{pid}/recipe`) — the per-video ingredients card.
**SEO** `POST /api/projects/{pid}/package {thumb_text?, thumb_template?}`
(`app/packaging.py`): **title options are CURIOSITY-GAP first (hard rule
2026-07-05)** — the cold-open hook + a deterministic reframe of the subject
("The Lie Behind X", "What Happened to X?", marker-picked from the narration)
lead; the literal storyboard title is the fallback (it leads only if it
already contains gap markers). Description with chapters (every ≥25 s), tags =
title phrases + recurring narration bigrams + top words + channel
`seo_keywords` pool (≤470 chars, video-specific terms lead → unique per video
BY CONSTRUCTION), hashtags. Saved to `project.seo`; `PUT .../seo` persists
user edits; the uploader reads the edited copy. Writes
`video/youtube_package.md` too.

**Thumbnails** (`app/thumbs.py`, hard rules 2026-07-05): 5 fixed reusable
templates (spotlight · case-file · reveal · split · bar), ALL rendered to
`video/thumbs/<tpl>.png` per package call + the chosen one copied to
`thumbnail.png` (what the uploader sends). Text is REAL PIL typography
(title fragment ≤5 words + a kicker tag) — never AI-drawn glyphs. **The
EMOTION rule is baked in**: frame pick prefers expressive people on
reveal/impact beats (`grammar.beat_of` + `scenes.scene_has_people`;
author's `video.thumbnail_scene` still wins), and every composite gets a
mood grade — `grammar.mood_for` (same mood the audio scorer hears) →
tint/vignette/saturation + default kicker line from
`data/thumb_templates.json` (`mood_grades`, editable, whys included; default
kickers must be TRUE of any video in the mood). Channel pins its look in
`channel.defaults.thumb {template, accent, kicker ("EXHIBIT No. {n}" — {n} =
stable per-channel serial), font, kicker_font}`.

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
`writer.generate_json(prompt, progress)` is the shared LLM door (roulette
uses it too).

**Channel roulette** (`app/roulette.py`, 2026-07-05): hub card "🎲 Channel
roulette" / `POST /api/roulette/roll {hint?}` (job). Python rolls inspiration
dice (subject × aesthetic × tone from curated automation-friendly lists) →
local LLM invents the full concept (name/niche/brief/style_suffix/voice
instruct/music vibe/topic bank/example titles/SEO pool/accent/thumb template;
`_sanitize` clamps everything, curated fallback concepts if no LLM) → the
brandkit fixed krea2 graph renders a 5-slot identity (profile · banner ·
thumbnail · host · ambiance; `build_graph(only=…)`). Rolls live in
`data/roulette/<rid>/` (concept.json + PNGs + graph.json — drag a PNG into
ComfyUI to remix). `GET /api/roulette` lists; `POST /api/roulette/{rid}/accept
{id?,name?}` creates the real channel (defaults + brand stills + ui accent,
authoring=assisted); `DELETE` moves the roll to `data/trash/roulette/`.
LLM-invented topic banks are IDEAS, not facts — run the research algorithm
before scripting from them.

**Auto-scoring** (`app/score.py` + `app/audiolib.py`): `produce` runs a `score`
stage (before animate, always on). `audiolib` = stdlib-urllib clients for two
free-tier libraries — **Jamendo** `api.jamendo.com/v3.0/tracks` (music; keep
non-NC commercial CC; `fuzzytags`, `vocalinstrumental=instrumental`,
`durationbetween`, popularity order) and **Freesound** `apiv2/search/text`
(SFX; prefer `license:"Creative Commons 0"`; download the free HQ-preview mp3 —
original download needs OAuth2, preview needs only the token). Downloads are
transcoded to wav (beds→`data/music/`, SFX→`data/sfx_library/` tagged by cue)
and logged to `data/audio_library/ledger.json`. `score` derives mood, picks one
bed (Jamendo→ACE-Step→existing), fills every empty `audio_cue` and fetches a
real CC sound for each distinct cue, writes `project.audio_plan`, and collects
CC-BY attribution → `packaging.build` appends a Credits block to the
description. Keys: `settings.audio.{jamendo_client_id,freesound_token}` (free,
pasted in Settings·Audio); keyless ⇒ ACE + procedural synths. Kill the ACE
sidecar (8765) after, before Wan.

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

## 2026-07-10: Autopilot, ref cards, ending tone, GPU lifecycle
- **Autopilot** (`app/pilot.py`): idea in, video out, fully local. Stages:
  interpret (local LLM) > Wikipedia research (`app/webresearch.py`) > script
  (spec + playbook sections as the prompt "skills") > assisted import > ref
  images > produce poll > package. `POST /api/channels/{cid}/autopilot`;
  `GET /api/autopilot/{aid}`. Not a queue job (it waits on queue jobs).
  Writer: Ollama `qwen3:8b` (num_ctx 16384, keep_alive 0, auto-picks an
  installed model if the configured one is missing) > in-process Qwen3-4B.
- **Ref cards** (`app/refcards.py` + `webresearch.fetch_refs`): Wikipedia
  lead images of integral people/items/places, license + credit logged
  (credit auto-joins SEO sources). First-mention mapping per scene, spoken
  word sync from words.json, tilted card + typeset label + pop tick in
  assemble. Overrides: `scene.ref` dict forces, `false` blocks.
- **Ending-aware one-take** (`voiceover.submit_onetake`): last 2-3 scenes
  (10%, min 1, max 3, only when >= 6 scenes) synthesized with a wind-down
  instruct as the tail of the same take, split at a scene boundary so the
  seam sits inside a natural pause. `narration.outro_scenes` records it.
- **GPU lifecycle** (`app/gpu.py`): stage frees inside produce + idle reaper
  (30 s tick, `settings.gpu.idle_unload_min`, default 5). Frees: TTS models,
  Whisper, depth pipe, diffusers pipe, ComfyUI `/free`, ACE sidecar kill.
  Job worker touches activity on start/finish. One-take releases TTS before
  Whisper loads (peak VRAM).
- **Publish**: Post video button previews the auto-attached metadata (saved
  SEO title/description/tags + thumbnail) and can pick any render; backend
  upload already used project.seo and thumbnail.png.

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
