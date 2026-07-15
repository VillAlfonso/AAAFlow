"""COMPOSITION LINT: catch a board that was composed scene-by-scene.

User, 2026-07-14: the composer must read the WHOLE script and compose the
VIDEO, not 40 independent pictures. That rule needs teeth, because an
isolation-composed board looks fine one scene at a time — every prompt is
vivid, and the video is still a slideshow.

These checks only see GLOBAL properties, the ones a scene-by-scene composer
cannot get right by accident:

  spine        does a visual_plan exist at all?
  cast         do recurring characters keep the SAME look, verbatim?
  world        do spaces RECUR, or is every scene a new room?
  presence     how many scenes have nobody in them? (24/40 was our slideshow)
  rhythm       three neighbours at the same scale = monotony
  mix          is the media budget honoured, or is it 40 of one thing?
  callbacks    is anything set up and paid off?
  drift        does each picture still show what its own line says?

Warnings, never blocks: a human (or Claude) decides. Wired into the
storyboard lint so it fires on import and on `POST /api/storyboard/lint`.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List

SCALES = ("extreme-wide", "wide diorama", "wide", "medium", "close",
          "macro", "overhead", "surveillance", "split")

STOP = set("""a an the is are was were be been being of in on at to for with and or but it its this
that those these he she they them his her their there here as by from into over under about not no
nor so than then when while who whom which what where why how all any both each few more most other
some such only own same too very can will just now""".split())


def _words(t: str) -> set:
    return {w for w in re.findall(r"[a-z']+", (t or "").lower())
            if w not in STOP and len(w) > 3}


def _scale_of(prompt: str) -> str:
    low = (prompt or "").lower()
    for s in SCALES:
        if s in low:
            return s
    return "unspecified"


def kind_of(scene: Dict) -> str:
    """What KIND of picture is this scene? Locked real media (a captured
    document, an archival photograph) is not a generated shot and must not be
    judged like one — it has nobody in it by design, and its prompt is a label,
    not a description."""
    f = (scene.get("image_file") or "")
    if scene.get("image_locked") or scene.get("no_video"):
        if "evidence" in f or scene.get("receipt"):
            return "document"
        if "archival" in f:
            return "archival"
        return "still"
    return "generated"


def check(board: Dict) -> List[str]:
    """Return composition warnings for a storyboard (never raises)."""
    scenes = board.get("scenes") or []
    video = board.get("video") or {}
    plan = video.get("visual_plan") or {}
    bible = board.get("character_bible") or []
    warns: List[str] = []
    n = len(scenes)
    if not n:
        return warns
    gen = [s for s in scenes if kind_of(s) == "generated"]

    # 1. was there a plan at all?
    if not plan:
        warns.append(
            "no video.visual_plan — this board was composed scene-by-scene. "
            "Read the whole script first and write the plan (spine, cast, "
            "world, motifs, callbacks, media budget): /compose-scenes LAW 0")

    # 2. is anyone on screen? (only GENERATED scenes can be judged: a captured
    # document or an archival photo has nobody in it BY DESIGN, and it is doing
    # the most important job in the video — proving the claim)
    if gen:
        people = sum(1 for s in gen
                     if re.search(r"\b(figure|figures|mannequin|man|woman|person|"
                                  r"people|crowd|officer|hand|hands)\b",
                                  (s.get("image_prompt") or ""), re.I))
        if people < len(gen) * 0.5:
            warns.append(
                f"only {people}/{len(gen)} GENERATED scenes have anyone on "
                f"screen — a wall of still-life props reads as a slideshow "
                f"(aim for 60%+ with a character DOING the line's verb)")

    # 3. do characters keep the same look?
    for c in bible:
        look = (c.get("description") or "").strip()
        name = c.get("name") or "?"
        if not look:
            continue
        key = " ".join(look.split()[:6]).lower()      # the look's fingerprint
        appears = [s for s in gen
                   if name.lower() in (s.get("image_prompt") or "").lower()
                   or key in (s.get("image_prompt") or "").lower()
                   or name in (s.get("characters") or [])]
        drifted = [s["id"] for s in appears
                   if key not in (s.get("image_prompt") or "").lower()]
        if len(appears) > 1 and drifted:
            warns.append(
                f"character “{name}” appears in {len(appears)} scenes but its "
                f"fixed look is not restated in scene(s) {drifted[:6]} — t2v has "
                f"no reference conditioning, so an unrestated character drifts")

    # 4. do spaces recur?
    spaces = Counter()
    for s in scenes:
        for m in re.finditer(r"\b(bedroom|office|courtroom|prison|street|hall|"
                             r"lobby|room|hangar|warehouse|kitchen|corridor)\b",
                             (s.get("image_prompt") or ""), re.I):
            spaces[m.group(1).lower()] += 1
    recurring = [k for k, v in spaces.items() if v >= 3]
    if not recurring and n >= 12:
        warns.append(
            "no space recurs 3+ times — the viewer never learns the geography. "
            "Pick 2-3 rooms and return to them (a world, not 40 hotel lobbies)")

    # 5. scale rhythm
    runs = 0
    prev, streak = None, 0
    for s in scenes:
        sc = _scale_of(s.get("image_prompt") or "")
        streak = streak + 1 if sc == prev and sc != "unspecified" else 1
        prev = sc
        if streak >= 3:
            runs += 1
    if runs:
        warns.append(f"{runs} run(s) of 3+ neighbouring scenes at the same "
                     f"framing — rotate scale (LAW 5)")

    # 6. media mix vs the plan's budget
    budget = plan.get("media_budget") or {}
    if budget:
        got = Counter()
        for s in scenes:
            k = kind_of(s)
            if k in ("document", "archival"):
                got[k] += 1
                continue
            p = (s.get("image_prompt") or "").lower()
            if "diorama" in p or "mannequin" in p or "reconstruction" in p:
                got["reconstruction"] += 1
            elif "map" in p:
                got["map"] += 1
        for kind, want in budget.items():
            have = got.get(kind, 0) / n
            if abs(have - float(want)) > 0.2:
                warns.append(f"media budget: plan wants {kind} at "
                             f"{float(want):.0%}, board has {have:.0%}")

    # 7. callbacks
    cbs = plan.get("callbacks") or []
    if plan and not cbs:
        warns.append("visual_plan has no callbacks — nothing is set up and paid "
                     "off, so the video has no shape")
    for cb in cbs:
        a, b = cb.get("setup"), cb.get("payoff")
        sa = next((s for s in scenes if s.get("id") == a), None)
        sb = next((s for s in scenes if s.get("id") == b), None)
        if not sa or not sb:
            warns.append(f"callback {a}->{b} points at a scene that does not exist")
        elif not (_words(sa.get("image_prompt")) & _words(sb.get("image_prompt"))):
            warns.append(f"callback {a}->{b}: the two shots share no visual "
                         f"element, so the payoff will not read")

    # 8. per-scene drift (the picture must still show ITS line)
    drift = []
    for s in gen:
        nw, iw = _words(s.get("narration")), _words(s.get("image_prompt"))
        if nw and iw and not (nw & iw):
            drift.append(s.get("id"))
    if gen and len(drift) > len(gen) * 0.45:
        warns.append(
            f"{len(drift)}/{len(gen)} generated scenes share no content word with their own "
            f"narration — some are legitimate metaphors, but check that the "
            f"picture still ANSWERS the line (scenes {drift[:8]}…)")
    return warns
