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
    ("black flash", "blackflash"), ("dip to black", "blackflash"),
    ("blink", "blackflash"),
    ("dip to white", "whiteflash"), ("white flash", "whiteflash"),
    ("flash to white", "whiteflash"), ("bloom out", "whiteflash"),
    ("flash", "flash"), ("bolt", "flash"), ("lightning", "flash"),
    ("shake", "shake"), ("rumble", "shake"), ("earthquake", "shake"),
    ("crash zoom", "crash"), ("crash-zoom", "crash"), ("crash", "crash"),
    ("drop-in", "drop"), ("drop in", "drop"), ("slam down", "drop"),
    ("falls in", "drop"), ("guillotine", "drop"),
    ("smash", "punch"), ("record-scratch", "punch"), ("record-needle", "punch"),
    ("punch-in", "punch"), ("quick punch", "punch"), ("fast zoom", "punch"),
    ("glitch", "glitch"), ("rewind", "glitch"), ("reverse-zoom", "glitch"),
    ("static", "glitch"), ("corrupt", "glitch"),
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
    """Settle from a slightly zoomed state to rest over d seconds (push/pull/iris).

    Wrapped in a fixed W*H composite: a bare time-varying resize reports its
    t=0 (zoomed, possibly odd) size, which inflates concatenate(compose) and
    can hand libx264 an odd width."""
    try:
        from moviepy import CompositeVideoClip

        def scale(t):
            p = _ease_out(t / d) if d > 0 else 1.0
            return 1.0 if t >= d else (start + (1.0 - start) * p) * snap
        z = clip.resized(scale).with_position("center")
        return CompositeVideoClip([z], size=(W, H)).with_duration(clip.duration)
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


def _shake(clip, d, W, H):
    """Impact shake: slight over-zoom + decaying two-axis jitter on entry."""
    try:
        import math

        from moviepy import CompositeVideoClip
        dd = max(0.28, min(0.5, d))
        amp = 0.012 * W
        z = clip.resized(1.05)

        def pos(t):
            if t >= dd:
                return ((W - z.w) / 2, (H - z.h) / 2)
            decay = (1 - t / dd) ** 1.5
            return ((W - z.w) / 2 + amp * decay * math.sin(t * 73.0),
                    (H - z.h) / 2 + 0.6 * amp * decay * math.cos(t * 97.0))
        return CompositeVideoClip([z.with_position(pos)],
                                  size=(W, H)).with_duration(clip.duration)
    except Exception:
        return clip


def _flash(clip, d, W, H):
    """White flash-frame over a snappy punch-in (music-video style cut)."""
    base = _punch(clip, d, W, H)
    try:
        from moviepy import ColorClip, CompositeVideoClip
        from moviepy.video.fx import CrossFadeOut
        fd = 0.14
        white = (ColorClip(size=(W, H), color=(255, 255, 255))
                 .with_duration(fd).with_effects([CrossFadeOut(fd)]))
        return CompositeVideoClip([base, white],
                                  size=(W, H)).with_duration(clip.duration)
    except Exception:
        return base


def _crash(clip, d, W, H):
    """Crash zoom: violent, near-instant zoom slam — the hardest hit we have."""
    return _zoom(clip, max(0.10, min(d, 0.16)), W, H, start=1.42)


def _drop(clip, d, W, H):
    """Scene drops in from above and lands with a tiny settle (verdict energy)."""
    try:
        from moviepy import CompositeVideoClip
        dd = max(0.16, min(0.30, d))

        def pos(t):
            if t >= dd:
                return (0, 0)
            p = _ease_out(t / dd)
            over = 0.015 * H * (1 - abs(2 * p - 1)) if p > 0.75 else 0
            return (0, int(-H * (1 - p) + over))
        moving = clip.with_position(pos)
        return CompositeVideoClip([moving], size=(W, H)).with_duration(clip.duration)
    except Exception:
        return clip


def _blackflash(clip, d, W, H):
    """Two-frame dip-to-black on the cut — the edit 'blinks' and the beat lands."""
    try:
        from moviepy import ColorClip, CompositeVideoClip
        from moviepy.video.fx import CrossFadeOut
        fd = 0.09
        black = (ColorClip(size=(W, H), color=(0, 0, 0))
                 .with_duration(fd).with_effects([CrossFadeOut(fd)]))
        return CompositeVideoClip([clip, black],
                                  size=(W, H)).with_duration(clip.duration)
    except Exception:
        return clip


def _whiteflash(clip, d, W, H):
    """Dip to white — the incoming scene blooms out of a bright frame; the
    brighter sibling of dip-to-black, for revelation / realisation beats."""
    try:
        from moviepy import ColorClip, CompositeVideoClip
        from moviepy.video.fx import CrossFadeOut
        fd = 0.12
        white = (ColorClip(size=(W, H), color=(255, 255, 255))
                 .with_duration(fd).with_effects([CrossFadeOut(fd)]))
        return CompositeVideoClip([clip, white],
                                  size=(W, H)).with_duration(clip.duration)
    except Exception:
        return clip


