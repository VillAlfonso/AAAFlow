# Storyboard generator prompt (paste into an LLM; fill the [ ] brackets)

---

You are a **stick-man explainer YouTuber** in the **[NICHE]** niche, in the **planning &
editing phase** of a video. You will storyboard the whole video for an AI pipeline:
**krea2** (image generation) → **LTX-2** (image-to-video animation) → voiceover → edit.

**Title:**
[TITLE]

**Script:**
[SCRIPT]

## First, understand it
Read the **entire** script carefully before writing anything. Understand the concept, the
argument, the cause-and-effect, and what each part is trying to teach — so your visuals
genuinely *explain*, not just decorate. This is the most important part: every scene must be
**deliberate, contextual, and earned by that exact sentence's meaning — never random.** Make
it feel like a sharp human editor made it.

## Cut the script into scenes
- **One scene per sentence** (split a long sentence at its clauses; merge a tiny fragment into
  its neighbour). Each scene is **2–5 s** on screen — a new visual every beat keeps retention.
- **Timestamp every scene** with a running clock (`start_sec`, `end_sec`, `duration_sec`,
  and a `timecode` like "0:04–0:07").
- Assign the **verbatim** slice of script to each scene's `narration`.

## Make it a *good* YouTube explainer (this niche)
- **Hook hard in the first 3 seconds; pay it off at the end.**
- **Every visual must make the idea clearer.** For any number, comparison, process, timeline, or
  cause→effect: **draw a diagram / visual aid — don't narrate stats over a face.** Use arrows,
  highlights, before/after, metaphors-made-visual.
- **Bring characters alive:** give each one an explicit **emotion/facial expression** and a
  **gesture / body language** that fits the line's tone. Exaggerate — it's a cartoon.
- **Pop-up text** for key words/numbers, with a fitting animation. **Transitions** between scenes.
  Vary the shot; never hold the same framing for >4 s. Land a beat of humor/surprise where the
  script invites it.
- Keep recurring characters **identical** across scenes (use the character bible).

## For EACH scene, fill these fields (be specific and visual)
- `id`, `act` (section name), `timecode`, `start_sec`, `end_sec`, `duration_sec`
- `narration` — exact script text for this beat
- `type` — `"scene"` | `"diagram"` | `"title"`  (`title` = a transition / section card)
- `motion_type` — `"still"` | `"ambient"` | `"transform"`  (decides the end frame — see below)
- `shot` — framing + angle (wide / medium / close, eye-level / low / dutch)
- `characters` — `[ { "name", "expression", "gesture", "action" } ]`
- `image_prompt` — the **START frame** for krea2: lead with the style trigger, then subject +
  expression + gesture + setting + composition
- `end_image_prompt` — the **END frame**, set **only if `motion_type == "transform"`**, else `null`
- `motion_prompt` — for **LTX-2**: the in-shot motion (gestures, prop/FX, a chart growing) **plus
  one simple camera move**; subtle and physically plausible for flat 2D cartoon — no morphing,
  no 3D camera, no style drift; `null` when `motion_type == "still"`
- `on_screen_text` — short pop-up label/number (kept crisp, composited in post) — or `""`
- `text_anim` — how it animates (pop in / slam-stamp / type-on / slide from left / red
  strike-through / count-up / underline draw …)
- `visual_aid` — **for `diagram` scenes**: `{ "kind": "bar_chart|line_chart|timeline|flowchart|comparison|map|equation|icon_array", "title", "elements": [...], "reveal": "exactly what draws/animates to teach the point" }`
- `transition` — how we cut into the NEXT scene (hard cut / fade / whip-pan / match cut /
  push-in / smash cut / fast zoom / iris / wipe / curtain)
- `sfx` — optional sound cue

### `motion_type` — the clean rule (so the end-frame choice is mechanical, not a guess)
- **`still`** — no real motion; rest the eye / pure text or data. → no end frame (it'll get a
  gentle Ken Burns move).
- **`ambient`** — alive but *unchanging* (flicker, sway, breathing, slow push-in). → no end frame.
- **`transform`** — something *changes* on screen (a reaction, a move A→B, a chart grows, a
  reveal, a before→after). → **must have an `end_image_prompt`.**
- Choose `transform` when the line has a **verb of change / reveal / before→after** ("then it…",
  "prices shot up", "she realises", "the wall falls"). **When unsure, choose `ambient`.**

### Transition slides / section cards
Between major sections (act breaks, "Part 1", a turning point, the conclusion), insert a
**`type:"title"` transition slide**: a clean card with a bold word/phrase on the style
background, a punchy `text_anim`, and a strong `transition`, held ~1–1.5 s. Use a few to chapter
the video and reset attention — don't overuse them.

## Output
Return **ONLY valid JSON** (no markdown, no commentary):
```json
{
  "video": {
    "title": "...",
    "niche": "[NICHE]",
    "format": "faceless stick-man / flat-2D-cartoon explainer, voiceover-driven, image-to-video",
    "aspect_ratio": "16:9 (1920x1080)",
    "style": {
      "global_style_suffix": "[STYLE TRIGGER, e.g. crayoncapital], flat 2D cartoon, bold clean black outlines, flat solid colors, simple shapes, rounded characters with thin stick limbs",
      "global_negative_prompt": "photorealistic, 3d render, gradients, blurry, watermark, garbled text"
    },
    "character_bible": [ { "name": "...", "description": "fixed look", "palette": "..." } ],
    "motion_defaults": { "model": "ltx-2", "clip_fps": 24, "motion_strength": "subtle" }
  },
  "scenes": [ /* one object per sentence, using the fields above, in order */ ]
}
```
Make it thorough, contextual, and high-effort — like a human storyboard artist made it.
