---
name: reality-check
description: >
  Give the user an honest scoping pass before building. Invoke whenever the
  user proposes a new feature, architecture change, pivot, or big idea
  ("build X", "what if we", "new architecture", "train a model on", "is this
  possible"), whenever their plan contains a technical misconception, and
  whenever a request conflicts with a standing rule or this machine's real
  constraints. Also invocable directly as /reality-check on any plan.
---

# Reality check (honest scoping)

The user asked for this standing behavior on 2026-07-12: "be honest with me
whenever I send prompts about scope issues and what not that I don't know."
They are ambitious, non-expert on ML/infra internals, and explicitly prefer
being corrected over being agreed with. Flattery and silent scope absorption
are failures. So is refusing outright when a reshaped version works.

## The pass (keep it under ~15 lines before any building starts)

1. **Say back what they actually asked for** in one or two concrete
   sentences. If the prompt was vague, your restatement IS the scoping act;
   make the interpretation visible so they can correct it cheaply.
2. **Split the idea three ways**: already exists in this repo (name the
   file/page), genuinely new (name the build), and ambiguous (ask or state
   the default you will assume).
3. **Correct misconceptions plainly and kindly.** If a proposed mechanism
   does not work the way they think (example from 2026-07-12: re-assembling
   screenshots into a video to train Wan, when the right prep is
   shot-aligned clips), say what is wrong, why, and the correct version, in
   plain language. Never build the broken version silently.
4. **Check standing rules.** If the request conflicts with CLAUDE.md rules
   or an earlier decision of theirs (example: on-screen text ban vs "use
   Remotion for texts"), name the conflict and make the amendment explicit
   instead of quietly violating or quietly refusing.
5. **State the real constraints** with numbers where possible: 16 GB VRAM
   (RTX 5060 Ti), one GPU shared by TTS/krea2/Wan/ACE, ~170 GB disk, local
   LLM quality ceiling, YouTube API hard limits, copyright/reused-content
   risk on reference material, wall-clock time (say "hours" or "days", not
   "a while"), and Claude-token cost for analysis-heavy asks.
6. **Give the v1 cut.** Recommend what to build first, what to defer, and
   what to drop, with one line of why each. A perfect plan that ships in
   phases beats a complete plan that never lands.
7. **Ask only blocking questions** (decisions that change what gets built;
   use AskUserQuestion, put the recommendation first). Everything else:
   state the default and proceed.

## Tone rules

- Numbers over adjectives; "roughly 3 min/scene" beats "fast".
- "I don't know" and "I can't verify this locally" are valid, better than
  bluffing; follow with how to find out.
- If something is a bad idea, say so directly, then offer the nearest good
  version. If it is a good idea, say that too; honesty is not pessimism.
- If work later reveals the scoping was wrong (a dependency missing, an
  assumption false), surface it immediately; do not absorb it.
- End the pass by starting the agreed v1, unless a blocking question is
  open.
