"""Disk janitor — storage report + safe cleanup actions.

Everything it deletes is either a regenerable cache (parallax clips, upscaled
stills, ComfyUI in/out copies), a superseded artifact (old final renders,
moviepy temp files), or log bloat. Model weights and project sources are never
touched. Exposed as GET /api/storage (report) + POST /api/storage/clean.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List

from . import config, projects

# Directories worth showing in the "where the disk went" table.
_OVERVIEW = [
    ("ComfyUI model weights", config.COMFY_DIR / "ComfyUI" / "models"),
    ("HF model cache (TTS/whisper/depth)", config.MODELS_DIR),
    ("ACE-Step (music engine)", config.ACE_DIR),
    ("Channels (projects + UIs)", config.CHANNELS_DIR),
    ("Standalone projects", config.PROJECTS_DIR),
    ("Deleted channels (data/trash)", config.TRASH_DIR),
    ("Music library", config.MUSIC_DIR),
    ("Python env", config.BASE_DIR / ".venv"),
    ("LoRA trainer (musubi)", config.BASE_DIR / "trainers"),
]


def _project_dirs():
    """Every project folder across all channels + the legacy flat dir."""
    for root in projects._project_roots():
        if root.exists():
            yield from (p for p in root.iterdir() if (p / "project.json").exists())


def _size(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _gb(n: int) -> float:
    return round(n / 1024**3, 2)


# --- cleanable scanners ------------------------------------------------------
# Each returns a list of (Path, bytes). clean() deletes them; logs are special-
# cased (truncate, keep the file).
def _old_renders() -> List[Path]:
    """Every final_*.mp4 except the newest one per project."""
    out: List[Path] = []
    for proj in _project_dirs():
        finals = sorted((proj / "video").glob("final_*.mp4"),
                        key=lambda f: f.stat().st_mtime, reverse=True)
        out.extend(finals[1:])
    return out


def _parallax_cache() -> List[Path]:
    out: List[Path] = []
    for proj in _project_dirs():
        out.extend((proj / "video").glob("scene_*_plx_*.mp4"))
    return out


def _upscale_cache() -> List[Path]:
    out: List[Path] = []
    for proj in _project_dirs():
        out.extend((proj / "images").glob("*_up2x.png"))
    return out


def _comfy_io() -> List[Path]:
    """ComfyUI input copies + output leftovers (results are copied into projects)."""
    out: List[Path] = []
    base = config.COMFY_DIR / "ComfyUI"
    for sub in ("input", "output", "temp"):
        d = base / sub
        if d.exists():
            out.extend(f for f in d.rglob("*") if f.is_file()
                       and not f.name.startswith("put_"))
    return out


def _pycache() -> List[Path]:
    out: List[Path] = []
    for top in (config.APP_DIR, config.BASE_DIR / "trainers", config.BASE_DIR / "scratchpad"):
        if top.exists():
            out.extend(p for p in top.rglob("__pycache__") if p.is_dir())
    return out


def _moviepy_temp() -> List[Path]:
    out = list(config.BASE_DIR.glob("*TEMP_MPY*"))
    for root in (config.PROJECTS_DIR, config.CHANNELS_DIR):
        if root.exists():
            out.extend(root.rglob("*TEMP_MPY*"))
    return out


def _hf_incomplete() -> List[Path]:
    out: List[Path] = []
    for pat in ("**/*.incomplete", "**/*.lock"):
        out.extend(config.MODELS_DIR.glob(pat))
    locks = config.MODELS_DIR / ".locks"
    if locks.exists():
        out.append(locks)
    return out


_LOG_KEEP = 512 * 1024        # keep the newest 512 KB of each log


def _fat_logs() -> List[Path]:
    return [f for f in config.DATA_DIR.glob("*.log")
            if f.exists() and f.stat().st_size > 2 * 1024 * 1024]


_ACTIONS = {
    "old_renders": ("Old final renders (newest per project kept)", _old_renders),
    "parallax_cache": ("Parallax clip cache (regenerates on assemble)", _parallax_cache),
    "upscale_cache": ("Upscaled-still cache (regenerates on assemble)", _upscale_cache),
    "comfy_io": ("ComfyUI input/output leftovers (already copied into projects)", _comfy_io),
    "moviepy_temp": ("Stray moviepy temp files", _moviepy_temp),
    "hf_incomplete": ("Interrupted model-download fragments", _hf_incomplete),
    "pycache": ("Python bytecode caches", _pycache),
    "logs": ("Fat logs (truncated, newest 512 KB kept)", _fat_logs),
}


def _entry_size(p: Path) -> int:
    try:
        return _size(p) if p.is_dir() else p.stat().st_size
    except OSError:
        return 0


def report() -> Dict:
    du = shutil.disk_usage(config.BASE_DIR)
    cleanables = []
    for aid, (label, scan) in _ACTIONS.items():
        items = scan()
        size = sum(_entry_size(p) for p in items)
        if aid == "logs":       # only the truncatable excess counts
            size = sum(max(0, p.stat().st_size - _LOG_KEEP) for p in items)
        if items:
            cleanables.append({"id": aid, "label": label, "count": len(items),
                               "bytes": size, "gb": _gb(size)})
    cleanables.sort(key=lambda c: -c["bytes"])
    dirs = [{"label": lbl, "path": str(p), "gb": _gb(_size(p))}
            for lbl, p in _OVERVIEW if p.exists()]
    dirs.sort(key=lambda d: -d["gb"])
    return {
        "free_gb": _gb(du.free), "total_gb": _gb(du.total),
        "used_pct": round(100 * (du.total - du.free) / du.total, 1),
        "dirs": dirs,
        "cleanables": cleanables,
    }


def clean(action_ids: List[str]) -> Dict:
    freed = 0
    details: Dict[str, int] = {}
    for aid in action_ids or []:
        if aid not in _ACTIONS:
            continue
        items = _ACTIONS[aid][1]()
        got = 0
        for p in items:
            try:
                if aid == "logs":
                    size = p.stat().st_size
                    tail = p.read_bytes()[-_LOG_KEEP:]
                    p.write_bytes(tail)
                    got += max(0, size - len(tail))
                elif p.is_dir():
                    got += _size(p)
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    got += p.stat().st_size
                    p.unlink(missing_ok=True)
            except OSError:
                pass
        details[aid] = got
        freed += got
    return {"freed_bytes": freed, "freed_gb": _gb(freed), "details": details}
