# Storyboard v3 — minimal authoring spec (works with ANY model, even small ones)

Give this file + a topic to any LLM. The model only writes **narration lines
and picture subjects**. Everything else — transitions, sound effects, camera
moves, hero-scene animation, art style, punctuation safety, timing — is filled
in deterministically by AAAFlow's auto-director on import. Fields you DO
provide are respected; fields you leave out cannot break the video.

## What the model must produce (JSON)

```json
{
  "video": {
    "title": "…",
    "global_style_suffix": ""
  },
  "character_bible": [
    {"name": "…", "description": "fixed physical look, clothes, colors", "palette": "…"}
  ],
  "scenes": [
    {"id": 1, "narration": "…", "image_prompt": "…", "characters": ["Name"]}
  ]
}
```

That's it. `global_style_suffix` may be left "" (the flat-cartoon house style
is applied). `characters` lists bible names appearing in that scene so their
look stays consistent. Optional per-scene overrides (`transition`,
`audio_cue`, `motion_type`, `shot`) are honored if present — skip them unless
you know what you want.

## The viral formula the script MUST follow (this is the important part)

0. **The title opens a CURIOSITY GAP — never face value.** Write what makes
   the viewer think "wait, what?", not what the video "is about".
   BAD: "The Story of Victor Lustig", "The Dyatlov Pass Incident Explained".
   GOOD: "He Sold the Eiffel Tower. Twice.", "Nine Hikers Walked In. The
   Mountain Kept Them.", "They Lied About What Was in the Box".
   Rules of thumb: a person is "he/she/they" not a name; withhold the noun the
   video reveals; tension words (never, no one, wrong, hidden, until) earn
   clicks; ≤ 60 characters; must still be TRUE — the payoff must pay it off.
   - Scene 1 narration: the single most absurd TRUE fact of the story,
     **≤ 12 words**. No greetings, no "today we're going to".
   - Hook scenes are SHORT: 6–12 words each. One idea per scene.
   - End the hook by raising the question the rest of the video answers.
2. **Escalation.** Each act tops the previous one; put the second-best fact
   at ~60–70% as a mid-video re-hook.
3. **Payoff ending.** The last line is a punchline or gut-punch callback,
   ≤ 15 words. Never summarize, never "and that's the story of".
4. **Length.** ~2 minutes ≈ 300–320 narration words over 24–30 scenes.
5. **Sentences read aloud well**: short, concrete, contractions fine. Every
   line ends with . ! or ? (never a trailing comma).

## Keep the viewer ON the story (clarity rules — as important as the hook)

- **One idea per scene.** If a line carries two events, it's two scenes.
- **Chain cause → effect out loud**: prefer "so", "because", "but", "which
  meant" over dropping disconnected facts. The viewer must always know WHY
  this line follows the last one.
- **Re-anchor names.** Say the person's NAME again every ~5 scenes; "he/she"
  across a whole act loses the story. Same for places.
- **Signpost time jumps** ("Three weeks later.", "Back in London.") — one
  short scene, never buried mid-sentence.
- **Emphasis markup**: wrap the ONE load-bearing word or number of a line in
  asterisks — `He paid *ten million* for it.` — at most one per scene, only
  where a human narrator would lean in. The editor lands a micro zoom/flash
  and a tick exactly on that spoken word (the asterisks never reach the
  voice). Don't mark filler; an unmarked line gets a sensible auto-pick.

## Picture-subject rules (image_prompt)

- **The picture SHOWS what the line SAYS.** A viewer with the sound off must
  still follow the story from the images alone. Every image_prompt depicts
  the concrete subject of ITS narration line — the person doing the thing,
  the object, the place — never a generic mood shot. (The linter flags scenes
  whose visual shares no words with the narration: that's slideshow filler.)
- ONE clear subject per scene, physical and drawable ("A wooden box with a
  brass crank pushing out a banknote"), never abstract ("the economy
  collapsing morally").
- Characters: reference bible names and let their `description` carry the
  look; write their EMOTION into the scene ("sweating with excitement").
- No readable text/documents close-up (models write gibberish). No real-person
  photo likeness. Object/landscape scenes: say "empty", "deserted", "nobody
  around" and list no characters.
- Vary framing across neighboring scenes (wide → close → detail).

## What you never write
- on_screen_text (never rendered), timecodes, durations (timing comes from
  the voice take), style boilerplate per scene (the global style is appended
  automatically), motion prompts (authored at animate time).

## Import & check
Upload on the Projects page, or validate first:
`POST /api/storyboard/lint {"data": <storyboard>}` → auto-directed copy +
report (hook density stats, warnings like "scene 1 too long"). Fix warnings —
they are the difference between a video and a viral video.
