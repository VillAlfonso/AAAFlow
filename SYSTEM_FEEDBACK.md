# AAAFlow limits test — findings from building "The Man Who Sold Paris"

One full production (28 scenes, 2:20, voice + images + music + 8 LTX clips +
assembled edit) run end-to-end on 2026-07-02 explicitly to find where the
system breaks. What broke, what I fixed during the run, and what to build next.

## Fixed during this run (already in the code)

1. **TTS hallucination shipped silently.** Scene 6's narration ended with a
   comma; Qwen3-TTS kept going and invented *"...and a phone and phone's on
   time, be happy I can't swim."* Nothing in the pipeline would ever have
   caught it. I whisper-transcribed all 28 scenes and compared to the script
   (only real failure: that one scene). → **Built inline for this run; should
   be a pipeline stage** (see "Build next" #1).
2. **Phantom characters in object/landscape scenes.** The cartoon style text
   describes bodies/faces, so krea2 drew random figures into the Eiffel-tower
   opener, the money-box diagram, the Alcatraz wide. Prompt-level "empty,
   deserted" did NOT beat it at cfg 1.0. Fixed properly:
   `build_image_prompt` strips the style's people-clause
   (`config.KREA2_STYLE_CHAR_CLAUSE`) when `scenes.scene_has_people()` is
   false. Re-renders came back clean.
3. **Zoom transitions crashed the final encode.** Time-varying `resized()`
   clips report their t=0 size; `concatenate(compose)` inflated the video to
   2265×1274 and libx264 refused the odd width. All zoom transitions now
   bounded in fixed W×H composites (`transitions.py`).
4. **Caption styling was an AI tell.** Thin ink text + 2 px stroke vanished on
   busy art. Now white bold + heavy dark stroke (the human-editor standard).
5. **Music ducking existed as a setting but was never implemented.** The
   `duck` flag was accepted and ignored. Now real: sidechain-style gain curve
   (music dips to 35 % under speech, breathes back in pauses), single-mix
   audio session with a peak limiter.
6. **No editing SFX layer existed.** Built `app/sfx.py`: procedural whoosh /
   impact / riser / ding / ka-ching / pop synthesized from each scene's
   `audio_cue` text (risers end ON the cut; 12 stingers in this video).
7. **Ken Burns was a metronome** (same 6 % zoom-in every scene). Now
   alternates in/out and drift direction per scene.
8. **Character consistency without reference conditioning.** New
   character-bible grounding (`Featuring Name (description)`) kept Lustig
   on-model across ~14 scenes on krea2, which has no IP-Adapter. It works
   noticeably well — same fedora/tie/watch-chain everywhere.

## Where the system is still lacking (build next, roughly in order)

1. **A QA gate per stage, not per heroic session.** The pipeline generates and
   *hopes*. Each stage should self-check and auto-retry before marking ready:
   - Voiceover: whisper-transcribe each clip, fuzzy-match to narration,
     re-synth on mismatch (catches hallucination + truncation). The inline
     script from this run is the prototype.
   - Images: a cheap VLM pass ("does this frame contain X? any extra people?
     photoreal drift?") would have caught all 5 bad frames automatically.
   - This is the single biggest step toward "type script → good video."
2. **Assemble is too slow and too fragile.** ~30 min to encode 2:20 at 1080p30
   (moviepy composites frame-by-frame in Python). An ffmpeg filtergraph (or
   pre-rendering each scene clip with ffmpeg zoompan and concatenating) would
   cut it to minutes. Fragility: two of the three failures this run were
   moviepy-layer issues.
3. **VRAM lifecycle is manual.** TTS engine, ComfyUI (krea2 → LTX), and the
   ACE-Step sidecar all hold VRAM with no coordination; I killed the music
   sidecar by PID before animating. Engines need an unload/stop API and the
   job runner should release the previous stage's engine before the next.
4. **One music bed for the whole video.** A 2-act story wants at least
   hook/body/outro segments or beat-matched cues. Multi-segment music with
   crossfades = big human-feel win. (Also: no auto loudness normalization to
   the -14 LUFS YouTube target; this render sits at -20.)
5. **No end-to-end "make the video" button.** This run was me chaining six
   API calls with QA between. A pipeline orchestrator (script → storyboard →
   voice+QA → images+QA → music → animate → assemble, checkpointed in
   project.json, resumable) is exactly what "type script in, video out" means.
6. **Whip-pan direction, true crossfades, and J/L audio cuts** don't exist
   (crossfade currently degrades to fade-in; audio always hard-cuts with the
   scene). Small, but they're the difference between "slideshow with effects"
   and "edited."
7. **Storyboard authoring is the quality ceiling.** This video worked because
   the storyboard was written like a director: per-scene transitions, text
   anims, audio cues, motion flags, a character bible. The Script→JSON page
   should prompt the LLM with that full recipe (hook density, cue vocabulary,
   bible), not just split sentences.
8. **Small paper cuts.** LTX snaps 2.0 s → 1.42 s silently (surface the real
   length in the UI); `total_runtime_sec` is planning-only and drifts from the
   voiced timeline; scene modal shows no per-scene audio QA status; ComfyUI
   console window pops up on the user's desktop mid-run.

## What genuinely impressed
- krea2 turbo at 8 steps: ~40 s/frame with strong prompt adherence and comedy
  acting (Poisson hugging the tower, Capone laughing) — the creative bottleneck
  is prompt/QA, not the model.
- LTX-2 with project-derived style anchoring + short clips: zero melt across
  all 8 clips on first try.
- Qwen3-TTS with a persona instruct: expressive, YouTube-ready narration
  (one hallucination in 29 clips — hence the QA gate).
