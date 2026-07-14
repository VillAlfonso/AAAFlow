"""Technique pass: the analyzer's editing-literate eye + the needs manifest.

Runs a gathered pack's frame sheets through the local VLM (app/vlm.py) and
writes back into the pack folder:

  report.json["techniques"]   per-tile rows + the aggregate profile
  techniques.md               human-readable: media mix, devices, per-sheet log
  needs.json                  observed moves our pipeline can NOT execute yet

The needs manifest is the self-improvement hook (user, 2026-07-13: "a system
where it takes a look at the findings and then downloads everything it needs
and then implements it properly"): each entry names the observed label, its
share of the reference video, and the acquisition step from the editable
dictionary ``data/technique_executors.json``. Skill distillation and channel
genesis read these instead of guessing.

Zero cloud: needs a detached ``ollama serve`` + a pulled vision model
(qwen3-vl:8b). ~10-20 s per 30-tile sheet on the RTX 5060 Ti.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import config, jobs, storage, vlm
from .gatherer import GATHER_DIR

EXECUTORS_FILE = config.DATA_DIR / "technique_executors.json"

MEDIA_LABELS = ["real-photo", "painting", "engraving-or-print",
                "flat-illustration", "3d-render", "map", "document",
                "typeset-card", "meme-or-clipart", "live-footage",
                "talking-head", "screenshot", "other"]
TECH_LABELS = ["plain", "zoom-or-punch-in", "split-screen", "overlay-inset",
               "highlight-or-arrow", "caption-card", "transition-frame",
               "chart-or-diagram", "other"]

SHEET_PROMPT = (
    "This is a contact sheet of frames from one YouTube video. Every tile has "
    "a black label strip at its bottom reading 'SHOTID @ TIME'. Go tile by "
    "tile in reading order (left to right, top to bottom) and return STRICT "
    "JSON: {\"tiles\": [{\"label\": \"<burned label text>\", "
    "\"media\": <one of " + json.dumps(MEDIA_LABELS) + ">, "
    "\"text\": <one of [\"none\",\"word\",\"phrase\",\"block\"]>, "
    "\"text_content\": \"<largest on-screen words, max 8, else empty>\", "
    "\"technique\": <one of " + json.dumps(TECH_LABELS) + ">, "
    "\"subject\": \"<3-6 words, concrete>\"}]}. "
    "media = what the picture itself IS (a real photograph vs a painting vs a "
    "flat drawn illustration vs a text/typography card, etc). technique = the "
    "editing device visible in the frame. One entry per tile, all tiles, no "
    "commentary."
)


THUMB_PROMPT = (
    "This is a YouTube thumbnail. Return STRICT JSON: "
    '{"text": "<ALL words visible in the image, exactly as written, empty '
    'string if none>", "elements": "<the main visual elements, one line>", '
    '"emotion": "<facial expression / mood if any, else \'none\'>", '
    '"colors": "<3 dominant colors>"}. No commentary.')


def _read_thumbnail(job_dir: Path, model: Optional[str]) -> Optional[Dict]:
    """Thumbnail text + look, paired with the video title by the caller —
    the title-vs-thumbnail CONTRAST is a core packaging fingerprint (user,
    2026-07-14: what the thumb says vs what the title says, same video)."""
    thumb = job_dir / "thumbnail.jpg"
    if not thumb.exists():
        return None
    try:
        return vlm.describe_json(thumb, THUMB_PROMPT, model=model)
    except Exception:  # noqa: BLE001 — thumbnail read is best-effort
        return None


def _needs_rules() -> Dict:
    return storage.read_json(EXECUTORS_FILE, {}) or {}


def _parse_label(label: str):
    """'S006 | 0:28.8' / '12 @ 3:41.5' -> (shot, seconds); OCR-tolerant."""
    m = re.search(r"[Ss]?0*(\d+)\s*[@|]\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)",
                  label or "")
    if m:
        h = int(m.group(2) or 0)
        t = h * 3600 + int(m.group(3)) * 60 + float(m.group(4))
        return int(m.group(1)), t
    m = re.search(r"[Ss]?0*(\d+)\s*[@|]\s*(\d+(?:\.\d+)?)", label or "")
    if m:
        return int(m.group(1)), float(m.group(2))
    return None, None


def _aggregate(rows: List[Dict]) -> Dict:
    n = max(1, len(rows))
    media = Counter(r.get("media") or "other" for r in rows)
    tech = Counter(r.get("technique") or "plain" for r in rows)
    text_rows = [r for r in rows if (r.get("text") or "none") != "none"]
    words = [r.get("text_content") or "" for r in text_rows]
    return {
        "tiles": len(rows),
        "media_mix": {k: round(v / n, 3) for k, v in media.most_common()},
        "technique_mix": {k: round(v / n, 3) for k, v in tech.most_common()},
        "text_share": round(len(text_rows) / n, 3),
        "text_samples": [w for w in words if w][:20],
    }


def _gaps(agg: Dict, min_share: float = 0.04) -> List[Dict]:
    """Observed labels above min_share whose executor is not 'have'."""
    rules = _needs_rules()
    out: List[Dict] = []
    for kind, mix_key in (("media", "media_mix"), ("technique", "technique_mix")):
        table = rules.get(kind) or {}
        for label, share in (agg.get(mix_key) or {}).items():
            if share < min_share or label == "other":
                continue
            rule = table.get(label) or {}
            if (rule.get("status") or "missing") != "have":
                out.append({"kind": kind, "label": label, "share": share,
                            "status": rule.get("status", "missing"),
                            "executor": rule.get("executor"),
                            "acquire": rule.get("acquire")})
    out.sort(key=lambda r: -r["share"])
    return out


def analyze_pack(gid: str, progress: Optional[Callable] = None,
                 model: Optional[str] = None) -> Dict:
    """Technique-tag one gathered pack in place. Safe to re-run."""
    def note(msg, frac):
        if progress:
            progress(msg, frac)

    job_dir = GATHER_DIR / gid
    report_file = job_dir / "report.json"
    if not report_file.exists():
        raise ValueError(f"No report.json in pack {gid}.")
    if not vlm.available():
        raise RuntimeError("No local vision model reachable "
                           "(detached ollama serve + qwen3-vl:8b).")
    model = model or vlm.pick_model()
    sheets = sorted(job_dir.glob("sheet_*.jpg"))
    if not sheets:
        raise ValueError(f"Pack {gid} has no frame sheets.")

    rows: List[Dict] = []
    sheet_log: List[str] = []
    t0 = time.time()
    for i, sheet in enumerate(sheets):
        note(f"Reading {sheet.name} ({i + 1}/{len(sheets)}) with {model}",
             i / len(sheets))
        data = vlm.describe_json(sheet, SHEET_PROMPT, model=model)
        tiles = (data or {}).get("tiles") or []
        for t in tiles:
            shot, ts = _parse_label(t.get("label", ""))
            t["shot"] = shot
            t["t"] = ts
            t["sheet"] = sheet.name
            rows.append(t)
        sheet_log.append(f"{sheet.name}: {len(tiles)} tiles")

    agg = _aggregate(rows)
    gaps = _gaps(agg)
    note("Reading the thumbnail (title-vs-thumb contrast)", 0.97)
    report_now = storage.read_json(report_file, {}) or {}
    title = (report_now.get("title")
             or (report_now.get("meta") or {}).get("title") or "")
    thumb_read = _read_thumbnail(job_dir, model)
    thumbnail = ({**thumb_read, "title": title} if thumb_read else None)
    result = {"model": model, "analyzed": time.strftime("%Y-%m-%d %H:%M"),
              "seconds": round(time.time() - t0, 1),
              "aggregate": agg, "gaps": gaps, "thumbnail": thumbnail,
              "tiles": rows}

    report = storage.read_json(report_file, {}) or {}
    report["techniques"] = result
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    storage.write_json(job_dir / "needs.json", gaps)

    md = ["# Technique pass", "",
          f"Model {model} · {len(rows)} tiles · {result['seconds']} s", "",
          "## Media mix (what fills the screen)"]
    md += [f"- {k}: {v:.0%}" for k, v in agg["media_mix"].items()]
    md += ["", f"## Editing devices (on-screen text in {agg['text_share']:.0%} of tiles)"]
    md += [f"- {k}: {v:.0%}" for k, v in agg["technique_mix"].items()]
    if agg["text_samples"]:
        md += ["", "Text samples: " + " | ".join(agg["text_samples"][:10])]
    if thumbnail:
        md += ["", "## Thumbnail vs title (the contrast fingerprint)",
               f"- title: {thumbnail.get('title')}",
               f"- thumb text: {thumbnail.get('text') or '(none)'}",
               f"- thumb shows: {thumbnail.get('elements')}",
               f"- emotion: {thumbnail.get('emotion')} · colors: {thumbnail.get('colors')}"]
    md += ["", "## Needs (observed moves we cannot execute yet)"]
    md += [f"- [{g['status']}] {g['label']} ({g['share']:.0%}): {g['acquire'] or g['executor'] or 'no rule'}"
           for g in gaps] or ["- none: full coverage"]
    md += ["", "## Sheets"] + [f"- {s}" for s in sheet_log]
    (job_dir / "techniques.md").write_text("\n".join(md), encoding="utf-8")

    note("Technique pass done", 1.0)
    return {"gid": gid, "tiles": len(rows), "aggregate": agg, "gaps": gaps}


def submit(gid: str) -> str:
    """Queue the technique pass as a job (serializes with GPU work)."""
    def task(progress) -> Dict:
        try:
            return analyze_pack(gid, progress=progress)
        finally:
            vlm.unload()
    return jobs.submit("techniques", task, pid=gid)
