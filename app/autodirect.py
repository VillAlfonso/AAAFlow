"""Deterministic direction — make a bare storyboard fully directed.

The intelligence a video needs to LOOK edited (transition variety, stinger
placement, hero-scene selection, shot variety, the no-text rule, TTS-safe
punctuation) lives HERE, in code, not in whichever LLM wrote the storyboard.
A minimal storyboard — title + scenes with narration and an image subject —
comes out the other side with every directing field filled. Fields the author
DID provide are never overwritten, so a strong model (or a human) can still
out-direct the defaults; a weak model simply can't produce an undirected video.

Runs automatically on project import; also exposed as POST /api/storyboard/lint
(report + optional fixed copy).
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from . import sfx
from .scenes import estimate_duration

HOOK_SECONDS = 30.0          # the window that must carry the densest editing

# Transition rotations (never two identical in a row). Hook = punchy set.
_HOOK_TRANSITIONS = ["smash cut", "whip-pan right", "punch-in", "hard cut",
                     "whip-pan left", "flash cut"]
_BODY_TRANSITIONS = ["hard cut", "push-in", "crossfade", "whip-pan right",
                     "hard cut", "pull-back", "fade"]

# Shot rotation → drives parallax camera-move variety downstream.
_SHOTS = ["wide establishing", "medium", "close-up", "low angle", "macro detail",
          "three-quarter medium"]

# keyword → audio_cue (cue text is matched against the SFX library tags later,
# so these stay valid even when the library grows).
_CUE_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("cash", "money", "bill", "paid", "bribe", "fortune", "price", "sold",
      "bought", "reward"), "cash register ding"),
    (("reveal", "secret", "hidden", "trick", "twist", "actually", "truth"),
     "shimmering riser"),
    (("crash", "arrest", "caught", "busted", "slam", "fell", "collapse",
      "boom", "explode"), "deep impact boom"),
    (("ran", "fled", "escape", "train", "chase", "vanish", "jump", "climb",
      "rush", "race"), "quick whoosh"),
    (("pop", "tiny", "small", "appear"), "pop"),
]


def _word_count(t: str) -> int:
    return len(re.findall(r"\w+", t or ""))


def _pick_cue(text: str) -> str:
    low = (text or "").lower()
    for keys, cue in _CUE_RULES:
        if any(k in low for k in keys):
            return cue
    return ""


def direct(raw: Dict) -> Tuple[Dict, Dict]:
    """Fill every empty directing field; return (storyboard, report)."""
    sb = dict(raw or {})
    video = dict(sb.get("video") or {})
    scenes = [dict(s) for s in (sb.get("scenes") or [])]
    fixes: List[str] = []
    warnings: List[str] = []

    if not (video.get("global_style_suffix") or "").strip():
        from . import config
        video["global_style_suffix"] = config.KREA2_STYLE
        fixes.append("video: empty global_style_suffix -> flat-cartoon preset")

    # cumulative planned time decides which scenes sit inside the hook window
    t = 0.0
    hook_idx: List[int] = []
    starts: List[float] = []
    for i, s in enumerate(scenes):
        starts.append(t)
        if t < HOOK_SECONDS:
            hook_idx.append(i)
        t += estimate_duration(s.get("narration") or "")

    last_transition = ""
    hero_budget = max(3, min(10, len(scenes) // 4))
    # hero scenes get motion: first scene, then the longest scenes spread out
    by_len = sorted(range(len(scenes)),
                    key=lambda i: -_word_count(scenes[i].get("narration") or ""))
    heroes = {0} | set(by_len[: hero_budget - 1])

    for i, s in enumerate(scenes):
        sid = s.get("id", i + 1)
        narr = (s.get("narration") or "").strip()

        # TTS-safe punctuation: trailing commas invite hallucinated continuations
        if narr.endswith(","):
            s["narration"] = narr[:-1] + "."
            fixes.append(f"scene {sid}: narration ended with ',' -> '.'")
        elif narr and narr[-1] not in ".!?…\"'":
            s["narration"] = narr + "."
            fixes.append(f"scene {sid}: added terminal period to narration")

        # the no-burned-text rule is absolute
        if (s.get("on_screen_text") or "").strip():
            s["on_screen_text"] = ""
            fixes.append(f"scene {sid}: cleared on_screen_text (never rendered)")

        if not (s.get("image_prompt") or "").strip():
            base = (s.get("visual") or s.get("narration") or "").strip()
            if base:
                s["image_prompt"] = f"Clear single-subject illustration of: {base}"
                warnings.append(f"scene {sid}: image_prompt synthesized from "
                                f"narration — a real prompt would look better")

        if not (s.get("transition") or "").strip():
            cycle = _HOOK_TRANSITIONS if i in hook_idx else _BODY_TRANSITIONS
            pick = cycle[i % len(cycle)]
            if pick == last_transition:
                pick = cycle[(i + 1) % len(cycle)]
            s["transition"] = pick
            fixes.append(f"scene {sid}: transition -> {pick}")
        last_transition = s["transition"]

        if not (s.get("audio_cue") or "").strip():
            cue = _pick_cue(f"{s.get('narration')} {s.get('image_prompt')}")
            if not cue and i in hook_idx and i > 0:
                cue = "quick whoosh"        # hook cuts always carry energy
            if cue:
                s["audio_cue"] = cue
                fixes.append(f"scene {sid}: audio_cue -> {cue}")

        if not (s.get("shot") or "").strip():
            s["shot"] = _SHOTS[i % len(_SHOTS)]

        if not (s.get("motion_type") or "").strip() and i in heroes:
            s["motion_type"] = "ambient"
            fixes.append(f"scene {sid}: flagged as hero (ambient motion)")

    # --- lint-only observations ---------------------------------------------
    if scenes:
        first = _word_count(scenes[0].get("narration") or "")
        if first > 14:
            warnings.append(f"hook: scene 1 narration is {first} words — open "
                            f"with <= 12 for a hard hook")
        hook_words = sum(_word_count(scenes[i].get("narration") or "")
                         for i in hook_idx)
        if hook_idx and hook_words / max(len(hook_idx), 1) > 16:
            warnings.append("hook: first-30s scenes average > 16 words — cut "
                            "faster (aim 6-12 words/scene)")
        total = sum(_word_count(s.get("narration") or "") for s in scenes)
        if total:
            est = total / 2.6 + len(scenes) * 0.4
            stats = {"scenes": len(scenes), "words": total,
                     "est_runtime_sec": round(est, 1),
                     "hook_scenes": len(hook_idx)}
        else:
            stats = {"scenes": len(scenes), "words": 0}
            warnings.append("no narration anywhere — nothing to voice")
    else:
        stats = {"scenes": 0}
        warnings.append("storyboard has no scenes")

    # unknown audio cues (won't match the library OR the synth fallback)
    for s in scenes:
        cue = (s.get("audio_cue") or "").strip()
        if cue and sfx.classify(cue) is None and sfx._match_library(cue) is None:
            warnings.append(f"scene {s.get('id')}: audio_cue '{cue}' matches no "
                            f"library tag or synth — it will be silent")

    sb["video"] = video
    sb["scenes"] = scenes
    report = {"fixes": fixes, "warnings": warnings, "stats": stats}
    return sb, report
