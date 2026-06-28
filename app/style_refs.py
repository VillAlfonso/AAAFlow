"""Cartoon style reference pack — the RAG store for IP-Adapter conditioning.

A flat folder of reference images (``data/style_refs/``) plus an ``index.json`` of
``{id, file, tags, source, created}``. At image-generation time the engine retrieves
the top-k references (optionally tag-filtered to a scene's characters/keywords) and
feeds them to IP-Adapter in style-transfer mode, so a standalone SDXL reproduces the
flat-cartoon look without ComfyUI. Seed it from existing krea2 renders.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import config, storage

_INDEX = config.STYLE_REFS_DIR / "index.json"
_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _load() -> List[Dict]:
    if not _INDEX.exists():
        return []
    try:
        return json.loads(_INDEX.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save(items: List[Dict]) -> None:
    config.STYLE_REFS_DIR.mkdir(parents=True, exist_ok=True)
    _INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def list_refs() -> List[Dict]:
    """All references with a web URL for the SPA."""
    out = []
    for it in _load():
        if (config.STYLE_REFS_DIR / it["file"]).exists():
            out.append({**it, "url": f"/style_refs/{it['file']}"})
    return out


def _norm_tags(tags) -> List[str]:
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace(",", " ").split()]
    return [t.lower() for t in (tags or []) if t and t.strip()]


def add_ref(src_path: str, tags=None, source: str = "upload",
            origin: Optional[str] = None) -> Dict:
    """Copy an image into the pack and index it."""
    src = Path(src_path)
    if src.suffix.lower() not in _IMG_EXT:
        raise ValueError("Reference must be a PNG/JPG/WEBP image.")
    rid = storage.new_id()
    fname = f"{rid}{src.suffix.lower()}"
    config.STYLE_REFS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, config.STYLE_REFS_DIR / fname)
    entry = {"id": rid, "file": fname, "tags": _norm_tags(tags),
             "source": source, "created": time.time()}
    if origin:
        entry["origin"] = origin
    items = _load(); items.append(entry); _save(items)
    return entry


def add_ref_bytes(data: bytes, suffix: str = ".png", tags=None,
                  source: str = "upload") -> Dict:
    rid = storage.new_id()
    suffix = suffix.lower() if suffix.lower() in _IMG_EXT else ".png"
    fname = f"{rid}{suffix}"
    config.STYLE_REFS_DIR.mkdir(parents=True, exist_ok=True)
    (config.STYLE_REFS_DIR / fname).write_bytes(data)
    entry = {"id": rid, "file": fname, "tags": _norm_tags(tags),
             "source": source, "created": time.time()}
    items = _load(); items.append(entry); _save(items)
    return entry


def delete_ref(rid: str) -> bool:
    items = _load()
    keep, gone = [], None
    for it in items:
        if it["id"] == rid:
            gone = it
        else:
            keep.append(it)
    if gone is None:
        return False
    try:
        (config.STYLE_REFS_DIR / gone["file"]).unlink()
    except OSError:
        pass
    _save(keep)
    return True


def seed_from_project(pid: str, limit: int = 12) -> int:
    """Seed the pack from a project's already-rendered scene images (krea2 look)."""
    from . import projects
    pdir = projects.project_dir(pid)
    proj = projects.get_project(pid)
    if not proj:
        raise ValueError("Project not found.")
    existing = {it.get("origin") for it in _load()}
    n = 0
    for s in proj.get("scenes", []):
        if n >= limit:
            break
        rel = s.get("image_file")
        if not rel:
            continue
        origin = f"{pid}/{rel}"
        if origin in existing:
            continue
        p = pdir / rel
        if not p.exists():
            continue
        add_ref(str(p), tags=["cartoon", "seed"], source=f"project:{pid}", origin=origin)
        n += 1
    return n


def retrieve(scene: Optional[Dict] = None, k: Optional[int] = None) -> List[str]:
    """Pick up to k reference image *paths* for a scene.

    v1 RAG: if the scene names characters/keywords that match reference tags, prefer
    those; otherwise fall back to the most recent references (the global style pack).
    """
    items = list_refs()
    if not items:
        return []
    k = int(k or config.IP_ADAPTER.get("top_k", 3))
    wanted = set()
    if scene:
        for c in (scene.get("characters") or []):
            wanted |= set(_norm_tags(c if isinstance(c, str) else c.get("name", "")))
        wanted |= set(_norm_tags(scene.get("on_screen_text", "")))
    scored = []
    for it in items:
        tags = set(it.get("tags") or [])
        score = len(tags & wanted)
        scored.append((score, it.get("created", 0), it))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    chosen = [it for _s, _c, it in scored[:k]]
    return [str(config.STYLE_REFS_DIR / it["file"]) for it in chosen]


def count() -> int:
    return len(list_refs())
