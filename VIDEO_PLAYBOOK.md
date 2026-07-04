# 🎬 THE VIDEO PLAYBOOK — read this before making any video

**This is the pre-flight brief.** It distills every guiding doc in this repo
(`CLAUDE.md`, `.claude/PIPELINE.md`, `storyboard_v3_prompt.md`, the skills, the
memory files, `SYSTEM_FEEDBACK.md`) into one place, and adds the two things that
turn "the app can make a video" into "the app makes a video worth watching": a
**research algorithm** and a **script algorithm**. Read it start to finish, then
build. When something here conflicts with a channel's own brief, the channel wins
on *taste* (niche, tone, look); this playbook wins on *method*.

> **The one rule.** Type a script in → a finished, human-looking YouTube video
> comes out — fully local, one RTX 5060 Ti. **If a viewer or a platform can tell
> it's AI, that's a failure.** Quality first; the "balanced" render profile is the
> speed default, never a quality excuse.

---

## 0. How a video gets made (the fixed order)

Voice comes **first** — never voice scene-by-scene (independent takes sound
stitched). The whole chain, which `POST /api/projects/{pid}/produce` runs in one
call:

```
RESEARCH → SCRIPT → [import into a channel] → auto-direction fills the craft
   → one-take VOICE (+Whisper QA) → storyboard timed AROUND the voice
   → KREA2 images → SCORE audio (bed + SFX) → ANIMATE heroes → ASSEMBLE
   → QA the mp4 → SEO package → (Shorts / Upload)
```

Everything after SCRIPT is automated and self-directing. Your leverage — and
where quality is won or lost — is **research + script + QA**. Spend your effort
there.

---

## 1. THE RESEARCH ALGORITHM (topic → a story worth telling)

A faceless documentary lives or dies on the *story*, not the visuals. Before a
single line is written, do this:

1. **Lock the promise (one sentence).** "By the end the viewer will *know / feel*
   ______." If you can't say it in one sentence, the topic isn't ready — narrow
   it until you can.
2. **Find the single spine.** ONE person, ONE event, ONE question. Never a
   listicle ("5 scams"). The most-watched faceless videos are a single narrative
   arc with a beginning, a turn, and an ending.
3. **Mine for specifics — they are the fuel.** Vague is skippable; specific is
   "wait, *what?*". Gather the **names, exact numbers** (dollar amounts, dates,
   counts, durations), **places**, the **one pivotal decision/moment**, and a
   **sensory detail or two**. A script full of specifics feels researched; one
   full of adjectives feels AI.
4. **Isolate the three load-bearing facts** — everything else is scaffolding:
   - **THE HOOK** — the single most outrageous *true* detail. This becomes the
     cold open (≤12 words). If you don't have a jaw-drop fact, keep researching.
   - **THE TURN** — the reveal that recontextualizes the story ("but it was all…",
     "what nobody knew…"). Placed ~two-thirds in.
   - **THE PAYOFF** — the irony, lesson, or gut-punch that lands the ending.
5. **Build the escalation ladder.** Order the remaining facts so each tops the
   last. Put the **second-best fact at ~60–70%** as a mid-video re-hook (that's
   where viewers drop — re-grab them).
6. **Verify and flag.** Use your own knowledge; if a web tool is available,
   confirm anything you'd stake credibility on and keep the source for the
   description. **Never invent quotes, numbers, or defamatory claims about real
   living people** — soften to "reportedly" or drop it. Flag anything uncertain
   in the handoff notes.
7. **Fit the channel.** Match angle and tone to the channel's brief/topic bank
   (`GET /api/channels/{cid}`): GRIFT *admires the craft*, Autopsy writes a
   *eulogy*, Night Shift is *calm awe*. The same facts get a different voice per
   channel.

**Research output** = promise · spine · the 3 load-bearing facts · the ordered
fact-ladder · any recurring character's fixed look (for the bible). That is the
raw material the script algorithm turns into a storyboard.

---

## 2. THE SCRIPT ALGORITHM (research → storyboard JSON)

The full spec is `storyboard_v3_prompt.md` (paste-ready for any model). As an
executable procedure:

1. **Cold open = scene 1, ≤12 words** — the hook fact, *in medias res*. No
   greeting, no "in this video", no biography. State the impossible thing plainly.
2. **Hook block = scenes 1–8 (first ~30 s), 6–12 words each.** One idea per
   scene, fast cuts. End the block on the question the video will answer.
