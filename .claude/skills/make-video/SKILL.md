---
name: make-video
description: >
  Make a finished YouTube video with the local AAAFlow Studio app end-to-end.
  Invoke whenever the user says "make me a video", "make a video about X",
  "make the next <channel> video", or gives a topic/script to turn into a video.
  Covers picking the channel, getting the script, consulting the effects-grammar
  dictionary, running the produce pipeline, QA'ing the mp4, and building SEO.
---

# Make a video (AAAFlow Studio)

The user runs this app to turn a script into a finished, human-looking YouTube
video, fully locally. When they ask you to "make a video", drive the app's REST
API (base `http://127.0.0.1:8000`).

## 0. Read the playbook FIRST (do not skip)
**Read `C:\AAAFlow\VIDEO_PLAYBOOK.md` in full before doing anything else.** It is
the pre-flight brief — it carries the summarized essence of every guiding doc in
this repo plus the **research algorithm** and the **script algorithm** that make
the difference between "a video" and one worth watching, and the full map of what
the system can do (scored sound, grammar transitions, krea images, parallax
zoom/pan/dolly motion, coverage, auto-edit). `CLAUDE.md` and
`.claude/PIPELINE.md` hold the deeper rules; the playbook points you to them.

## 0b. Preflight
- Make sure the server is up: `GET /api/status` (200). If not, start it (see
  CLAUDE.md · Operational rules) and log to a fresh `data/serverN.log`. **Never
  restart while a job runs.** ComfyUI auto-starts on the first render.
- **Never restart mid-job**; the single GPU serializes work.

## 1. Pick the channel
Everything (look, narrator voice, editing preset, music mood, authoring mode,
SEO pool, YouTube account) is inherited from a **channel**.
- `GET /api/channels`. If the user named one, use its `id`. If not, use the one
  they were last in / the obvious fit, and say which you picked.
- Projects created in a channel land in `data/channels/<cid>/projects/<pid>/`.

## 1b. RESEARCH the story before writing (real facts + receipts)
The topic bank gives ideas, not facts. Before scripting a true story:
- **WebSearch/WebFetch** 2–3 solid sources (Wikipedia, contemporary news,
  archives); pull the exact names, dates, amounts, and the one detail nobody
  explains. Wrong facts are the fastest way to lose comments-section trust.
- **Receipts (optional but powerful)**: with the **playwright MCP**
  screenshot a real article/archive page per act into `<project>/research/`.
  Capture the QUOTE's position in the same pass (normalized rect for the
  receipt move):
  `browser_evaluate: () => { const el = [...document.querySelectorAll('p,h1,h2,li')]
  .find(e => e.textContent.includes("THE QUOTE")); const r = el.getBoundingClientRect();
  return {x: r.x/innerWidth, y: r.y/innerHeight, w: r.width/innerWidth,
  h: r.height/innerHeight}; }` then a viewport screenshot.
- **Attach with the RECEIPT MOVE** (floating card → word-synced zoom →
  animated highlight, `app/receipts.py`): copy the shot to
  `images/scene_XXXX.png`, then `PATCH /api/projects/{pid}/scenes/{sid}
  {"image_file": "images/scene_XXXX.png", "image_locked": true,
  "receipt": {"focus": [x,y,w,h], "highlight": [x,y,w,h],
  "sync": "the phrase the narrator says"}}` — the zoom fires on the SPOKEN
  word (words.json timing). Omit `receipt` for a plain locked still.
  Real documents on screen are a documentary technique, not burned-in text;
  narrate over them ("this is the actual telegram").
- **REFERENCE IMAGES (2026-07-10, do this for every true story):** after the
  project exists, fetch real photos of the 2-5 integral references — the
  people involved first, then a key place/item:
  `POST /api/projects/{pid}/research/refs {"entities": [{"label": "Victor
  Lustig", "kind": "person"}]}` (Wikipedia lead image, license auto-recorded,
  credit auto-added to the SEO Sources). The assembler edits each photo in as
  a floating REF CARD exactly when the narrator FIRST says that name
  (word-synced). Per-scene override: `scene.ref = {file, label, sync}`;
  `ref: false` blocks a card on that scene.

