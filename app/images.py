"""Per-scene image generation orchestration (diffusers or ComfyUI, background jobs).

Builds each scene's prompt from scenes.build_image_prompt — image_prompt +
character-bible looks + the project's *editable* global style (clause-deduped),
with settings.image.style as an explicit override — runs the selected backend,
and saves a PNG into the project's images/ dir.
"""
from __future__ import annotations

import random
import time
from typing import Callable, Dict, List, Optional

from . import characters, config, jobs, projects, scenes, storage, style_refs
from .image_engine import DEFAULT_LORA, image_engine
from .comfy_engine import comfy_engine

ProgressFn = Callable[[str, float], None]


def _counts(project: Dict) -> Dict:
    sc = project.get("scenes", [])
    return {
        "total": len(sc),
        "audio": sum(1 for s in sc if s.get("status", {}).get("audio") == "ready"),
        "image": sum(1 for s in sc if s.get("status", {}).get("image") == "ready"),
    }


def _targets(scenes_list: List[Dict], video: Dict, scope: str, scene_id) -> List[Dict]:
    def renderable(s):
        # Needs scene content of its own — the global style alone isn't a scene.
        return bool((s.get("image_prompt") or s.get("visual")
                     or s.get("narration") or "").strip())
    if scope == "scene":
        return [s for s in scenes_list if str(s.get("id")) == str(scene_id) and renderable(s)]
    if scope == "all":
        return [s for s in scenes_list if renderable(s)]
    return [s for s in scenes_list
            if renderable(s) and s.get("status", {}).get("image") != "ready"]


def _resolve_dims(image_cfg: Dict) -> Dict:
    """Per-run dims: user overrides win, else the selected model's defaults."""
    model_key = image_cfg.get("model", config.DEFAULT_IMAGE_MODEL)
    mdef = config.IMAGE_BASES.get(model_key)
    if not mdef:
        m = storage.get_image_model(model_key) or {}
        mdef = {"steps": m.get("steps", 26), "guidance": m.get("guidance", 7.0),
                "width": m.get("width", 896), "height": m.get("height", 512),
                "type": m.get("base_type", "sd")}

    def num(k, default):  # treat None/""/0 as "use default" (dims/steps can't be 0)
        v = image_cfg.get(k)
        return default if v in (None, "", 0) else v

    g = image_cfg.get("guidance")            # guidance 0.0 is valid (FLUX schnell)
    guidance = mdef.get("guidance", 7.0) if g in (None, "") else float(g)
    seed = image_cfg.get("seed", -1)
    return {
        "width": int(num("width", mdef.get("width", 896))),
        "height": int(num("height", mdef.get("height", 512))),
        "steps": int(num("steps", mdef.get("steps", 26))),
        "guidance": float(guidance),
        "seed": int(-1 if seed is None else seed),
        "type": mdef.get("type", "sd"),
    }


