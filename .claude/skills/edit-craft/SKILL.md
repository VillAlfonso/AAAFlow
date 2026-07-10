---
name: edit-craft
description: >
  The composer/editor rulebook for AAAFlow videos: WHERE effects belong (and
  where they don't), how researched reference images get edited in at the
  narrator's first mention, the date text pop, receipts, the ending fade, and
  the optional Remotion overlay engine. Invoke when working on the Edit step,
  placing SFX/transitions, wiring ref images into scenes, or tuning how a
  video is cut.
---

# Edit craft (the composer's rulebook)

The edit is decided by the grammar (`data/effects_dictionary.json`) and
executed by `autodirect` + `assemble`. These are the WHEN rules; break them
and the video reads as random.

## 1. Effects belong to what is SPOKEN, nowhere else
- The beat detector runs on the NARRATION only, never the image prompt (a
  burning-house picture must not smash-cut a calm line).
- Stingers need air: at most one auto SFX per `sfx_gating.min_gap_scenes`
  (default 2). Silence between stingers is what makes the next one land.
- A cue with no real sound file stays silent (procedural big synths are
  banned; only tiny UI ticks like pop/click may synth).
- Signature transitions (flash, smash, punch-in, crash zoom) fire ONLY on a
  detected beat; non-beat scenes rotate the calm hook/body sets and never
  repeat back to back.
- Scene FX (letterbox, vignette) only on hero scenes with a real beat.
- If a video needs a different feel, edit the DICTIONARY
  (`PUT /api/effects_dictionary`, or `/add-effect`), never one project.

## 2. Reference images: first-mention cards (the webscraper's payoff)
When research fetched a photo of a person/place/item
(`POST /api/projects/{pid}/research/refs`, manifest `research/refs.json`):
- The card composites in EXACTLY when the narrator FIRST says that name,
  word-synced via `audio/words.json` (`app/refcards.py` plans first-mention
  scenes; the assembler lands the card on the spoken word with a soft pop).
- One card per scene max; receipt scenes never get one; scenes with
  `ref: false` are skipped; `scene.ref = {file, label, sync}` forces one.
- The look: tilted polaroid, typeset name label, gentle float, fade out.
  Same sanctioned-text family as date chips (real fonts only).

## 3. Dates always pop text
A spoken year/date stamps a typeset DATE CHIP (georgiab + gold underline +
click) low-left, styled to the channel vibe. Auto-detected on new years only,
never two scenes running; `scene.date_chip` overrides. This plus ref cards
plus receipt stills are the ONLY on-screen text, ever.

## 4. Receipts (documents) vs ref cards (photos)
- A real article/document screenshot = RECEIPT: full-scene floating card
  with word-synced zoom + marker highlight (`scene.receipt{focus,highlight,
  sync}` + `image_file` + `image_locked`).
- A photo of a person/thing = REF CARD overlay; the scene keeps its own art.

## 5. The ending must END
- The narrator's take winds down on the last 2-3 scenes (ending-aware TTS).
- The final scene fades to black (`end_fade`, default 1.2 s) into a short
  black tail (`end_pad`, default 1.0 s) while ALL audio eases to silence.
  Presets can override both; Shorts windows keep their hard out.

## 6. Overlay engines
- DEFAULT: the built-in PIL/moviepy overlays (fast, no dependencies).
- OPTIONAL: Remotion (`tools/remotion/`, `app/remotion_engine.py`) renders
  spring-animated RefCard/DateChip as transparent webm; enable with assemble
  opts `{"overlay_engine": "remotion"}`. It degrades silently to PIL if node
  or the render fails. Preview/edit compositions: `npm run studio` in
  tools/remotion. ("hyperframes" is not a known package; Remotion fills that
  role here. If the user means a specific tool, ask for a link.)

## 7. QA the edit like a human
Watch the first 30 s and one act boundary: every effect should feel CAUSED by
the line it lands on. If you can't say why an effect is there, it shouldn't
be. Fix the rule in the dictionary, not the symptom in the project.
