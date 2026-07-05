"""YouTube packaging — deterministic upload kit for a finished video.

Running multiple channels means every video also needs its *packaging*: title
options, a description with chapter timestamps, tags, and a thumbnail. All of
it derives deterministically from the storyboard + timeline (and the project's
channel), so packaging quality doesn't depend on which model wrote the script.

Writes ``video/youtube_package.md`` + ``thumbnail.png`` in the project dir.
Thumbnails MAY carry text — the no-text rule is about frames burned into the
video itself, never the packaging. Thumbnails are composited by ``app/thumbs.py``
(fixed templates, real typeset text, mood-graded — the emotion rule).

TITLE RULE (user mandate 2026-07-05, hardcoded): titles must open a CURIOSITY
GAP, never state face value. "They Lied About the Eiffel Tower" beats "The
Story of Victor Lustig". The option list therefore leads with the cold-open
hook (written as a gap by spec) and a curiosity reframe of the subject; the
storyboard's literal title rides along only as a fallback.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional

from . import channels, projects, thumbs

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


# --- curiosity titles (HARD RULE: open a gap, never state face value) ----------
_CURIOSITY_MARKERS = re.compile(
    r"\b(no ?one|nobody|never|vanish\w*|disappear\w*|impossible|unexplained|"
    r"secret\w*|hidden|lie[ds]?|lied|hoax|cursed?|haunt\w*|wrong|mystery|"
    r"shouldn't|couldn't|can't|why |what |gone|missing|found|until)\b", re.I)


_GENERIC = set("man woman person people story thing place case night day time "
               "history video".split())


def _subject_np(title: str, max_words: int = 6) -> str:
    """The subject noun-phrase of a title — cut before the explanatory clause.
    Returns "" when the cut leaves nothing specific ("The Man") — a weak
    subject makes a junk reframe, so we'd rather skip it."""
    t = re.split(r"[.!?]", (title or "").strip())[0].strip()   # first sentence only
    for cut in (" — ", " – ", ": ", " that ", " who ", " and every", " and the "):
        i = t.lower().find(cut.lower())
        if i > 3:
            t = t[:i]
    t = " ".join(t.split()[:max_words])
    specific = [w for w in _words(t)
                if w not in _STOP and w not in _GENERIC and len(w) > 2]
    if not specific:
        return ""
    return (t[0].lower() + t[1:]) if t[:4].lower() == "the " else t


def _curiosity_titles(title: str, hook: str, narration: str) -> List[str]:
    """Deterministic curiosity reframes of the subject. The viewer should think
    'wait — what?', not 'ah, a video about X'."""
    np = _subject_np(title)
    low = narration.lower()
    out: List[str] = []
    # The cold open is WRITTEN as a curiosity gap by spec — best title we have.
    if hook and 20 <= len(hook) <= 70 and not hook.lower().startswith(title.lower()[:12]):
        out.append(hook)
    if np:
        Np = np[0].upper() + np[1:]
        if re.search(r"\b(lie[ds]?|fraud|fake|hoax|con |conned|swindle)", low):
            out.append(f"The Lie Behind {Np}")
        elif re.search(r"\b(vanish\w*|disappear\w*|missing|without a trace)", low):
            out.append(f"What Happened to {Np}?")
        elif re.search(r"\b(curse\w*|haunt\w*|possess\w*)", low):
            out.append(f"Why No One Will Go Near {Np}")
        elif re.search(r"\b(unexplained|no one knows|nobody knows|never solved|unsolved)", low):
            out.append(f"No One Can Explain {Np}")
        else:
            out.append(f"The Truth About {Np}")
    return out


def build(pid: str, thumb_text: Optional[str] = None,
          thumb_template: Optional[str] = None) -> Dict:
    p = projects.get_project(pid)
    if not p:
        raise ValueError("project not found")
    video = p.get("video", {})
    scenes = p.get("scenes", [])
    ch = channels.get(p.get("channel"))
    title = (video.get("title") or p.get("name") or "Untitled").strip().rstrip(".")
    hook = (scenes[0].get("narration") or "").strip().rstrip(".") if scenes else ""
    narration = " ".join((s.get("narration") or "") for s in scenes)

    # Curiosity-gap options lead; the literal storyboard title is a fallback —
    # UNLESS the author already wrote a gap (markers present), then it leads.
    titles: List[str] = []

    def _add_title(t: str):
        t = (t or "").strip().rstrip(".")
        if t and len(t) <= 100 and t.lower() not in (x.lower() for x in titles):
            titles.append(t)

    # A multi-sentence title ("He Sold the Eiffel Tower. Twice.") is already a
    # crafted hook — face-value titles are single noun phrases.
    already_gap = bool(_CURIOSITY_MARKERS.search(title)
                       or re.search(r"[.!?]\s+\S", title))
    if already_gap:
        _add_title(title)
        if hook and 20 <= len(hook) <= 70:
            _add_title(hook)
    else:
        for t in _curiosity_titles(title, hook, narration):
            _add_title(t)
    _add_title(title)
    _add_title(f"{title} — {ch['tagline'].rstrip('.')}" if ch and ch.get("tagline")
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
    # Auto-attribution: any CC-licensed music/SFX the scorer used must be credited
    # here (CC0 needs none, but the scorer only lists what actually requires it).
    credits = ((p.get("audio_plan") or {}).get("attribution")) or []
    if credits:
        desc_lines += ["Credits:"] + credits + [""]
    desc_lines += [" ".join(hashtags)]
    description = "\n".join(desc_lines).strip()

    thumb_rel, thumb_err, thumb_info = None, None, {}
    try:
        thumb_info = thumbs.build_for_project(p, text=thumb_text,
                                              template=thumb_template)
        thumb_rel = thumb_info.get("thumbnail")
    except Exception as exc:  # noqa: BLE001 — packaging text must not die on PIL issues
        thumb_err = str(exc)

    md = [f"# YouTube package — {p.get('name')}", "",
          "## Title options"] + [f"{i+1}. {t}" for i, t in enumerate(titles)] + [
          "", "## Description", "```", description, "```",
          "", "## Tags (comma-separated)", ", ".join(tags), ""]
    if thumb_rel:
        md += [f"Thumbnail: `{thumb_rel}` (template “{thumb_info.get('template')}”, "
               f"mood “{thumb_info.get('mood')}”; variants in video/thumbs/)", ""]
    out_file = projects.project_dir(pid) / "video" / "youtube_package.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(md), encoding="utf-8")

    seo = {"titles": titles, "description": description, "tags": tags,
           "hashtags": hashtags, "chapters": chapters,
           "file": "video/youtube_package.md", "thumbnail": thumb_rel,
           "thumbnail_variants": thumb_info.get("variants") or {},
           "thumb_template": thumb_info.get("template"),
           "thumb_mood": thumb_info.get("mood"),
           "thumbnail_error": thumb_err}
    # persist on the project so the Publish page (and the uploader) use the
    # user-edited version, not a regeneration
    import time as _t
    p2 = projects.get_project(pid)
    if p2 is not None:
        p2["seo"] = {**{k: seo[k] for k in ("titles", "description", "tags",
                                            "hashtags", "chapters", "thumbnail",
                                            "thumbnail_variants", "thumb_template",
                                            "thumb_mood")},
                     "built": _t.time()}
        projects.save_project(p2)
    return seo


# Thumbnail composition moved to app/thumbs.py (templated, mood-graded,
# real typeset text — the emotion rule).
