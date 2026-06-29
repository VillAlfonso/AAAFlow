"""Scene-graph → LoRA dataset bridge (keep rich JSON as the source of truth).

A LoRA trainer wants ``image.png`` + ``image.txt``. But hand-written captions lock
you in: change your mind about what the LoRA should learn and you're relabeling
thousands of files. So instead we keep each image's structured **scene graph**
(camera, characters+emotions, subject, style, seed, …) as a ``.json`` sidecar and
*generate* the ``.txt`` caption from it via a configurable template. Change the
template, hit recaption, and every caption regenerates in seconds — no relabeling.

    project.json scene  ──scene_to_scenegraph──▶  scene_001.json   (source of truth, RAG-ready)
                                                       │
                                          caption_from_scenegraph (template)
                                                       ▼
                                                  scene_001.txt   (what the trainer reads)
                                                  scene_001.png

This is fully file-based — no MongoDB / vector server. The same ``.json`` sidecars
can later feed embedded semantic search without changing anything here.
"""
from __future__ import annotations

import re
import shutil
from typing import Dict, List, Optional

from . import config, projects, storage

# Which scene-graph fields a caption may include. Toggle these to steer the LoRA:
# e.g. for a *style* LoRA you typically OMIT the style words (the trigger absorbs
# the style); for a *character* LoRA you describe everything BUT the character.
DEFAULT_CAPTION_OPTS: Dict[str, bool] = {
    "trigger": True,        # the LoRA trigger word, first
    "style": False,         # the global style suffix (off: let the trigger learn the style)
    "camera": True,         # shot / angle
    "act": False,           # story act / role
    "characters": True,     # character names
    "emotion": True,        # per-character expression
    "action": True,         # per-character pose / gesture / action
    "subject": True,        # the image_prompt / visual description
    "on_screen_text": False,
}


def _shot_phrase(shot: str) -> str:
    s = (shot or "").strip().lower()
    if not s:
        return ""
    return s if "shot" in s or "angle" in s or "view" in s else f"{s} shot"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().strip(",").strip()


def scene_to_scenegraph(scene: Dict, video: Dict) -> Dict:
    """The canonical, rich per-image record (source of truth + RAG-ready)."""
    meta = scene.get("image_meta") or {}
    chars = []
    for c in (scene.get("characters") or []):
        if isinstance(c, str):
            chars.append({"name": c})
        elif isinstance(c, dict):
            chars.append({k: c.get(k) for k in
                          ("name", "expression", "emotion", "gesture", "action", "pose")
                          if c.get(k)})
    return {
        "scene_id": scene.get("id"),
        "act": scene.get("act") or "",
        "camera": {"shot": scene.get("shot") or ""},
        "subject": scene.get("image_prompt") or scene.get("visual") or "",
        "characters": chars,
        "style": (video.get("global_style_suffix") or "").strip(),
        "on_screen_text": scene.get("on_screen_text") or "",
        "narration": scene.get("narration") or "",
        "motion": {"type": scene.get("motion_type") or "",
                   "prompt": scene.get("motion_prompt") or ""},
        "image": scene.get("image_file") or "",
        "seed": meta.get("seed"),
        "prompt": meta.get("prompt") or "",
        "negative_prompt": (video.get("global_negative_prompt") or "").strip(),
    }


def caption_from_scenegraph(sg: Dict, trigger: str = "",
                            opts: Optional[Dict] = None) -> str:
    """Build a training caption from a scene graph, honoring the field toggles."""
    o = {**DEFAULT_CAPTION_OPTS, **(opts or {})}
    parts: List[str] = []
    if o["trigger"] and trigger:
        parts.append(trigger.strip())
    if o["style"] and sg.get("style"):
        parts.append(sg["style"])
    if o["camera"] and sg.get("camera", {}).get("shot"):
        parts.append(_shot_phrase(sg["camera"]["shot"]))
    if o["act"] and sg.get("act"):
        parts.append(sg["act"])
    if o["characters"]:
        for c in (sg.get("characters") or []):
            bits = [c.get("name", "")]
            if o["emotion"]:
                bits.append(c.get("expression") or c.get("emotion") or "")
            if o["action"]:
                bits.append(c.get("gesture") or c.get("action") or c.get("pose") or "")
            seg = _clean(" ".join(b for b in bits if b))
            if seg:
                parts.append(seg)
    if o["subject"] and sg.get("subject"):
        parts.append(sg["subject"])
    if o["on_screen_text"] and sg.get("on_screen_text"):
        parts.append(f'text "{sg["on_screen_text"]}"')
    seen, out = set(), []
    for p in (_clean(x) for x in parts):
        key = p.lower()
        if p and key not in seen:
            seen.add(key)
            out.append(p)
    return ", ".join(out)


