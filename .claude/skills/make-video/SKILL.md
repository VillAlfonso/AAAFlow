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

## 6. SEO — every video ships with it (hard rule)
`POST /api/projects/{pid}/package` → unique-to-this-video tags leading, channel
`seo_keywords` behind; description with chapters; the scorer's credits are
appended automatically. Review `project.seo`; adjust via `PUT .../seo` if weak.

## 7. Optional finish
- Shorts: `POST /api/projects/{pid}/shorts` (vertical hook + payoff).
- Upload: `POST /api/projects/{pid}/upload` (the channel's own YouTube account,
  **private** by default — never publish public without the user saying so).

## Report back
Give the user: the channel, the final mp4 path
(`data/channels/<cid>/projects/<pid>/video/final_*.mp4`), duration, what the
scorer chose (mood + bed + #SFX), and the SEO title. If you edited the effects
grammar, say what reflex you taught it.
