"""Editing SFX: a file library with a procedural synth fallback.

The storyboard's free-text ``audio_cue`` per scene ("deep impact boom",
"quick whoosh", "shimmering riser", "cash register ding"…) is matched against
``data/sfx_library/`` (tagged wav files listed in ``data/sfx_library.json``).
Drop any downloaded packs into that folder — filenames become tags — and
they're used automatically. When no library file matches, the cue falls back
to the built-in numpy synths, which also seed the library on first run so
there is always something to browse when writing a script.

Everything returns stereo float32 @ 44100, peak-normalized — the assembler
scales by its sfx volume setting.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import config, storage

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


def click(dur: float = 0.09) -> np.ndarray:
    """Small mechanical UI click (date chips, typeset elements landing)."""
    t = _t(dur)
    burst = _lowpassish(_noise(len(t), seed=21), 3) * np.exp(-t * 260.0)
    tick = np.sin(2 * np.pi * 2900.0 * t) * np.exp(-t * 300.0) * 0.6
    return _norm(_stereo(burst * 0.7 + tick), 0.5)


# (keywords, synth, pre) — first match wins; pre=True means the clip should
# END at the cut (risers build into a scene) instead of starting on it.
_RULES: List[Tuple[Tuple[str, ...], object, bool]] = [
    (("click", "tick"), click, False),
    (("ris", "build"), riser, True),
    (("whoosh", "swish", "swoosh", "woosh"), whoosh, False),
    (("ka-ching", "kaching", "cash", "register", "coin"), kaching, False),
    (("ding", "bell", "chime"), ding, False),
    (("boom", "impact", "thud", "slam", "hit", "clank", "punch", "drop"), impact, False),
    (("pop",), pop, False),
]

# Big synthesized stingers read as SYNTHETIC (user, 2026-07-05: "they sound
# terrible") — only these tiny UI ticks may come from the procedural synths;
# whoosh/boom/riser/kaching/ding now require a REAL library file (Freesound
# fetch or user-imported wav) or they stay silent.
_TICK_SYNTHS = {"pop", "click"}
_BIG_BUILTINS = {"whoosh_air", "impact_boom", "riser_build", "ding_bell",
                 "kaching_register"}


def classify(cue: str) -> Optional[Tuple[object, bool]]:
    c = (cue or "").strip().lower()
    if not c:
        return None
    for keys, fn, pre in _RULES:
        if any(k in c for k in keys):
            return fn, pre
    return None


# --- file library ------------------------------------------------------------
# Built-in synths that seed the library (id, synth, tags).
_BUILTINS = [
    ("whoosh_air", whoosh, ["whoosh", "swish", "swoosh", "transition", "air"]),
    ("impact_boom", impact, ["impact", "boom", "hit", "thud", "slam", "clank", "drop", "punch"]),
    ("riser_build", riser, ["riser", "rise", "build", "shimmer", "sweep"]),
    ("ding_bell", ding, ["ding", "bell", "chime"]),
    ("kaching_register", kaching, ["kaching", "ka-ching", "cash", "register", "coin", "money"]),
    ("pop_cartoon", pop, ["pop", "bubble", "blip"]),
    ("ui_click", click, ["click", "tick", "ui"]),
]


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def seed_library() -> int:
    """Write the procedural stingers as wavs + manifest entries (idempotent)."""
    import soundfile as sf
    config.SFX_LIB_DIR.mkdir(parents=True, exist_ok=True)
    manifest = storage.read_json(config.SFX_LIBRARY_FILE, []) or []
    have = {m.get("id") for m in manifest}
    added = 0
    for sid, fn, tags in _BUILTINS:
        path = config.SFX_LIB_DIR / f"{sid}.wav"
        if not path.exists():
            arr = fn()
            sf.write(str(path), arr, SR)
        if sid not in have:
            manifest.append({"id": sid, "file": path.name, "tags": tags,
                             "dur": round(len(fn()) / SR, 2),
                             "source": "builtin-procedural", "pre": sid == "riser_build"})
            added += 1
    if added:
        storage.write_json(config.SFX_LIBRARY_FILE, manifest)
    return added


def library() -> List[Dict]:
    """Manifest + any loose wavs dropped into the folder (filename = tags)."""
    seed_library()
    manifest = storage.read_json(config.SFX_LIBRARY_FILE, []) or []
    known = {m.get("file") for m in manifest}
    changed = False
    if config.SFX_LIB_DIR.exists():
        for f in sorted(config.SFX_LIB_DIR.glob("*.wav")):
            if f.name in known:
                continue
            manifest.append({"id": f.stem, "file": f.name, "tags": _words(f.stem),
                             "source": "imported", "pre": "riser" in f.stem.lower()})
            changed = True
    if changed:
        storage.write_json(config.SFX_LIBRARY_FILE, manifest)
    return manifest


def _load_wav(path) -> Optional[np.ndarray]:
    try:
        import soundfile as sf
        wav, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if wav.shape[1] == 1:
            wav = np.repeat(wav, 2, axis=1)
        if sr != SR:
            n = int(round(len(wav) * SR / sr))
            xp = np.linspace(0, 1, len(wav), endpoint=False)
            x = np.linspace(0, 1, n, endpoint=False)
            wav = np.stack([np.interp(x, xp, wav[:, c]) for c in range(2)], axis=-1)
        return _norm(wav.astype(np.float32), 0.9)
    except Exception:
        return None


def _match_library(cue: str) -> Optional[Dict]:
    """Best REAL sound for a cue. Fetched/imported files always beat the
    seeded procedural wavs; the big procedural stingers are excluded entirely
    (they sound synthetic — user rule 2026-07-05)."""
    cw = set(_words(cue))
    if not cw:
        return None
    best, score = None, -1
    for entry in library():
        if entry.get("id") in _BIG_BUILTINS:
            continue
        s = len(cw & set(entry.get("tags") or []))
        if s <= 0:
            continue
        real = 0 if entry.get("source") == "builtin-procedural" else 1
        if (s + real * 10) > score:
            best, score = entry, s + real * 10
    return best


def render(cue: str) -> Optional[np.ndarray]:
    """Stinger for a free-text cue: real library file first; only tiny UI
    ticks (pop/click) may fall back to a synth — big cues stay silent rather
    than sound fake."""
    entry = _match_library(cue)
    if entry:
        arr = _load_wav(config.SFX_LIB_DIR / entry["file"])
        if arr is not None:
            return arr
    hit = classify(cue)
    if not hit:
        return None
    fn, _pre = hit
    return fn() if fn.__name__ in _TICK_SYNTHS else None


def is_pre(cue: str) -> bool:
    entry = _match_library(cue)
    if entry is not None:
        return bool(entry.get("pre"))
    hit = classify(cue)
    return bool(hit and hit[1])
