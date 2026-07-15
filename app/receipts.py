"""The RECEIPT MOVE — the classic YouTuber article-reference treatment.

A research screenshot doesn't just sit on screen: it floats in as a tilted
card over a blurred dark backdrop, drifts gently (never dead-still), and when
the narrator reaches the referenced point the camera EASES INTO the exact
region while an animated marker highlight sweeps across the quoted line —
the "as they say it, it zooms in on their point" move (user, 2026-07-05).

Timing comes from the one-take word timestamps (audio/words.json), so the
zoom lands on the SPOKEN word, not a guess.

Scene schema (set via PATCH /api/projects/{pid}/scenes/{sid}):

    "image_file":  "images/scene_0117.png",   # the screenshot / evidence still
    "image_locked": true,                      # batch regen never repaints it
    "receipt": {
        "focus":     [0.28, 0.30, 0.46, 0.22], # normalized x,y,w,h to zoom into
        "highlight": [0.30, 0.38, 0.40, 0.06], # optional marker-swept region
        "sync":      "five thousand dollars"   # phrase whose word time triggers
    }                                          # the zoom (else ~35% into scene)

Tunables live in the effects dictionary under "receipt" (grammar.receipt_cfg).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import grammar

# module defaults; data/effects_dictionary.json "receipt" section overrides
DEFAULTS = {
    "tilt_deg": -1.8,          # resting tilt of the card (never perfectly straight)
    "float_px": 7,             # gentle vertical bob amplitude
    "margin": 0.10,            # card inset from frame edges before the zoom
    "zoom_ease_s": 0.9,        # how long the push into the focus region takes
    "highlight_color": (255, 214, 60),
    "highlight_alpha": 0.42,
    "highlight_sweep_s": 0.45,
    "backdrop_blur": 22,
    "backdrop_dark": 0.72,
}


def _cfg() -> Dict:
    try:
        return {**DEFAULTS, **(grammar.dictionary().get("receipt") or {})}
    except Exception:  # noqa: BLE001
        return dict(DEFAULTS)


def _ease(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)                 # smoothstep


def _canvas(img_path: Path, W: int, H: int, cfg: Dict):
    """Pre-compose the floating-card canvas (blurred-screenshot backdrop +
    tilted, shadowed card) and return (canvas_rgb_np, card_rect_on_canvas)."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    shot = Image.open(img_path).convert("RGB")
    CW, CH = W * 2, H * 2                       # 2x canvas → clean zoom headroom
    # backdrop: the screenshot itself, cover-filled, blurred and darkened
    sc = max(CW / shot.width, CH / shot.height)
    bg = shot.resize((round(shot.width * sc), round(shot.height * sc)),
                     Image.LANCZOS)
    bg = bg.crop(((bg.width - CW) // 2, (bg.height - CH) // 2,
                  (bg.width - CW) // 2 + CW, (bg.height - CH) // 2 + CH))
    bg = bg.filter(ImageFilter.GaussianBlur(int(cfg["backdrop_blur"])))
    bg = ImageEnhance.Brightness(bg).enhance(1.0 - float(cfg["backdrop_dark"]))

    # card: the screenshot fit inside the margin, slight tilt, drop shadow
    m = float(cfg["margin"])
    fit = min((CW * (1 - 2 * m)) / shot.width, (CH * (1 - 2 * m)) / shot.height)
    card = shot.resize((round(shot.width * fit), round(shot.height * fit)),
                       Image.LANCZOS)
    pad = 14
    mat = Image.new("RGB", (card.width + pad * 2, card.height + pad * 2),
                    (238, 234, 224))
    mat.paste(card, (pad, pad))
    tilt = float(cfg["tilt_deg"])
    rot = mat.rotate(tilt, expand=True, resample=Image.BICUBIC)
    x = (CW - rot.width) // 2
    y = (CH - rot.height) // 2
    base = bg.convert("RGBA")
    sh = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.rectangle((x + 18, y + 26, x + rot.width + 18, y + rot.height + 26),
                fill=(0, 0, 0, 165))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))
    base.paste(rot, (x, y), rot.convert("RGBA"))
    canvas = np.asarray(base.convert("RGB"))
    # where the (untilted) screenshot content sits on the canvas — good enough
    # for focus/highlight mapping at small tilt angles
    cx = x + (rot.width - card.width) // 2
    cy = y + (rot.height - card.height) // 2
    return canvas, (cx, cy, card.width, card.height)


