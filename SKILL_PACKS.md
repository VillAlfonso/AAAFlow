# Skill packs: training channels from reference studies (architecture v2)

The loop: **study → distill → genesis → produce → score.** The user names a
reference channel. The study intake (`app/study.py`, Data Gatherer page)
ranks its uploads by views, saves avatar + banner, and runs the top 3-5
videos through the Data Gatherer at dense 1s sampling. Claude then reads the
evidence and writes the seven skill packs below into
`data/studies/<sid>/skills/`. Creating a channel FROM a study copies the
packs to `data/channels/<cid>/skills/` and seeds every channel default from
them. Videos produced on that channel follow the skills; renders can be fed
back through the gatherer and diffed against the numeric targets.

## Analysis stack (who does what)

- **Data Gatherer** (deterministic, no ML): cuts, shot durations, motion
  labels, word-level pauses, wpm, loudness, SEO meta, thumbnails, frame
  sheets. This is the evidence substrate; never re-derive what it measures.
- **Local VLM for bulk labels** (optional): Qwen-VL via Ollama, or the
  vendored `trainers/musubi-tuner/caption_images_by_qwen_vl.py`, to caption
  per-shot frames at scale when a study needs full coverage cheaply.
- **Claude** reads the frame sheets and packs directly (they were designed
  for AI reading) for the deep exemplar passes and writes the skill packs.
  Depth beats coverage: annotate 2-3 videos shot-by-shot, skim the rest.

## Hard guardrails

1. **Inspired-by, never impersonation.** Learn niche, structure, pacing,
   manner. Never copy the channel's name, logo, actual footage, exact
   thumbnail faces, or anything that would read as being them.
2. **Visual style: prompt DNA + skills first; LoRA allowed (amended
   2026-07-14 by the user, overriding 2026-07-12).** Reference footage may
   train Wan style LoRAs: shot-aligned 2-4 s clips cut at gatherer
   boundaries, VLM-captioned (`app/lora_dataset.py`), low training res.
   Copyright risk was disclosed and accepted; clips never ship in videos,
   and rule 1 (inspired-by, never impersonation) still binds absolutely.
3. **On-screen text** (rule amended 2026-07-12): typeset Remotion motion
   graphics are allowed when `editing.json` documents that the studied style
   uses them. Real fonts only; AI-drawn glyphs stay banned; date chips,
   receipts and ref cards keep their existing rules.
4. **Narration skill designs a voice, it never clones the reference
   narrator's actual voice.** Delivery characteristics (pace, pauses, arc)
   are learnable; the person's voice is not copyable.
5. **Evidence honesty.** Every rule cites evidence (video id + shot ids or
   timestamps). A rule needs support from 2+ videos, or one clearly dominant
   pattern; below that, mark it LOW-CONFIDENCE or call
   `POST /api/studies/{sid}/gather {more}` and widen the sample. Prefer
   numbers over adjectives. Note the sampling window (the ranking scans the
   ~300 most recent long-form uploads).

## Pack format

Each skill is one `<name>.md` (the human-readable rulebook: rules, evidence
citations, exemplars) plus one `<name>.json` (the machine half the pipeline
consumes). Keep the JSON small and numeric; the md carries the why.