def scene_to_caption(scene: Dict, video: Dict, trigger: str = "",
                     opts: Optional[Dict] = None) -> str:
    return caption_from_scenegraph(scene_to_scenegraph(scene, video), trigger, opts)


# --- dataset build / recaption ---------------------------------------------
def _dataset_dir(base: str, name: str):
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip()) or "dataset"
    return config.TRAINING_DIR / (base or "krea2") / safe / "dataset"


def build_dataset_from_project(pid: str, base: str, name: str, trigger: str = "",
                               opts: Optional[Dict] = None, scope: str = "rendered") -> Dict:
    """Export a project's rendered scenes as image / .txt / .json triplets.

    Writes the trainer-ready ``.txt`` AND the rich ``.json`` scene graph so captions
    stay regenerable. ``scope`` "rendered" = only scenes with an image.
    """
    proj = projects.get_project(pid)
    if not proj:
        raise ValueError("Project not found.")
    video = proj.get("video", {})
    dest = _dataset_dir(base, name)
    dest.mkdir(parents=True, exist_ok=True)
    pdir = projects.project_dir(pid)
    trigger = (trigger or "").strip()
    n = 0
    for s in proj.get("scenes", []):
        rel = s.get("image_file")
        if not rel:
            continue
        src = pdir / rel
        if not src.exists():
            continue
        stem = f"scene_{projects.scene_key(s.get('id'))}"
        shutil.copy2(src, dest / f"{stem}{src.suffix.lower()}")
        sg = scene_to_scenegraph(s, video)
        storage.write_json(dest / f"{stem}.json", sg)
        (dest / f"{stem}.txt").write_text(
            caption_from_scenegraph(sg, trigger, opts), encoding="utf-8")
        n += 1
    if not n:
        raise ValueError("No rendered scene images to export — generate images first.")
    return {"images": n, "base": base, "name": name, "dataset": str(dest)}


def recaption(base: str, name: str, trigger: str = "",
              opts: Optional[Dict] = None) -> Dict:
    """Regenerate every .txt caption from its .json scene graph + the new template.

    The whole point: change what the LoRA should learn (toggle fields / trigger)
    and rebuild thousands of captions in seconds, without touching images."""
    dest = _dataset_dir(base, name)
    if not dest.is_dir():
        raise ValueError("Dataset not found.")
    trigger = (trigger or "").strip()
    n = 0
    samples: List[str] = []
    for jf in sorted(dest.glob("*.json")):
        try:
            sg = storage.read_json(jf, None)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(sg, dict):
            continue
        cap = caption_from_scenegraph(sg, trigger, opts)
        (dest / f"{jf.stem}.txt").write_text(cap, encoding="utf-8")
        if len(samples) < 3:
            samples.append(cap)
        n += 1
    return {"recaptioned": n, "samples": samples}


def preview_captions(pid: str, trigger: str = "", opts: Optional[Dict] = None,
                     limit: int = 5) -> List[Dict]:
    """A few sample captions for a project's scenes, for the UI to preview a template."""
    proj = projects.get_project(pid)
    if not proj:
        raise ValueError("Project not found.")
    video = proj.get("video", {})
    out = []
    for s in proj.get("scenes", []):
        if not s.get("image_file"):
            continue
        out.append({"scene": s.get("id"),
                    "caption": scene_to_caption(s, video, trigger, opts)})
        if len(out) >= limit:
            break
    return out
