# AAAFlow Studio

## Mission
**Type a script in → a finished YouTube video comes out.** Fully local, one machine
(RTX 5060 Ti 16 GB), zero cloud. The output must look like it was made by a human
creator — writing, pacing, art direction, editing, sound. If a viewer (or a
platform) can tell it's AI-generated, that's a failure.

**QUALITY OVER EVERYTHING (user rule, 2026-07-03).** Render time is explicitly
not a concern on this machine. Default to the highest-quality path everywhere:
Wan "max" profile (20 steps, native 720p, no speed LoRAs), enhance chain on,
CRF 17 final encodes, Real-ESRGAN-sharpened stills. Fast/draft profiles exist
only for previews and must be opted into.

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

## THE PIPELINE ORDER (non-negotiable — see .claude/PIPELINE.md for detail)
Voice comes FIRST. Never voice a video scene-by-scene: independent per-scene TTS
generations sound cut-up and out of tone; only prosody *within* a take is good.

1. **Script** — write/receive the full script (spec: `storyboard_v3_prompt.md`).
2. **One-take narration** — the WHOLE script in a single Qwen3-TTS pass:
   `POST /api/projects/{pid}/voiceover/onetake` (UI: Voiceover → "One-take
   narration"). Whisper aligns every scene to the take and QA-checks the
   transcript against the script (TTS hallucinates; never skip the QA result).
3. **Storyboard around the voice** — scene timings come FROM the narration
   alignment. Compose/adjust image prompts, camera hints, audio_cue per scene.
4. **Images** — krea2 via ComfyUI; prompt = scene image_prompt + editable
   global style (`video.global_style_suffix`, clause-deduped). Spot-check
   frames; phantom-people and style drift are the classic failures.
5. **Music / SFX** — ACE-Step bed set on the project (ducked automatically);
   stinger SFX come from `data/sfx_library/` via each scene's `audio_cue`
   (browse `GET /api/sfx` when writing the script; drop new wavs in the folder).
6. **Animate (optional per style)** — **Wan 2.2 14B** clips (fp8 MoE via
   ComfyUI; LTX-2 was deleted 2026-07-03) for hero/motion scenes, "max"
   quality profile by default, then the **enhance chain** (minterpolate →
   Real-ESRGAN animevideov3) sharpens every clip. Engine/quality/preset are
   chosen per project at creation (Projects page) or in settings.animate.
7. **Assemble** — style preset decides scene motion:
   `cinematic` = LTX clips + 2.5D **parallax** (depth camera moves) + SFX;
   `parallax-slides` = parallax only (no LTX); `dynamic-slides` /
   `simple-slides` = Ken Burns. Presets live in `data/effects_presets.json` —
   reusable across all videos, editable, `PUT /api/effects_presets` to save a
   new look.
8. **QA the actual mp4** (frame-sample + loudness) before calling it done.

One call runs 2→7: `POST /api/projects/{pid}/produce` (UI: Assemble →
"Produce everything"); poll `GET /api/projects/{pid}/produce`.

## Hard rules
- **NO on-screen text is ever burned into the video.** Narration + visuals
  carry it. (The assembler no longer composites captions at all.)
- One art direction per video, sourced from the project's
  `video.global_style_suffix` — never hardcode a look into a pipeline stage.
- Scenes with no people get the style minus its character clause
  (`scenes.scene_has_people`) or the model draws phantom figures.
- Keep animated clips short (~3 s) and subtle; the project style LEADS every
  clip prompt (see animate.py) so Wan animates the drawing, not repaints it.
- Narration lines should end with a period — trailing commas invite TTS to
  keep talking (hallucination).

## Operational rules
- Backend (`app/*.py`) edits need a **full server restart** (no hot-reload):
  `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
  from repo root (log to `data/server.log`). Bump `app.js?v=` in
  `web/index.html` after frontend changes. **Never restart while a job runs.**
- One GPU: TTS, krea2, LTX, ACE-Step contend. The job queue serializes, but
  the ACE sidecar (port 8765) holds VRAM with no unload API — kill its process
  before LTX work on 16 GB.
- ComfyUI auto-starts from `ComfyUI_windows_portable/`. Don't auto-open
  media/browser on the user's machine.
- Projects: `data/projects/<pid>/` (`project.json` + audio/ images/ video/).
  Long builds keep a `HANDOFF.md` there, updated as stages finish.

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
