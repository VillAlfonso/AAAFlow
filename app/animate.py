"""Per-scene animation: turn generated stills into short LTX-2 clips.

Only scenes whose storyboard declares motion are animated (``motion_prompt`` set,
or ``motion_type`` ambient/transform) — animation is expensive on a 16 GB GPU.
For ``transform`` scenes with an ``end_image_prompt`` we first render an end frame
with krea2 (same global style as the still) and use LTX first+last-frame so
the scene morphs from the still to the end frame. Output: ``video/scene_XXXX.mp4``.

The narration audio is intentionally *not* baked into the clip here — the assemble
stage muxes the Qwen3-TTS voiceover over the (silent) animation, audio-led.
"""
from __future__ import annotations

import random
import time
from typing import Callable, Dict, List, Optional

from . import config, jobs, projects, scenes, storage
from .comfy_engine import comfy_engine
from .ltx_engine import ltx_engine
from .wan_engine import wan_engine

ProgressFn = Callable[[str, float], None]


def _targets(scenes_list: List[Dict], scope: str, scene_id) -> List[Dict]:
    """Scenes eligible for animation. All require a rendered still first."""
    def has_img(s):
        return s.get("status", {}).get("image") == "ready" and s.get("image_file")
    if scope == "scene":
        return [s for s in scenes_list if str(s.get("id")) == str(scene_id) and has_img(s)]
    if scope == "all":                       # force-animate every still
        return [s for s in scenes_list if has_img(s)]
    if scope == "missing":                   # animatable, still, not yet animated
        return [s for s in scenes_list if has_img(s) and scenes.is_animatable(s)
                and s.get("status", {}).get("video") != "ready"]
    return [s for s in scenes_list if has_img(s) and scenes.is_animatable(s)]  # "motion"


def _krea2_end_frame(proj, sc, video, sid, seed, width, height) -> Optional[str]:
    """Render the transform end frame with krea2; return its project-relative path."""
    tmp = dict(sc)
    tmp["image_prompt"] = sc.get("end_image_prompt") or ""
    # Same style rule as the stills (explicit override else the storyboard's
    # global style) — start and end frames must live in the same look or LTX
    # morphs between two art styles.
    style = (proj.get("settings", {}).get("image", {}).get("style") or "").strip() or None
    prompt, neg = scenes.build_image_prompt(tmp, video, style=style,
                                            characters=proj.get("characters"))
    if not prompt.strip():
        return None
    mdef = config.IMAGE_BASES["krea2"]
    img = comfy_engine.generate(
        prompt, neg, width=width, height=height,
        steps=mdef["steps"], guidance=mdef["guidance"], seed=seed, mdef=mdef)
    rel = f"images/scene_{projects.scene_key(sid)}_end.png"
    img.save(str(projects.project_dir(proj["id"]) / rel))
    return rel


def fill_motion_prompts(pid: str, overwrite: bool = False) -> Dict:
    """Author a motion_prompt + motion_type for every scene from its storyboard
    fields (fast, text-only). By default only fills scenes that lack one."""
    proj = projects.get_project(pid)
    if not proj:
        raise ValueError("Project not found.")
    n = 0
    for s in proj.get("scenes", []):
        if not overwrite and (s.get("motion_prompt") or "").strip():
            continue
        mp, mt = scenes.auto_motion_prompt(s)
        s["motion_prompt"] = mp
        s["motion_type"] = s.get("motion_type") or mt
        n += 1
    projects.save_project(proj)
    return {"filled": n, "total": len(proj.get("scenes", []))}


def submit_ltx_download() -> str:
    """Download any missing LTX-2 weights in-app (headless, no terminal).

    Uses huggingface_hub (integrity-checked, resumable) and SKIPS files already
    present with the right size, so it no-ops when the weights are already there.
    """
    def task(progress: ProgressFn) -> Dict:
        import os
        import shutil
        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url

        targets = [
            ("Lightricks/LTX-2", "ltx-2-19b-dev-fp4.safetensors",
             "checkpoints", config.LTX2["checkpoint"]),
            ("Comfy-Org/ltx-2", "split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors",
             "text_encoders", config.LTX2["text_encoder"]),
        ]
        mroot = config.comfy_models_dir()
        n = len(targets)
        for i, (repo, rfile, sub, outname) in enumerate(targets):
            dest = mroot / sub / outname
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                want = get_hf_file_metadata(hf_hub_url(repo, rfile)).size
            except Exception:  # noqa: BLE001
                want = None
            if dest.exists() and want and dest.stat().st_size == want:
                progress(f"{outname} present ✓", (i + 1) / n)
                continue
            progress(f"Downloading {outname} ({i + 1}/{n})", i / n)
            cached = hf_hub_download(repo, rfile)
            if not dest.exists() or os.path.getsize(cached) != dest.stat().st_size:
                shutil.copy2(cached, dest)
            progress(f"{outname} ready", (i + 1) / n)
        ready = config.ltx2_ready()
        progress("Ready" if ready else "Some files still missing", 1.0)
        return {"ready": ready}

    return jobs.submit("ltx_download", task)


