# AAAFlow Storyboard v2 — the generator prompt + schema

An upgrade of `weimar_hyperinflation_scenes.json` that adds:
1. **Expressive characters** — explicit facial emotion + gesture per scene.
2. **Explainer diagrams** — a `diagram` scene type for data/comparisons/processes.
3. **LTX-2 animation** — a `motion_prompt` that turns each krea2 still into a clip.
4. **Start → end keyframes** — `image_prompt` (start) + optional `end_image_prompt` (end);
   LTX-2 animates between them.

Pipeline it targets: **krea2** (start/end frames) → **LTX-2** (image-to-video) →
**Qwen3-TTS** (voiceover) → assembled MP4.

---

## The generator prompt (paste into an LLM, give it a TOPIC or SCRIPT)

> You are a storyboard director for **faceless flat-2D-cartoon explainer videos**.
> Given a TOPIC or SCRIPT, output **one JSON object** `{ "video": {...}, "scenes": [...] }`
> for the AAAFlow pipeline (krea2 image-gen → LTX-2 image-to-video → Qwen3-TTS voiceover).
>
> **Rules**
> - **One scene per sentence.** Split a long sentence at its clauses (each clause = its own scene);
>   merge a tiny fragment ("And then?") into its neighbor. Each scene holds **1.5–6 s** (audio-led).
>   Change the visual every beat — never the same shot for more than ~4 s.
> - Keep a **character_bible**: every recurring character has a fixed name, look and palette.
>   Reference characters **by name** in every scene so krea2 stays consistent.
> - **Expressiveness is mandatory.** For every character in a scene give an explicit
>   **`expression`** (the emotion on the face) and **`gesture`** (body language) that match the
>   narration's tone. **Exaggerate** — this is a cartoon. Bake that expression + gesture into the
>   `image_prompt` too.
> - **Use diagrams to explain, don't narrate numbers over a face.** Any data, comparison,
>   timeline, process, or cause→effect becomes a `"type": "diagram"` scene with a `graphic` spec.
> - **Classify every scene's `motion_type`** — a clean 3-way choice (don't agonize), which also
>   decides the end frame *for you*:
>   - `"still"` — no real motion; rest the eye / pure data text. → **no end frame**; rendered as a
>     krea2 still with a gentle Ken Burns move (cheap — no LTX).
>   - `"ambient"` — alive but *unchanging* (flicker, sway, breathing, slow push-in). → **no end
>     frame**; LTX-2 animates the single start frame.
>   - `"transform"` — something *changes* on screen (a reaction, a move A→B, a chart growing, a
>     reveal, a before→after). → **requires `end_image_prompt`**; LTX-2 interpolates start→end.
>   - **Hard rule:** `end_image_prompt` is non-null **iff** `motion_type == "transform"`. **When
>     unsure, choose `"ambient"`** (safe + cheap — it never looks wrong).
>   - Pick `"transform"` when the narration has a **verb of change / reveal / before→after**
>     ("then it...", "prices shot up", "she realized", "the wall fell"). Otherwise it's `still`/`ambient`.
> - For each scene write:
>   - **`image_prompt`** = the **START frame** for krea2 (always). Lead with the style trigger.
>   - **`end_image_prompt`** = the **END frame** for krea2 — set **only** when `motion_type ==
>     "transform"`, else `null`.
>   - **`motion_prompt`** = instructions for **LTX-2**: the in-shot motion + **one simple camera
>     move**. Subtle + physically plausible for flat 2D cartoon — gestures, a prop moving,
>     flicker/sway, a slow push-in/pan. **No morphing, no 3D camera, no style drift.** (`null` for `still`.)
> - `on_screen_text` = crisp labels/numbers (composited in post, not drawn) + a `text_anim`.
> - Output **ONLY valid JSON**, no commentary.

---

## Schema

**`video` (global)**
```jsonc
{
  "title": "string",
  "niche": "e.g. economics / history explainer",
  "format": "faceless flat-2D-cartoon, voiceover-driven, image-to-video",
  "aspect_ratio": "16:9 (1920x1080)",
  "style": {
    "global_style_suffix": "crayoncapital, flat 2D cartoon illustration, bold clean black outlines, flat solid colors, simple shapes, rounded cartoon bodies with thin stick limbs",
    "global_negative_prompt": "photorealistic, 3d render, gradients, blurry, watermark, garbled text"
  },
  "character_bible": [
    { "name": "Frau", "description": "young woman, brown bob, grey wool coat, rounded cartoon body, thin limbs", "palette": "grey coat, brown hair, pale skin" }
  ],
  "motion_defaults": { "model": "ltx-2", "clip_fps": 24, "clip_seconds": "2-5", "default_camera": "subtle push-in or static", "motion_strength": "subtle" }
}
```

