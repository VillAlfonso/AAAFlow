"""Parse the storyboard JSON format into normalized scenes.

The format (see weimar_hyperinflation_scenes.json) is::

    { "video":  { ...metadata, global_style_suffix, global_negative_prompt... },
      "scenes": [ { id, narration, image_prompt, on_screen_text, start_sec,
                    end_sec, duration_sec, transition, ... }, ... ] }

This module is deliberately tolerant: only ``scenes`` with some narration/prompt
is required; everything else has sensible fallbacks so other storyboards in the
same shape import cleanly.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Words-per-second the storyboard assumes for its TTS-paced estimates
# (see the JSON's _pipeline_notes). Used only to estimate a planned duration
# when the JSON doesn't give one.
WORDS_PER_SEC = 2.6
MIN_SCENE_SEC = 1.2

# Verbatim text fields carried through for display + assembly.
TEXT_FIELDS = (
    "act", "shot", "timecode", "narration", "visual", "image_prompt",
    "on_screen_text", "text_anim", "character_action", "transition", "audio_cue",
)


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # reject NaN
    except (TypeError, ValueError):
        return None


def _word_count(text: str) -> int:
    return len([w for w in re.findall(r"\w+", text or "")])


def estimate_duration(narration: str) -> float:
    """Fallback planned duration from word count (matches the JSON's pacing rule)."""
    words = _word_count(narration)
    return round(max(MIN_SCENE_SEC, words / WORDS_PER_SEC + 0.4), 2)


def normalize_scene(raw: Dict, index: int) -> Dict:
    """One raw scene dict -> a normalized scene with planned timing + asset slots."""
    raw = raw or {}
    sid = raw.get("id", index + 1)
    narration = (raw.get("narration") or "").strip()

    start = _num(raw.get("start_sec"))
    end = _num(raw.get("end_sec"))
    dur = _num(raw.get("duration_sec"))
    if dur is None and start is not None and end is not None:
        dur = round(end - start, 2)
    if dur is None or dur <= 0:
        dur = estimate_duration(narration)
    if start is None:
        start = 0.0
    if end is None:
        end = round(start + dur, 2)

    scene = {field: (raw.get(field) or "") for field in TEXT_FIELDS}
    scene["id"] = sid
    scene["narration"] = narration
    scene["planned_start"] = round(start, 3)
    scene["planned_end"] = round(end, 3)
    scene["planned_dur"] = round(dur, 3)

    # Pipeline / asset state, filled in by the voiceover + image phases.
    scene["audio_file"] = None        # relative to the project dir, e.g. audio/scene_0001.wav
    scene["audio_dur"] = None         # real measured seconds
    scene["audio_voice"] = None       # label of the voice used
    scene["image_file"] = None        # images/scene_0001.png
    scene["image_seed"] = None
    scene["image_meta"] = None
    # v2 storyboard fields — carried through for the future animation/diagram stages;
    # the current static pipeline ignores them, so importing a v2 JSON stays safe.
    scene["type"] = raw.get("type") or "scene"           # scene | diagram | title
    scene["motion_type"] = raw.get("motion_type") or ""  # still | ambient | transform
    scene["end_image_prompt"] = raw.get("end_image_prompt") or ""
    scene["motion_prompt"] = raw.get("motion_prompt") or ""
    scene["characters"] = raw.get("characters") or []
    scene["visual_aid"] = raw.get("visual_aid")
    scene["end_image_file"] = None    # end frame (krea2) for start->end animation
    scene["video_file"] = None        # animated clip (LTX-2)
    scene["transcript"] = None        # timed sentence blocks (Whisper, anchored to narration)
    scene["status"] = {"audio": "none", "image": "none", "video": "none",
                       "transcript": "none"}
    return scene


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "character"


def normalize_character(raw, index: int) -> Dict:
    """One raw character_bible entry -> a normalized bible character (no sheet yet)."""
    if isinstance(raw, str):
        raw = {"name": raw}
    raw = raw or {}
    name = (raw.get("name") or f"Character {index + 1}").strip()
    aliases = raw.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [a.strip() for a in aliases.split(",")]
    return {
        "id": _slug(name),
        "name": name,
        "aliases": [a.strip() for a in aliases if a and a.strip()],
        "description": (raw.get("description") or raw.get("look")
                        or raw.get("appearance") or "").strip(),
        "palette": (raw.get("palette") or raw.get("colors") or "").strip(),
        "anchor": None,            # rel path to the front/neutral reference
        "sheet": [],               # [{file, label, kind}] generated references
        "status": "none",          # none | generating | ready
    }


def parse_characters(raw: Dict) -> List[Dict]:
    """Extract the storyboard's top-level character bible, if present."""
    bible = raw.get("character_bible")
    if not isinstance(bible, list):
        v = raw.get("video") or {}
        bible = v.get("character_bible") if isinstance(v, dict) else None
    if not isinstance(bible, list):
        return []
    out: List[Dict] = []
    seen = set()
    for i, c in enumerate(bible):
        ch = normalize_character(c, i)
        if ch["id"] in seen:
            continue
        seen.add(ch["id"])
        out.append(ch)
    return out


def blank_scene(index: int = 0) -> Dict:
    """An empty scene holding every key the importer reads (see normalize_scene).

    Timing numbers are null so they auto-pace from the narration until filled in.
    """
    scene: Dict = {"id": index + 1, "type": "scene"}  # type: scene | diagram | title
    scene.update({field: "" for field in TEXT_FIELDS})
    scene["start_sec"] = None         # seconds; leave null to auto-pace from narration
    scene["end_sec"] = None
    scene["duration_sec"] = None
    scene["motion_type"] = ""         # "" | still | ambient | transform
    scene["motion_prompt"] = ""
    scene["end_image_prompt"] = ""    # only used when motion_type == "transform"
    scene["characters"] = []          # character names/ids appearing in this scene
    scene["visual_aid"] = None
    return scene


def blank_character() -> Dict:
    """An empty character_bible entry with every key normalize_character reads."""
    return {"name": "", "aliases": [], "description": "", "palette": ""}


def blank_storyboard(n_scenes: int = 1, n_characters: int = 1) -> Dict:
    """A full-schema, *empty* storyboard template for the import box / download.

    Carries every key the pipeline actually reads (video meta + per-scene fields +
    character bible) with blank values, so it can be filled in by hand or by an LLM
    and uploaded on the Projects tab. Kept here next to parse_storyboard so the
    offered template can never drift from what the parser consumes.
    """
    n_scenes = max(1, min(int(n_scenes or 1), 500))
    n_characters = max(0, min(int(n_characters or 0), 200))
    return {
        "video": {
            "title": "",
            "global_style_suffix": "",      # appended to every image prompt
            "global_negative_prompt": "",   # negative prompt for every image
            "total_runtime": "",            # display only, e.g. "9:56"
            "total_runtime_sec": None,      # planned timeline length, seconds
            "character_bible": [],          # optional: may live here instead of top level
        },
        "scenes": [blank_scene(i) for i in range(n_scenes)],
        "character_bible": [blank_character() for _ in range(n_characters)],
    }


def parse_storyboard(raw: Dict) -> Dict:
    """Validate + normalize a full storyboard JSON object."""
    if not isinstance(raw, dict):
        raise ValueError("Top-level JSON must be an object with 'video' and 'scenes'.")
    scenes_raw = raw.get("scenes")
    if not isinstance(scenes_raw, list) or not scenes_raw:
        raise ValueError("JSON has no non-empty 'scenes' array.")
    video = raw.get("video")
    if not isinstance(video, dict):
        video = {}
    scenes = [normalize_scene(s, i) for i, s in enumerate(scenes_raw)]
    return {"video": video, "scenes": scenes, "characters": parse_characters(raw)}


def _norm_clause(c: str) -> str:
    return re.sub(r"\s+", " ", c).strip(" .;:").lower()


def merge_style(base: str, style: str) -> str:
    """Append the style's comma-clauses to base, skipping clauses already there.

    Storyboard LLMs tend to bake the global style into every scene's
    image_prompt *and* provide it as global_style_suffix — naive concatenation
    would repeat ~40 words of style text per scene (and partial bakes would
    half-repeat). Deduping clause-by-clause keeps the prompt clean whichever
    form the JSON arrives in, while any style clause the scene is missing
    still gets appended.
    """
    base = (base or "").strip().strip(",").strip()
    have = {_norm_clause(c) for c in base.split(",")}
    add = [c.strip() for c in (style or "").split(",")
           if _norm_clause(c) and _norm_clause(c) not in have]
    if not add:
        return base
    return f"{base}, {', '.join(add)}" if base else ", ".join(add)


def character_blurb(scene: Dict, characters: Optional[List[Dict]]) -> str:
    """Ground the scene's bible characters textually: 'Name: fixed look'.

    Backends without reference conditioning (krea2) only know a character by
    what the prompt says, so recurring characters drift unless every scene
    restates their look.
    """
    if not characters:
        return ""
    idx: Dict[str, Dict] = {}
    for c in characters:
        for nm in [c.get("name", "")] + (c.get("aliases") or []):
            if nm:
                idx[nm.strip().lower()] = c
    bits, seen = [], set()
    for ref in (scene.get("characters") or []):
        name = (ref.get("name") if isinstance(ref, dict) else ref) or ""
        c = idx.get(name.strip().lower())
        if not c or c.get("id") in seen:
            continue
        seen.add(c.get("id"))
        desc = ", ".join(p for p in [(c.get("description") or "").strip(),
                                     (c.get("palette") or "").strip()] if p)
        if desc:
            bits.append(f"{c.get('name')} ({desc})")
    return f"Featuring {'; '.join(bits)}." if bits else ""


def build_image_prompt(scene: Dict, video: Dict, style: Optional[str] = None,
                       characters: Optional[List[Dict]] = None) -> Tuple[str, str]:
    """Compose the per-scene generation prompt.

    prompt = image_prompt (+ character-bible looks) + style, where ``style``
    is an explicit override when given, else the storyboard's editable
    global_style_suffix — one rule for every backend, so what the UI shows is
    what renders. Style clauses the scene already contains aren't appended
    twice (see merge_style). on_screen_text is ignored (composited in post).
    Negative = global_negative_prompt.
    """
    base = (scene.get("image_prompt") or scene.get("visual")
            or scene.get("narration") or "").strip().rstrip(",")
    blurb = character_blurb(scene, characters)
    if blurb:
        base = f"{base}. {blurb}" if base else blurb
    suffix = (style if style and style.strip()
              else (video.get("global_style_suffix") or "")).strip()
    prompt = merge_style(base, suffix)
    negative = (video.get("global_negative_prompt") or "").strip()
    return prompt, negative


# Default camera/ambient motion per motion_type, used when a scene declares it
# wants to move but gives no explicit motion_prompt.
_MOTION_FALLBACK = {
    "ambient": "subtle ambient motion, gentle idle movement and breathing, slow "
               "drifting camera, the scene stays composed and on-model",
    "transform": "smooth animated transition from the first frame to the last frame, "
                 "the change happens gradually and clearly",
    "still": "very subtle, almost still, a faint breathing motion only",
}


def _clean(text: str) -> str:
    """Drop control/mojibake chars and tidy whitespace from storyboard text."""
    if not text:
        return ""
    out = "".join(ch for ch in str(text) if ch == "\n" or 32 <= ord(ch) < 0xFFFD)
    out = re.sub(r"�", "", out)            # stray replacement chars
    return re.sub(r"\s+", " ", out).strip()


# keyword -> a single, *gentle* ambient motion phrase (kept subtle so LTX doesn't
# overdrive the effect and melt the drawing)
_AMBIENT_RULES = [
    (r"\bfire|flame|campfire|burn|ember|stove\b", "the fire flickers softly"),
    (r"\bsnow\b", "a few snowflakes drift down slowly"),
    (r"\brain\b", "light rain falls gently"),
    (r"\bwind|blow\b", "a slight breeze stirs"),
    (r"\bbanknote|notes?\b|\bmoney|cash|bill|mark|currency|coin|wage|price\b", "a banknote flutters slightly"),
    (r"\bchart|graph|curve|bar ?graph|diagram|arrow|number|percent|index|rate\b",
     "the chart line rises slowly, numbers ticking up"),
    (r"\bcrowd|queue|line of|people|workers?|protest|riot|march\b", "the crowd stirs with small movements"),
    (r"\bclock|hour|time\b", "the clock hands tick slowly"),
    (r"\bwater|river|wave\b", "the water ripples gently"),
    (r"\btrain|car|wheel|cart\b", "a slight forward drift"),
]


def _camera_for_shot(shot: str) -> str:
    s = (shot or "").lower()
    if any(k in s for k in ("wide", "establish", "aerial", "long")):
        return "slow cinematic push-in"
    if any(k in s for k in ("insert", "close", "extreme", "macro", "detail")):
        return "minimal camera movement, a slight slow zoom"
    if "medium" in s:
        return "gentle slow push-in"
    if any(k in s for k in ("pov", "over", "handheld")):
        return "subtle handheld drift"
    return "subtle slow camera move"


def auto_motion_prompt(scene: Dict) -> Tuple[str, str]:
    """Author a *minimalist* (motion_prompt, motion_type) for a scene.

    Deliberately tiny motion — a gentle bouncy idle bob + a shot-appropriate slow
    camera move, and at most one *very* subtle ambient effect. No big character
    actions: those make LTX over-move and smear small details, which reads as the
    "AI feel" the user wants to avoid. Returns motion-only text (the still's subject
    is added by build_motion_prompt; the flat-cartoon style by ltx_engine)."""
    blob = " ".join(_clean(scene.get(f)) for f in ("image_prompt", "narration", "visual")).lower()
    effect = ""
    for pat, phrase in _AMBIENT_RULES:
        if re.search(pat, blob):
            effect = phrase
            break
    parts = ["the character moves with a gentle, slightly exaggerated cartoon rhythm, "
             "small bouncy idle motion"]
    if effect:
        parts.append(effect)
    parts.append("the camera holds steady")
    return ", ".join(parts), "ambient"


def is_animatable(scene: Dict) -> bool:
    """A scene wants animation if its storyboard gives it motion to play."""
    mt = (scene.get("motion_type") or "").strip().lower()
    if (scene.get("motion_prompt") or "").strip():
        return True
    return mt in ("ambient", "transform")


def wants_end_frame(scene: Dict) -> bool:
    """Transform scenes animate from the still to a generated end frame."""
    return ((scene.get("motion_type") or "").strip().lower() == "transform"
            and bool((scene.get("end_image_prompt") or "").strip()))


def build_motion_prompt(scene: Dict, video: Dict, fallback: str = "") -> str:
    """LTX prompt for animating a scene: its motion_prompt (or a sensible default),
    grounded with the still's subject so the model keeps the same content moving."""
    mt = (scene.get("motion_type") or "").strip().lower()
    motion = (scene.get("motion_prompt") or "").strip()
    if not motion:
        motion = (fallback.strip() or _MOTION_FALLBACK.get(mt)
                  or _MOTION_FALLBACK["ambient"])
    subject = (scene.get("image_prompt") or scene.get("visual")
               or scene.get("narration") or "").strip().rstrip(",")
    if subject:
        return f"{subject}. {motion}"
    return motion