def submit_animate(pid: str, opts: Optional[Dict] = None, scope: str = "motion",
                   scene_id=None) -> str:
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    opts = dict(opts or {})
    engine = (opts.get("engine") or "ltx").lower()
    if engine == "wan":
        if not config.wan_ready():
            raise ValueError("Wan 2.2 weights are missing — run download_wan14.bat.")
    elif not config.ltx2_ready():
        raise ValueError(
            "LTX-2 weights are missing. Use “Download LTX-2” on the Animate page first.")
    video = project.get("video", {})
    targets = _targets(project["scenes"], scope, scene_id)
    if not targets:
        raise ValueError("No scenes are ready to animate (need a rendered image "
                         "and, for the motion scope, declared motion).")

    ecfg = config.WAN if engine == "wan" else config.LTX2
    seconds = opts.get("seconds")
    fps = int(opts.get("fps") or ecfg["fps"])
    width = int(opts.get("width") or ecfg["width"])
    height = int(opts.get("height") or ecfg["height"])
    fallback = (opts.get("motion_prompt") or "").strip()
    base_seed = opts.get("seed", 42)
    target_ids = [s["id"] for s in targets]

    # Anchor LTX to the same style the stills were rendered in: the project's
    # global style leads, a style-hold tail replaces the flat-cartoon one, and
    # the project negative + motion-quality terms replace the anti-3D set (which
    # would melt e.g. a low-poly-3D storyboard). No global style -> old defaults.
    gstyle = (video.get("global_style_suffix") or "").strip().strip(",").strip()
    gneg = (video.get("global_negative_prompt") or "").strip()
    style_lead = style_tail = ltx_negative = None
    if gstyle:
        style_lead = gstyle
        style_tail = ("The art style stays exactly the same as the first frame "
                      "throughout, consistent and on-model. No style change, no "
                      "repainting.")
        ltx_negative = ", ".join(p for p in (gneg, config.LTX2["negative_motion"]) if p)

    def task(progress: ProgressFn) -> Dict:
        proj = projects.get_project(pid)
        projects.ensure_dirs(pid)
        progress(f"Starting ComfyUI / {engine.upper()}", 0.02)
        comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.02 + 0.08 * f))
        comfy_engine.open_ui()   # surface ComfyUI so the user can watch it animate

        n = len(target_ids)
        done = 0
        pdir = projects.project_dir(pid)
        for sid in target_ids:
            sc = projects.get_scene(proj, sid)
            seed = (int(base_seed) + int(sid) if base_seed not in (None, -1)
                    else random.randint(0, 2**31 - 1))
            mp = scenes.build_motion_prompt(sc, video, fallback=fallback)
            lead = 0.1 + 0.85 * done / max(n, 1)
            progress(f"Animating scene {sid} ({done + 1}/{n})", lead)

            still = str(pdir / sc["image_file"])
            cb = lambda s, f, _l=lead: progress(s, _l)
            if engine == "wan":
                data = wan_engine.animate(still, mp, seconds=seconds, fps=fps,
                                          width=width, height=height, seed=seed, progress=cb)
                end_rel = None
            else:
                end_rel = None
                if scenes.wants_end_frame(sc):
                    progress(f"Scene {sid}: end frame (krea2)", lead)
                    try:
                        end_rel = _krea2_end_frame(proj, sc, video, sid, seed, width, height)
                    except Exception as exc:  # noqa: BLE001 - fall back to single-still i2v
                        end_rel = None
                        progress(f"Scene {sid}: end frame failed ({exc}); ambient i2v", lead)
                data = ltx_engine.animate(
                    still, mp, seconds=seconds, fps=fps, width=width, height=height,
                    seed=seed, end_image_path=(str(pdir / end_rel) if end_rel else None),
                    style_lead=style_lead, style_tail=style_tail,
                    negative=ltx_negative, progress=cb)

            rel = f"video/scene_{projects.scene_key(sid)}.mp4"
            (pdir / rel).write_bytes(data)
            projects.set_scene_video(
                proj, sid, rel,
                {"engine": engine, "prompt": mp, "seconds": seconds or ecfg["default_seconds"],
                 "fps": fps, "width": width, "height": height, "seed": seed,
                 "end_frame": bool(end_rel)},
                end_rel=end_rel)
            done += 1
            if done % 2 == 0:
                projects.save_project(proj)

        projects.save_project(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "animate", "project": pid, "project_name": proj["name"],
            "scenes": done,
            "text_preview": f"Animated {done} scene(s) of “{proj['name']}” ({engine.upper()})",
        })
        nready = sum(1 for s in proj["scenes"]
                     if s.get("status", {}).get("video") == "ready")
        return {"done": done, "video_done": nready}

    return jobs.submit("animate", task)