**`scenes[]` (per scene)**
```jsonc
{
  "id": 1,
  "act": "Cold Open",
  "type": "scene",                 // "scene" | "diagram" | "title"
  "motion_type": "ambient",        // "still" | "ambient" | "transform"  (end_image_prompt iff "transform")
  "narration": "VO line for this beat.",
  "shot": "medium, eye-level",
  "characters": [
    { "name": "Frau", "expression": "tired, hollow-eyed, grimly resigned", "gesture": "shoulders slumped, calmly feeding a banknote into the fire", "action": "burning cash for warmth" }
  ],
  "image_prompt": "START frame for krea2 (style trigger + subject + EXPRESSION + GESTURE + setting + composition)",
  "end_image_prompt": "END frame for krea2 — set ONLY when motion_type=='transform', else null",
  "motion_prompt": "LTX-2: the motion between start/end + ambient motion + one camera move",
  "duration_sec": 3.0,
  "on_screen_text": "short label",
  "text_anim": "small caption fades in, then a '?' bounces",
  "transition": "cold open on black, fade up",
  "sfx": "crackling fire, cold wind",

  // only for "type":"diagram"
  "graphic": {
    "kind": "comparison_bars",     // bar_chart | line_chart | timeline | flowchart | comparison_bars | map | equation | icon_array
    "title": "Wages vs Prices, 1923",
    "elements": [
      { "label": "Wages",  "value": "x2",   "color": "teal" },
      { "label": "Prices", "value": "x100", "color": "red"  }
    ],
    "reveal": "both bars empty; wages grows to x2; prices rockets up and flies off the top",
    "style": "hand-drawn crayon chart, bold black outlines, flat colors, cream background"
  }
}
```

---

## Worked examples

**Character beat (start→end + emotion + subtle motion)**
```json
{
  "id": 1, "act": "Cold Open", "type": "scene", "motion_type": "transform",
  "narration": "This woman is burning money — and it was the smart thing to do.",
  "shot": "medium, eye-level",
  "characters": [{ "name": "Frau", "expression": "hollow-eyed, grimly resigned", "gesture": "shoulders slumped, calmly lowering a banknote into the flames", "action": "burning cash for warmth" }],
  "image_prompt": "crayoncapital, a weary woman crouched by a small campfire at night in the snow, hollow tired eyes, faint resigned frown, lowering a paper banknote toward the flames, bare trees, deep blue night, warm orange firelight on her face, medium shot",
  "end_image_prompt": "crayoncapital, same woman, the banknote now curling in the fire, a thin grim half-smile of relief, brighter firelight on her face, same snowy night",
  "motion_prompt": "she slowly lowers the banknote into the fire; flames flicker and rise casting moving orange light on her face; her shoulders ease; very slow camera push-in; light snow drifting",
  "duration_sec": 3.0, "on_screen_text": "burning money = smart?", "text_anim": "caption fades in, then a '?' bounces",
  "transition": "cold open on black, fade up", "sfx": "crackling fire, cold wind"
}
```

**Diagram beat (explain a number)**
```json
{
  "id": 14, "act": "The Spiral", "type": "diagram", "motion_type": "transform",
  "narration": "Wages doubled — but prices went up a hundred times.",
  "shot": "flat-on graphic",
  "graphic": { "kind": "comparison_bars", "title": "Wages vs Prices, 1923",
    "elements": [{ "label": "Wages", "value": "x2", "color": "teal" }, { "label": "Prices", "value": "x100", "color": "red" }],
    "reveal": "wages bar grows to x2; price bar rockets up and shoots off the top", "style": "hand-drawn crayon chart, bold black outlines, flat colors, cream board" },
  "image_prompt": "crayoncapital, a simple hand-drawn bar chart on a cream board, two labeled bars WAGES (short, teal) and PRICES (towering, red, breaking past the top edge), bold black outlines, flat colors",
  "end_image_prompt": "crayoncapital, same chart, the red PRICES bar shooting far off the top of frame, the teal WAGES bar tiny beside it",
  "motion_prompt": "the teal wages bar grows a little; the red prices bar shoots upward fast and flies off the top; numbers tick up beside each bar; slight camera shake as it launches",
  "duration_sec": 2.5, "on_screen_text": "WAGES x2   PRICES x100", "text_anim": "numbers count up; 'x100' slams in red",
  "transition": "hard cut to clean graphic", "sfx": "rising whoosh"
}
```

---

## How it maps to the pipeline + practical notes

- **krea2** renders `image_prompt` (and `end_image_prompt` when present) → the start/end frames.
- **LTX-2** takes start (+end) frame + `motion_prompt` → a short clip per scene. First+last-frame
  keyframing is exactly your "start → end frame" idea — LTX-2 interpolates the motion between them.
- **`motion_type` decides the end frame for you** (no judgment needed): `still` → krea2 still +
  Ken Burns, no LTX; `ambient` → LTX on the single start frame; `transform` → LTX start→end (the
  only type that gets an `end_image_prompt`). Default to `ambient` when unsure. You can eyeball or
  override this one field per scene — far easier to trust than a vague "needs end frame?" guess.
- **Keep motion subtle.** Flat 2D cartoon breaks if you ask for big motion, morphs, or 3D camera.
  Think "a little alive," not "fully animated."
- **Hybrid for speed (important on 16 GB):** LTX video is heavy — animating all ~160 scenes is a
  lot of compute/time. Best practice: **animate the hero/emotional/diagram beats with LTX-2**, and
  leave calmer scenes as **krea2 stills with Ken Burns** (the current assemble path). Mark which is
  which (e.g. `"motion_prompt": null` ⇒ Ken Burns still).
- **LTX-2 "Pro"** is likely the cloud/API tier (fastest, paid). Local LTX-Video runs on 16 GB but
  expect ~minutes per clip — generate krea2 frames first, then batch the LTX clips overnight, or
  use the Pro API for the hero shots.

> Wiring LTX-2 into AAAFlow is a future build step (a new `animate` stage that reads
> `motion_prompt` + the start/end frames). This schema is already shaped for it, so storyboards you
> write now stay compatible.
