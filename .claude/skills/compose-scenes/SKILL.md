---
name: compose-scenes
description: Write image prompts that are specific, recognizable and varied, so a video never reads as generic AI slop. Load before writing or reviewing any storyboard's image_prompts.
---

# Composing scenes (the anti-boring rulebook)

## LAW 0 — READ THE WHOLE SCRIPT FIRST. Compose the VIDEO, not the scene.

User, 2026-07-14: *"direct the composer so that it reads the whole script and
then decides what to do with those scenes, not each scene in isolation."*

Composing scene-by-scene is what produced every failure in this file: a
diorama on scene 2 because it was "the diorama's turn", a SIM card on the
wrong line, 24 of 40 scenes with no character in them, no space the viewer
ever returned to, nothing set up and nothing paid off. Local decisions,
globally incoherent. A slideshow.

**Before writing a single image_prompt, read the entire script and write the
VISUAL PLAN.** It goes in the storyboard as `video.visual_plan`:

```json
{"spine": "the story told in pictures, in three sentences",
 "acts": [{"name": "", "scenes": [1, 10], "function": "", "visual_shift": ""}],
 "cast": [{"name": "", "look": "fixed wardrobe/silhouette, verbatim every time",
           "appears_in": [1, 2, 10]}],
 "world": [{"space": "", "description": "", "scenes": [1, 12, 40]}],
 "motifs": [{"object": "", "meaning": "", "scenes": [4, 27]}],
 "callbacks": [{"setup": 5, "payoff": 9, "what": ""}],
 "media_budget": {"reconstruction": 0.6, "archival": 0.15, "document": 0.1,
                  "map": 0.05, "typeset-card": 0.1},
 "scale_plan": "how framing rotates across the whole video"}
```

Then, and only then, derive each scene's prompt FROM the plan:
its **character** (verbatim look), its **space** (a world entry, not a new
room), its **device** (drawn from the media budget), its **scale** (from the
rhythm plan), doing the **verb of its own line**.

Ask of every scene: *what does this do for the VIDEO?* A shot that only
serves its own sentence and connects to nothing is filler, however pretty.

**The composer is trained on the analyzer.** `app/composer_analysis.py`
reads the reference channel shot by shot WITH the narration spoken over each
shot, and produces `line_kind_to_picture` (what a number-claim gets shown,
what a date gets, what an abstraction gets) plus `rules_for_composer` for the
whole video. Consult those before inventing anything.

User verdict that created this skill (2026-07-14): *"don't make the image
prompt so bland, actually have it be close and recognizable to what the
narrator is saying"* and *"what we are producing right now is boring."*

The failure it names: narration said "Barack Obama's account posts it. Then
Joe Biden's. Then Jeff Bezos and Bill Gates," and the prompt said *"a grid of
glowing screens showing an abstract social feed."* Four of the most
recognizable people alive, rendered as **wallpaper**. That is slideshow
filler, and it is the difference between a video someone watches and one they
scroll past.

## LAW 0b — SHOW THE PROOF, NOT THE PICTURE. (measured, 2026-07-15)

The analyzer read 584 fern shots against the words spoken over each one. The
result rewrites the job:

- Only **19%** of their shots literally depict the line. **35% are EVIDENCE**
  (a document, a screenshot, a record that PROVES the claim) and **33% are
  CONTEXT** (the wider place, time, scale).
- Only **16%** of their screen time is 3D reconstruction. 23% is archival
  video, 22% screenshots, 18% documents.

So the default question is NOT "what does this line show?" — it is
**"what would PROVE this line?"** A narrated event gets a court filing or a
chat log, not a drawing of the event. Reserve reconstruction for what cannot
be filmed or sourced, and for the MIDDLE of the video, where the story is
building a world rather than proving a point.

Before writing any board, read the channel's `composition.json` →
`line_kind_to_picture` (what an event gets, what a person gets, what a number
gets) and honour `our_media_budget`. Composing 40 generated reconstructions
is the single fastest way to make a hollow video.

## LAW 1b — NO MIRRORS, NO REFLECTIONS. And one hand per hand-shot.

Two recurring AI tells the user flagged (2026-07-15):