**AI-AGNOSTIC CONTRACT (user, 2026-07-14: "whatever AI, whether it's Claude
or something from Cline, it will work").** Skill packs are plain markdown +
plain JSON and must stand alone:

- No tool-specific syntax: no Claude skill frontmatter, no MCP references,
  no "call this API" steps inside the rulebooks. Rules are written as
  instructions any competent model (or human) can follow with just the pack
  in context.
- Every skills folder carries an `INDEX.md`: one line per pack (file, what
  it governs, when to load it) plus a short generic entry prompt ("You are
  producing a video for this channel. Load the packs relevant to your task
  and follow them as binding style law."). Any agent — Claude, Cline, the
  local autopilot's LLM — starts there.
- The `.json` halves are consumed by PIPELINE CODE (packaging, autodirect,
  thumbs, voiceover), never by prompt-injection, so they work identically no
  matter which model wrote the storyboard.
- Cite evidence inline in the md (video id + shots); a reader without
  access to the packs' raw evidence must still be able to apply the rule.

**Transcripts train the script skill.** The gathered word-level transcripts
are the primary evidence for `script.md`: analyze them like a human story
editor (structure, hook mechanics, information order, sentence rhythm,
re-anchoring, wind-down) and write the findings as rules with quoted
examples. The script skill IS the trained writing model — it upgrades every
writer that loads it, local or cloud.

### 1. titles (`titles.md` / `titles.json`)
Evidence: the study's ranked candidates list (30 titles WITH view counts,
which is a real formula-vs-performance signal) + the gathered videos.
Extract: structural formulas (slots, length band, punctuation, caps,
number usage, curiosity mechanic), what the top decile does that the rest
does not. JSON: `{formulas: [], length: {min, max}, rules: [], examples: []}`.
Plugs into: `packaging` title options + the channel authoring prompt
(Rule 0 addendum).

### 2. thumbnails (`thumbnails.md` / `thumbnails.json`)
Evidence: `thumbnail.jpg` per gathered video (also the THUMB tile on sheet
1) read against its title. Extract: composition (face share, framing,
palette, contrast), word count of thumb text, emotion, title-thumbnail
division of labor, recurring template. **REQUIRED (user, 2026-07-14): the
title-vs-thumb-text CONTRAST table — for every studied video list the pair
(title, thumbnail text) and derive the relationship rule: do they repeat,
complement, or set-up/pay-off each other, and which half carries the noun
vs the tension.** The techniques pass measures the raw pairs into
`report.json["techniques"]["thumbnail"]`. JSON: `{template_hints: [],
text_words: {min, max}, palette: [], kicker_style: "", face: "",
title_thumb_contrast: ""}`.
Plugs into: `thumbs.py` template pick + kicker pool, brandkit thumbnail
slot prompt DNA.

### 3. editing (`editing.md` / `editing.json`)
Evidence: gatherer metrics + timelines across all gathered videos.
Extract: cuts/min by act (hook, body, outro), median/avg shot, share of
<1s shots, cut-on-sentence %, cut-in-pause %, motion mix, fade usage,
loudness dynamics, on-screen text and motion-graphic usage (from sheets).
JSON: numeric targets plus a grammar overlay:
`{targets: {cuts_per_min: [lo, hi], median_shot: [lo, hi],
cut_on_sentence_pct: n, ...}, grammar: {transitions: [], sfx_density: "",
emphasis_rate: ""}, remotion_text: {usage: "none|light|heavy", styles: []}}`.
Plugs into: per-channel effects-grammar overlay, preset choice, assemble
opts, and it IS the scorecard target set.

### 4. seo (`seo.md` / `seo.json`)
Evidence: description, tags, category, chapters, engagement per video.
Extract: description skeleton (first-line pattern, links, hashtags,
chapters), tag strategy (count, entity vs broad mix). JSON:
`{description_skeleton: [], tags: {count: [lo, hi], lead: ""},
chapters: bool, hashtags: n}`. Plugs into: `packaging` per-channel
description builder + tag pools.

### 5. script (`script.md` / `script.json`)
Evidence: full transcripts with pause markers. Extract: sentence length
distribution, address (I/you/we), question rate, hook construction (first
15s), chaining devices, recurring phrases, CTA timing and wording,
wind-down shape. `script.md` doubles as an authoring-prompt ADDENDUM
appended to `storyboard_v3_prompt.md` for this channel. JSON: the stats.
Plugs into: the channel authoring prompt + writer + lint thresholds.

### 6. composition (`composition.md` / `composition.json`)
The core new skill: per-shot narration-to-visual mapping. For 2-3 exemplar
videos, table every shot: narration line → what is on screen → why it works
(b-roll, talking head, typeset graphic, chart, archival, reenactment).
Distill rhythm rules: b-roll per seconds of talking head, which narration
beats get graphics, when text appears, re-anchor patterns. JSON:
`{beat_visuals: {money: "", reveal: "", impact: "", small: ""},
broll_ratio: n, graphic_triggers: [], shot_variety: []}`.
Plugs into: `autodirect` scene guidance, writer picture-subject rules,
Remotion scene selection.

### 7. narration (`narration.md` / `narration.json`)
Evidence: word timings + speech metrics. Extract: wpm speaking band, pause
profile (rate, avg/max, what precedes long pauses), energy arc, ending
cadence. JSON: `{wpm: [lo, hi], pauses: {per_min: n, long_before: ""},
instruct: "", humanize: "natural|off|preset", outro: ""}`.
Plugs into: channel voice defaults (`voice_instruct`, humanize, outro),
TTS `speed`, score.py mood hints.

### 8. camera (`camera.md` / `camera.json`) — added 2026-07-14
Replaces the RETIRED parallax mode (user: "that mode looks so ugly"): real
camera grammar learned from the reference, not fake 2.5D depth.
Evidence: per-shot motion labels in report.json `shots` rows
(`[t0, t1, transition, motion]` where motion ∈ static/hand/zoom-in/
zoom-out/pan-L/pan-R/motion) correlated with the transcript segment playing
under each shot, plus the techniques pass's per-tile subjects. Extract: the
channel's shot-type vocabulary (establisher, drone push, slow push-in on
subject, static insert, whip to detail, handheld-over-document...), the
motion mix (% moving vs static), and WHERE each type is used (chapter
opens, tension lines, reveals, map/data moments, breathers). JSON:
`{motion_mix: {}, types: [{type, share, use_when, prompt_words}],
rules: []}` — `prompt_words` are the exact phrases to inject into Wan
motion prompts. Plugs into: t2v/i2v clip prompts (`animate.py`,
`scenes.build_motion_prompt`), storyboard camera hints, Ken Burns energy.

## Scorecard (close the loop)

After producing a video on a trained channel, analyze OUR render and diff
its measured metrics against `editing.json` targets and `narration.json`
bands (their median shot 2.1s vs ours 3.4s, and so on). Fix misses by
editing the channel's grammar overlay or pacing, not by hand-tweaking one
video. (Gatherer support for analyzing a local file instead of a YouTube
URL is the one missing piece; until it lands, upload-then-gather or run the
metrics ad hoc.)