def _glitch(clip, d, W, H):
    """Real digital tear on entry: RGB channel split + horizontal slice jitter
    for a fraction of a second (wrongness / tech / corruption beats)."""
    try:
        import numpy as _np
        dd = max(0.14, min(0.26, d))

        def fx(get_frame, t):
            frame = get_frame(t)
            if t >= dd:
                return frame
            k = 1.0 - t / dd                       # decaying intensity
            f = frame.copy()
            sh = max(2, int(10 * k))
            f[:, :, 0] = _np.roll(frame[:, :, 0], sh, axis=1)      # R right
            f[:, :, 2] = _np.roll(frame[:, :, 2], -sh, axis=1)     # B left
            h = f.shape[0]
            rng = _np.random.default_rng(int(t * 997) + 7)
            for _ in range(max(1, int(5 * k))):
                y0 = int(rng.integers(0, max(1, h - 24)))
                band = min(int(rng.integers(6, 26)), h - y0)
                f[y0:y0 + band] = _np.roll(f[y0:y0 + band],
                                           int(rng.integers(-36, 37) * k), axis=1)
            return f
        return clip.transform(fx)
    except Exception:
        return _punch(clip, d, W, H)


def apply_transition(clip, kind: str, *, dur: float, W: int, H: int, raw: str = ""):
    d = max(0.18, min(0.5, dur / 3.0))
    fn = _TRANSITIONS.get(kind)
    if not fn:
        return clip
    try:
        if kind == "slide":
            frm = "left" if "left" in (raw or "").lower() else "right"
            return _slide(clip, d, W, H, frm=frm)
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
    "glitch": _glitch,
    "crash": _crash,
    "drop": _drop,
    "blackflash": _blackflash,
    "whiteflash": _whiteflash,
    "slide": _slide,
    "shake": _shake,
    "flash": _flash,
}


# --- whole-scene FX (letterbox / vignette — frame the beats that matter) -----
_VIG_CACHE: Dict = {}


def _vignette_overlay(W: int, H: int, strength: float = 0.34):
    """Cached RGBA radial-dark overlay as an ImageClip source array."""
    key = (W, H, round(strength, 2))
    if key not in _VIG_CACHE:
        import numpy as _np
        y, x = _np.ogrid[:H, :W]
        cx, cy = W / 2, H / 2
        r = _np.sqrt(((x - cx) / (0.72 * W)) ** 2 + ((y - cy) / (0.72 * H)) ** 2)
        alpha = _np.clip((r - 0.55) / 0.65, 0, 1) ** 1.5 * (255 * strength)
        rgba = _np.zeros((H, W, 4), dtype=_np.uint8)
        rgba[:, :, 3] = alpha.astype(_np.uint8)
        _VIG_CACHE[key] = rgba
    return _VIG_CACHE[key]


def apply_scene_fx(clip, fx, *, W: int, H: int):
    """Apply whole-scene overlay effects (list of names from the grammar's
    scene_fx catalog: "letterbox", "vignette"). Unknown names are ignored;
    failures return the clip unchanged."""
    for name in (fx or []):
        n = str(name).strip().lower()
        try:
            from moviepy import ColorClip, CompositeVideoClip, ImageClip
            if n == "letterbox":
                bh = int(H * 0.11)
                bars = [ColorClip(size=(W, bh), color=(0, 0, 0))
                        .with_duration(clip.duration).with_position(p)
                        for p in ((0, 0), (0, H - bh))]
                clip = CompositeVideoClip([clip, *bars],
                                          size=(W, H)).with_duration(clip.duration)
            elif n == "vignette":
                ov = (ImageClip(_vignette_overlay(W, H))
                      .with_duration(clip.duration))
                clip = CompositeVideoClip([clip, ov],
                                          size=(W, H)).with_duration(clip.duration)
        except Exception:
            continue
    return clip


# --- video-wide film filters (the "wear a look" pass — applied LAST) ----------
_VHS_CACHE: Dict = {}


