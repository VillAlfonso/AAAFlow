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
                 "crash zoom", "whip-pan left", "flash cut", "dip to white"],
        "body": ["hard cut", "push-in", "crossfade", "whip-pan right",
                 "hard cut", "pull-back", "drop-in", "fade", "dip to white"],
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
    # WORD-level emphasis: the auto-director marks 0-1 phrases per scene
    # (writer *markup* wins, else these detectors), the assembler lands a micro
    # effect + a tiny tick exactly on the spoken word via the Whisper word
    # timestamps of the one-take narration.
    "emphasis": {
        "max_per_scene": 1,
        "min_gap_s": 2.5,
        "detect_numbers": True,
        "detect_words": ["never", "no one", "nobody", "nothing", "alone",
                         "vanished", "vanish", "gone", "disappeared",
                         "impossible", "dead", "died", "last", "first", "only",
                         "secret", "cursed", "every", "none", "wrong", "lie",
                         "lied", "empty", "silent", "locked", "missing"],
        "effects": ["zoom_bump", "flash_soft", "shake_micro"],
        "by_beat": {"impact": "shake_micro", "reveal": "flash_soft",
                    "money": "zoom_bump"},
        "sfx": {"cue": "pop", "volume": 0.16},
        "why": ("the words a human editor punches — absolutes, numbers, the "
                "load-bearing noun — get a ~0.4 s zoom bump / soft flash / "
                "micro shake timed to the spoken word, so emphasis is HEARD "
                "and SEEN together"),
    },
    # Whole-scene overlay FX on the beats that matter (hero scenes only by
    # default so it stays an event, not wallpaper).
    "scene_fx": {
        "by_beat": {"reveal": "letterbox", "impact": "vignette"},
        "hero_only": True,
        "why": ("cinema frames its big moments: bars on a reveal say LOOK, a "
                "darkened edge on an impact closes in — used sparingly they "
                "read as intent, everywhere they read as a filter"),
    },
    # Video-wide film looks the assembler can wear (preset/assemble "filter").
    "filters": {
        "vhs": {"grain": 0.035, "scanlines": 0.055, "bleed_px": 2,
                "wobble_every_s": 2.8, "lift": 7, "bottom_tear": True,
                "why": ("analog memory: grain, scanlines, chroma fringe and a "
                        "tracking wobble — found-footage dread that also melts "
                        "the last AI smoothness out of the frames")},
        "why": "applied LAST per scene so flashes, chips and receipts wear it too",
    },
    # Cinematic GRADE — the "Lumetri" pass a pro editor adds LAST, over the
    # finished mp4 (app/grade.py, one ffmpeg filter_complex): film colour +
    # halation bloom + vignette + fine grain. It's a POST-process, so it
    # upgrades any render without a re-assemble. mood/channel/preset picks the
    # look; Menagerie wears "ember" to deepen its ember-glow art direction.
    "grades": {
        "by_mood": {"dark": "ember", "tense": "noir", "money": "warm",
                    "calm": "soft", "emotional": "warm", "neutral": "cinematic",
                    "default": "cinematic"},
        "looks": {
            "ember": {"why": "Menagerie: gold ember highlights over crushed cool "
                      "shadows, soft halation bloom, heavy vignette, fine grain",
                      "contrast": 1.11, "saturation": 1.04, "gamma": 0.93,
                      "brightness": -0.010, "shadows": [-0.05, -0.02, 0.06],
                      "mids": [0.02, 0.0, -0.02], "highlights": [0.09, 0.035, -0.07],
                      "glow": 0.36, "glow_sigma": 15, "glow_lift": 0.02,
                      "vignette": 0.74, "grain": 9},
            "cinematic": {"why": "default film grade — teal shadows, warm "
                          "highlights, mild bloom",
                          "contrast": 1.09, "saturation": 1.08, "gamma": 0.97,
                          "brightness": 0.0, "shadows": [-0.04, 0.0, 0.05],
                          "mids": [0.0, 0.0, 0.0], "highlights": [0.06, 0.03, -0.05],
                          "glow": 0.26, "glow_sigma": 12, "glow_lift": 0.02,
                          "vignette": 0.55, "grain": 6},
            "noir": {"why": "cold desaturated thriller — high contrast, heavy "
                     "vignette", "contrast": 1.18, "saturation": 0.72,
                     "gamma": 0.95, "brightness": -0.015, "shadows": [-0.03, 0.0, 0.04],
                     "mids": [0.0, 0.0, 0.01], "highlights": [-0.02, 0.0, 0.03],
                     "glow": 0.20, "glow_sigma": 10, "glow_lift": 0.0,
                     "vignette": 0.85, "grain": 8},
            "warm": {"why": "golden-hour warmth for money / emotional beats",
                     "contrast": 1.06, "saturation": 1.10, "gamma": 0.99,
                     "brightness": 0.005, "shadows": [0.02, 0.0, -0.02],
                     "mids": [0.02, 0.0, -0.02], "highlights": [0.08, 0.04, -0.06],
                     "glow": 0.30, "glow_sigma": 13, "glow_lift": 0.03,
                     "vignette": 0.45, "grain": 5},
            "soft": {"why": "gentle low-contrast calm look, airy bloom, light grain",
                     "contrast": 1.02, "saturation": 1.03, "gamma": 1.02,
                     "brightness": 0.01, "shadows": [0.02, 0.02, 0.03],
                     "mids": [0.0, 0.0, 0.0], "highlights": [0.03, 0.03, 0.0],
                     "glow": 0.34, "glow_sigma": 18, "glow_lift": 0.03,
                     "vignette": 0.35, "grain": 4},
            "none": {"why": "no grade"},
        },
        "why": ("amateur footage looks flat; a pro grades it — crushed shadows, "
                "warm highlights, a soft bloom on the brights, a vignette that "
                "holds the eye, and grain that kills the last digital cleanliness"),
    },
    # Typeset date stamps on year/backstory jumps (the ONE sanctioned on-screen
    # text besides receipt stills — user amendment 2026-07-05). Real fonts,
    # composited by the assembler, land with a tiny click.
    "date_chip": {
        "enabled": True,
        "why": ("a date appearing exactly as the narrator says it is the "
                "cleanest signpost there is — the viewer never loses WHEN"),
    },
    # The receipt move's tunables (renderer defaults in app/receipts.py).
    "receipt": {
        "tilt_deg": -1.8, "float_px": 7, "zoom_ease_s": 0.9,
        "highlight_color": [255, 214, 60], "highlight_alpha": 0.42,
        "why": ("a real editor never pastes a flat screenshot: it floats, "
                "tilts, breathes, then the camera commits to the exact line "
                "as the narrator reads it — receipts should feel HANDLED"),
    },
    # DIRECTION CARDS — the anti-factory dial (user, 2026-07-05: "one video
    # should really be distinguishable from the next; keep some rules, let
    # some creative things happen"). Each video draws ONE card that bends the
    # whole build: how the hook opens, how it ends, a shifted cut rhythm, a
    # different camera energy. The writer follows hook_style/ending; the
    # director + assembler apply the offsets. Same grammar, different meal.
    "direction_cards": {
        "cards": [
            {"id": "cold-fact", "hook_style": "open on the single most absurd "
             "TRUE fact, stated flat, ≤12 words", "ending": "gut-punch callback "
             "to the opening fact", "transition_offset": 0,
             "emphasis_offset": 0, "kb_strength": 1.0},
            {"id": "in-medias-res", "hook_style": "open mid-moment — someone is "
             "already doing something at a specific time of night",
             "ending": "freeze on the question the story never answered",
             "transition_offset": 2, "emphasis_offset": 1, "kb_strength": 1.1},
            {"id": "object-first", "hook_style": "open on the OBJECT (the "
             "exhibit) in unsettling detail before any people appear",
             "ending": "return to the object, changed by what we now know",
             "transition_offset": 4, "emphasis_offset": 2, "kb_strength": 0.85},
            {"id": "question-first", "hook_style": "open with the unanswerable "
             "question itself, then make the viewer need it answered",
             "ending": "give half the answer; admit the missing half",
             "transition_offset": 1, "emphasis_offset": 1, "kb_strength": 1.05},
            {"id": "countdown", "hook_style": "open with a clock — 'X hours "
             "before…' — and let timestamps structure the acts",
             "ending": "the clock stops where the record stops",
             "transition_offset": 3, "emphasis_offset": 2, "kb_strength": 0.95},
        ],
        "why": ("a fixed formula reads as a factory; a drawn card varies the "
                "skeleton (open, rhythm, camera, ending) while every hard rule "
                "still holds — videos stay siblings, not clones"),
    },
    # Every effect name the assembler can actually execute, in one place. If a
    # name isn't here, no rule should reference it; teach new reflexes by
    # pointing rules at these (or add an implementation first).
    "catalog": {
        "transitions": {
            "hard cut": "the default — invisible, keeps pace",
            "smash cut": "abrupt over-zoom entrance for hard consequences",
            "punch-in": "snappy zoom-in, transaction/payoff energy",
            "crash zoom": "violent near-instant zoom slam — the single biggest fact",
            "whip-pan left/right": "scene whips in from an edge — movement, travel",
            "push-in": "slow settle zoom-in — leaning closer to the story",
            "pull-back": "settle zoom-out — revealing context",
            "crossfade / fade": "breath between acts, passage of time",
            "flash cut": "white flash frame — reveals, realizations",
            "black flash": "2-frame dip to black — the edit blinks, the beat lands",
            "dip to white": "incoming scene blooms out of a bright frame — revelations",
            "glitch": "RGB tear + slice jitter — wrongness, tech, corruption",
            "drop-in": "scene slams down from above — verdicts, doors, endings",
            "iris": "zoom + fade combo, old-cinema flavor",
            "shake": "decaying impact jitter on entry",
        },
        "scene_fx": {
            "letterbox": "cinema bars for the scene — reveals, climaxes",
            "vignette": "darkened edges — dread, focus, closing in",
        },
        "receipt": ("evidence screenshots float in as a tilted card, the camera "
                    "eases into the referenced region ON the spoken word, and a "
                    "marker highlight sweeps the quote (app/receipts.py; scene "
                    "needs image_file + receipt{focus,highlight,sync})"),
        "filters": {"vhs": "grain + scanlines + chroma fringe + tracking wobble "
                           "— whole-video analog look (preset/assemble filter)"},
        "grade": {"note": "cinematic 'Lumetri' pass over the FINISHED render "
                          "(app/grade.py, one ffmpeg filter_complex) — film "
                          "colour + halation bloom + vignette + grain; 5 looks "
                          "(ember/cinematic/noir/warm/soft), mood/channel picks",
                  "ember": "Menagerie: gold highlights, crushed cool shadows, "
                           "soft bloom, heavy vignette, fine grain"},
        "date_chip": "typeset year/date stamp + click on time jumps (auto-"
                     "detected from narration; scene date_chip field)",
        "emphasis": {
            "zoom_bump": "+5% zoom over ~0.4 s on the word, then settle",
            "flash_soft": "2-frame 30% white flash on the word",
            "shake_micro": "tiny decaying jitter on the word",
        },
        "why": "the assembler's full vocabulary — the WHEN lives in the rules above",
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


def emphasis_cfg() -> Dict:
    """The word-level emphasis config (merged over defaults)."""
    return {**DEFAULT_GRAMMAR["emphasis"], **(_load().get("emphasis") or {})}


def direction_cards() -> List[Dict]:
    cfg = {**DEFAULT_GRAMMAR["direction_cards"],
           **(_load().get("direction_cards") or {})}
    return list(cfg.get("cards") or [])


def scene_fx_for(beat: str) -> str:
    """Whole-scene FX name for a story beat ("" = none)."""
    cfg = {**DEFAULT_GRAMMAR["scene_fx"], **(_load().get("scene_fx") or {})}
    return (cfg.get("by_beat") or {}).get(beat, "")


def scene_fx_hero_only() -> bool:
    cfg = {**DEFAULT_GRAMMAR["scene_fx"], **(_load().get("scene_fx") or {})}
    return bool(cfg.get("hero_only", True))


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


def grades() -> Dict:
    """The cinematic-grade section (looks + mood map), merged over defaults."""
    return {**DEFAULT_GRAMMAR["grades"], **(_load().get("grades") or {})}


def grade_for(mood: str) -> str:
    """Film-look name for a mood label (grades.by_mood → 'ember'/'noir'/…)."""
    bm = grades().get("by_mood") or {}
    return bm.get((mood or "").lower(), bm.get("default", "cinematic"))
