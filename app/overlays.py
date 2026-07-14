"""The OVERLAY DIRECTOR: reads the storyboard, decides where text belongs.

User, 2026-07-14: "in scene one it says a date, so a system should be able to
read the source.json and determine where remotion comes in."

Wan renders content and NEVER text (hard rule). Every legitimate on-screen
word is typeset by Remotion, and this module is what decides which words,
which composition, and on which spoken moment. Its whole vocabulary lives in
``data/overlay_rules.json`` (editable, each rule carries its ``why``) — the
same philosophy as the effects grammar: teaching the system a new text move
is a JSON edit, never a code change.

Output, written onto each scene:

    scene["overlays"] = [{"comp": "DateChip", "props": {...},
                          "sync": "<spoken word to land on>", "seconds": 2.6,
                          "detector": "datestamp"}]

The assembler renders them (Remotion when ``overlay_engine: remotion``, the
PIL path otherwise) and words.json gives the exact spoken timing.

Re-runnable: ``plan(pid)`` recomputes from scratch, author-set overlays
(scene["overlays_locked"]) are never touched.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from . import config, storage

RULES_FILE = config.DATA_DIR / "overlay_rules.json"

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")

# "the 15th of July, 2020" / "July 15, 2020" / "15 July 2020"
RE_FULL_DATE = re.compile(
    rf"\b(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+of\s+({MONTHS}),?\s*(\d{{4}})?\b"
    rf"|\b({MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})\b"
    rf"|\b(\d{{1,2}})\s+({MONTHS})\s+(\d{{4}})\b", re.I)
RE_MONTH_YEAR = re.compile(rf"\b({MONTHS})\s+(\d{{4}})\b", re.I)
RE_YEAR = re.compile(r"\b(1[6-9]\d{2}|20[0-4]\d)\b")
RE_CLOCK = re.compile(r"\b(\d{1,2}:\d{2})\s*(UTC|GMT|AM|PM|am|pm)?\b")
# "Tampa, Florida" / "Lincoln, Montana" / "Butler, Pennsylvania"
RE_PLACE = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s+([A-Z][a-z]+"
                      r"(?:\s[A-Z][a-z]+)?)\b")
RE_CHAPTER = re.compile(
    r"^(a year earlier|back in\b|meanwhile\b|three weeks later|"
    r"in (?:march|april|may|june|july|august|september|october|november|"
    r"december|january|february)\b|on the \d{1,2}(?:st|nd|rd|th)? of\b|"
    r"by \d{4}\b|\d+ (?:days?|weeks?|months?|years?) later)", re.I)
RE_EMPHASIS = re.compile(r"\*([^*]+)\*")
RE_NAME = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})\b")

_STOP_PLACES = {"United States", "New York"}          # too generic to stamp alone


def rules() -> Dict:
    return storage.read_json(RULES_FILE, {}) or {}


def _first_word(text: str) -> Optional[str]:
    m = re.search(r"[A-Za-z0-9']+", text or "")
    return m.group(0) if m else None


def _fmt_date(m: re.Match) -> str:
    g = [x for x in m.groups() if x]
    if len(g) >= 3:
        day, month, year = None, None, None
        for x in g:
            if re.fullmatch(r"\d{4}", x):
                year = x
            elif re.fullmatch(r"\d{1,2}", x):
                day = x
            else:
                month = x
        parts = [p for p in (day, (month or "").upper(), year) if p]
        return " ".join(parts)
    return " ".join(x.upper() for x in g)


def _people_from_research(project: Dict) -> Dict[str, str]:
    """{name: role label} from research facts + the character bible."""
    out: Dict[str, str] = {}
    research = project.get("research") or {}
    blob = " ".join([research.get("summary") or ""]
                    + [str(f) for f in (research.get("facts") or [])])
    for m in RE_NAME.finditer(blob):
        name = m.group(1)
        if name in out or name.split()[0] in ("The", "This", "It", "And"):
            continue
        tail = blob[m.end():m.end() + 90]
        role = ""
        agem = re.search(r",\s*(\d{2}),", tail)
        if agem:
            role = f"age {agem.group(1)}"
        placem = RE_PLACE.search(tail)
        if placem:
            role = (role + ", " if role else "") + placem.group(0)
        out[name] = role
    return out


def plan(project: Dict, channel: Optional[Dict] = None) -> List[Dict]:
    """Decide every typeset moment. Writes scene["overlays"]; returns the plan."""
    rl = rules()
    det = rl.get("detectors") or {}
    gat = rl.get("gating") or {}
    style = rl.get("style") or {}
    accent = (((channel or {}).get("ui") or {}).get("accent")
              if style.get("accent_from_channel_ui") else None) or "#b33a2b"
    font = style.get("font", "Georgia, serif")
    ink = style.get("ink", "#f2ede0")

    scenes = project.get("scenes") or []
    people = _people_from_research(project)
    seen_people = set()
    counts: Dict[str, int] = {}
    last_i: Dict[str, int] = {}
    out: List[Dict] = []
    budget = int(len(scenes) * float(gat.get("max_text_share", 0.55)))
    used = 0

    def allowed(kind: str, i: int) -> bool:
        d = det.get(kind) or {}
        if used >= budget:
            return False
        if counts.get(kind, 0) >= int(d.get("max_per_video", 99)):
            return False
        gap = int(d.get("min_gap_scenes", 0))
        return i - last_i.get(kind, -99) >= gap

    for i, s in enumerate(scenes):
        if s.get("overlays_locked"):
            continue
        s["overlays"] = []
        nar = (s.get("narration") or "").strip()
        if not nar:
            continue
        picked: Optional[Dict] = None

        # 1. CHAPTER card — a signposted jump owns the whole frame
        if not picked and RE_CHAPTER.match(nar) and allowed("chapter", i) and i > 2:
            title = re.split(r"[.,]", nar)[0].strip()
            picked = {"detector": "chapter", "comp": "SegmentCard",
                      "props": {"title": title.upper(), "kicker": "",
                                "bg": "#0e0e11", "ink": ink, "accent": accent,
                                "font": font},
                      "sync": None,
                      "seconds": float((det.get("chapter") or {}).get("seconds", 2.2))}

        # 2. DATE + PLACE stamp (merged when both are in the line)
        if not picked:
            dm = RE_FULL_DATE.search(nar) or RE_MONTH_YEAR.search(nar) \
                or RE_CLOCK.search(nar) or RE_YEAR.search(nar)
            pm = RE_PLACE.search(nar)
            if pm and pm.group(0) in _STOP_PLACES:
                pm = None
            if (dm or pm) and (allowed("datestamp", i) or allowed("location", i)):
                bits = []
                if pm:
                    bits.append(pm.group(0).upper())
                if dm:
                    bits.append(_fmt_date(dm) if dm.re is RE_FULL_DATE
                                else dm.group(0).upper())
                sep = (det.get("location") or {}).get("merge_separator", "  ·  ")
                kind = "location" if pm else "datestamp"
                picked = {"detector": kind, "comp": "DateChip",
                          "props": {"text": sep.join(bits), "accent": accent},
                          "sync": _first_word((dm or pm).group(0)),
                          "seconds": float((det.get(kind) or {}).get("seconds", 2.6))}

        # 3. PERSON name tag on first mention
        if not picked and allowed("person", i):
            for name, role in people.items():
                if name in seen_people or name not in nar:
                    continue
                seen_people.add(name)
                picked = {"detector": "person", "comp": "RefCard",
                          "props": {"label": name.upper(), "sub": role,
                                    "accent": accent, "font": font},
                          "sync": name.split()[0],
                          "seconds": float((det.get("person") or {}).get("seconds", 3.2))}
                break

        # 4. EMPHASIS line (author *markup* only)
        if not picked and allowed("emphasis", i):
            em = RE_EMPHASIS.search(nar)
            if em:
                picked = {"detector": "emphasis", "comp": "KineticTitle",
                          "props": {"text": em.group(1), "accent": accent,
                                    "ink": ink, "font": font, "position": "lower"},
                          "sync": _first_word(em.group(1)),
                          "seconds": float((det.get("emphasis") or {}).get("seconds", 2.4))}

        # 5. author CALLOUT
        if not picked and s.get("callout") and allowed("callout", i):
            c = s["callout"]
            picked = {"detector": "callout", "comp": "ArrowCallout",
                      "props": {"x": float(c.get("x", 0.6)), "y": float(c.get("y", 0.4)),
                                "r": float(c.get("r", 0.09)),
                                "label": str(c.get("label", "")), "accent": accent,
                                "font": font},
                      "sync": c.get("sync"),
                      "seconds": float((det.get("callout") or {}).get("seconds", 2.4))}

        if picked:
            s["overlays"] = [picked]
            counts[picked["detector"]] = counts.get(picked["detector"], 0) + 1
            last_i[picked["detector"]] = i
            used += 1
            out.append({"scene": s["id"], **picked})

    return out


def plan_project(pid: str) -> Dict:
    """Re-run the director on a saved project and persist the plan."""
    from . import channels, projects
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    ch = channels.get(project.get("channel")) if project.get("channel") else None
    rows = plan(project, ch)
    projects.save_project(project)
    by_kind: Dict[str, int] = {}
    for r in rows:
        by_kind[r["detector"]] = by_kind.get(r["detector"], 0) + 1
    return {"overlays": len(rows), "by_kind": by_kind, "plan": rows}