def submit_images(pid: str, image_cfg: Dict, scope: str = "missing",
                  scene_id=None) -> str:
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    image_cfg = dict(image_cfg or {})
    video = project.get("video", {})
    targets = _targets(project["scenes"], video, scope, scene_id)
    if not targets:
        raise ValueError("No scenes need images for that selection.")
    dims = _resolve_dims(image_cfg)
    target_ids = [s["id"] for s in targets]

    def task(progress: ProgressFn) -> Dict:
        proj = projects.get_project(pid)
        proj["settings"]["image"] = {**proj["settings"].get("image", {}), **image_cfg}
        # Persist the chosen model into global settings so the engine reads it.
        storage.save_settings({"image": proj["settings"]["image"]})
        projects.ensure_dirs(pid)

        is_comfy = dims["type"] == "comfyui"
        mdef = config.IMAGE_BASES.get(image_cfg.get("model", "")) or {}
        uses_ip = bool(mdef.get("ip_adapter")) and image_cfg.get("use_refs", True)
        # The storyboard's (editable) global_style_suffix drives the look on
        # every backend; settings.image.style is an explicit override only.
        style = (image_cfg.get("style") or "").strip() or None
        ip_scale = image_cfg.get("ip_scale")
        comfy_lora = None
        if is_comfy:
            cl = image_cfg.get("comfy_lora") or {}
            if (cl.get("name") or "").strip():
                comfy_lora = {"name": cl["name"].strip(),
                              "strength": float(cl.get("strength", 0.8))}

        # warm the backend once (first scene shows load / start-up progress)
        if is_comfy:
            progress("Starting ComfyUI / krea2", 0.02)
            comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.02 + 0.18 * f))
        else:
            progress("Loading image model", 0.02)
            image_engine.get_pipeline(progress=lambda s, f: progress(s, 0.02 + 0.18 * f))

        n = len(target_ids)
        done = 0
        for sid in target_ids:
            sc = projects.get_scene(proj, sid)
            prompt, neg = scenes.build_image_prompt(
                sc, proj.get("video", {}), style=style,
                characters=proj.get("characters"))
            progress(f"Rendering scene {sid} ({done + 1}/{n})", 0.2 + 0.78 * done / max(n, 1))
            seed = dims["seed"]
            seed = (seed + int(sid) if seed is not None and seed >= 0
                    else random.randint(0, 2**31 - 1))
            if is_comfy:
                img = comfy_engine.generate(
                    prompt, neg, width=dims["width"], height=dims["height"],
                    steps=dims["steps"], guidance=dims["guidance"], seed=seed, mdef=mdef,
                    lora=comfy_lora)
            else:
                refs = None
                if uses_ip:
                    # Character bible first (keeps recurring characters on-model),
                    # then a couple of style refs for the channel look.
                    char_refs = characters.retrieve_for_scene(proj, sc)
                    style_r = style_refs.retrieve(sc, k=2 if char_refs else None)
                    refs = (char_refs + style_r) if char_refs else style_r
                img = image_engine.generate(
                    prompt, neg, width=dims["width"], height=dims["height"],
                    steps=dims["steps"], guidance=dims["guidance"], seed=seed,
                    ref_images=refs, ip_scale=ip_scale)
            rel = f"images/scene_{projects.scene_key(sid)}.png"
            img.save(str(projects.project_dir(pid) / rel))
            projects.set_scene_image(proj, sid, rel, seed,
                                     {"prompt": prompt, "negative": neg, **dims,
                                      "seed": seed})
            done += 1
            if done % 3 == 0:
                projects.save_project(proj)

        projects.save_project(proj)
        counts = _counts(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "images", "project": pid, "project_name": proj["name"],
            "model": image_cfg.get("model", config.DEFAULT_IMAGE_MODEL),
            "scenes": done,
            "text_preview": f"Rendered {done} image(s) for “{proj['name']}”",
        })
        return {"done": done, "counts": counts,
                "lora": image_engine.status().get("adapters", [])}

    return jobs.submit("images", task)


def submit_download_defaults() -> str:
    """Warm the currently-selected image backend (ComfyUI/krea2, or download FLUX)."""
    def task(progress: ProgressFn) -> Dict:
        img = storage.get_settings().get("image", {})
        model_key = img.get("model", config.DEFAULT_IMAGE_MODEL)
        mdef = config.IMAGE_BASES.get(model_key, {})
        if mdef.get("type") == "comfyui":
            progress("Starting ComfyUI / krea2", 0.1)
            comfy_engine.ensure_running(progress=progress)
            progress("Ready", 1.0)
            return {"ready": True, "comfy": comfy_engine.status()}
        progress("Downloading + loading model", 0.05)
        image_engine.get_pipeline(progress=progress)
        try:
            from huggingface_hub import hf_hub_download
            progress("Downloading built-in LoRA", 0.9)
            hf_hub_download(DEFAULT_LORA["repo"], DEFAULT_LORA["filename"])
        except Exception:  # noqa: BLE001
            pass
        progress("Ready", 1.0)
        return {"ready": True, "status": image_engine.status()}

    return jobs.submit("image_warmup", task)
