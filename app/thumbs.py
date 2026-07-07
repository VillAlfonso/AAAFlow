"""Templated thumbnail composer — premade reusable layouts, real typeset text.

HARD RULES (user mandate 2026-07-05, baked into the pipeline — not per-video
judgment calls):

1. **The thumbnail must carry EMOTION.** A thumbnail earns the click because
   the viewer can *feel* the video's mood before reading a word — that's why
   faces work. So frame choice prefers the most emotionally loaded scene
   (expressive people on a reveal/impact beat > people > beat scenes >
   ambient), and every composite gets a deterministic MOOD GRADE — the same
   mood the audio scorer hears (``grammar.mood_for``) tints the color, sets
   the vignette, and picks the kicker line. Calm reads calm, dread reads
   dark, money reads gold. One shared cinematic language.

2. **No AI-drawn text, ever.** All type is genuine fonts composited by PIL —
   title + kicker with stroke and soft shadow. The image model never draws a
   glyph (its "text" is gibberish and reads as AI instantly).

3. **Templates are fixed and reusable.** Five layouts (spotlight · case-file ·
   reveal · split · bar) every video reuses forever — same reason real
   channels do: the brand stays recognizable. Tunables (and the mood-grade
   table) live in ``data/thumb_templates.json``; a channel pins its default
   template + accent in ``channel.defaults.thumb`` and may override per video.

Every package render writes ALL five variants to ``video/thumbs/<tpl>.png``
plus the chosen one as ``thumbnail.png`` (what the uploader sends), so
swapping the look is a file pick, not a re-render.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import channels, config, grammar, projects, scenes, storage

TEMPLATES_FILE = config.DATA_DIR / "thumb_templates.json"

_FONT_DIR = Path(r"C:\Windows\Fonts")
_TITLE_FONTS = ["impact.ttf", "seguibl.ttf", "arialbd.ttf"]
_KICKER_FONTS = ["seguibl.ttf", "arialbd.ttf", "impact.ttf"]

_STOP = set("a an the of in on and or to for with that this from at by is was "
            "are were it its as into over under".split())

# The whole look of the system in one editable file — layout tunables + the
# mood→grade table the emotion rule runs on. Every entry carries its why.
DEFAULT_TEMPLATES: Dict = {
    "_why": ("Thumbnails are composited from fixed reusable templates with real "
             "typeset text (AI glyphs are gibberish) and are REQUIRED to carry "
             "the video's emotion — mood-graded color, vignette and kicker — "
             "because viewers click what they can already feel."),
    "default": "spotlight",
    "max_words": 5,
    "spotlight": {"panel": 0.56, "opacity": 0.88,
                  "why": "classic documentary look: dark side panel, huge title, "
                         "subject untouched on the other side"},
    "case-file": {"tag_angle": -5, "vignette": 0.5,
                  "why": "evidence-tag energy: rotated accent label + stamped "
                         "title — mystery/true-crime"},
    "reveal": {"vignette": 0.78, "ring": True,
               "why": "one lit subject in darkness + a ring that says LOOK — "
                      "pure curiosity gap"},
    "split": {"seam": 0.055,
              "why": "two-panel contrast (before/after, X vs Y) — instant story"},
    "bar": {"bar": 0.24,
            "why": "clean lower-third title bar — reads at tiny sizes, minimal "
                   "channels"},
    "poster": {"inset": 0.035, "vignette": 0.55,
               "why": "vintage poster: double accent frame + centered title — "
                      "collectible, event energy"},
    "big-word": {"fill": 0.92,
                 "why": "ONE giant word owns the frame, the rest whispers above "
                        "it — maximum thumb-size legibility, pure intrigue"},
    # High-variance rule (user mandate 2026-07-05): consecutive videos must not
    # look templated. When a channel pins no template, the composer rotates
    # through this pool per video (seeded by project id) and never repeats the
    # previous video's pick.
    "variance_pool": ["spotlight", "case-file", "reveal", "split", "bar",
                      "poster", "big-word"],
    # mood → (tint hex, tint strength, vignette floor, saturation, kicker lines).
    # Same mood labels grammar.mood_for gives the audio scorer — sound and
    # thumbnail always agree about what the video feels like.
    # Default kickers must be TRUE of any video in the mood (a kicker is a
    # promise — "NOBODY CAME BACK" on a con story is a lie and reads as spam).
    # Channels should pin their own (e.g. "EXHIBIT No. {n}").
    "mood_grades": {
        "dark":      {"tint": "#141c2b", "strength": 0.30, "vignette": 0.6,
                      "saturation": 0.92,
                      "kickers": ["NEVER EXPLAINED", "STILL UNSOLVED",
                                  "THE PART THEY LEFT OUT"]},
        "tense":     {"tint": "#2b1c16", "strength": 0.26, "vignette": 0.52,
                      "saturation": 0.97,
                      "kickers": ["SOMETHING WENT WRONG", "IT ALMOST WORKED",
                                  "NOBODY SAW IT COMING"]},
        "money":     {"tint": "#2b2210", "strength": 0.22, "vignette": 0.42,
                      "saturation": 1.08,
                      "kickers": ["THE PERFECT LIE", "EVERYONE BELIEVED IT",
                                  "WHERE DID IT GO?"]},
        "calm":      {"tint": "#152026", "strength": 0.16, "vignette": 0.34,
                      "saturation": 1.0,
                      "kickers": ["TAKE A CLOSER LOOK", "STRANGER THAN IT SEEMS"]},
        "emotional": {"tint": "#281a24", "strength": 0.24, "vignette": 0.5,
                      "saturation": 1.02,
                      "kickers": ["THEY NEVER KNEW", "NOBODY TALKS ABOUT THIS"]},
        "neutral":   {"tint": "#10151a", "strength": 0.14, "vignette": 0.4,
                      "saturation": 1.0,
                      "kickers": ["THE FULL STORY", "WHAT REALLY HAPPENED"]},
    },
}


def _params() -> Dict:
    """Live tunables — auto-writes the defaults file so it's editable."""
    cur = storage.read_json(TEMPLATES_FILE, None)
    if not isinstance(cur, dict) or "mood_grades" not in cur:
        storage.write_json(TEMPLATES_FILE, DEFAULT_TEMPLATES)
        return dict(DEFAULT_TEMPLATES)
    return storage.deep_merge(dict(DEFAULT_TEMPLATES), cur)


