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
    scene["status"] = {"audio": "none", "image": "none"}
    return scene


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
    return {"video": video, "scenes": scenes}


def build_image_prompt(scene: Dict, video: Dict, style: Optional[str] = None) -> Tuple[str, str]:
    """Compose the per-scene generation prompt.

    Default (no ``style``): prompt = image_prompt + ', ' + global_style_suffix, per
    the JSON's _pipeline_notes. When a ``style`` preset is given (e.g. the krea2
    flat-cartoon look), it *replaces* the storyboard's ink/whiteboard suffix and
    leads the prompt; wording that fights a non-ink style ("stick figure",
    "whiteboard") is softened so the scene content survives. on_screen_text is
    ignored (composited in post). Negative = global_negative_prompt.
    """
    base = (scene.get("image_prompt") or scene.get("visual")
            or scene.get("narration") or "").strip().rstrip(",")
    if style and style.strip():
        base = re.sub(r"\bstick[- ]?figures?\b", "character", base, flags=re.I)
        base = re.sub(r"\bwhiteboard\b", "", base, flags=re.I)
        base = re.sub(r"\s{2,}", " ", base).strip().rstrip(",")
        prompt = f"{style.strip()}. {base}" if base else style.strip()
    else:
        suffix = (video.get("global_style_suffix") or "").strip()
        prompt = f"{base}, {suffix}" if (base and suffix) else (base or suffix)
    negative = (video.get("global_negative_prompt") or "").strip()
    return prompt, negative
