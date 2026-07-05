# AAAFlow Studio

> **Making a video? Read `VIDEO_PLAYBOOK.md` first.** It's the all-in-one
> pre-flight brief — the research algorithm, the script algorithm, the full
> capability map (scored sound, grammar transitions, krea images, parallax
> zoom/pan motion, auto-edit) and the quality bar, distilled from every doc
> here. The `/make-video` skill loads it automatically.

## Mission
**Type a script in → a finished YouTube video comes out.** Fully local, one machine
(RTX 5060 Ti 16 GB), zero cloud. The output must look like it was made by a human
creator — writing, pacing, art direction, editing, sound. If a viewer (or a
platform) can tell it's AI-generated, that's a failure.

**QUALITY, THEN SPEED (user rules, 2026-07-03).** Original mandate: quality
over everything. Amended same day after validating results ("this wan model
is actually doing great… If theres any way to make the production of videos
faster please do everything you can"): **"balanced" is the production
default** — Wan 4-step lightx2v at NATIVE 720p + enhance (~3-4 min/scene),
visually ≈ max on flat art. "max" (20 steps, no speed LoRAs, ~20 min/scene)
is the opt-in flagship profile — never silently substituted either way.
Still always on: enhance sharpening (interpolation OFF — it ghosts), NVENC
cq19 final encodes (x264 crf17 fallback), Real-ESRGAN-sharpened stills.
Never trade visible quality for speed without the user's sign-off.

## Design principle: the SYSTEM carries the intelligence
The pipeline must produce a competent, human-looking video even when the
storyboard came from a small/weak model. Everything that can be decided
deterministically IS: `app/autodirect.py` runs on every import and fills
transitions, SFX cues, shot variety, hero-scene motion flags, style fallback,
and fixes TTS-unsafe punctuation — author-provided fields are never
overwritten. The writing model only has to produce narration lines + picture
subjects following `storyboard_v3_prompt.md` (which carries the viral formula:
≤12-word cold open, 6–12-word hook scenes, escalation, payoff ending).
Validate any storyboard without importing: `POST /api/storyboard/lint`.
When a video underwhelms, improve the template/auto-director/validators —
not just that one video.

**The effects grammar (2026-07-04).** The "which effect WHEN" choices are NOT
hardcoded — they live in one editable dictionary `data/effects_dictionary.json`
(`app/grammar.py`, UI: Settings · Effects grammar, `GET/PUT
/api/effects_dictionary`). It maps a narration **beat** (money/reveal/impact/
motion/small) → the SFX stinger, the transition (reveals *flash*, impacts
*smash*, money *punch-in*), the shot rotation, and the tone → music mood. BOTH
`autodirect.py` and the audio scorer `score.py` read it, so teaching the system
a new reflex is a one-JSON edit (or the `/add-effect` skill), never a code
change. Every rule carries a `why` so it reads like a playbook.

**"Make me a video" is THE entry point (user, 2026-07-04, reaffirmed).** The
user's chosen production method is now **Claude Code (set to Haiku) driving this
system directly** to make videos — NOT the old `Script → JSON` UI flow (that was
the previous way; it's demoted to a per-channel manual import, no longer how
videos get generated). So the durable path is the **`/make-video` skill**
(`.claude/skills/make-video/`): pick channel → get/write script → lint → the
director fills effects from the grammar dictionary → `produce` → QA the mp4 →
SEO. `/add-effect` teaches the grammar a new reflex. Keep the API + skills clean
enough that a small model can run the whole pipeline.

**Hub is channel-first; per-channel tools stay per-channel (user, 2026-07-04).**
`Script → JSON` and `History` are per-channel exclusives — removed from the
GLOBAL hub tool rail/footer (`HUB_TOOL_NAV`), shown only inside a channel
workspace. History lives with its channel; **"main" holds the merged legacy
history**. Never resurface them as app-wide tools.

**Authoring modes (the "Haiku mode", 2026-07-03):** `settings.authoring` is
`"pro"` (fill gaps only, never touch author text) or `"assisted"` (small-model
scripts — the director may also REWRITE structure: trims an overlong cold open
at a clause boundary, splits >26-word multi-sentence scenes into extra cuts,
renumbers). Set per channel default or per project at creation ("Script
author" select). Lint accepts `{channel, authoring}` too.

## Channels (multi-channel operation; re-architected channel-first 2026-07-03)
The user runs SEVERAL YouTube channels off this one machine. **The app opens
on a HUB** — a dashboard of channel cards (+ a "New channel" card); clicking
one enters that channel's own studio (the classic UI, fully scoped: its
videos, its defaults, its uploads). Routes: `#/hub`, `#/ch/<cid>`,
`#/p/<pid>/<step>`. Channels share only the tools (Qwen3-TTS, krea2, Wan,
ACE); everything else is per-channel.

**Each channel is a FOLDER** (`app/channels.py`): `data/channels/<cid>/`
holds `channel.json` (niche, art direction, voice+instruct, preset,
engine/quality/coverage, music vibe, authoring mode, brief + topic bank, SEO
pool, YouTube OAuth), `projects/<pid>/` (ALL its videos live inside it), and
`ui/` — the channel's own UI, meant to be vibe-coded per channel:
`ui.json` `{"accent":"#hex"}` tints the studio, `theme.css` restyles it,
`index.html` replaces it entirely (served at `/ch/<cid>/`, same REST API).
`projects.project_dir(pid)` resolves a pid across every channel folder, so
`/projects/<pid>/…` asset URLs never break. Deleting a channel MOVES its
folder to `data/trash/` (never destroys).

The 5 seed channels were **merged into one channel "main"** (2026-07-03, user
request) — GRIFT's proven defaults, combined topic/SEO pools, the five
originals preserved under `merged_from` (resurrect by copying one into a new
channel; full backup: `data/channels.legacy.json`). Creating a project in a
channel inherits its defaults; creation-time picks override; the storyboard
wins over everything. "Write with AI" / `POST /api/channels/{cid}/write`
(Ollama, else local Qwen3-4B) and the copy-paste script prompt
`GET /api/channels/{cid}/authoring_prompt?topic=...` live on the hub card and
the channel's Videos page. Never bake a channel's look into code — it lives
in the channel's folder.

**Channel impression (`app/brandkit.py`, 2026-07-04).** A FIXED ComfyUI node
graph that renders a channel's whole CORE VIBE — the reference every future video
must match. One krea2 workflow, shared UNET/CLIP/VAE loaders → **ten** branded
outputs grouped as the impression (`_SLOTS`/`_SLOT_META`, `_GROUP_ORDER`):
**Identity** (profile · banner · thumbnail) · **Characters** (host/narrator +
recurring character — how the cast LOOKS, the top vibe anchor) · **Thumbnail
models** (reaction + reveal click templates) · **Ambiance** (wide · detail ·
moment, no-people to avoid phantoms). The channel's `style_suffix` is on every
branch + its `niche` seeds them, so each channel's impression is EXCLUSIVE —
never shared or similar to another's. The modal also shows an **Edit & sound
grammar** panel (preset + transitions + SFX beats + music from the effects
dictionary) so the moving/audio vibe is legible too. Hub card "Brand preview" /
`POST /api/channels/{cid}/preview {seed_offset}` (job) saves the graph to
`data/channels/<cid>/brand/graphs/channel_preview.json` + PNGs to `brand/`;
`GET .../brand` returns `{assets, videos}`, served at `/channels/<cid>/brand/<f>`.
Regenerate = new `seed_offset`; every output PNG embeds the graph (drag into
ComfyUI :8188 to edit nodes). **This is the reusable YouTube-identity template**:
the same fixed architecture fits any channel by reading its `style_suffix`/`niche`.
The identity has a MOVING half too — `POST /api/channels/{cid}/snippets
{keys?,seconds,quality}` animates chosen stills into short Wan 2.2 brand motion
snippets (logo sting from `profile`, teaser from `thumbnail`) via the enhance
chain (`brandkit.submit_snippets`, motion in `_SNIPPET_MOTION`); `GET .../brand`
lists them under `videos`.

**Channel roulette (`app/roulette.py`, 2026-07-05).** Hub card "🎲 Channel
roulette": one button rolls inspiration dice → the local LLM
(`writer.generate_json`; curated fallbacks if none) invents a whole channel
(niche, brief, art direction, voice, music, topic bank, example titles, SEO,
accent, thumb template) → the brandkit graph renders a 5-slot identity to
`data/roulette/<rid>/` (+ the node graph; PNGs drag into ComfyUI). Accept →
real channel folder with brand kit + accent (authoring=assisted); discard →
`data/trash/roulette/`. LLM topic banks are ideas, not facts — research
before scripting. Menagerie voice retuned same day: calm flat-but-prosodic
narrator + calm-dark-ambient `music_vibe` (ACE beds follow it). BOTH node graphs persist to `brand/graphs/` —
`channel_preview.json` (krea2 stills) + `snippet_<key>.json` (Wan i2v, saved via
`wan_engine.animate(save_graph=…)`) — so the whole architecture (image AND video
halves) is inspectable/re-runnable in ComfyUI. The stills graph outputs only
`SaveImage` nodes by design; video is a SEPARATE Wan i2v graph that takes a
finished still as `LoadImage` input. The ComfyUI **MCP** (`.mcp.json`) drives/inspects the
same live :8188 instance — validated 2026-07-04 (health_check sees krea2 + both
Wan i2v 14B fp8; the fixed graph validates clean). Example channel: **The
Midnight Menagerie** (dark-carnival true-macabre, harlequin-noir, clownpierce
clone voice) — full identity (6 stills + snippets) generated as the template.

## THE PIPELINE ORDER (non-negotiable — see .claude/PIPELINE.md for detail)
Voice comes FIRST. Never voice a video scene-by-scene: independent per-scene TTS
generations sound cut-up and out of tone; only prosody *within* a take is good.

1. **Script** — write/receive the full script (spec: `storyboard_v3_prompt.md`).
2. **One-take narration** — the WHOLE script in a single Qwen3-TTS pass:
   `POST /api/projects/{pid}/voiceover/onetake` (UI: Voiceover → "One-take
   narration"). Whisper aligns every scene to the take and QA-checks the
   transcript against the script (TTS hallucinates; never skip the QA result).
3. **Storyboard around the voice** — scene timings come FROM the narration
   alignment. Compose/adjust image prompts, camera hints, audio_cue per scene.
4. **Images** — krea2 via ComfyUI; prompt = scene image_prompt + editable
   global style (`video.global_style_suffix`, clause-deduped). Spot-check
   frames; phantom-people and style drift are the classic failures.
5. **Music / SFX — AUTO-SCORED (`app/score.py`, user rule 2026-07-03).** Every
   produce runs the scorer: it reads the mood (channel `music_vibe` + narration
   tone → dark/tense/money/calm/emotional) and fits ONE mood-matched instrumental
   **bed** ducked under the voice, plus a real **stinger on every beat**. Sources,
   in order: **Jamendo** library (music, commercial-safe CC, `app/audiolib.py`) →
   local **ACE-Step** generation → any existing bed; SFX: **Freesound** (CC0
   preferred) fetched into `data/sfx_library/` → procedural synths. Free API keys
   (Jamendo client_id, Freesound token) live in **Settings · Audio**
   (`settings.audio`); with no keys it still scores via ACE-Step + procedural
   synths (never blocks). Any attribution-required track is auto-credited in the
   SEO description; every download is logged to `data/audio_library/ledger.json`.
   On demand: Assemble → "Score audio" / `POST /api/projects/{pid}/score`.
6. **Animate** — **Wan 2.2 14B** clips (fp8 MoE via ComfyUI; LTX-2 deleted
   2026-07-03), profile "balanced" by default ("max" = flagship opt-in), then
   the **enhance chain** (Real-ESRGAN animevideov3 2x — NO frame
   interpolation, it ghosts flat art). **Every phrase/scene always cuts to a
   fresh moving visual** (retention rule); `coverage` picks which scenes get
   real Wan clips: "heroes" (budgeted; scales to ~16 for long videos) /
   "all" (every scene — ~3.5 min GPU each at balanced; user-configurable
   knowingly) / "none". Engine/quality/coverage/preset chosen per channel or
   at creation.
7. **Assemble** — style preset decides scene motion:
   `cinematic` = Wan clips + 2.5D **parallax** (depth camera moves) + SFX;
   `parallax-slides` = parallax only (no video model); `dynamic-slides` /
   `simple-slides` = Ken Burns. Presets live in `data/effects_presets.json` —
   reusable across all videos, editable, `PUT /api/effects_presets` to save a
   new look.
8. **QA the actual mp4** (frame-sample + loudness) before calling it done.
9. **Publish** (UI: step "8 · Publish") — three parts, all channel-aware:
   **SEO** `POST /api/projects/{pid}/package` (titles, keyword-front-loaded
   description with chapters, tags, thumbnail; saved to `project.seo`, edits
   via `PUT .../seo`; the uploader uses the edited version). **Shorts**
   `POST .../shorts` cuts vertical 9:16 hook + payoff at scene boundaries.
   **Upload** `POST .../upload` sends a render to the channel's own YouTube
   account (per-channel OAuth in the channel editor; defaults to PRIVATE —
   publish manually on YouTube after review). Thumbnails MAY carry text —
   the no-text rule is only about frames inside the video.

One call runs 2→7: `POST /api/projects/{pid}/produce` (UI: Assemble →
"Produce everything"); poll `GET /api/projects/{pid}/produce`.

**Long videos (11-20 min) are supported**: >40 scenes auto-switches the
assembler to SEGMENTED mode (parts of ~24 scenes, NVENC-encoded, lossless
concat, one audio-mix mux) — flat memory, ~linear time. Scripts >650 words
get a TTS-drift lint warning; spot-check the one-take QA extra carefully.

## Hard rules
- **NO on-screen text is ever burned into the video.** Narration + visuals
  carry it. (The assembler no longer composites captions at all.)
- **Thumbnails carry EMOTION and use fixed templates (user rules, 2026-07-05).**
  `app/thumbs.py` composites every thumbnail from 5 reusable templates
  (spotlight/case-file/reveal/split/bar) with REAL typeset text — never
  AI-drawn glyphs. The emotion rule is pipeline-enforced: frame pick prefers
  expressive people on reveal/impact beats, and a mood grade
  (`grammar.mood_for` — same mood the scorer hears) tints color/vignette and
  picks the kicker line (`data/thumb_templates.json`, editable). Channels pin
  template/accent/kicker in `defaults.thumb`. All variants land in
  `video/thumbs/`; the chosen one is `thumbnail.png`.
- **Titles open a CURIOSITY GAP, never face value (user rule, 2026-07-05).**
  "He Sold the Eiffel Tower. Twice." not "The Story of Victor Lustig". Rule 0
  in `storyboard_v3_prompt.md` (writers) + `packaging.build` leads its title
  options with the hook + a deterministic curiosity reframe. Kickers/titles
  must still be TRUE — the payoff pays off the promise.
- **Every video ships WITH its SEO (user rule, 2026-07-03).** Whenever Claude
  makes a video, it must also build the SEO package — and it must be UNIQUE to
  that video and that channel's niche (video-specific phrases lead the tags;
  the channel's `seo_keywords` pool fills behind them; never boilerplate).
  Generate via `POST /api/projects/{pid}/package`, review it like any other
  output, adjust `project.seo` if weak.
- **Every video ships auto-SCORED (user rule, 2026-07-03).** Music bed + SFX
  are placed by `app/score.py` on every produce — never leave a video silent or
  hand-drop tracks. Prefer real royalty-free libraries (Jamendo music, Freesound
  SFX) when keys are set; else ACE-Step + procedural. Keep the license ledger +
  auto-attribution intact (commercial-safe). Free/commercial-royalty-free only —
  never a copyrighted track.
- One art direction per video, sourced from the project's
  `video.global_style_suffix` — never hardcode a look into a pipeline stage.
- Scenes with no people get the style minus its character clause
  (`scenes.scene_has_people`) or the model draws phantom figures.
- Keep animated clips short (~3 s) and subtle; the project style LEADS every
  clip prompt (see animate.py) so Wan animates the drawing, not repaints it.
- Narration lines should end with a period — trailing commas invite TTS to
  keep talking (hallucination).

## Operational rules
- Backend (`app/*.py`) edits need a **full server restart** (no hot-reload):
  `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
  from repo root (log to `data/server.log`). Bump `app.js?v=` in
  `web/index.html` after frontend changes. **Never restart while a job runs.**
- One GPU: TTS, krea2, Wan, ACE-Step contend. The job queue serializes, but
  the ACE sidecar (port 8765) holds VRAM with no unload API — kill its process
  before Wan work on 16 GB.
- ComfyUI auto-starts from `ComfyUI_windows_portable/`. Don't auto-open
  media/browser on the user's machine. A **ComfyUI MCP** is wired in
  `.mcp.json` (`comfyui-mcp` via npx, pointed at `127.0.0.1:8188`) so Claude
  can inspect/drive the live graph; approve it in Claude Code on first use
  (first launch npx-downloads the package).
- Projects: `data/channels/<cid>/projects/<pid>/` (`project.json` + audio/
  images/ video/); `data/projects/` is only the legacy/standalone fallback.
  Always resolve paths via `projects.project_dir(pid)` — never build them.
  Long builds keep a `HANDOFF.md` there, updated as stages finish.
- **Storage is precious** (2026-07-03 purge freed ~100 GB: last LTX remnant,
  training-only raw weights, superseded SDXL/IP-Adapter caches — everything
  re-downloads on demand; see `trainers/weights/README.md`). Disk janitor:
  `GET /api/storage` + `POST /api/storage/clean` (UI: Settings · Storage).
  **krea2 is the ONLY image model** (user decision 2026-07-03: cartoon-rag/
  SD15/FLUX removed from IMAGE_BASES + style-ref pack deleted so nothing can
  re-download multi-GB weights; character sheets now render on krea2 via
  ComfyUI; the diffusers engine remains only for user-imported checkpoints).
  Never leave duplicate multi-GB weights around.

## Claude upkeep rule (user mandate, 2026-07-03)
After ANY user prompt that changes direction, rules, preferences, or adds a
capability: update CLAUDE.md / `.claude/PIPELINE.md` / auto-memory in the same
turn — tersely (a few lines, not essays; don't burn tokens re-writing whole
files). This applies in EVERY chat, current and future. New standing user
decisions belong here; deep process detail belongs in `.claude/PIPELINE.md`;
cross-session facts belong in auto-memory.

## Token-efficient playbook (for Claude)
- Use `produce` + one status poll instead of babysitting stage jobs.
- Poll with `scratchpad/poll.py <job_id>` in background; don't re-poll inline.
- QA by sampling ~6 frames (hook start, one per act, ending), not every scene.
- Whisper-QA is built into one-take voiceover — read its `qa` result instead
  of re-transcribing.
- project.json is large (431-scene boards exist): read specific scenes with a
  python one-liner, never the whole file.

## Quality checklist before calling a video done
- [ ] Watch (or frame-sample) the actual output mp4 — never ship unviewed.
- [ ] First 30 s: hook lands, edit density high, thumbnail promise paid off.
- [ ] Audio: narration clear over ducked music, no clipping, no dead air > 1 s,
      one-take QA `ok: true`.
- [ ] No AI tells: phantom figures, melted hands/faces, gibberish glyphs,
      style drift, robotic pacing.