3. **Escalation body.** Each scene raises the stake. **End scenes on
   mini-cliffhangers** ("But then…", "What they didn't know…"). Drop the
   second-best fact at ~60–70%.
4. **The turn** gets its own scene(s) — let the reveal breathe.
5. **Payoff ending, ≤15 words** — a punchline or callback that gut-punches.
   Never "and that's the story of…", never a summary.
6. **Length.** ~300–320 narration words over 24–30 scenes ≈ 2 min. Scale
   proportionally (~13 scenes/min) for longer videos.
7. **Every phrase is a new visual** (the retention rule) — so one clear,
   *drawable* subject per scene.
8. **Write for the auto-director's ear.** You don't set effects — you write
   language its beat-detector recognizes, and it fires the matching
   transition + sound (the grammar in `data/effects_dictionary.json`):

   | Say a word like…                     | Beat     | You get (transition + SFX)      |
   |--------------------------------------|----------|---------------------------------|
   | fortune, paid, bribe, sold, gold     | money    | punch-in + cash-register ding   |
   | but the truth, secret, actually, twist | reveal | **flash cut** + shimmering riser |
   | crash, arrested, collapse, died, shot | impact  | **smash cut** + deep boom       |
   | raced, fled, chase, escaped, flew    | motion   | whip-pan + whoosh               |

   (Prefer explicit control? Set `audio_cue` / `shot` / `motion_type` per scene —
   they're honored. Or teach a new reflex with the `/add-effect` skill.)
9. **Picture subjects (`image_prompt`).** Physical and specific ("a wooden box
   with a brass crank pushing out a banknote"), never abstract. **No readable
   text/documents** (models draw gibberish), **no real-person likeness**. For
   object/landscape scenes write "empty / deserted / nobody around" **and list no
   characters** — otherwise krea draws phantom people. **Vary framing**
   wide → close → detail across neighbors (this also drives the parallax camera).
10. **Recurring characters → the bible.** One fixed look each (clothes, colors,
    props); reference the name per scene. krea has no IP-Adapter, so identity is
    carried by that fixed descriptor + a per-character seed family — it holds
    well when the description is consistent.
11. **TTS safety.** Every narration line ends with `.` `!` or `?` — **never a
    trailing comma** (it makes the TTS hallucinate a continuation).
12. **Leave `global_style_suffix` empty** — the channel paints its own look on.
13. **Lint before you build:** `POST /api/storyboard/lint {channel, data}` → fix
    every warning. Those warnings ("scene 1 too long", "hook averages >16 words",
    "cue matches nothing") are the difference between a video and a viral one.

---

## 3. THE CAPABILITY MAP (everything you can pull on — use ALL of it)

**Voice** — one-take Qwen3-TTS of the whole script, Whisper-aligned + QA'd. It's
the timing spine every scene is cut to. Always read the QA result.

**Images — Krea2 (the only image model).** Flat cartoon art via ComfyUI, no
download. The *look* comes from the channel's `global_style_suffix`, applied to
every scene (never hardcode a look). Phantom-people are auto-stripped from
people-less scenes. Consistency = character-bible descriptor + seed family.

**Effects grammar** (`data/effects_dictionary.json`, Settings · Effects grammar)
— the editable map of *which effect when*: the per-beat **transitions** (reveal →
flash, impact → smash, money → punch-in, motion → whip-pan) and **SFX cues**, the
**shot rotation**, and the tone → **music mood**. The director and the audio
scorer both read it. Change how videos *feel* by editing this JSON, not code.

**Sound — audio auto-scoring** (`app/score.py`, runs every produce). Reads the
mood, fits **one mood-matched instrumental bed** ducked under the narration, and
puts a **real sound effect on every beat**. Sources: Jamendo (music) + Freesound
(SFX) when free keys are set in **Settings · Audio**, else local ACE-Step
generation + procedural stingers — it always scores, never silent. Any
attribution-required track is auto-credited in the description.

**Motion & auto-editing — this is your "zooms, pans, auto-edit" toolbox:**
- **Wan 2.2 clips** — real ~3 s moving footage on **hero scenes** (the beats a
  viewer must feel). Balanced profile at native 720p.
- **Parallax 2.5D camera moves** — depth-aware moves on *stills* (Depth-Anything
  → GPU warp), so a flat drawing gains real camera motion. The moves, steered by
  each scene's shot/framing hint:
  - `dolly_in` / `dolly_out` = **zoom in / out** (push/close/macro → in;
    wide/establishing/aerial → out)
  - `pan_left` / `pan_right` = **pan** (whip-pan hints)
  - `tilt_up` = **tilt** (tall/tower/rise)
  - `arc` = **orbit sweep**
  Write framing into `shot`/`image_prompt` and you're directing the camera.
- **Ken Burns** — zoom/pan on stills (alternates in/out per scene; never a
  metronome).
- **Coverage knob** — *every phrase always cuts to a fresh moving visual*
  (retention). Coverage only decides which scenes get a real Wan clip vs.
  parallax/Ken Burns: `heroes` (budgeted, default) · `all` (costly) · `none`.
- **Transitions** between every scene, chosen by the grammar (§3 above).

**Assembly presets** (`data/effects_presets.json`): `cinematic` (Wan + parallax +
SFX) · `parallax-slides` (parallax only, no video model) · `dynamic-slides` /
`simple-slides` (Ken Burns). Chosen per channel or at creation.

---

## 4. THE BUILD (exact calls)

1. **Channel** → `GET /api/channels`; make the project inside it (inherits look,
   voice, mood, preset, SEO pool, YouTube account).
2. **Import the script** → `POST /api/projects {channel, text}` (auto-direction
   runs on import), after linting.
3. **Produce everything** → `POST /api/projects/{pid}/produce`; poll
   `GET /api/projects/{pid}/produce` (one target — don't babysit stage jobs).
4. **Re-score audio on demand** → `POST /api/projects/{pid}/score` (Assemble →
   "Score audio"); inspect `project.audio_plan`.
5. **SEO** → `POST /api/projects/{pid}/package` (unique to the video + channel;
   credits auto-appended). Review `project.seo`; `PUT .../seo` to adjust.
6. **Optional** → `POST .../shorts` (vertical hook + payoff), `POST .../upload`
   (channel's own YouTube, **private** by default — never public without a say-so).

Token-thrifty: `produce` + one poll; QA by sampling ~6 frames; read the built-in
one-take QA instead of re-transcribing; read specific scenes from `project.json`
with a one-liner, never the whole file.

---

## 5. THE QUALITY BAR (never ship a video that fails this)

- [ ] **Watched / frame-sampled the actual mp4** — never ship unviewed.
- [ ] **First 30 s**: the hook lands, the edit density is high, the thumbnail
      promise is paid off.
- [ ] **Audio**: narration clear over the ducked bed, no clipping, no dead air
      > 1 s, one-take QA `ok: true`, ≈ −16 LUFS.
- [ ] **No AI tells**: phantom figures, melted hands/faces, gibberish glyphs,
      style drift, robotic pacing. (Motion-QA with **consecutive** frames —
      frame interpolation is banned here because it ghosts flat art into "melt".)
- [ ] **Characters stay on-model** across scenes (same clothes/props/colors).
- [ ] **SEO shipped** with the video, unique to it and the channel's niche.

**Hard-won lessons baked into the pipeline** (from the first full build): TTS can
hallucinate off a trailing comma → the QA gate catches it; the cartoon style
draws phantom people into empty scenes → the people-clause is stripped; one flat
music bed feels cheap → the scorer mood-matches and ducks it; a metronome Ken
Burns reads as a slideshow → moves now vary. If a *new* failure mode shows up,
fix it in the system (director / grammar / scorer / validators), not just in that
one video.

---

## 6. WHERE THE DEEP DETAIL LIVES (index)

| Doc | What it holds |
|-----|---------------|
| `CLAUDE.md` | Standing user rules, the non-negotiable pipeline order, hard rules |
| `.claude/PIPELINE.md` | Deep per-stage reference (why each step sits where it does) |
| `storyboard_v3_prompt.md` | The script spec, paste-ready for any writing model |
| `data/effects_dictionary.json` | The effects grammar (edit to retune feel) |
| `.claude/skills/make-video` | The end-to-end operating checklist (this playbook is its step 0) |
| `.claude/skills/add-effect` | Teach the grammar a new reflex |
| `SYSTEM_FEEDBACK.md` | Build history + what's still worth improving |
| memory: `aaaflow-*` | Channels, audio-scoring, effects-grammar, canonical pipeline |

**Bottom line:** research a real story, write the hook cold and the ending hard,
let the system carry the craft (voice → krea → grammar transitions + scored sound
→ parallax/Wan motion → assembled edit), then QA like a skeptic before it ships.