# --- text ---------------------------------------------------------------------
def _headline(title: str, max_words: int) -> str:
    """The punchiest ≤N words of the title (thumb text ≠ the title — it's the
    emotional fragment of it). Never crosses a sentence boundary: a complete
    short sentence ("THE LIGHT WENT OUT") beats a longer broken clause."""
    t = (title or "").strip().strip("\"'“”")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    first = sentences[0] if sentences else t
    if len(first.split()) <= max_words:
        return first.rstrip(".,;:").upper()
    words = first.split()          # window WITHIN the first sentence only
    best_i, best = 0, -1.0
    for i in range(len(words) - max_words + 1):
        win = words[i:i + max_words]
        score = float(sum(len(w) for w in win if w.lower() not in _STOP))
        if i == 0:
            score += 2          # openings usually carry the subject
        if win[0].lower() in _STOP:
            score -= 4          # never start on "the/of/and"
        if score > best:
            best, best_i = score, i
    return " ".join(words[best_i:best_i + max_words]).upper().strip(".,;:—-")


def _font_path(names: List[str], override: Optional[str]) -> Optional[str]:
    for n in ([override] if override else []) + names:
        f = _FONT_DIR / n
        if f.exists():
            return str(f)
    return None


def _hex_rgb(h: str, default=(230, 169, 75)) -> Tuple[int, int, int]:
    m = re.match(r"^#([0-9a-fA-F]{6})$", (h or "").strip())
    if not m:
        return default
    v = int(m.group(1), 16)
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255)


# --- image helpers --------------------------------------------------------------
def _cover(frame: Path, W: int, H: int, fx: float = 0.5):
    from PIL import Image
    im = Image.open(frame).convert("RGB")
    sc = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * sc), round(im.height * sc)), Image.LANCZOS)
    x = int((im.width - W) * min(max(fx, 0.0), 1.0))
    y = (im.height - H) // 2
    return im.crop((x, y, x + W, y + H)).convert("RGBA")


