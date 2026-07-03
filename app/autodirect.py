"""Deterministic direction — make a bare storyboard fully directed.

The intelligence a video needs to LOOK edited (transition variety, stinger
placement, hero-scene selection, shot variety, the no-text rule, TTS-safe
punctuation) lives HERE — the WHICH-effect-WHEN choices come from the editable
``app/grammar.py`` dictionary (``data/effects_dictionary.json``), not whichever
LLM wrote the storyboard.
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

from . import grammar, sfx
from .scenes import estimate_duration

HOOK_SECONDS = 30.0          # the window that must carry the densest editing

# Transition rotations, shot variety and keyword→cue mappings all live in the
# editable grammar dictionary now (app/grammar.py -> data/effects_dictionary.json)
# so "when to use which effect" is one JSON, shared with the audio scorer.


def _word_count(t: str) -> int:
    return len(re.findall(r"\w+", t or ""))


def _pick_cue(text: str) -> str:
    return grammar.pick_cue(text)


# --- assisted mode (small-model authoring, e.g. Haiku) -----------------------
# In "assisted" mode the director may REWRITE weak structure, not just fill
# gaps: an overlong cold open gets trimmed to a hard hook, rambling scenes are
# split into extra cuts. Runs before the fill pass so new scenes get directed
# like any other. Pro mode never touches author text beyond punctuation.
_SENT_RE = re.compile(r"(?<=[.!?…])\s+")


def _trim_hook(text: str, max_words: int = 12):
    """Shorten an overlong opening line at a sentence/clause boundary."""
    if _word_count(text) <= max_words + 2:
        return None
    first = _SENT_RE.split(text.strip())[0].strip()
    if 3 <= _word_count(first) <= max_words + 2:
        return first if first[-1:] in ".!?…" else first + "."
    cut = None
    for m in re.finditer(r"[,;:—–-]", text):
        if _word_count(text[: m.start()]) <= max_words:
            cut = m.start()
        else:
            break
    if cut and _word_count(text[:cut]) >= 4:
        return text[:cut].rstrip() + "."
    return None


def _split_scene(s: Dict):
    """Split a long multi-sentence scene into two cuts near its word midpoint."""
    narr = (s.get("narration") or "").strip()
    if _word_count(narr) <= 26:
        return None
    sents = [x.strip() for x in _SENT_RE.split(narr) if x.strip()]
    if len(sents) < 2:
        return None
    total, acc, best_i, best_gap = _word_count(narr), 0, None, 1e9
    for i in range(len(sents) - 1):
        acc += _word_count(sents[i])
        gap = abs(acc - total / 2)
        if gap < best_gap:
            best_gap, best_i = gap, i
    a = " ".join(sents[: best_i + 1])
    b = " ".join(sents[best_i + 1:])
    if _word_count(a) < 6 or _word_count(b) < 6:
        return None
    s1, s2 = dict(s), dict(s)
    s1["narration"], s2["narration"] = a, b
    ip = (s.get("image_prompt") or "").strip()
    if ip:
        s2["image_prompt"] = ip + " — a different moment, alternate angle and composition"
    # scene B is a fresh cut: clear directing fields so the fill pass re-picks
    for k in ("transition", "shot", "audio_cue", "motion_type", "motion_prompt"):
        s2[k] = ""
    for sc in (s1, s2):
        for k in ("start_sec", "end_sec", "duration_sec"):
            sc.pop(k, None)               # re-pace both halves from narration
    return s1, s2


def _assist(scenes: List[Dict], video: Dict, fixes: List[str]) -> List[Dict]:
    if scenes:
        trimmed = _trim_hook(scenes[0].get("narration") or "")
        if trimmed:
            scenes[0]["narration"] = trimmed
            fixes.append(f"assist: cold open trimmed to a hard hook — '{trimmed}'")
    out: List[Dict] = []
    splits = 0
    for s in scenes:
        pair = _split_scene(s) if splits < 8 else None
        if pair:
            splits += 1
            fixes.append(f"scene {s.get('id')}: long narration split into two cuts (assist)")
            out.extend(pair)
        else:
            out.append(s)
    if splits:
        remap: Dict = {}
        for i, s in enumerate(out):
            old = s.get("id")
            if old is not None and old not in remap:
                remap[old] = i + 1
            s["id"] = i + 1
        if video.get("thumbnail_scene") in remap:
            video["thumbnail_scene"] = remap[video["thumbnail_scene"]]
        fixes.append(f"assist: scenes renumbered 1..{len(out)} after {splits} split(s)")
    return out


def direct(raw: Dict, *, default_style: str | None = None,
           strict: bool = False, coverage: str = "heroes") -> Tuple[Dict, Dict]:
    """Fill every empty directing field; return (storyboard, report).

    ``default_style`` (usually the project's channel art direction) wins over
    the built-in flat-cartoon fallback when the storyboard declares no style.
    ``strict`` enables assisted mode: structural rewrites for weak-model
    scripts (hook trimming, long-scene splitting).
    ``coverage`` decides which scenes get flagged for Wan animation:
    "heroes" (budgeted — every scene still cuts to a fresh moving visual via
    parallax/Ken Burns), "all" (every scene gets a real clip; ~3.5 min GPU per
    scene at balanced), or "none".
    """
    sb = dict(raw or {})
    video = dict(sb.get("video") or {})
    scenes = [dict(s) for s in (sb.get("scenes") or [])]
    fixes: List[str] = []
    warnings: List[str] = []

    if not (video.get("global_style_suffix") or "").strip():
        if (default_style or "").strip():
            video["global_style_suffix"] = default_style.strip()
            fixes.append("video: empty global_style_suffix -> channel art direction")
        else:
            from . import config
            video["global_style_suffix"] = config.KREA2_STYLE
            fixes.append("video: empty global_style_suffix -> flat-cartoon preset")

    if strict:
        scenes = _assist(scenes, video, fixes)

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
    # animation coverage: "all" = a real clip on every scene (viewer-retention
    # maximalist — costly), "heroes" = budgeted (dense for short videos, grows
    # slowly for long ones), "none" = parallax/Ken Burns carry all motion.
    ns = len(scenes)
    if coverage == "all":
        heroes = set(range(ns))
    elif coverage == "none":
        heroes = set()
    else:
        hero_budget = (max(3, min(10, ns // 4)) if ns <= 60
                       else min(16, 10 + (ns - 60) // 30))
        # hero scenes get motion: scene 1, then the longest scenes spread out
        by_len = sorted(range(ns),
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

        beat = grammar.beat_of(f"{narr} {s.get('image_prompt')}")
        if not (s.get("transition") or "").strip():
            # A detected story beat picks its signature cut (reveal→flash,
            # impact→smash…); otherwise rotate the hook/body set, never repeating.
            pick = grammar.transition_for_beat(beat) if beat else ""
            if not pick or pick == last_transition:
                cycle = grammar.transitions(i in hook_idx)
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
            shots = grammar.shots()
            s["shot"] = shots[i % len(shots)]

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
            if total > 650:
                warnings.append(f"long script ({total} words): one-take TTS can "
                                f"drift past ~5 min — spot-check the QA transcript "
                                f"extra carefully (chapter takes are the next fix "
                                f"if it drifts)")
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

    # retention: a long stretch on one motionless image is where viewers leave
    for s in scenes:
        est = estimate_duration(s.get("narration") or "")
        if est > 18.0 and (s.get("motion_type") or "") not in ("ambient", "transform"):
            warnings.append(f"scene {s.get('id')}: ~{est:.0f}s on a single still "
                            f"— split the narration or flag motion_type ambient")

    sb["video"] = video
    sb["scenes"] = scenes
    report = {"fixes": fixes, "warnings": warnings, "stats": stats,
              "mode": "assisted" if strict else "standard"}
    return sb, report
