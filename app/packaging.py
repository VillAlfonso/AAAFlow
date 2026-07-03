"""YouTube packaging — deterministic upload kit for a finished video.

Running multiple channels means every video also needs its *packaging*: title
options, a description with chapter timestamps, tags, and a thumbnail. All of
it derives deterministically from the storyboard + timeline (and the project's
channel), so packaging quality doesn't depend on which model wrote the script.

Writes ``video/youtube_package.md`` + ``thumbnail.png`` in the project dir.
Thumbnails MAY carry text — the no-text rule is about frames burned into the
video itself, never the packaging.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from . import channels, projects

_STOP = set("""a an and are as at be but by for from had has have he her his i in
is it its of on or our she that the their there they this to was we were what
when who will with you your not so if then than into over under after before
about just one two it's don't didn't he's she's out up down all can could would
did do does got get his him them how more most other some very much many made
make makes""".split())


def _words(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z'-]+", (text or "").lower())


def _clause(text: str, max_words: int = 6) -> str:
    """First clause of a narration line, cleaned up for a chapter label."""
    t = re.split(r"[.!?…]", (text or "").strip())[0]
    t = re.split(r"[,;:—–]", t)[0].strip()
    ws = t.split()
    if len(ws) > max_words:
        t = " ".join(ws[:max_words])
    return (t[:1].upper() + t[1:]) if t else "Chapter"


def _stamp(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def _chapters(project: Dict) -> List[Dict]:
    tl = project.get("timeline") or projects.recompute_timeline(project)
    rows = (tl or {}).get("scenes") or []
    scene_by_id = {str(s.get("id")): s for s in project.get("scenes", [])}
    out: List[Dict] = []
    last = -999.0
    for i, r in enumerate(rows):
        sc = scene_by_id.get(str(r.get("id"))) or {}
        if i == 0 or (r["start"] - last) >= 25.0:
            out.append({"time": 0.0 if i == 0 else r["start"],
                        "stamp": _stamp(0 if i == 0 else r["start"]),
                        "label": _clause(sc.get("narration") or sc.get("image_prompt") or "")})
            last = 0.0 if i == 0 else r["start"]
    return out


def _bigrams(text: str, top: int = 6) -> List[str]:
    """Recurring two-word phrases — the video-unique long-tail search terms."""
    ws = [w for w in _words(text) if w not in _STOP and len(w) > 2]
    pairs = Counter(f"{a} {b}" for a, b in zip(ws, ws[1:]))
    return [p for p, c in pairs.most_common(top * 3) if c >= 2][:top]


def _tags(project: Dict, channel: Optional[Dict]) -> List[str]:
    """SEO tag mix, most-specific first: this video's phrases + words, then the
    channel's niche keyword pool. Unique per video by construction — the
    video-specific terms always lead and fill most of the budget."""
    text = " ".join((s.get("narration") or "") for s in project.get("scenes", []))
    title = project.get("video", {}).get("title") or ""
    tags: List[str] = []

    def _add(t: str):
        t = t.strip().lower()
        if t and t not in tags:
            tags.append(t)

    tw = [w for w in _words(title) if w not in _STOP]
    for i in range(len(tw) - 1):                  # title phrases ("eiffel tower")
        _add(f"{tw[i]} {tw[i+1]}")
    for p in _bigrams(text):
        _add(p)
    counts = Counter(w for w in _words(text) if len(w) > 3 and w not in _STOP)
    for w, _c in counts.most_common(12):
        _add(w)
    if channel:
        for k in (channel.get("seo_keywords") or []):
            _add(k)
        for w in _words(channel.get("niche") or "")[:4]:
            if len(w) > 3 and w not in _STOP:
                _add(w)
        _add(channel.get("name", ""))
    out, budget = [], 470          # YouTube tag budget is 500 chars
    for t in tags:
        if budget - len(t) - 1 > 0:
            out.append(t)
            budget -= len(t) + 1
    return out


def build(pid: str, thumb_text: Optional[str] = None) -> Dict:
    p = projects.get_project(pid)
    if not p:
        raise ValueError("project not found")
    video = p.get("video", {})
    scenes = p.get("scenes", [])
    ch = channels.get(p.get("channel"))
    title = (video.get("title") or p.get("name") or "Untitled").strip().rstrip(".")
    hook = (scenes[0].get("narration") or "").strip().rstrip(".") if scenes else ""

    titles = [title]
    if hook and 24 <= len(hook) <= 70 and hook.lower() != title.lower():
        titles.append(hook)
    titles.append(f"{title} — {ch['tagline'].rstrip('.')}" if ch and ch.get("tagline")
                  else f"{title} — The Full Story")

    chapters = _chapters(p)
    tags = _tags(p, ch)
    hashtags = ["#" + re.sub(r"[^a-z0-9]", "", t) for t in tags[:3] if t and len(t) < 24]
    # First ~150 chars are the search snippet: hook + the title keywords, front-loaded.
    synopsis = f"The full story of {title[:1].lower() + title[1:]}."
    if ch:
        synopsis += f" From {ch.get('name')} — {ch.get('tagline', '')}"

    desc_lines = ([hook + "."] if hook else []) + [synopsis, ""]
    if len(chapters) >= 3:
        desc_lines += ["Chapters:"] + [f"{c['stamp']} {c['label']}" for c in chapters] + [""]
    if ch:
        niche_word = (_words(ch.get("niche") or "story") or ["story"])[0]
        desc_lines += [f"New {niche_word} stories every week — subscribe so the "
                       f"next one finds you.", ""]
    desc_lines += [" ".join(hashtags)]
    description = "\n".join(desc_lines).strip()

    thumb_rel = None
    try:
        thumb_rel = render_thumbnail(p, thumb_text)
    except Exception as exc:  # noqa: BLE001 — packaging text must not die on PIL issues
        thumb_rel = None
        thumb_err = str(exc)
    else:
        thumb_err = None

    md = [f"# YouTube package — {p.get('name')}", "",
          "## Title options"] + [f"{i+1}. {t}" for i, t in enumerate(titles)] + [
          "", "## Description", "```", description, "```",
          "", "## Tags (comma-separated)", ", ".join(tags), ""]
    if thumb_rel:
        md += [f"Thumbnail: `{thumb_rel}`", ""]
    out_file = projects.project_dir(pid) / "video" / "youtube_package.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(md), encoding="utf-8")

    seo = {"titles": titles, "description": description, "tags": tags,
           "hashtags": hashtags, "chapters": chapters,
           "file": "video/youtube_package.md", "thumbnail": thumb_rel,
           "thumbnail_error": thumb_err}
    # persist on the project so the Publish page (and the uploader) use the
    # user-edited version, not a regeneration
    import time as _t
    p2 = projects.get_project(pid)
    if p2 is not None:
        p2["seo"] = {**{k: seo[k] for k in ("titles", "description", "tags",
                                            "hashtags", "chapters", "thumbnail")},
                     "built": _t.time()}
        projects.save_project(p2)
    return seo


# --- thumbnail ---------------------------------------------------------------
_FONTS = [r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\seguibl.ttf",
          r"C:\Windows\Fonts\arialbd.ttf"]


def _pick_frame(p: Dict) -> Optional[Path]:
    d = projects.project_dir(p["id"])
    scenes = p.get("scenes", [])
    want = str(p.get("video", {}).get("thumbnail_scene") or "")
    ordered = ([s for s in scenes if str(s.get("id")) == want]
               + [s for s in scenes if s.get("motion_type") == "ambient"]
               + scenes)
    for s in ordered:
        rel = s.get("image_file")
        if rel:
            f = d / rel
            up = f.with_name(f.stem + "_up2x.png")   # prefer the sharpened copy
            if up.exists():
                return up
            if f.exists():
                return f
    return None


def render_thumbnail(p: Dict, text: Optional[str] = None,
                     size=(1280, 720)) -> str:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    frame = _pick_frame(p)
    if not frame:
        raise ValueError("no rendered scene image to build a thumbnail from")
    W, H = size
    im = Image.open(frame).convert("RGB")
    scale = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)),
                   Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2,
                  (im.width - W) // 2 + W, (im.height - H) // 2 + H))

    title = (text or p.get("video", {}).get("title") or p.get("name") or "").strip()
    words = title.split()
    if not text and len(words) > 5:
        title = " ".join(words[:5])
    title = title.upper().rstrip(".!,")

    if title:
        # darken the text zone so the type always reads
        grad = Image.new("L", (1, H), 0)
        for y in range(H):
            grad.putpixel((0, y), int(190 * max(0, (y / H - 0.45)) ** 1.4))
        im.paste(Image.new("RGB", (W, H), (8, 8, 12)), (0, 0),
                 grad.resize((W, H)))
        draw = ImageDraw.Draw(im)
        font_path = next((f for f in _FONTS if Path(f).exists()), None)
        # wrap to <=2 lines and shrink until it fits
        for fsize in range(150, 60, -8):
            font = (ImageFont.truetype(font_path, fsize) if font_path
                    else ImageFont.load_default())
            lines, cur = [], ""
            for w in title.split():
                t = (cur + " " + w).strip()
                if draw.textlength(t, font=font) <= W - 120:
                    cur = t
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
            if len(lines) <= 2 and all(draw.textlength(l, font=font) <= W - 120
                                       for l in lines):
                break
        lh = fsize + 12
        y = H - 60 - lh * len(lines)
        for line in lines:
            draw.text((60, y), line, font=font, fill=(255, 255, 255),
                      stroke_width=max(4, fsize // 16), stroke_fill=(10, 10, 14))
            y += lh
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60))

    out = projects.project_dir(p["id"]) / "thumbnail.png"
    im.save(out)
    return "thumbnail.png"
