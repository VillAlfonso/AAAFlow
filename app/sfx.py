"""Procedural editing SFX (whoosh / impact / riser / ding / pop) — no models.

The storyboard's free-text ``audio_cue`` per scene ("deep impact boom",
"quick whoosh", "shimmering riser", "cash register ding"…) is classified by
keyword and synthesized with numpy at render time. These are the tiny editing
stingers a human editor drops on cuts; generated audio (ACE-Step) stays for
music beds. Everything returns stereo float32 @ 44100, peak-normalized —
the assembler scales by its sfx volume setting.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

SR = 44100


def _t(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR), dtype=np.float32) / SR


def _stereo(mono: np.ndarray, spread: float = 0.0) -> np.ndarray:
    """Mono -> stereo; small `spread` delays one channel a few ms for width."""
    left = mono
    right = mono
    if spread > 0:
        d = int(spread * SR)
        right = np.pad(mono, (d, 0))[: len(mono)]
    return np.stack([left, right], axis=-1).astype(np.float32)


def _norm(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) or 1.0
    return (x * (peak / m)).astype(np.float32)


def _noise(n: int, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _lowpassish(x: np.ndarray, k: int) -> np.ndarray:
    """Cheap moving-average lowpass (k samples)."""
    if k <= 1:
        return x
    kern = np.ones(k, dtype=np.float32) / k
    return np.convolve(x, kern, mode="same").astype(np.float32)


def whoosh(dur: float = 0.55) -> np.ndarray:
    """Airy swish: filtered noise with a bell envelope that peaks just
    before the end, so placed *at* a cut it reads as movement into it."""
    t = _t(dur)
    n = len(t)
    body = _lowpassish(_noise(n, seed=3), 24)
    p = t / dur
    env = np.sin(np.pi * np.clip(p, 0, 1) ** 0.8) ** 2
    return _norm(_stereo(body * env, spread=0.004), 0.8)


def impact(dur: float = 0.85) -> np.ndarray:
    """Deep boom: descending sine thump + a short noise click on the front."""
    t = _t(dur)
    f = 90.0 * np.exp(-t * 3.0) + 42.0
    phase = 2 * np.pi * np.cumsum(f) / SR
    thump = np.sin(phase) * np.exp(-t * 5.0)
    click = _lowpassish(_noise(len(t), seed=11), 6) * np.exp(-t * 90.0) * 0.7
    return _norm(_stereo(thump + click), 0.9)


def riser(dur: float = 1.1) -> np.ndarray:
    """Building sweep that ends at full volume — placed to END on the cut."""
    t = _t(dur)
    n = len(t)
    p = t / dur
    air = _lowpassish(_noise(n, seed=5), 10) * (p ** 2.2)
    f = 160.0 + 620.0 * (p ** 1.6)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * (p ** 2.6) * 0.35
    return _norm(_stereo(air + tone, spread=0.003), 0.75)


def ding(dur: float = 0.9, base: float = 1245.0) -> np.ndarray:
    """Small bright bell (partials with staggered decay)."""
    t = _t(dur)
    x = (np.sin(2 * np.pi * base * t) * np.exp(-t * 6)
         + 0.5 * np.sin(2 * np.pi * base * 1.5 * t) * np.exp(-t * 9)
         + 0.25 * np.sin(2 * np.pi * base * 2.0 * t) * np.exp(-t * 12))
    return _norm(_stereo(x), 0.55)


def kaching(dur: float = 0.9) -> np.ndarray:
    """Two quick bells (cash-register feel)."""
    a = ding(dur, base=1175.0)
    b = ding(dur, base=1568.0)
    off = int(0.09 * SR)
    out = a.copy()
    out[off:] += b[: len(out) - off] * 0.9
    return _norm(out, 0.55)


def pop(dur: float = 0.22) -> np.ndarray:
    """Tiny cartoon pop: click + fast-decaying low blip."""
    t = _t(dur)
    click = _noise(len(t), seed=9) * np.exp(-t * 220.0)
    f = 340.0 * np.exp(-t * 14.0) + 120.0
    blip = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 22.0)
    return _norm(_stereo(click * 0.5 + blip), 0.6)


# (keywords, synth, pre) — first match wins; pre=True means the clip should
# END at the cut (risers build into a scene) instead of starting on it.
_RULES: List[Tuple[Tuple[str, ...], object, bool]] = [
    (("ris", "build"), riser, True),
    (("whoosh", "swish", "swoosh", "woosh"), whoosh, False),
    (("ka-ching", "kaching", "cash", "register", "coin"), kaching, False),
    (("ding", "bell", "chime"), ding, False),
    (("boom", "impact", "thud", "slam", "hit", "clank", "punch", "drop"), impact, False),
    (("pop",), pop, False),
]


def classify(cue: str) -> Optional[Tuple[object, bool]]:
    c = (cue or "").strip().lower()
    if not c:
        return None
    for keys, fn, pre in _RULES:
        if any(k in c for k in keys):
            return fn, pre
    return None


def render(cue: str) -> Optional[np.ndarray]:
    """Synthesize the stinger for a free-text cue, or None if unrecognized."""
    hit = classify(cue)
    if not hit:
        return None
    fn, _pre = hit
    return fn()


def is_pre(cue: str) -> bool:
    hit = classify(cue)
    return bool(hit and hit[1])
