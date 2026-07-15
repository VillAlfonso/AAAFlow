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

## Architecture v2: SKILL-TRAINED CHANNELS (user, 2026-07-12)
The loop: **study → distill → genesis → produce → score.** User names
reference channels; the STUDY INTAKE (`app/study.py`; Data Gatherer page →
"Channel studies" card; `GET/POST /api/studies`, `{sid}/gather {more}`,
DELETE moves to trash) resolves any URL/@handle, ranks the ~300 most recent
long-form uploads by views, saves avatar + banner to `data/studies/<sid>/`,
and runs the top 3-5 videos through the gatherer at dense 1s sampling
("+ samples" honestly widens evidence when rules don't converge; a ranked
30-candidate pool is kept). Claude then STUDIES the packs and writes seven
SKILL PACKS (titles, thumbnails, editing, SEO, script, composition,
narration) into `data/studies/<sid>/skills/` per **`SKILL_PACKS.md`** (repo
root: formats, evidence rules, consumption points; the packs are git-
tracked). Channel genesis from a study + per-channel dictionary overlays +
the scorecard (gather our own render, diff numbers vs editing.json targets)
are the next build phases. DECIDED 2026-07-12: (1) visual style enters as
skills + PROMPT DNA ONLY, no LoRA on reference footage ever (reaffirms
2026-07-05; own/licensed material only, and only if skills prove
insufficient); (2) the no-burned-text rule is AMENDED: typeset Remotion
motion graphics are allowed when the study's editing.json documents the
style uses them (real fonts only, AI glyphs stay banned, existing text
exceptions unchanged); (3) "hyperframes/hypervisor" = Remotion, to be
expanded from overlays into a full motion-graphics scene engine. Analysis
stack: gatherer (deterministic) + local Qwen-VL for bulk shot labels
(musubi's `caption_images_by_qwen_vl.py` is on disk; Ollama when running) +
Claude reads the sheets for deep passes. Narration skill designs a voice,
never clones the reference narrator's. Channels stay inspired-by, never
impersonations.

**2026-07-13 SMARTER-SYSTEM PASS (user: sample video "formulaic, so AI
coded" — root causes fixed, not the one video):**
- **Voice.** `NARRATION_GUARDRAILS` (voiceover.py) is the user's standing
  Never-list (no ad/motivational/DJ tone, no random emphasis, no rushed or
  rising ending) auto-appended to EVERY narration instruct. One-take now
  APPLIES pace: `voice.speed` > channel `defaults.voice_speed` (pitch-safe
  atempo via `audio.retime`, BEFORE humanize/Whisper) and gap levers
  `voice_gap_ms`/`voice_paragraph_gap_ms`. Every channel gets a DESIGNED
  voice at genesis (speaker x instruct x speed x gaps x humanize), never a
  silent default; Qwen3-TTS has only 2 native-EN speakers (Ryan/Aiden) so
  identity comes from the design, or a clone from own/licensed recordings.
  Unruly = Ryan @ speed 1.25, gaps 120/300.
- **Real SFX.** 65 Kenney CC0 sounds imported (curated tags + diegetic/
  non-diegetic class in `data/sfx_library.json`, CC0-logged in the ledger);
  `score._real_sfx_for_cue` counts ANY real source. "riser" still has no
  real file (stays silent) — a free Freesound key in Settings · Audio is
  the unlock.
- **Analyzer v2 (the video eyes).** `app/vlm.py` = local Ollama vision
  client (use `qwen2.5vl:7b`; qwen3-vl force-thinks through its whole token
  budget on structured tasks and Ollama's `format:"json"` returns EMPTY for
  it — both verified). `app/techniques.py` reads a pack's frame sheets →
  per-tile media/text/device rows + aggregate into report.json, and diffs
  them against editable `data/technique_executors.json` to write
  `needs.json` — the machine-readable "what we can't execute yet" list
  (POST `/api/gatherer/{gid}/techniques`). Studies should run it per pack;
  skills/genesis consume the needs manifest.
- **Remotion expanded + FIXED.** Preset libs installed (@remotion/
  transitions/shapes/motion-blur/noise/google-fonts, remotion-animated);
  new comps `SegmentCard` (opaque typeset story card), `KineticTitle`
  (word-by-word emphasis line), `ArrowCallout` (circle+label annotate).
  `render_overlay` NEVER actually worked before: alpha needs
  `--image-format=png`, and durations now ride in as a prop
  (`durationInFrames` via calculateMetadata) so any length renders.
- **Wan 2.2 t2v direct.** t2v experts + t2v lightning LoRAs in config
  (`wan_t2v_ready()`), `wan_engine.generate()` (EmptyHunyuanLatentVideo
  graph), `animate.submit_t2v_visuals` renders EVERY scene as a clip with a
  poster-frame still; channel/project `animate.engine: "t2v"` makes produce
  use it as the images stage (animate stage skipped). The krea2-free path
  the user asked for; i2v remains the default elsewhere.
- **Archival media (top de-AI lever).** `app/archival.py`: Wikimedia
  Commons search (PD/CC0 first, CC BY flagged, NC skipped), download to
  `research/archival/`, `apply_to_scene` locks real paintings/photos/maps
  as full-frame scene art (`image_locked`) + auto-appends the credit line
  to research sources. Routes: GET `/api/archival/search`, POST
  `/api/projects/{pid}/archival {scene,query,pick}`. History channels
  should MIX archival + generated + typeset cards, never 100% one source —
  uniformity is the formula smell.

**2026-07-14 (user):** (1) **AUTO-UPLOAD** — `app/autopub.py` runs on every
produce completion: channels with `auto_upload {enabled, hour, every_days}`
(default ON for new channels; editor has the controls) package if needed and
upload PRIVATE with `publishAt` = the channel's next free slot
(`last_slot` persists on the record). This AMENDS "publish manually": the
user chose scheduled hands-off publishing; private-first stays the safety.
Skips quietly when not connected / already uploaded / no render. (2) Hub
cards show a real **YouTube connected badge** (API exposes
`youtube.connected`; the old card checked `refresh_token` which the API
strips, so the badge NEVER showed — fixed). (3) **LoRA rule AMENDED by the
user** ("train a lora please"): reference footage MAY train Wan style LoRAs
now; copyright risk was disclosed (gray zone, reused-content risk on
monetization); dataset stays shot-aligned 2-4 s clips
(`app/lora_dataset.py` builds it from kept study videos + gatherer shots +
VLM captions into `data/lora_datasets/<name>/`), channels stay inspired-by.
musubi CANNOT train from fp8_scaled weights (docs/wan.md) — training base
must be fp8_e4m3fn (non-scaled) or bf16, low-noise expert first on 16 GB
(`--fp8_base --blocks_to_swap`), result wired via `WAN["extra_loras"]`.
(4) Studies can now `keep_video` (study.py passthrough) for LoRA datasets.
(5) **Fern mission** running: study 20260714-002311-44c2 (@fern-tv, 5 packs
kept) → techniques → skills → genesis (t2v-only channel) → LoRA → sample.
(6) **SFX DISABLED globally** (user: "disable it for now"):
`settings.audio.sfx_enabled=false` silences every stinger/tick in assemble
and skips scorer fetches; music beds unaffected; the 65-sound library stays
for re-enable. (7) **Skills are AI-AGNOSTIC** (SKILL_PACKS.md contract):
plain md+JSON, no tool-specific syntax, INDEX.md entry point — Claude,
Cline or the local pilot must all be able to run them; transcripts are the
primary evidence for script.md (the script skill IS the trained writer).
(8) **Title-vs-thumbnail CONTRAST is required study evidence**: techniques
pass reads thumbnail text/emotion (`techniques.thumbnail` in report.json);
Serious History finding: title carries the CATEGORY, thumb text the
shocking INSTANCE, never repeating (repeats = their weaker videos).
(9) LoRA training infra READY: musubi venv at
`trainers/musubi-tuner/.venv` (torch 2.11 cu128, CUDA ok); ComfyUI
`wan_2.1_vae.safetensors` is musubi-valid; the ComfyUI umt5 fp8_scaled is
NOT (scale_weight tensors = garbage embeddings; official pth downloaded to
`trainers/weights/wan/`); DiT training base = t2v low-noise fp16 (28.6 GB,
on disk) + `--fp8_base`; pip cache purged. (10) **PARALLAX RETIRED**
(user: "looks so ugly"): removed from every preset (`parallax-slides`
preset deleted; cinematic/cinematic-vhs = clips + Ken Burns fallback); the
depth model never loads now; code stays for rollback but nothing calls it.
Replaced by **skill pack #8 camera** (SKILL_PACKS.md): shot-type + motion
vocabulary learned per reference channel (gatherer motion labels x
transcript), with use_when rules + prompt_words feeding Wan motion prompts.
(11) **The iteration loop + SFX necessity rule** are standing (see their
sections/memory): critiques become SYSTEM changes; stingers off globally,
deliberate per-scene use only.

## NO MIRRORS, ANATOMY BACKSTOP (user, 2026-07-15)
Two AI tells the user flagged on the first full render: an **extra hand** on
a figure, and **mirrors reflecting the mannequins wrong**. Fixes:
`config.WAN["negative_motion"]` + the channel `negative_style` now carry
extra-hand/finger/arm and mirror/reflection terms on every render. The
`/compose-scenes` skill LAW 1b makes it a composing rule: never write a
mirror or a reflection (the reflected figure renders broken; avoid "glass"
that could mirror), and a hand close-up names ONE hand doing ONE thing (two
hands in a tight shot is the extra-limb trap). NEVER use mirrors, period.

## NEVER NSFW (user, 2026-07-14 — absolute)
**No nudity, no gore, nothing sexual, nothing disturbing, ever**, in any
channel, any style, any prompt. Enforced in code, not trust:
`config.WAN["negative_safety"]` is force-appended to EVERY render by
`wan_engine._no_text()` alongside the no-text block.
Why it bit us: a real mannequin is a NUDE store dummy with a sculpted face,
so the word "mannequin" pulls Wan toward a bare, uncanny half-human body —
Fathom's scene 4 came back as a nude sculpted-face figure. So: **every
figure in every prompt must be explicitly CLOTHED** (name the garment), and
the negative bans bare skin, sculpted faces, eyebrows/lips and uncanny
realism. If a figure's clothing is not written, the prompt is not finished.

## WAN RENDERS CONTENT, REMOTION RENDERS TEXT (user, 2026-07-14)
A Wan clip came back with gibberish glyphs burned across the mannequin
("It'ss.s: st or V:idally"). The rule is now absolute and enforced in code:

- **The video models NEVER draw text.** `config.WAN["negative_text"]` (text,
  letters, captions, subtitles, watermark, logo, signage, gibberish text…)
  is force-appended to EVERY Wan render by `wan_engine._no_text()`. No
  channel, preset or storyboard can opt out.
- **GLYPH GUARD** (`animate._has_glyphs`): after each t2v clip, a frame goes
  to the local VLM ("any visible text? YES/NO"); a YES re-rolls the seed
  (2 retries). Needed because a LoRA trained on caption-heavy reference
  footage carries a LEARNED prior toward glyphs — the negative prompt alone
  is not proof. Degrades to a no-op if no VLM is running.
- **All legitimate on-screen text is TYPESET BY REMOTION** from the SAME
  storyboard JSON: name/role tags (RefCard), date + location stamps
  (DateChip), chapter cards (SegmentCard), annotations (ArrowCallout),
  emphasis lines (KineticTitle). Real fonts only; AI glyphs stay banned.
  Enable per render with assemble opts `{"overlay_engine": "remotion"}`.
- **THE ANALYZER'S FIRST VERDICT (2026-07-15): fern is an EVIDENCE channel,
  not a reconstruction channel.** Measured over 584 shots read against their
  narration: archival-video 23%, screenshots 22%, documents 18%,
  **3D mannequin reconstruction only 16%**, archival photos 7%, talking
  heads 5%. And the pictures rarely depict the line: evidence 35%, context
  33%, **literal only 19%**, metaphor 13%. Their arc: fastest cutting in the
  OPENING (16-21 cuts/min, screenshots + archival, metaphor/evidence), a
  SLOWER middle (12-14, context up to 57% — where the mannequins actually
  live, building a world), 2-4 LONG HOLDS of 20-41 s on uncut evidence, then
  a close that returns to context + evidence and is almost never literal.
  **We had built a 100% mannequin channel — copying the most distinctive 16%
  and discarding the 84% that carries the documentary weight.** That is why
  it read as hollow. Every channel's `composition.md` must now be DISTILLED
  FROM THIS ANALYSIS (see `data/studies/*/skills/composition.md`), never
  guessed from frame sheets. Our media budget mirrors it within what we can
  lawfully source: documents+screenshots ~40% (playwright on PUBLIC records +
  `receipts.py`), archival ~20% (`archival.py`: Wikimedia PD/CC + US
  government works), reconstruction ~25% (Wan + LoRA, reserved for the middle
  and the unfilmable), typeset/maps ~15% (Remotion). We do NOT auto-scrape
  the copyrighted news footage fern uses under fair-use commentary.
- **THE TRUE VIDEO ANALYZER** (`app/composer_analysis.py`, user 2026-07-14:
  "study the scene, see how the youtuber draws and presents the information
  whilst taking into account what the narrator says… and analyze the video
  as a whole, how they all connect, reading between the lines"). The
  gatherer measures WHAT is on screen; this asks **why**. PASS 1 pairs every
  shot with the EXACT narration spoken over it (segment times x shot
  boundaries) and reads frame + line together in the VLM, recording
  `depicts / device / relation (literal|evidence|metaphor|context|reaction|
  transition) / framing / why`, and aggregating the **`line_kind_to_picture`
  lookup** (what a number-claim gets shown, what a date gets, what an
  abstraction gets). PASS 2 hands the ordered record to any model
  (AI-agnostic prompt + record) which returns the ARCHITECTURE: acts,
  opening/closing strategy, recurring spaces + characters, callbacks
  (setup->payoff), literal-vs-metaphor rhythm, and **`rules_for_composer`**.
  The composition SKILL is distilled from this, never hand-guessed from
  frame sheets. Routes: `POST /api/gatherer/{gid}/composition`,
  `GET/POST .../composition/synthesis`. Needs the study's `keep_video`.
- **THE OVERLAY DIRECTOR decides WHERE text belongs** (`app/overlays.py`,
  user 2026-07-14: "a system should be able to read the source.json and
  determine where remotion comes in"). It runs inside `autodirect.direct()`
  on every import (and on demand: `POST /api/projects/{pid}/overlays`),
  reads each scene's narration + the project research, and writes
  `scene["overlays"] = [{comp, props, sync, seconds, detector}]` — the
  assembler composites them, landing each on its SPOKEN word via
  words.json. Detectors: full dates/clock times, City+State locations
  (merged into one stamp when both are in a line), first-mention person
  name+role tags (labels mined from research), chapter cards on signposted
  time jumps, `*starred*` emphasis, author callouts. The whole vocabulary
  + gating lives in **`data/overlay_rules.json`** (`GET/PUT
  /api/overlay_rules`, every rule carries its `why`) — teaching the system
  a new text move is a JSON edit, never a code change. Gating caps typeset
  moments (default ≤55% of scenes, per-detector budgets + min gaps): we
  copy the reference's STAMPS, never their baked-in subtitle track.
  `scene["overlays_locked"]` protects author-set text.

## LoRA CAPTIONS MUST TEACH THE STYLE (user, 2026-07-14)
A style LoRA can only bind a look to words that appear in its captions. Our
first fern pass captioned CONTENT only ("a man at a podium") and would have
taught nothing about the look. Every caption in a dataset now reads:

  `<TRIGGER>, <style clause for that clip's media class>, <content>. <camera>.`

**fern/Fathom TRIGGER = `3d mannequin documentary`** (plain words the T5
encoder already knows, so it steers Wan even at low LoRA strength). Put the
trigger at the FRONT of every caption and into the channel's
`style_suffix`, so generation prompts summon the trained look.

**The fern style DNA (measured, 762 3D-render frames; "mannequin" is the #1
subject word):** faceless matte humanoid MANNEQUIN figures (no faces, no
clothing detail) acting out reconstructions inside stylized 3D
environments; dark low-key lighting with deep shadows; ONE red rim-light /
accent; surveillance framings (REC overlays, thermal, CCTV); miniature
diorama city models; red-on-black data maps; intercut real archival
footage, documents and screenshots. Media-specific style clauses live in
`scratchpad/restyle_captions.py` (`STYLE` map) and the channel's
composition skill.

Practical rules for any future dataset: strip the VLM's boilerplate opener
("The documentary frame is a...") — it teaches nothing and its "document"
substring wrecks keyword matching; label each clip by its OWN media class
(gatherer techniques tiles, shot-id matched) so archival clips are never
captioned as mannequin shots; keep latent caches but ALWAYS rebuild the
text-encoder cache after editing captions.

## The iteration loop (user, 2026-07-14 — how we work from now on)
The user asks for a channel + video → watches it and CRITICIZES it the next
day → Claude translates EVERY critique into SYSTEM changes (skills,
dictionaries, code, docs — never one-off video fixes) → the user generates
again → repeat until the formula is right. Finished videos AUTO-UPLOAD
(app/autopub.py, private-first with scheduled publishAt) once the channel is
connected — connecting is the one manual step per channel (editor → Connect).
Criticism days are the most valuable input this project gets: capture every
point, fix root causes, log what changed.

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
   publish manually on YouTube after review). **Post video = REVIEW, not send
   (user, 2026-07-12: "I changed the thumbnail and title, the upload preview
   did not change").** The upload preview is a LIVE mirror of the SEO card
   (`seoDraft()`), unsaved keystrokes included, badged "unsaved edits"; every
   SEO mutation (save, regenerate, thumbnail pick) redraws it, and the 4 s
   tick never redraws over a dirty draft. Clicking **Post video** opens a
   *Review before posting* modal (nothing is sent yet): the exact payload,
   still editable (title, description, tags, thumbnail variant strip, render,
   privacy, publish-at). Its one button SAVES the SEO, then uploads, so the
   live video and the app can't disagree. Thumbnails MAY carry text —
   the no-text rule is only about frames inside the video.

One call runs 2→7: `POST /api/projects/{pid}/produce` (UI: Assemble →
"Produce everything"); poll `GET /api/projects/{pid}/produce`.

**Long videos (11-20 min) are supported**: >24 scenes auto-switches the
assembler to SEGMENTED mode (parts of ~18 scenes, NVENC-encoded, lossless
concat, one audio-mix mux) — flat memory, ~linear time. Scripts >650 words
get a TTS-drift lint warning; spot-check the one-take QA extra carefully.
**Parts encode IN PARALLEL (user, 2026-07-10: "assemble is so slow")**: 3
spawned worker processes compose+encode parts concurrently (the moviepy
per-frame loop is the bottleneck, so this is the ~2-3x lever); a parallax
pre-pass runs in the parent so workers never load the depth model; any pool
failure falls back to the sequential path automatically. Assemble-opt knobs:
`parallel_parts` (0 disables), `segment_scenes`, `segment_threshold`. NVENC
preset p5 (cq19 unchanged).

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
- **Music bed auto-scored; SFX are NECESSITY-ONLY (user, 2026-07-14,
  supersedes the 2026-07-03 every-beat stingers).** Beds keep auto-scoring
  (Jamendo → ACE-Step → existing). Stingers/ticks are globally OFF
  (`settings.audio.sfx_enabled=false`) and, when used at all, are DELIBERATE:
  a sound goes in only when that moment in the video needs it and it makes
  sense; sounds acquired for one video join `data/sfx_library/` for reuse;
  a sound existing in the library NEVER obligates its use. When SFX are
  re-enabled, they stay opt-in per scene (explicit audio_cue with a real
  file), not grammar-automatic. Real sounds only, procedural synths stay
  banned; license ledger + auto-attribution stay intact.
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
  Desktop-app OAuth client, test user). `channels._write` splits secrets
  itself too (belt, 2026-07-11: a pre-vault menagerie record in commit
  452c403 tripped GitHub push protection; the unpushed history was scrubbed
  in place with filter-branch, nothing reached GitHub).
- **SCHEDULED POSTS + the 1440p bitrate trick (user, 2026-07-10).** The
  Publish page has a "Goes public" datetime: the upload goes up PRIVATE with
  YouTube `publishAt`, and YouTube itself flips it public at that moment
  (needs the OAuth app verified to stick; until then it may stay private).
  The chosen time persists as `seo.publish_at` and shows as a "goes live"
  chip on every upload row. Quality: uploads default to a cached **1440p
  master** (`youtube._youtube_master`, lanczos + NVENC cq16) because YouTube
  starves 1080p uploads of bitrate; 1440p lands in a better codec tier.
  `master: false` uploads the original. The channel Videos page opens with a
  **channel preview** (brand banner + avatar + live YouTube stats + all
  videos as thumbnail cards). Custom thumbnails 403 until the channel is
  phone-verified (youtube.com/verify on ANY device incl. the phone, signed in
  as the channel's Google account, SMS code; one time, a CHANNEL feature, not
  app verification, and nothing the app can do on the user's behalf — the
  Publish page links it); every upload row records `thumbnail: set/failed` with a
  Retry button (`POST /api/projects/{pid}/youtube/thumbnail`). Right after
  an upload YouTube serves a low-res encode; the sharp 1440p tier appears
  when processing finishes. Uploads send `seo.titles[0]` as the title;
  re-packaging AFTER an upload rewrites the SEO, so every upload row also
  carries **⟳ Sync SEO** (`POST /api/projects/{pid}/youtube/sync`,
  `youtube.sync_seo`) that pushes the saved title/description/tags onto the
  live video (2026-07-12, user: "what I set up didn't match what uploaded").
  The Publish page is LIVE (2026-07-12, user: "real time ajax"): a 4 s tick
  watches the project's jobs and refreshes every card (upload stage/% shows
  even when started elsewhere), and upload rows show YouTube-side TRUTH from
  `GET /api/projects/{pid}/youtube/status` (`youtube.video_status`, one
  batched videos.list, ~20 s cache): live title with a drift flag vs saved
  SEO, privacy, ⏳ processing vs ✓ processed, 🗑 removed-on-YouTube. Redraws
  never clobber a card the user is interacting with.
  Pre-2026-07-10 uploads were plain 1080p and stay bitrate-starved forever;
  the only fix is re-upload (the master path is now the default).
- **APP-LEVEL OAuth (user, 2026-07-10: "publish this as an app").** The
  studio's own Google client lives in `data/secrets/app_oauth.json`
  (gitignored); every channel without its own creds inherits it in
  `channels._merge_secrets`, so connecting a channel is ONE Connect click,
  no client id/secret fields needed. Per-channel creds still win if set.
  NOTE: switching clients invalidates old refresh tokens; menagerie's vault
  was reset (backup `.oldclient.bak`) and must be reconnected once.
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
- **The style suffix is a LOOK, never a CAST (user, 2026-07-14: "why are
  there other mannequins standing behind the teenager").** It is appended to
  EVERY scene, so a subject noun inside it is silently requested in every
  shot — Fathom's suffix said "mannequin FIGURES" (plural) and Wan drew
  extras behind the one character. Style suffix = trigger + render style +
  environment + lighting + grade + texture ONLY. The cast belongs in the
  scene prompt, single-subject scenes say "alone, nobody else present", and
  prompts compose via `scenes.merge_style(subject, style)` so the SUBJECT
  LEADS and clauses dedupe (the t2v path used a naive join and repeated the
  trigger). Phantom-cast negatives live in `WAN["negative_motion"]`. The
  `/compose-scenes` skill is the full rulebook (also: name the real people
  and brands, mannequins DO the verb, rotate scale — a bland prompt is why a
  video reads as generic).
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
- **THE VIDEO ENDS, never stops (user, 2026-07-10 evening).** The one-take
  gives the LAST scene +0.8 s tail room (the falling cadence breathes), the
  assembler fades the final scene to black (`end_fade`, 1.2 s) into a short
  black tail (`end_pad`, 1.0 s), and ALL audio eases to silence over it.
  Presets/opts can override; Shorts windows keep their hard out. Menagerie's
  narrator is the "keeper v2" design voice (clownpierce character + the
  user's documentary delivery template, incl. the conclusive final cadence);
  the channel `voice_instruct` carries the begin-curious / settle / soften-
  at-the-end performance arc.
- **SFX/transitions belong to the SPOKEN line (user, 2026-07-10: "don't
  randomly put effects where they don't belong").** Beats are detected from
  narration ONLY (never the image prompt), auto stingers keep
  `sfx_gating.min_gap_scenes` (default 2) of air, signature cuts fire only
  on real beats. The `/edit-craft` skill is the composer rulebook (ref cards
  at first mention, date pops, receipts, ending, overlay engines).
- **SEO gets an LLM pass (user, 2026-07-10: "way too formulaic").**
  `packaging._llm_polish` rewrites titles + the description opening with the
  local LLM (Ollama only, never the in-process model mid-pipeline), grounded
  strictly in the narration; chapters/Sources/Credits/hashtags stay
  deterministic and re-attach verbatim; silent fallback to the deterministic
  kit. Thumbnails: text panels avoid the face (warm-tone mass picks the
  quiet side; case-file = narrow corner column + scrim), big-word centers
  its top line, kickers come ONLY from a channel's own `kicker_pool`
  (built-in mood lines like "STRANGER THAN IT SEEMS" are dead;
  `thumb.kicker: "off"` kills even the pool), REGENERATE rotates to the
  next template, a no-text "plain" variant always renders, and the Publish
  page shows every variant as a click-to-choose strip
  (`POST /api/projects/{pid}/thumbnail`). UI surfaces (user, 2026-07-10:
  "I don't even see the webscraping thing"): Edit page = Reference images
  card (manual fetch + first-mention scene mapping; date chips show as
  badges in the plan table); Assemble page = Overlays select
  (built-in | remotion).
- **Remotion overlay engine (optional).** `tools/remotion/` +
  `app/remotion_engine.py` render spring-animated RefCard/DateChip as
  transparent webm; enable via assemble opts `{"overlay_engine":
  "remotion"}`; PIL overlays remain the default and the silent fallback.
  ("hyperframes" is not a known package; Remotion fills that role.)
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
- **Data Gatherer page (2026-07-12, user: integrate AAADataGatherer).**
  Tool-rail 📥 Data Gatherer (hub + channel): paste YouTube links, each
  becomes an EVIDENCE PACK under `data/gatherer/<gid>/`: report.md (paste
  into any Claude: transcript with word-level pauses, shot/cut timeline with
  motion labels, loudness, SEO + engagement signals), report.json, labeled
  frame sheets, pack.pdf (report + sheets, attachable). `app/gatherer.py`
  (hot-reload safe); jobs run as kind "gather" through the shared queue, so
  Whisper serializes with GPU work, shows on the Queue page, cancels
  cleanly. Whisper model chosen per run (large-v3 default; cache shared at
  `models/whisper/`, auto-unloads after the batch and in `gpu.release_all`).
  API: `GET/POST /api/gatherer`, `{gid}/cancel`, `DELETE {gid}`,
  `{gid}/file/{name}`, `/api/gatherer/prompt`. `RULE_EXTRACTION_PROMPT.md`
  (repo root; "Copy rule-extraction prompt" button) turns 5-15 packs into
  numeric style rules for the studio. The standalone `AAADataGatherer/` app
  (port 8765, which `gpu.kill_ace` shoots on sight) is SUPERSEDED and
  gitignored; its packs + its 2.9 GB large-v3 cache were migrated in.
- **Queue page**: tool-rail 🗂 Queue lists every job, produce pipeline and
  autopilot run (`GET /api/queue`) with cancel buttons — check it before
  wondering why a button seems stuck. Cancel feedback is instant
  (2026-07-12): the button flips to "cancelling…" and `service.queue_snapshot`
  reports display-only `cancelling`/`stopping` states until the job's next
  checkpoint actually stops it. Start the server DETACHED
  (`Start-Process`), never as a Claude-Code background child: background
  children die when the CC process restarts (that is what killed the
  2026-07-10 re-voice pass mid-take).
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

## Honesty rule (user mandate, 2026-07-12)
The `/reality-check` skill is STANDING behavior: on any big/vague/pivot
prompt, give an honest scoping pass first (restate the ask, split
exists/new/ambiguous, correct misconceptions plainly, name conflicts with
standing rules, state real constraints with numbers, recommend the v1 cut,
ask only blocking questions). The user prefers correction over agreement;
never silently absorb scope or build a version you know is broken.

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
