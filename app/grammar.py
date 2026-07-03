"""The cinematic grammar — one editable dictionary of WHEN to use WHICH effect.

``data/effects_dictionary.json`` is the single source of truth for the
deterministic "this video looks *edited*" decisions the auto-director and the
audio scorer make on every import/produce:

* **sfx_cues**   — a narration beat (money / reveal / impact / motion / small)
                   → the stinger cue that punctuates it.
* **transitions**— which cut to use (a punchy hook set, a calmer body set, and
                   a per-beat override so a reveal flashes and an impact smashes).
* **shots**      — the camera-variety rotation that drives parallax moves.
* **music_moods**— a script's tone (dark / tense / money / calm / emotional)
                   → the mood label + a library/generation query.
* **motion**     — which story beats deserve a real moving (hero) clip.

Everything carries a ``why`` so it reads like a playbook — when a human (or
Claude, asked to "make me a video") wants to know *why* a beat got a certain
sound or cut, it's written here, and teaching the system a new reflex is a
one-JSON edit (or ``PUT /api/effects_dictionary``), never a code change.

The file is seeded from ``DEFAULT_GRAMMAR`` on first load and force-merged over
the defaults each load, so new built-in keys appear without wiping user edits.
This module is standalone (no app imports beyond config/storage) so autodirect
and score can both depend on it without a cycle.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import config, storage

DICT_FILE = config.DATA_DIR / "effects_dictionary.json"

# ---------------------------------------------------------------------------
# The built-in grammar. Edited copies live in data/effects_dictionary.json;
# these are the seed + the fallback when that file is missing/corrupt.
# ---------------------------------------------------------------------------
DEFAULT_GRAMMAR: Dict = {
    "version": 1,
    "note": ("WHEN→WHICH effect map. Edit freely (UI: Settings · Effects grammar, "
             "or PUT /api/effects_dictionary). autodirect + score read this on "
             "every video. First matching rule wins; keep the punchiest beats first."),
    # A beat is detected by keyword; it drives BOTH the SFX cue and (optionally)
    # the transition override, so a "reveal" line flashes AND shimmers.
    "sfx_cues": [
        {"beat": "money", "cue": "cash register ding",
         "when": ["cash", "money", "bill", "paid", "bribe", "fortune", "price",
                  "sold", "bought", "reward", "rich", "gold", "profit"],
         "why": "a transaction / payoff beat lands on a register ding"},
        {"beat": "reveal", "cue": "shimmering riser",
         "when": ["reveal", "secret", "hidden", "trick", "twist", "actually",
                  "truth", "turns out", "but then"],
         "why": "a turn or reveal builds on a riser that ENDS on the cut"},
        {"beat": "impact", "cue": "deep impact boom",
         "when": ["crash", "arrest", "caught", "busted", "slam", "fell",
                  "collapse", "boom", "explode", "death", "died", "shot"],
         "why": "a hard consequence hits on a low boom"},
        {"beat": "motion", "cue": "quick whoosh",
         "when": ["ran", "fled", "escape", "train", "chase", "vanish", "jump",
                  "climb", "rush", "race", "flew", "drove"],
         "why": "movement / travel carries a whoosh into the cut"},
        {"beat": "small", "cue": "pop",
         "when": ["pop", "tiny", "small", "appear", "blink", "click"],
         "why": "a small appearance gets a light pop"},
    ],
    "transitions": {
        # never two identical in a row; hook window is punchier than the body.
        "hook": ["smash cut", "whip-pan right", "punch-in", "hard cut",
                 "whip-pan left", "flash cut"],
        "body": ["hard cut", "push-in", "crossfade", "whip-pan right",
                 "hard cut", "pull-back", "fade"],
        # a detected beat overrides the rotation (this is the "more apparent
        # when to use which transition" the system now encodes explicitly).
        "by_beat": {
            "reveal": "flash cut",
            "impact": "smash cut",
            "motion": "whip-pan right",
            "money": "punch-in",
        },
        "default": "hard cut",
        "why": "hook cuts fast & hard; the body breathes; a story beat overrides both",
    },
    "shots": ["wide establishing", "medium", "close-up", "low angle",
              "macro detail", "three-quarter medium"],
    "motion": {
        "hero_beats": ["hook", "reveal", "impact", "climax", "payoff"],
        "why": "budgeted real (moving) clips go to the beats a viewer must feel",
    },
    "music_moods": [
        {"mood": "dark", "query": "dark cinematic tension ambient brooding",
         "when": ["death", "die", "dead", "murder", "kill", "dark", "fear",
                  "haunt", "grief", "cold", "tragedy", "collapse", "ruin",
                  "war", "blood", "grave"],
         "why": "loss / dread → low, brooding underscore"},
        {"mood": "money", "query": "cinematic corporate suspense understated",
         "when": ["money", "fortune", "rich", "gold", "empire", "million",
                  "billion", "luxury", "profit", "deal", "market", "fraud",
                  "scheme"],
         "why": "greed / stakes → cool, understated suspense"},
        {"mood": "tense", "query": "tense driving suspense percussion cinematic",
         "when": ["run", "chase", "escape", "race", "heist", "steal", "fight",
                  "danger", "hunt", "attack", "explode", "crash"],
         "why": "action / danger → driving percussion"},
        {"mood": "calm", "query": "calm ambient atmospheric underscore soft",
         "when": ["space", "ocean", "star", "dream", "calm", "quiet", "gentle",
                  "night", "sleep", "wonder", "deep", "silence", "vast"],
         "why": "awe / stillness → soft, spacious ambient"},
        {"mood": "emotional", "query": "emotional piano cinematic reflective",
         "when": ["love", "loss", "memory", "home", "heart", "hope", "alone",
                  "goodbye", "remember", "fell"],
         "why": "sentiment → reflective piano"},
    ],
    "default_mood": {"mood": "neutral",
                     "query": "cinematic underscore ambient instrumental"},
}


# ---------------------------------------------------------------------------
def _load() -> Dict:
    """The active grammar: user file force-merged over defaults (missing/corrupt
    → defaults), then re-seeded so the file always exists and stays forward-
    compatible with new built-in keys."""
    data = storage.read_json(DICT_FILE, None)
    if not isinstance(data, dict) or "sfx_cues" not in data:
        storage.write_json(DICT_FILE, DEFAULT_GRAMMAR)
        return dict(DEFAULT_GRAMMAR)
    merged = {**DEFAULT_GRAMMAR, **data}          # user keys win; new keys appear
    return merged


def dictionary() -> Dict:
    return _load()


def save(patch: Dict) -> Dict:
    """Replace the grammar (validated shallowly) and persist it."""
    if not isinstance(patch, dict):
        raise ValueError("grammar must be an object")
    cur = _load()
    cur.update(patch)
    if not isinstance(cur.get("sfx_cues"), list):
        raise ValueError("sfx_cues must be a list")
    storage.write_json(DICT_FILE, cur)
    return cur


def reset() -> Dict:
    storage.write_json(DICT_FILE, DEFAULT_GRAMMAR)
    return dict(DEFAULT_GRAMMAR)


# --- lookups (used by autodirect + score) -----------------------------------
def beat_of(text: str) -> str:
    """The narration beat this line reads as (money/reveal/impact/motion/small),
    or "" if none — same matcher the SFX + transition overrides key off."""
    low = (text or "").lower()
    for rule in _load().get("sfx_cues", []):
        if any(k in low for k in rule.get("when", [])):
            return rule.get("beat", "")
    return ""


def pick_cue(text: str) -> str:
    low = (text or "").lower()
    for rule in _load().get("sfx_cues", []):
        if any(k in low for k in rule.get("when", [])):
            return rule.get("cue", "")
    return ""


def transitions(hook: bool) -> List[str]:
    tr = _load().get("transitions", {})
    key = "hook" if hook else "body"
    return list(tr.get(key) or DEFAULT_GRAMMAR["transitions"][key])


def transition_default() -> str:
    return _load().get("transitions", {}).get("default", "hard cut")


def transition_for_beat(beat: str) -> str:
    return (_load().get("transitions", {}).get("by_beat", {}) or {}).get(beat, "")


def shots() -> List[str]:
    return list(_load().get("shots") or DEFAULT_GRAMMAR["shots"])


def hero_beats() -> List[str]:
    return list((_load().get("motion") or {}).get("hero_beats")
                or DEFAULT_GRAMMAR["motion"]["hero_beats"])


def mood_for(text: str) -> Tuple[str, str]:
    """(mood_label, search/generation query) for a script's tone."""
    low = (text or "").lower()
    best, hits = None, 0
    for rule in _load().get("music_moods", []):
        n = sum(1 for k in rule.get("when", []) if k in low)
        if n > hits:
            best, hits = rule, n
    if best:
        return best.get("mood", "neutral"), best.get("query", "")
    dm = _load().get("default_mood") or DEFAULT_GRAMMAR["default_mood"]
    return dm.get("mood", "neutral"), dm.get("query", "")
