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

**The effects grammar (2026-07-04; expanded 2026-07-05).** The "which effect
WHEN" choices are NOT hardcoded — they live in one editable dictionary
`data/effects_dictionary.json` (`app/grammar.py`, UI: Settings · Effects
grammar, `GET/PUT /api/effects_dictionary`). It maps a narration **beat**
(money/reveal/impact/motion/small) → the SFX stinger, the transition (reveals
*flash*, impacts *smash*, money *punch-in*), the shot rotation, and the tone →
music mood. BOTH `autodirect.py` and the audio scorer `score.py` read it, so
teaching the system a new reflex is a one-JSON edit (or the `/add-effect`
skill), never a code change. Every rule carries a `why` so it reads like a
playbook. 2026-07-05 additions (user: "add more editing effects, all in a
dictionary"): a **catalog** section lists every effect the assembler can
execute — new transitions *crash zoom*, real *glitch* (RGB tear), *drop-in*,
*black flash* (`app/transitions.py`); **scene_fx** (letterbox on reveals,
vignette on impacts — hero scenes only); and **emphasis** — the director marks
≤1 phrase/scene (writer `*markup*` wins, else number/absolute-word detectors)
and the assembler lands a micro zoom/flash/shake + tick on the exact SPOKEN
word (one-take Whisper word timestamps persist to `audio/words.json`).

**Video production now runs LOCALLY: AUTOPILOT (user, 2026-07-10; supersedes
the 2026-07-04 "Claude drives it" decision).** The user types a video IDEA,
broad or detailed, into the channel Videos page ("Put your video idea here");
`app/pilot.py` does the rest with zero cloud tokens: interpret idea (local
LLM: Ollama `qwen3:8b`, auto-falls back to any installed model, then
in-process Qwen3-4B), Wikipedia research + reference photos, script, assisted
import, produce, SEO. `POST /api/channels/{cid}/autopilot {idea, minutes}`;
poll `GET /api/autopilot/{aid}` (log included). The playbook + spec files ARE
the agent's skills, so improving those docs upgrades both drivers. Claude's
job is improving the SYSTEM, not burning tokens producing videos; the
`/make-video` skill remains for when the user explicitly asks Claude to drive.
(Ollama note: the tray app respawn-loops on this machine; a detached
`ollama serve` works and the writer degrades gracefully without it.)

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
**The generator is VISIBLE + EDITABLE (user, 2026-07-05):** slot prompts/sizes/
seeds live in `data/brandkit_slots.json` (`GET/PUT /api/brandkit_slots`; brand
modal → 🧬 Architecture edits them in-app), and "Open in ComfyUI" /
`POST /api/channels/{cid}/brand/comfy` re-renders the graph from the CURRENT
slots and copies all the channel's graphs into ComfyUI's own workflow library
(`ComfyUI/user/default/workflows/AAAFlow/<cid>_*.json` — sidebar → Workflows).
**Every generated graph AUTO-publishes there** (user: "so I don't have to drag
them"): brand previews, Wan snippet graphs, AND roulette brainstormer rolls
(`brandkit.publish_graph_to_comfy`, called by preview/snippets/roulette).
Menagerie's style_suffix carries an ember-glow infusion distilled from
user-supplied reference channels (2026-07-05); those four looks (ember-glow
dark fable / stickman comic / chibi mascot / parchment history comic) also
joined the roulette aesthetics dice — reference styles enter as PROMPT DNA,
never as LoRA training on other creators' art.
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
   narration"). The take is auto-HUMANIZED before alignment (2026-07-05, "voice
   still sounds AI"): `humanize.polish_wav` runs the mic/room/pacing-jitter
   chain — channel `defaults.voice_humanize` ("natural" default; "off"
   disables; Menagerie retuned with imperfection-heavy instruct). Then Whisper
   aligns every scene to the take, saves word times to `audio/words.json` (the
   emphasis system's clock) and QA-checks the transcript against the script
   (TTS hallucinates; never skip the QA result).
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
   publish manually on YouTube after review). The Publish page's **Post
   video** button (2026-07-10) previews exactly what attaches automatically
   (saved SEO title, description, tags, thumbnail) and can pick any render.
   Thumbnails MAY carry text —
   the no-text rule is only about frames inside the video.

One call runs 2→7: `POST /api/projects/{pid}/produce` (UI: Assemble →
"Produce everything"); poll `GET /api/projects/{pid}/produce`.

**Long videos (11-20 min) are supported**: >40 scenes auto-switches the
assembler to SEGMENTED mode (parts of ~24 scenes, NVENC-encoded, lossless
concat, one audio-mix mux) — flat memory, ~linear time. Scripts >650 words
get a TTS-drift lint warning; spot-check the one-take QA extra carefully.

## Hard rules
- **NO on-screen text is ever burned into the video.** Narration + visuals
  carry it. (The assembler no longer composites captions at all.) Exception
  (user, 2026-07-05): REAL article/document screenshots as evidence stills are
  a documentary technique, not burned text — attach via scene `image_file` +
  `image_locked: true` (batch regen skips locked scenes; playwright MCP in
  `.mcp.json` captures them into `<project>/research/`).
- **Visuals are STORY-FIRST, never slideshow (user, 2026-07-05).** Every
  scene's picture must SHOW what its line SAYS (sound-off test). The
  auto-director warns on zero subject overlap ("visuals drift"), repairs in
  assisted mode, and auto-fills scene `characters` from the bible so the
  recurring cast stays on-model. Spec carries matching clarity rules (one idea
  per scene, cause→effect connectors, re-anchor names, signpost time jumps).
- **Thumbnails carry EMOTION + HIGH VARIANCE (user rules, 2026-07-05).**
  `app/thumbs.py` composites every thumbnail from 7 reusable templates
  (spotlight/case-file/reveal/split/bar/poster/big-word) with REAL typeset
  text — never AI-drawn glyphs. The emotion rule is pipeline-enforced: frame
  pick prefers expressive people on reveal/impact beats, and a mood grade
  (`grammar.mood_for`) tints color/vignette and picks the kicker
  (`data/thumb_templates.json`, editable). VARIANCE is the default: when a
  channel pins no template, the pool rotates per video (pid-seeded), never
  repeating the previous video's pick; kickers draw from channel
  `kicker_pool` + mood lines and sometimes drop entirely. Serial-number
  kickers ("EXHIBIT No. {n}") are dead — Menagerie's pin removed; roulette no
  longer pins templates. Title reframes rotate per video too
  (`packaging._curiosity_titles` pool + seed). All variants land in
  `video/thumbs/`; the chosen one is `thumbnail.png`.
- **Titles open a CURIOSITY GAP, never face value (user rule, 2026-07-05).**
  "He Sold the Eiffel Tower. Twice." not "The Story of Victor Lustig". Rule 0
  in `storyboard_v3_prompt.md` (writers) + `packaging.build` leads its title
  options with the hook + a deterministic curiosity reframe. Kickers/titles
  must still be TRUE — the payoff pays off the promise.
- **Every video ships WITH its SEO — RESEARCH-DRIVEN (user rules 2026-07-03 +
  2026-07-05 "SEO is way too AI").** Save research first
  (`PUT /api/projects/{pid}/research {summary, facts, sources, keywords}`),
  then `POST .../package`: the description QUOTES the video's most specific
  narration lines + a public Sources block (no "The full story of…", no
  "subscribe so…" boilerplate — both removed); tags lead with real entities
  (names/places/years via `packaging._entities`) + research keywords, channel
  pool behind. Review `project.seo`, hand-polish via `PUT .../seo` if it still
  reads AI. Every package also writes `video/recipe.md` — the RECIPE CARD
  (user's chef model): exact ingredients + measurements (script stats,
  direction card, voice+humanize, look, cut/fx/emphasis counts, score plan,
  package, sources). Live JSON: `GET /api/projects/{pid}/recipe`.
- **Direction cards — the anti-factory dial (user, 2026-07-05: "one video
  should be distinguishable from the next; not a factory").** Every video
  draws ONE card (grammar `direction_cards`: cold-fact / in-medias-res /
  object-first / question-first / countdown) that bends hook style, ending
  type, transition-rotation offset, emphasis rotation, and Ken Burns energy.
  Author-set `video.direction_card` wins; the card shows in lint + recipe.
  Same rules every time, different skeleton every video.
- **Every video ships auto-SCORED (user rule, 2026-07-03; amended 2026-07-05
  "procedural SFX sound terrible").** Music bed + SFX placed by `app/score.py`
  on every produce. Stingers must be REAL sounds (Freesound fetch or imported
  wavs) — the big procedural synths (whoosh/boom/riser/kaching/ding) are
  banned; a cue with no real file stays SILENT. Only tiny UI ticks (pop,
  click) may synth. Beds: Jamendo → ACE-Step → existing. Keep the license
  ledger + auto-attribution intact; never a copyrighted track.
- **New editing furniture (user, 2026-07-05).** `edit` is now step 6 in the UI
  (the ffmpeg-led auto-editor): `POST /api/projects/{pid}/autoedit` re-decides
  every call (transitions/cues/shots/emphasis/fx/date chips) from the grammar
  with one click; the plan renders scene-by-scene. **Date chips**: a year/date
  mentioned in narration auto-stamps a small TYPESET date (georgiab) + click
  SFX — the one sanctioned on-screen text besides receipt stills. **Receipt
  move** (`app/receipts.py`): evidence screenshots float in as a tilted card,
  ease-zoom into the referenced region ON the spoken word, marker highlight
  sweeps it (scene `receipt{focus,highlight,sync}`). **Film filters**:
  `filter` on preset/assemble opts — "vhs" (grain/scanlines/chroma fringe/
  tracking wobble, `transitions.apply_filter`) is Menagerie's default via the
  `cinematic-vhs` preset.
- **Cinematic GRADE — the pro "Lumetri" pass (user, 2026-07-06: "make it look
  like it was edited by a professional youtuber, through ffmpeg").** Runs LAST
  over the FINISHED mp4 as ONE ffmpeg `filter_complex` (`app/grade.py`): film
  colour (contrast/gamma/3-way balance) + halation **bloom** + **vignette** +
  fine film **grain**. A POST-process, so it upgrades ANY render WITHOUT a
  re-assemble. Looks live in the effects dictionary (`grammar['grades']`:
  ember / cinematic / noir / warm / soft; `grade_for(mood)` picks by mood,
  channel/preset/`asm.grade` override — **Menagerie = ember**, deepening its
  ember-glow). `POST /api/projects/{pid}/grade {look?}` grades the newest
  render on demand; it also auto-runs as the produce **`grade`** stage (after
  assemble). New transition too: **dip to white** (`_whiteflash`, bright
  reveal bloom) joins the grammar rotation + catalog.
- **YouTube keys live in a git-ignored vault (user, 2026-07-05).**
  `data/secrets/<cid>.json` (`.gitignore`d); `channels.get()` merges them in
  memory, `upsert()` diverts them — channel.json never holds credentials. The
  channel editor carries an idiot-proof connect guide (console links,
  Desktop-app OAuth client, test user).
- **In-app YouTube control center (user, 2026-07-06: "everything I need here,
  no browser").** Connect a channel once (OAuth scope widened to
  `youtube.force-ssl`), then manage it from the **channel editor**: `GET
  /api/channels/{cid}/youtube/channels` (live avatar/banner/stats), `PUT
  .../youtube/branding` (description/keywords/country), `POST .../youtube/banner`
  (upload + set), `PUT .../youtube/video/{video_id}` (edit an uploaded video's
  title/desc/tags/privacy) — plus the existing per-project upload. **HARD API
  LIMITS (Google's, not ours — do NOT try to build around them):** you CANNOT
  create a channel or set the profile picture/avatar via API, and API channel
  RENAMES are usually silently ignored — those stay one-time youtube.com steps.
  Uploads still default **private** (unverified app can't publish public without
  Google's OAuth audit); user chose private → publish manually.
- One art direction per video, sourced from the project's
  `video.global_style_suffix` — never hardcode a look into a pipeline stage.
- Scenes with no people get the style minus its character clause
  (`scenes.scene_has_people`) or the model draws phantom figures.
- Animated clips run AS LONG AS THE SCENE IS ON SCREEN (user rule 2026-07-05:
  "the animation should last as long as the image is shown") — per-scene
  `planned_dur` from the voice alignment, clamped to Wan's sweet range
  2.5–6 s (beyond ~6 s the 14B degrades; longer scenes end on the assembler's
  drifting hold). Motion stays subtle; the project style LEADS every clip
  prompt (animate.py) so Wan animates the drawing, not repaints it.
- Narration lines should end with a period — trailing commas invite TTS to
  keep talking (hallucination).
- **NATURAL FLOW + MONOTONE scripts (user, 2026-07-10: "just be a great
  script writer, don't add personality").** Spec flow rules are law:
  throughline first, context BEFORE event (introduce every person/place at
  first mention), any 20 s stands alone, curiosity gap lives ONLY in the
  title + hook question. The narrator is flat by design: no exclamation
  marks, no hype words, no jokes or asides, pivots stated dry; the last 2-3
  scenes wind down to a quiet close.
- **Ending-aware voice (2026-07-10).** One-take TTS synthesizes the final 2-3
  scenes with a wind-down instruct split at a scene boundary, so the narrator
  audibly settles as the video ends. Default on; channel
  `defaults.voice_outro` = "off" disables, a custom string replaces the
  wording; per-run `voice.outro`.
- **REF CARDS (user, 2026-07-10).** Real photos of the story's integral
  people/items/places are edited in at the narrator's FIRST MENTION,
  word-synced, as a tilted floating card with a typeset name label + soft
  pop. Research fetch: `POST /api/projects/{pid}/research/refs {entities}`
  (Wikipedia lead images into `research/refs/`, license logged, credit
  auto-added to SEO sources); mapping `app/refcards.py`, compositing in
  assemble. Ref cards join date chips + receipt stills as the only sanctioned
  on-screen text. Per-scene: `scene.ref = {file,label,sync}` forces one,
  `ref: false` blocks.
- **No em dashes in ANY new writing (user, 2026-07-10).** Narration, titles,
  SEO copy, docs, UI text, code comments: use commas or periods instead.
  Enforced in code: `autodirect` rewrites em dashes in narration on every
  import (trailing to a period, internal to a comma) because they are an AI
  tell and the TTS stumbles on them; `packaging` no longer joins titles,
  taglines or sources with them.

## Operational rules
- Backend (`app/*.py`) edits: **hot-reload first, restart second** (user rule
  2026-07-05 "make it so it's not that way"). `POST /api/dev/reload
  {"modules": ["assemble", ...]}` swaps pure-logic modules on the LIVE server
  — running jobs keep their code, the next job/request uses the new code.
  `POST /api/dev/call {module, func, kwargs}` runs a brand-new function before
  its endpoint exists. Full restart still needed for: new/changed ROUTES,
  engine singletons (engine/comfy_engine/wan_engine/image_engine/
  music_engine), jobs/produce/config/storage —
  `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
  (log to `data/server.log`), and **never while a job runs**. Bump
  `app.js?v=` in `web/index.html` after frontend changes.
- One GPU: TTS, krea2, Wan, ACE-Step contend. The job queue serializes, but
  the ACE sidecar (port 8765) holds VRAM with no unload API — kill its process
  before Wan work on 16 GB.
- **Models load only when needed and auto-unload (user, 2026-07-10).**
  Engines stay lazy at boot; `app/gpu.py` frees what lingers: stage frees in
  produce (TTS+Whisper after voice, ComfyUI `/free` after the last
  image/animate stage, depth after assemble, ACE kill after score, everything
  at pipeline end) plus an idle reaper (`settings.gpu.idle_unload_min`,
  default 5 min, 0 disables). One-take drops the TTS model before Whisper
  loads. Manual: `GET /api/gpu`, `POST /api/gpu/release`.
- ComfyUI auto-starts from `ComfyUI_windows_portable/`; **run.bat also boots
  ComfyUI + opens both tabs** (user rule 2026-07-05 — that bat is the one
  sanctioned auto-open; Claude still never auto-opens media/browser itself).
  MCPs in `.mcp.json`: **comfyui-mcp** (inspect/drive the live graph at
  :8188) and **playwright** (headless browser — article screenshots/receipts
  for research; first use npx-downloads). Claude's built-in WebSearch/WebFetch
  cover search + article text.
- Projects: `data/channels/<cid>/projects/<pid>/` (`project.json` + audio/
  images/ video/); `data/projects/` is only the legacy/standalone fallback.
  Always resolve paths via `projects.project_dir(pid)` — never build them.
  Long builds keep a `HANDOFF.md` there, updated as stages finish.
- **DATA SAFETY (incident 2026-07-09; safeguards + recovery 2026-07-10).**
  `data/channels/` was wiped outside the app while untangling a failing
  GitHub push (untracked non-ignored files died; ignored + tracked survived;
  the app then silently re-migrated a bare "main"). **Windows Previous
  Versions did NOT save it**: the one VSS snapshot (2026-07-05 11:29) had the
  right file names and sizes but ZEROED data blocks, because freed clusters
  were TRIMmed on the SSD. Renders, narration wavs and project.json were
  unrecoverable; carving would find nothing either. What DID survive was
  text outside `data/`: two storyboards mined out of Claude session
  transcripts (`~/.claude/projects/C--AAAFlow/*.jsonl`) and Sodder's
  141-scene board as `sodder.py` in that session's temp scratchpad. All
  four projects were rebuilt from those and re-produced; the boards are
  archived in `scratchpad/recovered/`.
  **The IMAGES and the WAN CLIPS came back too**: `ComfyUI_windows_portable/`
  is gitignored, so its `output/` cache was untouched, and every artifact
  carries its own graph. Each krea2 PNG embeds the prompt that made it
  (`scratchpad/restore_images.py` matches the prompt prefix to a scene's
  `image_prompt`); each `output/AAAFlow/wan_*.mp4` carries the whole i2v
  graph in its mp4 `prompt` tag, whose positive text is
  "<style>. <scene image_prompt>. <motion suffix>"
  (`scratchpad/restore_clips.py`), and its `LoadImage` start frame still sits
  in `ComfyUI/input/`. Result: 242/242 images + all 36 hero clips recovered
  bit-for-bit, zero GPU. **Always check that cache before re-rendering.**
  The `tools/realesrgan/` binary died in the same wipe (models survived) and
  was re-downloaded; without the exe the enhance chain silently no-ops.
  **Now protected four ways:** (1) git TRACKS what defines the studio —
  `channel.json`, `ui/`, `brand/graphs/`, every `project.json` /
  `source.json` / `HANDOFF.md`, and the effects dictionaries — while media
  (audio/images/video/caches) and `data/secrets/` stay ignored, so
  `git add .` stays small and safe; (2) every channel write snapshots all
  records to `data/channels.backup.json`, and `_migrate` restores from it
  before the legacy merge; (3) every `save_project` mirrors project.json to
  `data/backups/projects/`; (4) session transcripts are the last resort.
  NEVER run `git clean` here without `-n` first, and never `git reset --hard`
  a commit that added data/.
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