def _thirds_energy(im) -> List[float]:
    """Contrast per horizontal third — where the subject probably is."""
    from PIL import ImageStat
    g = im.convert("L").resize((96, 54))
    return [ImageStat.Stat(g.crop((32 * i, 0, 32 * (i + 1), 54))).stddev[0]
            for i in range(3)]


def _vignette(im, strength: float, cx: float = 0.5, cy: float = 0.5,
              spread: float = 0.62) -> None:
    from PIL import Image, ImageDraw, ImageFilter
    if strength <= 0:
        return
    W, H = im.size
    s = 4
    m = Image.new("L", (W // s, H // s), 0)
    d = ImageDraw.Draw(m)
    rx, ry = int(W / s * spread), int(H / s * spread * 1.05)
    x0, y0 = int(W / s * cx) - rx, int(H / s * cy) - ry
    d.ellipse((x0, y0, x0 + 2 * rx, y0 + 2 * ry), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(W, H) // s // 6)).resize((W, H))
    dark = Image.new("RGBA", (W, H), (5, 6, 10, 255))
    dark.putalpha(m.point(lambda v: int((255 - v) * min(strength, 1.0))))
    im.alpha_composite(dark)


def _grade(im, grade: Dict) -> None:
    """The emotion rule's color half: tint toward the mood + saturation nudge.
    Subtle by design — it sets a feeling, it never repaints the art."""
    from PIL import Image, ImageEnhance
    tint = _hex_rgb(grade.get("tint") or "#10151a", (16, 21, 26))
    strength = float(grade.get("strength") or 0.15)
    overlay = Image.new("RGBA", im.size, tint + (int(255 * strength),))
    im.alpha_composite(overlay)
    sat = float(grade.get("saturation") or 1.0)
    if abs(sat - 1.0) > 0.01:
        base = ImageEnhance.Color(im.convert("RGB")).enhance(sat)
        im.paste(base.convert("RGBA"))
    contrast = ImageEnhance.Contrast(im.convert("RGB")).enhance(1.06)
    im.paste(contrast.convert("RGBA"))


def _fit(draw, text: str, font_path: Optional[str], max_w: int, max_lines: int,
         start: int, floor: int = 44):
    from PIL import ImageFont
    words = text.split()
    for size in range(start, floor - 1, -8):
        font = (ImageFont.truetype(font_path, size) if font_path
                else ImageFont.load_default())
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=font) <= max_w:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= max_lines and all(
                draw.textlength(l, font=font) <= max_w for l in lines):
            return font, lines
    return font, lines[:max_lines]


def _text_block(im, lines: List[str], font, x: int, y: int,
                fill=(255, 255, 255), stroke=(8, 8, 14),
                align: str = "left", box_w: Optional[int] = None) -> int:
    """Title type with a soft drop shadow + hard stroke — readable on anything."""
    from PIL import Image, ImageDraw, ImageFilter
    draw = ImageDraw.Draw(im)
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.08)

    def _lx(ln):
        if align == "center" and box_w:
            return x + (box_w - draw.textlength(ln, font=font)) / 2
        return x

    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    yy = y
    for ln in lines:
        sd.text((_lx(ln) + 4, yy + 7), ln, font=font, fill=(0, 0, 0, 210))
        yy += lh
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7)))
    yy = y
    sw = max(3, font.size // 16)
    for ln in lines:
        draw.text((_lx(ln), yy), ln, font=font, fill=fill,
                  stroke_width=sw, stroke_fill=stroke)
        yy += lh
    return yy


def _kicker_tag(im, text: str, accent, x: int, y: int, angle: float = 0.0,
                font_path: Optional[str] = None, size: int = 40) -> None:
    """A solid accent label carrying the kicker — dark type on bright tag."""
    from PIL import Image, ImageDraw, ImageFont
    if not text:
        return
    font = (ImageFont.truetype(font_path, size) if font_path
            else ImageFont.load_default())
    pad_x, pad_y = 26, 14
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = int(probe.textlength(text, font=font))
    asc, desc = font.getmetrics()
    tag = Image.new("RGBA", (tw + pad_x * 2, asc + desc + pad_y * 2), (0, 0, 0, 0))
    td = ImageDraw.Draw(tag)
    td.rectangle((0, 0, tag.width - 1, tag.height - 1),
                 fill=tuple(accent) + (255,))
    td.text((pad_x, pad_y), text, font=font, fill=(12, 10, 8))
    if angle:
        tag = tag.rotate(angle, expand=True, resample=Image.BICUBIC)
    im.paste(tag, (x, y), tag)


# --- the emotion rule: which frame ------------------------------------------------
def _scene_frames(p: Dict) -> List[Tuple[Dict, Path]]:
    d = projects.project_dir(p["id"])
    out = []
    for s in p.get("scenes", []):
        rel = s.get("image_file")
        if not rel:
            continue
        f = d / rel
        up = f.with_name(f.stem + "_up2x.png")     # prefer the sharpened copy
        if up.exists():
            out.append((s, up))
        elif f.exists():
            out.append((s, f))
    return out


def _pick_frames(p: Dict, n: int = 2) -> List[Path]:
    """Most emotionally loaded frames first (the hard rule): the author's pick,
    then expressive PEOPLE on a reveal/impact beat, then people, then beat
    scenes, then everything else."""
    avail = _scene_frames(p)
    if not avail:
        return []
    want = str(p.get("video", {}).get("thumbnail_scene") or "")

    def rank(item) -> Tuple:
        s, _f = item
        beat = grammar.beat_of(f"{s.get('narration') or ''} {s.get('image_prompt') or ''}")
        people = scenes.scene_has_people(s)
        shot = (s.get("shot") or "").lower()
        return (
            0 if str(s.get("id")) == want and want else 1,
            0 if (people and beat in ("reveal", "impact")) else 1,
            0 if people else 1,
            0 if beat else 1,
            0 if "close" in shot else 1,
        )

    ordered = sorted(avail, key=rank)
    picks: List[Path] = [ordered[0][1]]
    for s, f in reversed(ordered):                  # most-different second frame
        if f != picks[0]:
            picks.append(f)
            break
    return picks[:max(n, 1)]


# --- templates ---------------------------------------------------------------------
def _t_spotlight(frames, ctx):
    from PIL import Image
    W, H = ctx["size"]
    tp = ctx["params"]["spotlight"]
    base = _cover(frames[0], W, H, fx=0.5)
    e = _thirds_energy(base)
    panel_left = e[0] <= e[2]                    # panel over the quiet side
    _grade(base, ctx["grade"])
    pw = int(W * float(tp.get("panel", 0.56)))
    grad = Image.new("L", (pw, 1), 0)
    for x in range(pw):
        t = 1.0 - x / pw
        grad.putpixel((x, 0), int(255 * float(tp.get("opacity", 0.88)) * (t ** 0.8)))
    if not panel_left:
        grad = grad.transpose(Image.FLIP_LEFT_RIGHT)
    dark = Image.new("RGBA", (pw, H), (7, 8, 12, 255))
    dark.putalpha(grad.resize((pw, H)))
    base.alpha_composite(dark, (0 if panel_left else W - pw, 0))
    _vignette(base, ctx["grade"].get("vignette", 0.4) * 0.6)

    from PIL import ImageDraw
    draw = ImageDraw.Draw(base)
    box_w = int(pw * 0.86)
    font, lines = _fit(draw, ctx["title"], ctx["title_font"], box_w, 3, 148)
    asc, desc = font.getmetrics()
    block_h = int((asc + desc) * 1.08) * len(lines)
    x = 56 if panel_left else W - box_w - 56
    y = (H - block_h) // 2 + 20
    if ctx["kicker"]:
        _kicker_tag(base, ctx["kicker"], ctx["accent"], x, y - 74,
                    font_path=ctx["kicker_font"], size=34)
    _text_block(base, lines, font, x, y)
    draw.rectangle((x, y + block_h + 16, x + 180, y + block_h + 26),
                   fill=tuple(ctx["accent"]) + (255,))
    return base


def _t_casefile(frames, ctx):
    from PIL import ImageDraw
    W, H = ctx["size"]
    tp = ctx["params"]["case-file"]
    base = _cover(frames[0], W, H)
    _grade(base, ctx["grade"])
    _vignette(base, max(float(tp.get("vignette", 0.5)),
                        ctx["grade"].get("vignette", 0.4)))
    draw = ImageDraw.Draw(base)
    font, lines = _fit(draw, ctx["title"], ctx["title_font"], W - 160, 2, 138)
    asc, desc = font.getmetrics()
    block_h = int((asc + desc) * 1.08) * len(lines)
    _text_block(base, lines, font, 64, H - block_h - 56)
    if ctx["kicker"]:
        _kicker_tag(base, ctx["kicker"], ctx["accent"], 40, 44,
                    angle=float(tp.get("tag_angle", -5)),
                    font_path=ctx["kicker_font"], size=38)
    return base


def _t_reveal(frames, ctx):
    from PIL import ImageDraw
    W, H = ctx["size"]
    tp = ctx["params"]["reveal"]
    base = _cover(frames[0], W, H)
    e = _thirds_energy(base)
    fx = (0.18, 0.5, 0.82)[e.index(max(e))]      # the subject's third
    _grade(base, ctx["grade"])
    _vignette(base, max(float(tp.get("vignette", 0.78)),
                        ctx["grade"].get("vignette", 0.5)),
              cx=fx, cy=0.44, spread=0.44)
    draw = ImageDraw.Draw(base)
    if tp.get("ring", True):
        r = int(H * 0.21)
        cx_px, cy_px = int(W * fx), int(H * 0.44)
        draw.ellipse((cx_px - r, cy_px - r, cx_px + r, cy_px + r),
                     outline=tuple(ctx["accent"]) + (235,), width=7)
    font, lines = _fit(draw, ctx["title"], ctx["title_font"], W - 240, 2, 132)
    asc, desc = font.getmetrics()
    block_h = int((asc + desc) * 1.08) * len(lines)
    y = H - block_h - 48
    if ctx["kicker"]:   # top center — never over the lit subject or the title
        _kicker_tag(base, ctx["kicker"], ctx["accent"],
                    max((W - int(len(ctx["kicker"]) * 21) - 52) // 2, 40), 36,
                    font_path=ctx["kicker_font"], size=32)
    _text_block(base, lines, font, 120, y, align="center", box_w=W - 240)
    return base


def _t_split(frames, ctx):
    from PIL import Image, ImageDraw
    W, H = ctx["size"]
    a = _cover(frames[0], W, H, fx=0.3)
    if len(frames) > 1:
        b = _cover(frames[-1], W, H, fx=0.7)
    else:                                        # zoomed detail vs the wide
        b = _cover(frames[0], W, H, fx=0.5).resize((int(W * 1.7), int(H * 1.7)))
        b = b.crop((int(W * 0.35), int(H * 0.35),
                    int(W * 0.35) + W, int(H * 0.35) + H))
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(0, 0), (int(W * 0.58), 0), (int(W * 0.42), H), (0, H)], fill=255)
    base = Image.composite(a, b, mask).convert("RGBA")
    _grade(base, ctx["grade"])
    draw = ImageDraw.Draw(base)
    seam = int(W * float(ctx["params"]["split"].get("seam", 0.055)) / 4)
    draw.line([(int(W * 0.58), -8), (int(W * 0.42), H + 8)],
              fill=tuple(ctx["accent"]) + (255,), width=max(seam, 8))
    _vignette(base, ctx["grade"].get("vignette", 0.4) * 0.8)
    font, lines = _fit(draw, ctx["title"], ctx["title_font"], W - 140, 2, 126)
    _text_block(base, lines, font, 64, 44)
    if ctx["kicker"]:
        asc, desc = font.getmetrics()
        y = 44 + int((asc + desc) * 1.08) * len(lines) + 14
        _kicker_tag(base, ctx["kicker"], ctx["accent"], 64, y,
                    font_path=ctx["kicker_font"], size=30)
    return base


