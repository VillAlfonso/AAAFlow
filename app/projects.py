"""Projects: an imported storyboard + per-scene pipeline state, on disk.

Layout per project::

    data/projects/<pid>/
        project.json     normalized project (video meta, settings, scenes, renders)
        source.json      the original uploaded storyboard JSON
        audio/scene_0001.wav ...
        images/scene_0001.png ...
        video/final_*.mp4 ...

Asset paths stored on scenes are *relative* to the project dir, so the SPA can
fetch them at /projects/<pid>/<relpath> and a future move can't break them.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import config, storage
from .scenes import parse_storyboard


# --- paths -----------------------------------------------------------------
def project_dir(pid: str) -> Path:
    return config.PROJECTS_DIR / pid


def _project_file(pid: str) -> Path:
    return project_dir(pid) / "project.json"


def ensure_dirs(pid: str) -> Path:
    d = project_dir(pid)
    for sub in ("audio", "images", "video"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def scene_key(sid) -> str:
    """Zero-padded scene key used in asset filenames, e.g. 0001."""
    try:
        return f"{int(sid):04d}"
    except (TypeError, ValueError):
        return str(sid)


# --- defaults --------------------------------------------------------------
def default_project_settings() -> Dict:
    s = storage.get_settings()
    return {
        "voice": {
            "mode": "custom",
            "speaker": s.get("default_speaker", "Ryan"),
            "voice_id": None,
            "language": "English",
            "instruct": "",
        },
        "image": dict(s.get("image", {})),
        "sync": dict(s.get("sync", {})),
        "assemble": dict(s.get("assemble", {})),
        # QUALITY OVER EVERYTHING (user rule): Wan 2.2 max profile by default.
        "animate": {"engine": "wan", "quality": "max", "enhance": True},
        "music": None,        # background music bed {file, id, prompt, volume, fade} or None
    }


# --- CRUD ------------------------------------------------------------------
def _apply_engines(settings: Dict, engines: Optional[Dict]) -> Dict:
    """Per-project engine choices made at creation time (Projects page)."""
    e = engines or {}
    if e.get("image_model"):
        settings["image"] = {**settings.get("image", {}), "model": e["image_model"]}
    an = settings.setdefault("animate", {"engine": "wan", "quality": "max",
                                         "enhance": True})
    if e.get("animate_engine"):
        an["engine"] = e["animate_engine"]        # "wan" | "none"
    if e.get("quality"):
        an["quality"] = e["quality"]              # "max" | "fast"
    if e.get("preset"):
        settings["assemble"] = {**settings.get("assemble", {}), "preset": e["preset"]}
    return settings


def create_project(raw_json: Dict, name: Optional[str] = None,
                   engines: Optional[Dict] = None) -> Dict:
    # Auto-direction: whatever wrote this storyboard (a strong model, a weak
    # one, or a human sketch), every directing field is filled deterministically
    # before parsing — undirected videos can't happen. Author-provided fields
    # are never overwritten; the report says exactly what was filled/flagged.
    from . import autodirect
    directed, direction = autodirect.direct(raw_json)
    parsed = parse_storyboard(directed)        # raises ValueError on bad input
    pid = storage.new_id()
    d = ensure_dirs(pid)
    (d / "source.json").write_text(
        json.dumps(raw_json, ensure_ascii=False, indent=2), encoding="utf-8")

    video = parsed["video"]
    title = (name or video.get("title") or f"Project {pid[:6]}").strip()
    project = {
        "id": pid,
        "name": title,
        "created": time.time(),
        "updated": time.time(),
        "video": video,
        "settings": _apply_engines(default_project_settings(), engines),
        "scenes": parsed["scenes"],
        "characters": parsed.get("characters", []),
        "direction_report": direction,
        "timeline": None,
        "renders": [],
    }
    save_project(project)
    return project


def save_project(project: Dict) -> Dict:
    project["updated"] = time.time()
    ensure_dirs(project["id"])
    storage.write_json(_project_file(project["id"]), project)
    return project


def get_project(pid: str) -> Optional[Dict]:
    f = _project_file(pid)
    if not f.exists():
        return None
    return storage.read_json(f, None)


def list_projects() -> List[Dict]:
    out: List[Dict] = []
    if not config.PROJECTS_DIR.exists():
        return out
    dirs = [p for p in config.PROJECTS_DIR.iterdir() if (p / "project.json").exists()]
    dirs.sort(key=lambda p: (p / "project.json").stat().st_mtime, reverse=True)
    for d in dirs:
        p = storage.read_json(d / "project.json", None)
        if p:
            out.append(summarize(p))
    return out


def summarize(p: Dict) -> Dict:
    scenes = p.get("scenes", [])
    n = len(scenes)
    audio_done = sum(1 for s in scenes if s.get("status", {}).get("audio") == "ready")
    image_done = sum(1 for s in scenes if s.get("status", {}).get("image") == "ready")
    video_done = sum(1 for s in scenes if s.get("status", {}).get("video") == "ready")
    video = p.get("video", {})
    return {
        "id": p["id"], "name": p.get("name"),
        "created": p.get("created"), "updated": p.get("updated"),
        "scenes": n, "audio_done": audio_done, "image_done": image_done,
        "video_done": video_done,
        "renders": len(p.get("renders", [])),
        "title": video.get("title"),
        "target_runtime": video.get("total_runtime") or video.get("target_runtime_minutes"),
        "timeline_dur": (p.get("timeline") or {}).get("total_dur"),
    }


def delete_project(pid: str) -> bool:
    d = project_dir(pid)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def update_settings(pid: str, patch: Dict) -> Optional[Dict]:
    p = get_project(pid)
    if not p:
        return None
    p["settings"] = storage.deep_merge(p.get("settings", {}), patch or {})
    save_project(p)
    return p["settings"]


# The video-meta fields the UI may edit (global prompts drive every render).
_VIDEO_EDITABLE = ("title", "global_style_suffix", "global_negative_prompt")


def update_video_meta(pid: str, patch: Dict) -> Optional[Dict]:
    p = get_project(pid)
    if not p:
        return None
    v = p.setdefault("video", {})
    for k in _VIDEO_EDITABLE:
        if k in patch:
            v[k] = (patch[k] or "").strip() if isinstance(patch[k], (str, type(None))) else v.get(k)
    save_project(p)
    return v


# --- scene helpers ---------------------------------------------------------
def get_scene(project: Dict, sid) -> Optional[Dict]:
    for s in project.get("scenes", []):
        if str(s.get("id")) == str(sid):
            return s
    return None


_EDITABLE = ("narration", "image_prompt", "on_screen_text", "text_anim",
             "transition", "visual", "audio_cue", "shot", "act",
             "motion_prompt", "motion_type", "end_image_prompt")


def update_scene(pid: str, sid, patch: Dict) -> Optional[Dict]:
    p = get_project(pid)
    if not p:
        return None
    sc = get_scene(p, sid)
    if not sc:
        return None
    for k in _EDITABLE:
        if k in patch:
            sc[k] = patch[k]
    # Editing the narration invalidates any rendered audio (and the timeline).
    if "narration" in patch:
        sc["status"]["audio"] = "stale" if sc.get("audio_file") else "none"
        if sc.get("transcript"):
            sc["status"]["transcript"] = "stale"
    # Editing motion invalidates any rendered clip (so the card flags a re-animate).
    if ("motion_prompt" in patch or "motion_type" in patch) and sc.get("video_file"):
        sc["status"]["video"] = "stale"
    save_project(p)
    return sc


def set_scene_audio(project: Dict, sid, rel_path: Optional[str], duration: Optional[float],
                    voice_label: Optional[str] = None) -> None:
    sc = get_scene(project, sid)
    if not sc:
        return
    sc["audio_file"] = rel_path
    sc["audio_dur"] = round(duration, 3) if duration is not None else None
    sc["audio_voice"] = voice_label
    sc["status"]["audio"] = "ready" if rel_path else "none"
    # New audio invalidates any existing timestamps for this scene.
    if sc.get("transcript"):
        sc["status"]["transcript"] = "stale" if rel_path else "none"


def set_scene_image(project: Dict, sid, rel_path: Optional[str], seed=None,
                    meta: Optional[Dict] = None) -> None:
    sc = get_scene(project, sid)
    if not sc:
        return
    sc["image_file"] = rel_path
    sc["image_seed"] = seed
    sc["image_meta"] = meta
    sc["status"]["image"] = "ready" if rel_path else "none"


def set_scene_video(project: Dict, sid, rel_path: Optional[str],
                    meta: Optional[Dict] = None, end_rel: Optional[str] = None) -> None:
    sc = get_scene(project, sid)
    if not sc:
        return
    sc["video_file"] = rel_path
    if end_rel is not None:
        sc["end_image_file"] = end_rel
    sc["video_meta"] = meta
    sc["status"].setdefault("video", "none")
    sc["status"]["video"] = "ready" if rel_path else "none"


# --- timeline (audio-led) --------------------------------------------------
def recompute_timeline(project: Dict) -> Dict:
    """Rebuild the timeline.

    Two modes:
    * Narration-track (voiceover-first): one continuous master recording drives the
      timing. Each scene's image is held from its ``planned_start`` (the transcript
      time it inherited) until the next scene's start, tiling the whole recording
      with no gaps — the audio is never cut. Total runtime = the recording length.
    * Audio-led (per-scene): each scene starts when the previous ends; its on-screen
      duration is its real narration length (clamped to a minimum hold) + lead/tail.
    """
    narr = project.get("narration")
    scenes = project.get("scenes", [])
    if narr and scenes:
        starts = [float(s.get("planned_start") or 0.0) for s in scenes]
        ends = [float(s.get("planned_end") or 0.0) for s in scenes]
        total = float(narr.get("dur") or 0.0) or (max(starts + ends) if scenes else 0.0)
        rows = []
        for i, s in enumerate(scenes):
            st = starts[i]
            en = starts[i + 1] if i + 1 < len(scenes) else total
            en = max(en, st)
            rows.append({
                "id": s.get("id"),
                "start": round(st, 3),
                "end": round(en, 3),
                "dur": round(en - st, 3),
                "has_audio": s.get("status", {}).get("audio") == "ready",
                "has_image": s.get("status", {}).get("image") == "ready",
            })
        timeline = {"total_dur": round(total, 3), "scenes": rows,
                    "planned_dur": project.get("video", {}).get("total_runtime_sec"),
                    "narration": narr.get("file")}
        project["timeline"] = timeline
        return timeline

    sync = project.get("settings", {}).get("sync", {})
    min_hold = float(sync.get("min_hold_sec", 1.2))
    lead = float(sync.get("lead_in_ms", 120)) / 1000.0
    tail = float(sync.get("tail_ms", 250)) / 1000.0

    t = 0.0
    rows = []
    for s in project.get("scenes", []):
        adur = s.get("audio_dur")
        if adur:
            dur = max(min_hold, lead + float(adur) + tail)
        else:
            dur = max(min_hold, float(s.get("planned_dur") or min_hold))
        rows.append({
            "id": s.get("id"),
            "start": round(t, 3),
            "end": round(t + dur, 3),
            "dur": round(dur, 3),
            "has_audio": bool(adur),
            "has_image": s.get("status", {}).get("image") == "ready",
        })
        t += dur
    timeline = {"total_dur": round(t, 3), "scenes": rows,
                "planned_dur": project.get("video", {}).get("total_runtime_sec")}
    project["timeline"] = timeline
    return timeline
