"""REFERENCE CARDS: researched photos edited in at the first spoken mention.

User rule (2026-07-10): when the narrator first mentions a person integral to
the story, their real photo should be edited into the video at that exact
moment; same for a key item or place. The research stage downloads those
pictures (``app/webresearch.py`` -> ``research/refs.json``); this module maps
each ref to the FIRST scene whose narration mentions it and composites the
photo as a floating polaroid-style card, synced to the spoken word via the
one-take word timestamps (audio/words.json), with a small typeset name label
(same sanctioned-text family as date chips: real fonts, never AI glyphs).

Scene overrides win: ``scene.ref = {file, label, sync}`` forces a card,
``scene.ref = false`` blocks one. Receipt scenes never get a card (the
receipt IS the visual).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import storage

_FONTS = [r"C:\Windows\Fonts\georgiab.ttf", r"C:\Windows\Fonts\arialbd.ttf",
          r"C:\Windows\Fonts\arial.ttf"]


def _font() -> Optional[str]:
    return next((f for f in _FONTS if Path(f).exists()), None)


def load_refs(pdir: Path) -> List[Dict]:
    refs = storage.read_json(pdir / "research" / "refs.json", None) or []
    return [r for r in refs if isinstance(r, dict) and r.get("file")]


def plan(project: Dict, pdir: Path) -> Dict[str, Dict]:
    """{scene_id: ref} - each ref lands on the FIRST scene that mentions it.

    One card per scene at most; scenes with a receipt or ``ref: false`` are
    skipped; a manual ``scene.ref`` dict always wins and consumes its file.
    """
    scenes = project.get("scenes") or []
    out: Dict[str, Dict] = {}
    used_files = set()

    for s in scenes:
        manual = s.get("ref")
        if isinstance(manual, dict) and manual.get("file"):
            entry = dict(manual)
            entry.setdefault("label", "")
            entry.setdefault("match", [str(manual.get("sync") or entry["label"])])
            out[str(s.get("id"))] = entry
            used_files.add(entry["file"])

    refs = [r for r in load_refs(pdir)
            if r["file"] not in used_files and (pdir / r["file"]).exists()]
    if not refs:
        return out

    for ref in refs:
        aliases = sorted({a for a in (ref.get("match") or [])
                          if a and len(a) >= 3}, key=len, reverse=True)
        if not aliases:
            continue
        pats = [(a, re.compile(r"\b" + re.escape(a) + r"\b", re.I))
                for a in aliases]
        for s in scenes:
            sid = str(s.get("id"))
            if sid in out or s.get("receipt") or s.get("ref") is False:
                continue
            narr = s.get("narration") or ""
            hit = next((a for a, p in pats if p.search(narr)), None)
            if hit:
                out[sid] = {**ref, "sync": hit}
                break
    return out


def mention_time(aliases: List[str], row: Optional[Dict], words: List,
                 win_t0: float) -> Optional[float]:
    """Seconds into the scene when the ref's phrase is SPOKEN (else None)."""
    if not (row and words and aliases):
        return None
    t0, t1 = float(row["start"]) + win_t0, float(row["end"]) + win_t0
    span = [(w, a) for (w, a, _b) in words if t0 - 0.05 <= a < t1]
    best: Optional[float] = None
    for phrase in aliases:
        toks = re.findall(r"[a-z0-9']+", str(phrase).lower())
        if not toks:
            continue
        for j, (w, at) in enumerate(span):
            if w == toks[0] and all(
                    j + k < len(span) and span[j + k][0] == toks[k]
                    for k in range(min(len(toks), 3))):
                loc = max(0.0, at - t0)
                if best is None or loc < best:
                    best = loc
                break
    return best


