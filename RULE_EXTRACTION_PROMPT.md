# Prompt: extract style rules from evidence packs

Paste this (edited to taste) into the AI that should derive the rules, attaching one
`pack.pdf` per example video (or the `report.md` + sheet images separately).

---

You are a video style analyst. Attached are N "evidence packs", each describing one
YouTube video from the same niche: metadata, editing/speech metrics, and a timeline
where each shot (Sxxx, start time, duration, cut/fade, motion label such as zoom-in /
pan-L / motion) is paired with the exact words and pauses spoken during it. The frame
sheets show timestamped frames: yellow labels (`S014 3:12.4`) are shot starts, white
labels (`S014| 3:14.4`) are later frames inside the same shot. LOUD lines encode
loudness 0–9 per 5 s.

Derive the **reusable production rulebook** this niche follows. Only state rules
supported by at least two videos (or clearly dominant in one), and cite evidence as
video + shot ids or timestamps. Prefer numbers over adjectives.

Output sections:

0. **Niche & packaging (SEO)** — infer the niche from titles, tags, categories,
   descriptions and transcripts; then the packaging formula: title patterns, tag
   strategy, description structure (links/hashtags/CTAs), chapter usage, and thumbnail
   composition (THUMB tile: framing, text, faces, contrast). Note engagement signals
   (likes/comments %, views/day, views-to-subscriber ratio) as virality context.
1. **Hook (first 15–30 s)** — structure, cut density, spoken pattern, loudness.
2. **Pacing guardrails** — median/avg shot length, cuts-per-minute range and how it
   evolves (intro vs body vs outro), share of <1 s shots, when long shots are allowed.
3. **Cut placement** — relation of cuts to sentence ends and spoken pauses; jump-cut
   usage; fade/transition usage and when.
4. **Scripting** — sentence length, direct address, question frequency, recurring
   phrases, how topics are chained ("and then...", callbacks), CTA timing and wording.
5. **Delivery & prosody** — wpm range, pause lengths and what precedes/follows long
   pauses (reveals, punchlines), silence usage.
6. **Sound design** — loudness dynamics, quiet-vs-loud contrast moments, where music
   likely sits (loud with no speech), audio at cuts.
7. **Visual grammar** (from contact sheets) — talking-head vs b-roll rhythm, text
   overlays, framing changes, thumbnail-worthy moments.
8. **Machine rules** — the above condensed to JSON: numeric ranges + hard guardrails
   an automated video generator must respect. If I've told you what settings/features
   my generator exposes, map each rule onto those controls and propose new features
   for rules the generator cannot express yet.

Flag any rule you are unsure about with LOW-CONFIDENCE instead of guessing.