def render_receipt_clip(img_path, dur: float, *, W: int, H: int,
                        receipt: Optional[Dict] = None,
                        sync_local: Optional[float] = None):
    """A moviepy clip performing the receipt move for one scene."""
    import numpy as np
    from moviepy import VideoClip

    cfg = _cfg()
    rc = receipt or {}
    canvas, (cx, cy, cw, ch) = _canvas(Path(img_path), W, H, cfg)
    CH_, CW_ = canvas.shape[0], canvas.shape[1]

    def rect_on_canvas(nr) -> Tuple[float, float, float, float]:
        # accept [left, top, w, h] OR {"x","y","w","h"} where x,y are CENTER
        # (the overlay director / evidence board writes the dict form)
        if isinstance(nr, dict):
            w, h = float(nr["w"]), float(nr["h"])
            x = float(nr["x"]) - w / 2.0
            y = float(nr["y"]) - h / 2.0
        elif isinstance(nr, bool):             # highlight:true -> whole focus band
            x, y, w, h = 0.1, 0.45, 0.8, 0.1
        else:
            x, y, w, h = [float(v) for v in nr]
        return (cx + x * cw, cy + y * ch, max(w * cw, 1.0), max(h * ch, 1.0))

    # view rectangles: full frame → focus region (16:9-corrected, in-bounds)
    full = (0.0, (CH_ - CW_ * H / W) / 2 if CW_ * H / W < CH_ else 0.0,
            float(CW_), CW_ * H / W if CW_ * H / W < CH_ else float(CH_))
    if rc.get("focus"):
        fx, fy, fw, fh = rect_on_canvas(rc["focus"])
        pad_w = fw * 0.35
        vw = min(CW_, (fw + pad_w))
        vh = vw * H / W
        if vh < fh * 1.25:
            vh = min(CH_, fh * 1.25)
            vw = vh * W / H
        vx = min(max(0.0, fx + fw / 2 - vw / 2), CW_ - vw)
        vy = min(max(0.0, fy + fh / 2 - vh / 2), CH_ - vh)
        focus_view = (vx, vy, vw, vh)
    else:
        # no explicit focus: settle into the card's center
        vw = full[2] * 0.62
        vh = vw * H / W
        focus_view = (cx + cw / 2 - vw / 2,
                      min(max(0.0, cy + ch / 2 - vh / 2), CH_ - vh), vw, vh)

    t_zoom = sync_local if sync_local is not None else dur * 0.35
    t_zoom = max(0.6, min(t_zoom, max(0.7, dur - 1.2)))
    ease_s = float(cfg["zoom_ease_s"])
    hl = rect_on_canvas(rc["highlight"]) if rc.get("highlight") else None
    if hl:  # never let the marker spill off the card onto the backdrop
        hx0, hy0 = max(hl[0], cx), max(hl[1], cy)
        hx1 = min(hl[0] + hl[2], cx + cw)
        hy1 = min(hl[1] + hl[3], cy + ch)
        hl = (hx0, hy0, max(hx1 - hx0, 1.0), max(hy1 - hy0, 1.0))
    hl_t0 = t_zoom + ease_s * 0.55
    hl_sweep = float(cfg["highlight_sweep_s"])
    hl_col = np.array(cfg["highlight_color"], dtype=np.float32)
    hl_a = float(cfg["highlight_alpha"])
    bob = float(cfg["float_px"]) * (CW_ / W)

    def frame(t):
        p = _ease((t - t_zoom) / ease_s) if t > t_zoom else 0.0
        vx = full[0] + (focus_view[0] - full[0]) * p
        vy = full[1] + (focus_view[1] - full[1]) * p
        vw = full[2] + (focus_view[2] - full[2]) * p
        vh = full[3] + (focus_view[3] - full[3]) * p
        vy += bob * (1 - p) * math.sin(t * 1.4)          # the float, pre-zoom
        vy = min(max(0.0, vy), CH_ - vh)
        x0, y0 = int(vx), int(vy)
        x1, y1 = min(CW_, int(vx + vw)), min(CH_, int(vy + vh))
        crop = canvas[y0:y1, x0:x1]
        from PIL import Image as _Im
        out = np.asarray(_Im.fromarray(crop).resize((W, H), _Im.BILINEAR),
                         dtype=np.uint8)
        if hl and t >= hl_t0:
            sweep = _ease((t - hl_t0) / hl_sweep)
            sx = (hl[0] - vx) / vw * W
            sy = (hl[1] - vy) / vh * H
            sw = hl[2] / vw * W * sweep
            sh_ = hl[3] / vh * H
            ax0, ay0 = int(max(0, sx)), int(max(0, sy))
            ax1, ay1 = int(min(W, sx + sw)), int(min(H, sy + sh_))
            if ax1 > ax0 and ay1 > ay0:
                out = out.astype(np.float32)
                out[ay0:ay1, ax0:ax1] = (out[ay0:ay1, ax0:ax1] * (1 - hl_a)
                                         + hl_col * hl_a)
                out = out.astype(np.uint8)
        return out

    return VideoClip(frame, duration=dur)


def sync_time(scene: Dict, row: Optional[Dict], words: List,
              win_t0: float) -> Optional[float]:
    """Seconds into the scene when the receipt's sync phrase is SPOKEN."""
    phrase = ((scene.get("receipt") or {}).get("sync") or "").strip()
    if not (phrase and row and words):
        return None
    import re
    toks = re.findall(r"[a-z0-9']+", phrase.lower())
    if not toks:
        return None
    t0, t1 = float(row["start"]) + win_t0, float(row["end"]) + win_t0
    span = [(w, a) for (w, a, _b) in words if t0 - 0.05 <= a < t1]
    for j, (w, _a) in enumerate(span):
        if w == toks[0] and all(j + k < len(span) and span[j + k][0] == toks[k]
                                for k in range(min(len(toks), 3))):
            return max(0.0, span[j][1] - t0)
    return None