def _card_arrays(img_path: Path, label: str, W: int, H: int):
    """Pre-render the tilted photo card (+ label strip) as (rgb, alpha) arrays."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    shot = Image.open(img_path).convert("RGB")
    portrait = shot.height >= shot.width
    # size the card to the frame: portraits taller, landscapes wider
    if portrait:
        ch = int(H * 0.46)
        cw = max(1, round(shot.width * ch / shot.height))
        if cw > W * 0.30:
            cw = int(W * 0.30)
            ch = max(1, round(shot.height * cw / shot.width))
    else:
        cw = int(W * 0.32)
        ch = max(1, round(shot.height * cw / shot.width))
        if ch > H * 0.40:
            ch = int(H * 0.40)
            cw = max(1, round(shot.width * ch / shot.height))
    photo = shot.resize((cw, ch), Image.LANCZOS)

    pad = max(8, cw // 26)
    label = (label or "").strip()
    strip = 0
    font = None
    if label:
        fpath = _font()
        if fpath:
            try:
                font = ImageFont.truetype(fpath, size=max(16, int(H * 0.028)))
                strip = int(font.size * 1.9)
            except Exception:  # noqa: BLE001
                font = None
    mat = Image.new("RGB", (cw + pad * 2, ch + pad * 2 + strip), (240, 236, 226))
    mat.paste(photo, (pad, pad))
    if font is not None and label:
        d = ImageDraw.Draw(mat)
        d.text((pad + 2, pad + ch + int(strip * 0.16)), label,
               fill=(38, 34, 28), font=font)
        tw = d.textlength(label, font=font)
        y_bar = pad + ch + int(strip * 0.16) + font.size + 4
        d.rectangle((pad + 2, y_bar, pad + 2 + max(40, int(tw * 0.6)), y_bar + 3),
                    fill=(201, 162, 39))

    rot = mat.convert("RGBA").rotate(2.2, expand=True, resample=Image.BICUBIC)
    margin = 34
    canvas = Image.new("RGBA", (rot.width + margin * 2, rot.height + margin * 2),
                       (0, 0, 0, 0))
    # soft drop shadow behind the card
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.rectangle((margin + 10, margin + 16, margin + 10 + rot.width,
                 margin + 16 + rot.height), fill=(0, 0, 0, 150))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    canvas.alpha_composite(rot, (margin, margin))
    arr = np.asarray(canvas)
    return arr[:, :, :3].copy(), (arr[:, :, 3].astype("float32") / 255.0)


def overlay(base_clip, img_path: Path, label: str, *, dur: float,
            t0: Optional[float], W: int, H: int, kind: str = ""):
    """Composite the ref card over a scene clip. Returns (clip, t_shown)."""
    from moviepy import CompositeVideoClip, ImageClip
    from moviepy.video.fx import CrossFadeIn, CrossFadeOut

    t_in = t0 if t0 is not None else dur * 0.30
    t_in = max(0.15, min(t_in, max(0.2, dur - 1.4)))
    show = min(4.2, dur - t_in - 0.15)
    if show < 1.2:            # not enough scene left for a readable card
        return base_clip, None

    rgb, alpha = _card_arrays(Path(img_path), label, W, H)
    card = ImageClip(rgb).with_mask(ImageClip(alpha, is_mask=True))
    ch_, cw_ = rgb.shape[0], rgb.shape[1]
    x_end = int(W - cw_ - W * 0.035)
    y0 = int(H * 0.10)
    slide = 0.38

    def pos(t):
        p = min(1.0, max(0.0, t / slide))
        p = p * p * (3 - 2 * p)                      # smoothstep entrance
        x = x_end + (1 - p) * (cw_ * 0.35 + 40)
        y = y0 + 4.0 * math.sin((t + 0.4) * 1.3)     # gentle float, never static
        return (x, y)

    card = (card.with_duration(show).with_start(t_in).with_position(pos)
            .with_effects([CrossFadeIn(0.22), CrossFadeOut(0.35)]))
    out = CompositeVideoClip([base_clip, card],
                             size=(W, H)).with_duration(base_clip.duration)
    return out, t_in