- **Never write a mirror or a reflection.** "his blank head reflected in the
  glass", "reflected in the mirror", "reflective surface" — the model
  renders the reflected figure wrong (a second, broken mannequin). Banned in
  the prompt AND the negative. If you need to show a figure looking at a
  screen, describe the screen's CONTENT or the figure's posture, never its
  reflection. Avoid "glass" where it could act as a mirror (use "dark
  display case", "monitor", "window with blinds shut").
- **A hand/finger close-up names ONE hand doing ONE thing.** "fingers typing
  on a keyboard WHILE the other hand holds a phone" gave a figure THREE
  hands. Two hands described in a tight shot is the classic extra-limb trap.
  Write "one hand typing on a keyboard, close-up" and let the other hand be
  out of frame. The negative carries extra-hand/finger terms as a backstop.

## LAW 1a — NEVER NSFW. Every figure is explicitly CLOTHED.

Absolute, no exceptions: no nudity, no gore, nothing sexual or disturbing.
The engine force-appends `config.WAN["negative_safety"]` to every render, but
**the prompt must do its half**: name the garment on every figure.

The trap: a real mannequin is a NUDE store dummy with a sculpted face. Write
"a faceless mannequin figure at a desk" and the model happily returns a bare,
skin-toned half-human with eyebrows and lips. Uncanny and unusable — it
happened.

- Write: `a faceless matte grey mannequin figure **in a grey hoodie and jeans**…`
- Never leave a body unclothed by omission. No garment named = prompt not finished.
- Keep the head explicitly blank: "smooth blank head, no face, no facial
  features" — not merely "faceless".

## LAW 1 — Name the thing. Never write the generic noun.

If the line names a person, a company, a place or an object, the picture
shows THAT one, close enough to recognize.

| bland (banned) | specific (do this) |
|---|---|
| "a person at a desk" | "a mannequin in a hoodie hunched at a cluttered bedroom desk, three monitors, energy drink cans" |
| "a grid of screens" | "four mannequins at podiums: one tall in a dark suit, one in aviator sunglasses, one bald in a puffer vest, one in a v-neck sweater and glasses" |
| "abstract network nodes" | "a wall of employee profile photos, red lines connecting three of them" |
| "coins on a table" | "a single physical bitcoin coin, macro, on a scratched phone screen" |
| "a car" | "a black sedan with a lit rideshare windshield sign, rain, night street" |

## LAW 2a — The SUBJECT NOUN is always "mannequin figure". Never a human noun.

Learned the hard way: `"a faceless matte mannequin teenager in a hoodie"`
rendered a **real human boy with a face** — and then a phantom mannequin
standing behind him, because the model could not reconcile the two ideas and
drew both. "Teenager", "boy", "man", "officer", "employee" are powerful human
concepts that overpower the adjective "faceless".

- Write: `a faceless matte mannequin figure in a grey hoodie…`
- Never: `a mannequin teenager`, `a mannequin officer`, `a mannequin worker`.
- Age, role and rank come from PROPS and SETTING (backpack + bedroom = a kid;
  duty vest + cruiser lights = a cop), never from a human noun.
- Back it with negatives: `real human face, facial features, eyes, nose,
  mouth, hair, human skin, photorealistic person, portrait`. Hair and skin are
  the tells that betray a human render.

## LAW 2 — Real people become mannequins with SIGNATURE traits, never faces.

This is the whole reason the mannequin style exists: it lets you stage real,
named people without deepfaking anyone. Recognition comes from silhouette,
hair, wardrobe, props and setting.

- Trump: swept blond hair, dark suit, long red tie, rally podium, flags.
- Obama: tall, slim, dark suit, presidential-style podium.
- Musk: black t-shirt or leather jacket, rocket hangar / car factory.
- Bezos: bald mannequin head, puffer vest.
- Gates: round glasses, v-neck sweater.
- A cop: duty belt, vest, cruiser light spill.

Never write "a face", "a likeness", "a photo of <real person>". The faceless
head IS the ethical and stylistic device. Real people may also appear as
genuine ARCHIVAL photos (app/archival.py) — that is the other sanctioned way.

## LAW 3 — Brands are products and places, never drawn logos.

The video models paint garbled glyphs, and text/logos are banned in the
negative prompt anyway. Show the brand through its unmistakable physical
world:

- Apple -> a minimalist glass storefront, brushed aluminium laptop, white cable.
- Uber -> a sedan with a lit windshield sign, phone map with a car icon.
- Twitter -> a bird-blue interface glow, an open-plan SF office.
- A bank -> marble columns, a vault door.

If a real logo is genuinely needed, Remotion composites a real asset. Wan
never draws it.

## LAW 4 — The mannequin must DO the verb.

The narration's verb is the shot. "He convinced a phone carrier" is not a
person standing near a phone; it is a mannequin mid-call, leaning forward,
one hand raised, papers scattered. Reenactment beats portrait. Static figures
staring at monitors, three scenes running, is how a video dies.

## LAW 5 — Rotate scale and framing. **But LAW 1 always wins.**

Rotation is a tiebreaker among shots that ALL show the line. It is never a
licence to show something else. Applied mechanically it produces exactly the
failure the user caught: narration said *"a seventeen year old is about to
take over the most powerful accounts on the internet"* and the prompt was a
**miniature model house** — because it was "the diorama's turn". Random.

Order of operations, every scene:
1. What does this line SAY? (subject + verb) -> that is the shot.
2. THEN pick the scale/framing that shows it best, preferring one that
   differs from the last two scenes.
3. If no rotation fits the subject, repeat the scale. A repeated scale is a
   blemish; a wrong subject is a broken video.

**After ANY prompt edit, re-run the drift check** (shared content words
between narration and image_prompt, plus your own eyes — metaphors like an
empty press room for "the loudest voices cannot speak" share no words and
are GOOD). Editing project.json directly bypasses the importer's built-in
"visuals drift" lint, so the check is on you.

## LAW 5b — Keep the subject on ITS OWN line.

A second failure from the same pass: the SIM-card macro landed on the line
about *stealing bitcoin from an investor*, while the *"he did it with a SIM
swap"* line got a call-centre desk. Off by one. When you write prompts as a
batch, verify each id against its narration before rendering — a single
inserted or split scene shifts everything after it.

Cycle deliberately across neighbours:

1. **wide establisher** (a street, an office at night)
2. **miniature diorama** (a whole house/block as a tabletop model — a
   signature move of the reference style)
3. **medium action** (the mannequin doing the verb)
4. **macro detail** (a SIM card, a coin, a key, fingers on a keyboard)
5. **surveillance framing** (CCTV/thermal/REC overlay, security-cam angle)
6. **data map** (glowing red routes on black, top-down)
7. **archival/document insert** (a real photo, a paper, a screenshot)

Three consecutive scenes at the same scale = a flag. Every act should carry
at least one diorama, one macro and one surveillance/map frame.

## LAW 6 — The global style is a LOOK, never a CAST. Say "alone" when alone.

The `global_style_suffix` is appended to EVERY scene, so any subject noun
inside it is silently requested in every single shot. We shipped
`"…faceless matte humanoid mannequin FIGURES with no facial features…"` as a
channel style, and Wan dutifully rendered extra mannequins standing behind
the teenager in a scene that had exactly one character. Phantom cast.

- The style suffix may contain ONLY: trigger, render style, environment
  words, lighting, grade, texture. **Never a subject, never a plural.**
- The cast lives in each scene's own prompt.
- A single-subject scene says so: **"alone in the room, nobody else
  present"** (the same discipline as the existing "empty / deserted /
  nobody around" rule for object scenes).
- Compose with `scenes.merge_style(subject, style)` so the SUBJECT LEADS and
  style clauses are deduped — never a naive concatenation, which repeats the
  trigger and lets the style's nouns compete with the scene's.
- `config.WAN["negative_motion"]` carries "duplicate figures, cloned
  figures, unwanted background people, phantom figures, extra mannequins".

## LAW 7 — Every prompt leads with the channel trigger, ends with the mood.

`<TRIGGER>, <specific subject doing the verb>, <framing/scale>, <light + one
accent>` — e.g. `3d mannequin documentary, a faceless mannequin in a hoodie
mid-phone-call at a cluttered bedroom desk, medium reenactment shot, dark
low-key light, red monitor rim glow`.

## Checklist before any storyboard ships

- [ ] Every named person/brand/place in narration appears in ITS scene's prompt.
- [ ] No prompt contains: "abstract", "generic", "a person", "some", "various".
- [ ] No three neighbouring scenes share a scale (see LAW 5).
- [ ] At least one diorama, one macro, one surveillance/map shot per act.
- [ ] Mannequins are DOING the verb, not standing.
- [ ] No text or logos requested anywhere (Remotion handles those).