def _t_bar(frames, ctx):
    from PIL import Image, ImageDraw
    W, H = ctx["size"]
    tp = ctx["params"]["bar"]
    base = _cover(frames[0], W, H, fx=0.5)
    _grade(base, ctx["grade"])
    _vignette(base, ctx["grade"].get("vignette", 0.4) * 0.5)
    bh = int(H * float(tp.get("bar", 0.24)))
    bar = Image.new("RGBA", (W, bh), (8, 9, 13, 242))
    base.alpha_composite(bar, (0, H - bh))
    draw = ImageDraw.Draw(base)
    draw.rectangle((0, H - bh, 18, H), fill=tuple(ctx["accent"]) + (255,))
    font, lines = _fit(draw, ctx["title"], ctx["title_font"], W - 140,
                       2, min(int(bh * 0.52), 96), floor=40)
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.08)
    _text_block(base, lines, font, 54, H - bh + (bh - lh * len(lines)) // 2)
    if ctx["kicker"]:
        _kicker_tag(base, ctx["kicker"], ctx["accent"], 40, 40,
                    font_path=ctx["kicker_font"], size=34)
    return base


def _t_poster(frames, ctx):
    from PIL import ImageDraw
    W, H = ctx["size"]
    tp = ctx["params"].get("poster") or {}
    base = _cover(frames[0], W, H)
    _grade(base, ctx["grade"])
    _vignette(base, max(float(tp.get("vignette", 0.55)),
                        ctx["grade"].get("vignette", 0.4)))
    draw = ImageDraw.Draw(base)
    inset = int(min(W, H) * float(tp.get("inset", 0.035)))
    for k, wdt in ((inset, 5), (inset + 14, 2)):        # double frame
        draw.rectangle((k, k, W - k, H - k),
                       outline=tuple(ctx["accent"]) + (255,), width=wdt)
    font, lines = _fit(draw, ctx["title"], ctx["title_font"], W - 300, 2, 128)
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.08)
    _text_block(base, lines, font, 150, inset + 44, align="center", box_w=W - 300)
    if ctx["kicker"]:
        kw = int(len(ctx["kicker"]) * 19) + 52
        _kicker_tag(base, ctx["kicker"], ctx["accent"],
                    max((W - kw) // 2, inset + 20), H - inset - 92,
                    font_path=ctx["kicker_font"], size=32)
    return base


def _t_bigword(frames, ctx):
    from PIL import ImageDraw, ImageFont
    W, H = ctx["size"]
    base = _cover(frames[0], W, H)
    _grade(base, ctx["grade"])
    _vignette(base, max(0.45, ctx["grade"].get("vignette", 0.4)))
    draw = ImageDraw.Draw(base)
    words = ctx["title"].split()
    # the LAST strong word goes giant; everything before it stays a readable
    # phrase above ("THE LIGHT WENT" / "OUT" — never a gap-toothed sentence)
    bi = max((i for i, w in enumerate(words) if w.lower() not in _STOP),
             default=len(words) - 1) if words else 0
    big = words[bi] if words else ""
    rest = " ".join(words[:bi])
    # the giant word fills the width along the bottom
    size = 300
    fp = ctx["title_font"]
    while size > 90:
        font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        if draw.textlength(big, font=font) <= W * float(
                (ctx["params"].get("big-word") or {}).get("fill", 0.92)):
            break
        size -= 14
    asc, desc = font.getmetrics()
    y_big = H - (asc + desc) - 30
    if rest:
        rfont, rlines = _fit(draw, rest, fp, W - 160, 1, 84, floor=48)
        _text_block(base, rlines, rfont, 80, y_big - int(rfont.size * 1.5))
    _text_block(base, [big], font,
                int((W - draw.textlength(big, font=font)) / 2), y_big)
    draw.rectangle((int(W * 0.28), H - 22, int(W * 0.72), H - 12),
                   fill=tuple(ctx["accent"]) + (255,))
    if ctx["kicker"]:
        _kicker_tag(base, ctx["kicker"], ctx["accent"], 40, 40,
                    font_path=ctx["kicker_font"], size=32)
    return base


_TEMPLATES = {"spotlight": _t_spotlight, "case-file": _t_casefile,
              "reveal": _t_reveal, "split": _t_split, "bar": _t_bar,
              "poster": _t_poster, "big-word": _t_bigword}


# --- entry point ----------------------------------------------------------------
def _seed(pid: str) -> int:
    """Stable per-project number driving all variance picks."""
    return sum(ord(c) * (i + 3) for i, c in enumerate(pid or ""))


def _prev_template(p: Dict) -> Optional[str]:
    """The previous video's chosen template on this channel (never repeat it —
    the high-variance rule)."""
    try:
        sibs = projects.list_projects(p.get("channel"))
        mine = p.get("created") or 0
        prev = None
        for s in sorted(sibs, key=lambda x: x.get("created") or 0):
            if s.get("id") == p.get("id") or (s.get("created") or 0) >= mine:
                continue
            tpl = ((s.get("seo") or {}).get("thumb_template"))
            if tpl:
                prev = tpl
        return prev
    except Exception:  # noqa: BLE001 — variance never blocks a render
        return None


def _thumb_no(p: Dict) -> int:
    """A stable per-video serial for kicker patterns like 'EXHIBIT No. {n}'."""
    saved = (p.get("video") or {}).get("thumb_no")
    if saved:
        return int(saved)
    sibs = projects.list_projects(p.get("channel"))
    order = sorted(sibs, key=lambda x: x.get("created") or 0)
    n = next((i + 1 for i, x in enumerate(order) if x.get("id") == p.get("id")),
             len(order) + 1)
    p.setdefault("video", {})["thumb_no"] = n
    projects.save_project(p)
    return n


def build_for_project(p: Dict, text: Optional[str] = None,
                      template: Optional[str] = None,
                      size: Tuple[int, int] = (1280, 720)) -> Dict:
    """Render every template variant + the chosen one as thumbnail.png.
    Deterministic: same project, same result — regenerating is free."""
    params = _params()
    ch = channels.get(p.get("channel")) or {}
    tconf = ((ch.get("defaults") or {}).get("thumb") or {})

    frames = _pick_frames(p, 2)
    if not frames:
        raise ValueError("no rendered scene image to build a thumbnail from")

    narr = " ".join((s.get("narration") or "") for s in p.get("scenes", []))
    mood, _q = grammar.mood_for(narr)
    grades = params.get("mood_grades") or {}
    grade = dict(grades.get(mood) or grades.get("neutral") or {})

    accent = _hex_rgb(tconf.get("accent") or ((ch.get("ui") or {}).get("accent") or ""))
    kicker = (tconf.get("kicker") or "").strip()
    if kicker and "{n}" in kicker:
        kicker = kicker.replace("{n}", str(_thumb_no(p)))
    if not kicker:
        # variance: channel's own kicker pool (if any) + the mood's true-of-any-
        # video lines, picked per project — consecutive videos read differently
        ks = list(tconf.get("kicker_pool") or []) + list(grade.get("kickers") or [])
        kicker = ks[_seed(p["id"]) % len(ks)] if ks else ""
        if _seed(p["id"]) % 4 == 3:            # sometimes NO kicker at all
            kicker = ""

    title = _headline(text or p.get("video", {}).get("title") or p.get("name") or "",
                      int(params.get("max_words", 5)))
    ctx = {
        "size": size, "params": params, "grade": grade, "accent": accent,
        "kicker": kicker, "title": title,
        "title_font": _font_path(_TITLE_FONTS, tconf.get("font")),
        "kicker_font": _font_path(_KICKER_FONTS, tconf.get("kicker_font")),
    }

    pdir = projects.project_dir(p["id"])
    outdir = pdir / "video" / "thumbs"
    outdir.mkdir(parents=True, exist_ok=True)
    variants: Dict[str, str] = {}
    errors: List[str] = []
    for name, fn in _TEMPLATES.items():
        try:
            im = fn(frames, ctx).convert("RGB")
            from PIL import ImageFilter
            im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=55))
            im.save(outdir / f"{name}.png")
            variants[name] = f"video/thumbs/{name}.png"
        except Exception as exc:  # noqa: BLE001 — one bad layout must not kill the kit
            errors.append(f"{name}: {exc}")
    if not variants:
        raise ValueError("all thumbnail templates failed: " + "; ".join(errors))

    chosen = template or tconf.get("template")
    if not chosen:
        # HIGH VARIANCE (user mandate): rotate the pool per video, never
        # repeating the previous video's template on this channel.
        pool = [t for t in (params.get("variance_pool") or list(_TEMPLATES))
                if t in variants] or list(variants)
        k = _seed(p["id"]) % len(pool)
        if pool[k] == _prev_template(p) and len(pool) > 1:
            k = (k + 1) % len(pool)
        chosen = pool[k]
    if chosen not in variants:
        chosen = next(iter(variants))
    shutil.copy2(pdir / variants[chosen], pdir / "thumbnail.png")
    return {"thumbnail": "thumbnail.png", "template": chosen,
            "variants": variants, "text": title, "kicker": kicker,
            "mood": mood, "errors": errors}
