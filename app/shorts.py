"""Shorts cutter — vertical 9:16 cuts of a finished video's best windows.

Shorts are the cheapest subscriber engine for a new channel, so every long
video should ship with two: the HOOK (the first ~30 s, which was written to
be the densest part) and the PAYOFF (the ending reveal). Both are rendered
through the normal assembler with a time window + 1080x1920 — same sources
(Wan clips cover-cropped, parallax re-rendered natively vertical, Ken Burns
stills), same one-mix audio, no burned text (Shorts get "#Shorts" in their
UPLOAD title, never in the frame).
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from . import assemble, jobs, projects, storage

MAX_SEC = 35.0        # short length target (YouTube allows more; hooks don't need it)
MIN_SEC = 12.0


def _boundary_near(rows: List[Dict], target: float, lo: float, hi: float) -> Optional[float]:
    """The scene boundary closest to `target` within [lo, hi]."""
    best, gap = None, 1e9
    for r in rows:
        t = float(r["end"])
        if lo <= t <= hi and abs(t - target) < gap:
            best, gap = t, abs(t - target)
    return best


def pick_windows(project: Dict, count: int = 2, max_sec: float = MAX_SEC) -> List[Dict]:
    tl = projects.recompute_timeline(project)
    rows = tl.get("scenes") or []
    total = float(tl.get("total_dur") or 0.0)
    if not rows or total < MIN_SEC:
        raise ValueError("Timeline too short to cut Shorts from.")
    out: List[Dict] = []
    # 1) the hook: 0 → scene boundary nearest 30 s
    end = _boundary_near(rows, 30.0, MIN_SEC, max_sec) or min(max_sec, total)
    out.append({"name": "hook", "window": [0.0, round(end, 3)]})
    # 2) the payoff: last ~30 s, starting ON a scene boundary
    if count >= 2 and total > end + MIN_SEC:
        start = _boundary_near(rows, total - 30.0, end, total - MIN_SEC)
        if start is not None:
            out.append({"name": "payoff", "window": [round(start, 3), round(total, 3)]})
    # 3) optional mid-peak: the boundary nearest the middle
    if count >= 3 and total > 3 * max_sec:
        mid = total / 2
        s = _boundary_near(rows, mid, out[0]["window"][1], total - max_sec)
        if s is not None:
            e = _boundary_near(rows, s + 30.0, s + MIN_SEC, s + max_sec) or (s + max_sec)
            out.append({"name": "mid", "window": [round(s, 3), round(min(e, total), 3)]})
    return out


def submit_shorts(pid: str, opts: Optional[Dict] = None) -> str:
    opts = opts or {}
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    wins = pick_windows(project, count=int(opts.get("count", 2)),
                        max_sec=float(opts.get("max_sec", MAX_SEC)))

    def task(progress) -> Dict:
        made = []
        for i, w in enumerate(wins):
            progress(f"Rendering short “{w['name']}” "
                     f"({w['window'][0]:.0f}–{w['window'][1]:.0f}s)",
                     0.05 + 0.9 * i / len(wins))
            out = assemble._render(pid, {
                "window": w["window"], "width": 1080, "height": 1920,
                "out_name": f"short_{w['name']}",
                **({k: v for k, v in opts.items() if k in ("preset", "sources")}),
            }, lambda s, f: progress(f"{w['name']}: {s}",
                                     0.05 + 0.9 * (i + f) / len(wins)))
            made.append({"name": w["name"], "file": out["rel"],
                         "duration": out["duration"], "window": w["window"]})
        proj = projects.get_project(pid)
        proj["shorts"] = made
        projects.save_project(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "shorts", "project": pid, "project_name": proj["name"],
            "text_preview": f"Cut {len(made)} Shorts: " +
                            ", ".join(f"{m['name']} {m['duration']:.0f}s" for m in made),
        })
        return {"shorts": made}

    return jobs.submit("shorts", task, pid=pid)