def _vhs_assets(W: int, H: int, scan_amt: float):
    key = (W, H, round(scan_amt, 3))
    if key not in _VHS_CACHE:
        import numpy as _np
        rng = _np.random.default_rng(1985)
        bank = [rng.standard_normal((H, W, 1)).astype(_np.float32)
                for _ in range(7)]
        mask = _np.ones((H, W, 1), dtype=_np.float32)
        mask[::2] -= scan_amt                       # scanlines
        yy, xx = _np.ogrid[:H, :W]
        r2 = (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        mask *= (1.0 - 0.16 * r2[..., None]).astype(_np.float32)  # soft vignette
        _VHS_CACHE.clear()                          # one size in memory at a time
        _VHS_CACHE[key] = (bank, mask)
    return _VHS_CACHE[key]


def _vhs(clip, W: int, H: int, cfg: Optional[Dict] = None):
    """The VHS look: grain, scanlines, chroma fringe, occasional tracking
    wobble, lifted blacks, head-switch tear at the bottom. Vectorized numpy —
    a few ms per frame, deterministic (seeded bank)."""
    try:
        import numpy as _np
        c = cfg or {}
        grain = float(c.get("grain", 0.035)) * 255.0
        scan = float(c.get("scanlines", 0.055))
        bleed = int(c.get("bleed_px", 2))
        wob_every = float(c.get("wobble_every_s", 2.8))
        lift = float(c.get("lift", 7))
        tear = bool(c.get("bottom_tear", True))
        bank, mask = _vhs_assets(W, H, scan)
        nb = len(bank)

        def fx(get_frame, t):
            f = get_frame(t).astype(_np.float32)
            if f.shape[0] != H or f.shape[1] != W:
                return get_frame(t)
            if bleed:                                # chroma fringe
                f[:, :, 0] = 0.7 * f[:, :, 0] + 0.3 * _np.roll(f[:, :, 0], bleed, 1)
                f[:, :, 2] = 0.7 * f[:, :, 2] + 0.3 * _np.roll(f[:, :, 2], -bleed, 1)
            f += bank[int(t * 30) % nb] * grain      # grain
            f *= mask                                # scanlines + vignette
            f = f * (1.0 - lift / 255.0) + lift      # lifted blacks (never true black)
            if wob_every > 0 and (t % wob_every) < 0.1:   # tracking wobble
                y0 = int((t * 137.0) % max(1, H - 40))
                f[y0:y0 + 24] = _np.roll(f[y0:y0 + 24], 5, axis=1)
            if tear:                                 # head-switch noise bar
                f[-6:] = f[-6:] * 0.4 + bank[int(t * 47) % nb][-6:] * 90.0 + 60.0
            return _np.clip(f, 0, 255).astype("uint8")
        return clip.transform(fx)
    except Exception:
        return clip


_FILTERS: Dict = {"vhs": _vhs}


def apply_filter(clip, name: str, *, W: int, H: int, cfg: Optional[Dict] = None):
    """Video-wide film look (grammar catalog "filters"): applied after every
    other effect so the whole frame — flashes, bars, receipts — wears it."""
    fn = _FILTERS.get((name or "").strip().lower())
    if not fn:
        return clip
    try:
        return fn(clip, W, H, cfg)
    except Exception:
        return clip


# --- word-level emphasis (micro effects timed to the spoken word) -------------
def apply_emphasis(clip, hits, *, W: int, H: int):
    """Punch specific spoken words: hits = [{"t": sec_into_scene, "kind":
    "zoom_bump" | "shake_micro" | "flash_soft"}]. The kinds a human editor
    reaches for — a 5% zoom bump, a 2-frame soft flash, a tiny decaying shake —
    each ~0.3-0.5 s, never changing the composition."""
    hits = [h for h in (hits or [])
            if isinstance(h.get("t"), (int, float)) and h["t"] >= 0]
    if not hits:
        return clip
    try:
        import math

        from moviepy import ColorClip, CompositeVideoClip
        from moviepy.video.fx import CrossFadeOut
        zooms = [h["t"] for h in hits if h.get("kind") == "zoom_bump"]
        shakes = [h["t"] for h in hits if h.get("kind") == "shake_micro"]
        flashes = [h["t"] for h in hits if h.get("kind") == "flash_soft"]

        base = clip
        if zooms or shakes:
            AMP, RISE, FALL = 0.055, 0.09, 0.40
            pad = 0.022 if shakes else 0.0        # jitter never shows the frame edge

            def scale(t):
                s = 1.0 + pad
                for t0 in zooms:
                    dt = t - t0
                    if 0 <= dt < RISE:
                        s += AMP * (dt / RISE)
                    elif RISE <= dt < RISE + FALL:
                        p = (dt - RISE) / FALL
                        s += AMP * (1 - p) ** 1.6
                return s

            SAMP, SDUR = 0.0065 * W, 0.30

            def pos(t):
                z = scale(t)
                x, y = (W - W * z) / 2, (H - H * z) / 2
                for t0 in shakes:
                    dt = t - t0
                    if 0 <= dt < SDUR:
                        decay = (1 - dt / SDUR) ** 1.5
                        x += SAMP * decay * math.sin(dt * 78.0)
                        y += 0.6 * SAMP * decay * math.cos(dt * 101.0)
                return (x, y)
            base = clip.resized(scale).with_position(pos)
        layers = [base]
        for t0 in flashes:
            fd = 0.12
            layers.append(ColorClip(size=(W, H), color=(255, 255, 255))
                          .with_duration(fd).with_opacity(0.32)
                          .with_effects([CrossFadeOut(fd)]).with_start(t0))
        return CompositeVideoClip(layers, size=(W, H)).with_duration(clip.duration)
    except Exception:
        return clip


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
