"""Reusable scene-transition + on-screen-text animation effects (moviepy 2.x).

The storyboard's ``transition`` and ``text_anim`` fields are free-text director's
notes (38 distinct transitions, 151 distinct text animations across the Weimar
JSON), e.g. "Hard cut", "Slow push-in", "Whip-pan right", "SMASH CUT",
"Two labels pop in then get a red strike-through".

Rather than hard-code each one, every note is **classified** into a small set of
primitives by keyword, and each primitive has one reusable implementation. Unknown
notes fall back to a sensible default (cut for scenes, fade for text), so any
storyboard in this shape renders without special-casing.

    kind = classify_transition(scene["transition"])      # -> "cut" | "fade" | ...
    clip = apply_transition(clip, kind, dur=d, W=W, H=H)

    kind = classify_text_anim(scene["text_anim"])         # -> "fade" | "pop" | ...
    cap  = apply_text_anim(textclip, kind, dur=d, W=W, H=H, pos=pos)

All effects are wrapped defensively: if moviepy lacks an fx or anything raises,
the clip is returned unchanged (degrades to a hard cut / static caption) so a
render never dies on a transition.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# --- classification --------------------------------------------------------
# (substring, primitive) — first match wins, so order specific -> generic.
_TRANSITION_RULES: List[Tuple[str, str]] = [
    ("smash", "punch"), ("record-scratch", "punch"), ("record-needle", "punch"),
    ("punch-in", "punch"), ("quick punch", "punch"), ("fast zoom", "punch"),
    ("glitch", "glitch"), ("rewind", "glitch"), ("reverse-zoom", "glitch"),
    ("whip", "slide"), ("three-panel", "slide"), ("wipe", "slide"),
    ("card-flip", "slide"), ("curtain", "slide"),
    ("reveal pan", "slide"), ("reveal", "slide"),
    ("iris", "iris"),
    ("pull-back", "pull"), ("pull back", "pull"), ("zoom-out", "pull"),
    ("zoom out", "pull"), ("pull", "pull"),
    ("push-in", "push"), ("push in", "push"), ("push", "push"),
    ("punch", "push"), ("zoom-in", "push"), ("zoom in", "push"),
    ("pan", "slide"),
    ("fade up", "fade"), ("fade back", "fade"), ("fade", "fade"),
    ("cold open", "fade"),
    ("match cut", "cut"), ("match", "cut"), ("hard cut", "cut"), ("cut", "cut"),
]

_TEXTANIM_RULES: List[Tuple[str, str]] = [
    ("strike", "strike"),                                   # red strike-through
    ("slam", "slam"), ("stamp", "slam"), ("slams", "slam"), ("stamps", "slam"),
    ("thud", "slam"), ("lands", "slam"), ("drops", "slam"), ("crack", "slam"),
    ("odometer", "slam"), ("count-up", "slam"), ("counts up", "slam"),
    ("pop", "pop"), ("bounce", "pop"), ("balloon", "pop"), ("zooms in", "pop"),
    ("zoom in", "pop"), ("glint", "pop"), ("twinkle", "pop"),
    ("slide", "slide"), ("lower-third", "slide"), ("slides", "slide"),
    ("draws", "slide"), ("sweeps", "slide"), ("flutter", "slide"),
    ("type", "type"), ("types on", "type"), ("headline", "type"),
    ("dissolve", "fade"), ("melt", "fade"), ("rot", "fade"), ("mist", "fade"),
    ("fade", "fade"), ("fades", "fade"), ("appears", "fade"), ("glow", "fade"),
]


def _classify(text: str, rules: List[Tuple[str, str]], default: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return default
    for needle, prim in rules:
        if needle in t:
            return prim
    return default


def classify_transition(text: str) -> str:
    return _classify(text, _TRANSITION_RULES, "cut")


def classify_text_anim(text: str) -> str:
    return _classify(text, _TEXTANIM_RULES, "fade")


# --- easing ----------------------------------------------------------------
def _ease_out(p: float) -> float:
    p = 0.0 if p < 0 else (1.0 if p > 1 else p)
    return 1 - (1 - p) * (1 - p)          # quadratic ease-out


# --- scene transitions -----------------------------------------------------
# Each takes a composed W*H scene clip + the entrance duration and returns the
# clip with a self-contained entrance effect (no cross-clip overlap needed, so
# clips concatenate with hard joins). All scale effects stay >= 1.0 so the frame
# is always covered.
def _fade(clip, d, W, H):
    try:
        from moviepy.video.fx import FadeIn
        return clip.with_effects([FadeIn(d)])
    except Exception:
        try:
            from moviepy.video.fx import CrossFadeIn
            return clip.with_effects([CrossFadeIn(d)])
        except Exception:
            return clip


def _zoom(clip, d, W, H, start=1.10, snap=1.0):
    """Settle from a slightly zoomed state to rest over d seconds (push/pull/iris)."""
    try:
        def scale(t):
            p = _ease_out(t / d) if d > 0 else 1.0
            return 1.0 if t >= d else (start + (1.0 - start) * p) * snap
        return clip.resized(scale).with_position("center")
    except Exception:
        return clip


def _punch(clip, d, W, H):
    """Snappy, abrupt in-zoom for smash/punch/glitch."""
    return _zoom(clip, max(0.12, min(d, 0.22)), W, H, start=1.18)


def _slide(clip, d, W, H, frm="right"):
    """Slide the scene in from a screen edge (whip/pan/wipe)."""
    try:
        from moviepy import CompositeVideoClip
        x0 = W if frm == "right" else -W
        dd = max(0.15, d)

        def pos(t):
            p = _ease_out(t / dd) if dd > 0 else 1.0
            return (int(x0 * (1 - p)) if t < dd else 0, "center")
        moving = clip.with_position(pos)
        return CompositeVideoClip([moving], size=(W, H)).with_duration(clip.duration)
    except Exception:
        return clip


def apply_transition(clip, kind: str, *, dur: float, W: int, H: int):
    d = max(0.18, min(0.5, dur / 3.0))
    fn = _TRANSITIONS.get(kind)
    if not fn:
        return clip
    try:
        return fn(clip, d, W, H)
    except Exception:
        return clip


_TRANSITIONS: Dict = {
    "cut": lambda c, d, W, H: c,
    "fade": _fade,
    "push": lambda c, d, W, H: _zoom(c, d, W, H, start=1.10),
    "pull": lambda c, d, W, H: _zoom(c, d, W, H, start=1.12),
    "iris": lambda c, d, W, H: _fade(_zoom(c, d, W, H, start=1.14), d, W, H),
    "punch": _punch,
    "glitch": _punch,
    "slide": _slide,
}


# --- on-screen-text animations ---------------------------------------------
# Each takes a raw TextClip (with duration set) + the target position and returns
# the positioned, animated caption clip.
def _t_fade(t, d, W, H, pos):
    try:
        from moviepy.video.fx import CrossFadeIn
        return t.with_position(pos).with_effects([CrossFadeIn(min(0.35, d / 3))])
    except Exception:
        return t.with_position(pos)


def _t_pop(t, d, W, H, pos, start=0.4, over=1.12):
    """Scale-overshoot entrance: 0 -> overshoot -> settle to 1.0."""
    try:
        dd = min(0.45, max(0.18, d / 3))

        def scale(tt):
            if tt >= dd:
                return 1.0
            p = _ease_out(tt / dd)
            s = start + (over - start) * p
            return s if p < 1 else 1.0
        return _t_fade(t.resized(scale), d, W, H, pos)
    except Exception:
        return _t_fade(t, d, W, H, pos)


def _t_slam(t, d, W, H, pos):
    """Big -> slam down to rest (stamp/slam/odometer)."""
    try:
        dd = min(0.30, max(0.12, d / 4))

        def scale(tt):
            if tt >= dd:
                return 1.0
            p = _ease_out(tt / dd)
            return 1.7 + (1.0 - 1.7) * p          # 1.7 -> 1.0
        return t.resized(scale).with_position(pos)
    except Exception:
        return t.with_position(pos)


def _t_slide(t, d, W, H, pos):
    """Slide caption in from the left to its resting position."""
    try:
        y = pos[1] if isinstance(pos, (tuple, list)) else "center"
        cx = int((W - t.w) / 2)
        x0 = -int(t.w) - 20
        dd = min(0.4, max(0.15, d / 3))

        def position(tt):
            p = _ease_out(tt / dd) if tt < dd else 1.0
            return (int(x0 + (cx - x0) * p), y)
        return t.with_position(position)
    except Exception:
        return t.with_position(pos)


def apply_text_anim(textclip, kind: str, *, dur: float, W: int, H: int, pos):
    fn = _TEXT_ANIMS.get(kind, _t_fade)
    try:
        return fn(textclip, dur, W, H, pos)
    except Exception:
        try:
            return textclip.with_position(pos)
        except Exception:
            return textclip


_TEXT_ANIMS: Dict = {
    "fade": _t_fade,
    "pop": _t_pop,
    "slam": _t_slam,
    "slide": _t_slide,
    "type": _t_fade,        # true typewriter needs per-glyph clips; fade is the safe stand-in
    "strike": _t_fade,      # red strike-through is a content overlay; entrance falls back to fade
}
