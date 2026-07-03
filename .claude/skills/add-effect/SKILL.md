---
name: add-effect
description: >
  Teach AAAFlow's effects grammar a new reflex — a new SFX cue, transition,
  shot, or music-mood rule that the auto-director + audio scorer apply to every
  future video. Invoke when the user says things like "whenever the story does
  X, use sound/transition Y", "make reveals do Z", "add a mood for W", or "the
  videos should always <effect> on <beat>".
---

# Add / edit an effect in the grammar

AAAFlow's deterministic "when to use which effect" decisions live in ONE
editable dictionary: `C:\AAAFlow\data\effects_dictionary.json` (served by
`app/grammar.py`; read by `app/autodirect.py` and `app/score.py` on every
video). Teaching a new reflex is editing this file — not patching a single
project.

## Steps
1. **Read it**: `GET http://127.0.0.1:8000/api/effects_dictionary`.
2. **Find the right section** and add/adjust a rule (first match wins, so order
   the punchiest beats first):
   - **`sfx_cues[]`** — a beat: `{"beat","cue","when":[keywords],"why"}`. `cue`
     text is matched against the SFX library tags / procedural synths, so use an
     existing family (whoosh / impact / riser / ding / kaching / pop) or drop a
     matching wav into `data/sfx_library/`.
   - **`transitions.by_beat`** — `{"reveal":"flash cut", ...}`: the signature cut
     for a detected beat. `transitions.hook` / `.body` are the rotations.
   - **`shots[]`** — the camera-variety rotation (drives parallax moves).
   - **`music_moods[]`** — `{"mood","query","when":[keywords],"why"}`: tone →
     music search/generation query.
3. **Write it back**: `PUT /api/effects_dictionary` with the full (or partial)
   object. Keep every rule's `why` — the dictionary is meant to read like a
   playbook.
4. **Verify** on a real script without producing:
   `POST /api/storyboard/lint {channel, data}` and check the `report.fixes`
   assigned the transition/cue you intended; for mood, the audio scorer picks it
   on the next produce/`POST /api/projects/{pid}/score`.

## Notes
- No server restart needed — the dictionary is read live each video.
- To restore the built-ins: `POST /api/effects_dictionary/reset`.
- Keep it commercial-safe and consistent with the channel's art direction; a
  channel's *look* stays in the channel, but *editing grammar* is global here.