## 2. Get the script (voice comes FIRST in the pipeline, but the script is step 1)
Pick whichever fits what the user gave you:
- **Topic only** → let the channel write it locally:
  `POST /api/channels/{cid}/write {"topic": "..."}` (Ollama or in-process
  Qwen3-4B), which imports through the auto-director. OR write it yourself
  following `C:\AAAFlow\storyboard_v3_prompt.md` (≤12-word cold open, 6–12-word
  hook scenes, escalation, payoff) and `POST /api/projects {channel, text}`.
- **A script / storyboard JSON** → import it: `POST /api/projects {channel, text}`
  or the upload form.
- **Always lint first** to see what the director will fill/flag (no import):
  `POST /api/storyboard/lint {channel, data}` → read `report.fixes` + `warnings`.
  Fix `visuals drift` warnings — the picture must SHOW what the line says.
- **NATURAL FLOW + MONOTONE (user rules 2026-07-10, non-negotiable):** write
  the 3-sentence throughline first; context BEFORE event (introduce every
  person/place plainly at first mention); any 20 s must stand alone; the
  curiosity gap lives in the title + hook question, never in comprehension.
  The narrator is FLAT by design: no exclamation marks, no hype words, no
  jokes/asides/personality, no em dashes in narration; pivots stated dry;
  the last 2-3 scenes wind down (the TTS automatically settles its tone on
  them — write copy that suits a quiet close).
- Mark the ONE load-bearing word of a big line with `*asterisks*` — the
  assembler lands a micro zoom/flash + tick exactly on that spoken word
  (word-level Whisper timing). Unmarked lines get a sensible auto-pick.

## 3. Know the effects grammar (this is what makes it look edited)
The auto-director fills transitions, SFX cues, shot variety and hero-motion
flags **from the editable dictionary** `data/effects_dictionary.json`
(`GET /api/effects_dictionary`). It maps a narration **beat** → the stinger, the
transition (reveals *flash*, impacts *smash*, money *punch-in*), and the music
mood. The audio scorer reads the same file.
- If the user wants a specific treatment ("more whooshes", "darker music on the
  ending", "no crossfades"), **edit the dictionary** (`PUT /api/effects_dictionary`
  or use the `/add-effect` skill) so it sticks for this and every future video —
  don't hand-patch one project.

## 4. Produce (one call runs voice → images → score → animate → assemble)
`POST /api/projects/{pid}/produce` then poll `GET /api/projects/{pid}/produce`
(one poll target; don't babysit stage jobs).
- **Voice is one-take** (whole script, single Qwen3-TTS pass) with Whisper
  alignment + QA — **read the QA result**, TTS hallucinates.
- **Audio is auto-scored** (`app/score.py`): a mood-matched bed ducked under the
  voice + a real SFX on every beat. Free keys (Jamendo/Freesound) in
  Settings·Audio make the beds/SFX real; without them it uses ACE-Step +
  procedural synths. Attribution is auto-added to the description.
- Coverage: "heroes" clips are budgeted; every phrase still cuts to a fresh
  visual (parallax/Ken Burns) — the retention rule.

## 5. QA the actual mp4 — never ship unviewed
- Frame-sample ~6 frames (hook start, one per act, ending) — not every scene.
- Check motion with **consecutive** frames (interpolation was banned for
  ghosting/"melt"). Watch for phantom people, melted hands/faces, gibberish
  glyphs, style drift.
- Audio: narration clear over the ducked bed, no clipping, no dead air > 1 s,
  one-take QA `ok: true`, ~−16 LUFS.

## 6. SEO — every video ships with it, RESEARCH-DRIVEN (hard rule)
**First** save your research: `PUT /api/projects/{pid}/research {summary,
facts[], sources[{title,url}], keywords[]}` — then
`POST /api/projects/{pid}/package`. The description quotes the video's own
most specific lines + a public Sources block; tags lead with real entities
(names/places/years) + your research keywords, channel pool behind. Never
ship the old boilerplate style ("The full story of…", "subscribe so…") — if
the result still reads AI, rewrite the description by hand via `PUT .../seo`
in the narrator's voice.

## 7. Optional finish
- Shorts: `POST /api/projects/{pid}/shorts` (vertical hook + payoff).
- Upload: `POST /api/projects/{pid}/upload` (the channel's own YouTube account,
  **private** by default — never publish public without the user saying so).

## Report back
Give the user: the channel, the final mp4 path
(`data/channels/<cid>/projects/<pid>/video/final_*.mp4`), duration, what the
scorer chose (mood + bed + #SFX), and the SEO title. If you edited the effects
grammar, say what reflex you taught it.
