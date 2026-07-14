"""Per-scene animation: turn generated stills into short Wan 2.2 clips.

Only scenes whose storyboard declares motion (``motion_prompt`` set, or
``motion_type`` ambient/transform) are animated — animation is expensive on a
16 GB GPU. Each clip is anchored to the project's global style (the style
LEADS the prompt, a hold-the-style tail follows, and the project negative +
motion-quality terms replace generic negatives) so Wan animates the drawing
instead of repainting it. Raw 832x480@16 output then runs the enhance chain
(interpolate to 30 fps + Real-ESRGAN anime upscale) for crisp linework.
Output: ``video/scene_XXXX.mp4``.

The narration audio is intentionally *not* baked into the clip — the assemble
stage lays the narration track over the (silent) animation.

LTX-2 was removed 2026-07-03 (35 GB of weights for worse style-hold); Wan 2.2
14B fp8 + 4-step lightx2v LoRAs is the only video engine.
"""
from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import config, enhance, jobs, projects, scenes, storage
from .comfy_engine import comfy_engine
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


def submit_wan_download() -> str:
    """Download any missing Wan 2.2 weights in-app (headless, resumable).

    Skips files already present with the right size, so it no-ops when ready.
    """
    def task(progress: ProgressFn) -> Dict:
        import os
        import shutil

        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
        mroot = config.comfy_models_dir()
        n = len(config.WAN_DOWNLOADS)
        for i, (repo, rfile, sub, outname) in enumerate(config.WAN_DOWNLOADS):
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
            try:
                os.remove(cached)             # single copy on a tight disk
            except OSError:
                pass
            progress(f"{outname} ready", (i + 1) / n)
        ready = config.wan_ready()
        progress("Ready" if ready else "Some files still missing", 1.0)
        return {"ready": ready}

    return jobs.submit("wan_download", task)


def _has_glyphs(clip: Path) -> bool:
    """GLYPH GUARD (user, 2026-07-14: "never add text").

    Wan sometimes paints gibberish letters, and a style LoRA trained on
    caption-heavy reference footage has a *learned* prior toward them, so the
    negative prompt alone is not proof. Sample a frame and ask the local VLM.
    Unavailable VLM => False (never block a render on a missing optional tool).
    """
    try:
        from . import vlm
        if not vlm.available():
            return False
        import subprocess
        import tempfile
        frame = Path(tempfile.mktemp(suffix="_glyph.jpg"))
        subprocess.run([config.FFMPEG, "-y", "-ss", "1", "-i", str(clip),
                        "-frames:v", "1", str(frame)], capture_output=True)
        if not frame.exists():
            return False
        try:
            ans = vlm.describe(
                frame,
                "Does this frame contain ANY visible written text, letters, "
                "words, captions, subtitles or watermarks anywhere in the "
                "image? Ignore logos on physical objects. Answer with exactly "
                "one word: YES or NO.")
            return ans.strip().upper().startswith("YES")
        finally:
            frame.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 — QA must never break production
        return False


def submit_t2v_visuals(pid: str, opts: Optional[Dict] = None,
                       scope: str = "missing") -> str:
    """Every scene born as MOTION: Wan 2.2 t2v renders each scene's clip
    straight from its text — no krea2 still first (user, 2026-07-13: i2v on
    flat stills 'always glitches'). A poster frame is extracted as the scene
    image so thumbnails, QA and the assembler's drifting holds keep working.
    Runs as the produce IMAGES stage when settings.animate.engine == "t2v";
    the animate stage is then skipped (there is nothing left to animate)."""
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    opts = dict(opts or {})
    acfg = project.get("settings", {}).get("animate", {}) or {}
    if not config.wan_t2v_ready():
        raise ValueError("Wan 2.2 t2v weights are missing (experts + t2v "
                         "lightning LoRAs).")
    video = project.get("video", {})
    scenes_list = project.get("scenes", [])
    # Locked stills are REAL media (archival photos, receipts, screenshots) and
    # typeset cards: they are the scene, not a prompt to animate. The assembler
    # gives them a Ken Burns move. Skipping them is what keeps the media MIX
    # (the anti-formula rule) instead of a wall of generated clips.
    def animatable(s):
        return ((s.get("image_prompt") or "").strip()
                and not s.get("image_locked")
                and not s.get("no_video"))

    if scope == "all":
        targets = [s for s in scenes_list if animatable(s)]
    else:
        targets = [s for s in scenes_list if animatable(s)
                   and s.get("status", {}).get("video") != "ready"]
    if not targets:
        raise ValueError("No scenes need t2v visuals.")

    w = config.WAN
    seconds = opts.get("seconds")
    fps = int(opts.get("fps") or w["fps"])
    width = opts.get("width") or None
    height = opts.get("height") or None
    quality = (opts.get("quality") or acfg.get("quality") or w["quality"])
    do_enhance = bool(opts.get("enhance", acfg.get("enhance", True)))
    base_seed = opts.get("seed", 42)
    target_ids = [s["id"] for s in targets]

    gstyle = (video.get("global_style_suffix") or "").strip().strip(",").strip()
    gneg = (video.get("global_negative_prompt") or "").strip()
    style_tail = ("Consistent art style throughout, on-model, no style "
                  "change, no repainting. Subtle deliberate motion.")
    negative = ", ".join(p for p in (gneg, w["negative_motion"]) if p) or w["negative"]
    # the channel's own trained style LoRA (defaults.wan_loras), e.g. Fathom's
    # "3d mannequin documentary" fern LoRA on the low-noise expert
    from . import channels as _channels
    _ch = _channels.get(project.get("channel")) if project.get("channel") else None
    ch_loras = ((_ch or {}).get("defaults") or {}).get("wan_loras") or []

    def task(progress: ProgressFn) -> Dict:
        proj = projects.get_project(pid)
        projects.ensure_dirs(pid)
        progress("Starting ComfyUI / Wan 2.2 t2v", 0.02)
        comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.02 + 0.08 * f))

        n = len(target_ids)
        done = 0
        pdir = projects.project_dir(pid)
        for sid in target_ids:
            sc = projects.get_scene(proj, sid)
            seed = (int(base_seed) + int(sid) if base_seed not in (None, -1)
                    else random.randint(0, 2**31 - 1))
            mp = scenes.build_motion_prompt(sc, video, fallback="")
            subject = (sc.get("image_prompt") or "").strip().strip(".")
            full_prompt = ". ".join(p.strip().strip(".") for p in
                                    (gstyle, subject, mp, style_tail) if p.strip())
            sec = seconds
            if sec in (None, "", 0):
                sdur = float(sc.get("planned_dur") or 0) or None
                sec = min(6.0, max(2.5, sdur)) if sdur else None
            lead = 0.1 + 0.85 * done / max(n, 1)
            progress(f"Scene {sid} t2v ({done + 1}/{n}, "
                     f"{sec or w['default_seconds']:.0f}s)", lead)

            cb = lambda s, f, _l=lead: progress(s, _l)
            rel = f"video/scene_{projects.scene_key(sid)}.mp4"
            raw = pdir / f"video/scene_{projects.scene_key(sid)}_raw.mp4"
            raw.parent.mkdir(parents=True, exist_ok=True)

            # render, then GLYPH GUARD: re-roll a clip that painted text
            for attempt in range(1 + int(opts.get("glyph_retries", 2))):
                data = wan_engine.generate(full_prompt, negative=negative,
                                           seconds=sec, fps=fps, width=width,
                                           height=height, seed=seed,
                                           quality=quality, progress=cb,
                                           extra_loras=ch_loras)
                raw.write_bytes(data)
                if not _has_glyphs(raw):
                    break
                seed = random.randint(0, 2**31 - 1)
                progress(f"Scene {sid}: text detected, re-rolling "
                         f"(attempt {attempt + 2})", lead)
            if do_enhance:
                enhance.enhance_clip(raw, pdir / rel, progress=cb,
                                     label=f"scene {sid}")
                try:
                    raw.unlink()
                except OSError:
                    pass
            else:
                raw.rename(pdir / rel)

            # poster frame doubles as the scene still
            img_rel = f"images/scene_{projects.scene_key(sid)}.png"
            (pdir / "images").mkdir(parents=True, exist_ok=True)
            subprocess.run([config.FFMPEG, "-y", "-i", str(pdir / rel),
                            "-frames:v", "1", str(pdir / img_rel)],
                           capture_output=True)
            if (pdir / img_rel).exists():
                projects.set_scene_image(proj, sid, img_rel, seed)
            projects.set_scene_video(
                proj, sid, rel,
                {"engine": "wan-t2v", "quality": quality, "prompt": full_prompt,
                 "seconds": sec or w["default_seconds"], "fps": fps,
                 "seed": seed, "enhanced": do_enhance})
            done += 1
            if done % 2 == 0:
                projects.save_project(proj)

        projects.save_project(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "animate", "project": pid, "project_name": proj["name"],
            "scenes": done,
            "text_preview": f"t2v visuals for {done} scene(s) of “{proj['name']}” (Wan 2.2)",
        })
        return {"done": done, "engine": "wan-t2v"}

    return jobs.submit("animate", task, pid=pid)


def submit_animate(pid: str, opts: Optional[Dict] = None, scope: str = "motion",
                   scene_id=None) -> str:
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    opts = dict(opts or {})
    acfg = project.get("settings", {}).get("animate", {}) or {}
    if not config.wan_ready():
        raise ValueError("Wan 2.2 weights are missing — use “Download Wan 2.2” "
                         "on the Animate page first.")
    video = project.get("video", {})
    targets = _targets(project["scenes"], scope, scene_id)
    if not targets:
        raise ValueError("No scenes are ready to animate (need a rendered image "
                         "and, for the motion scope, declared motion).")

    w = config.WAN
    seconds = opts.get("seconds")
    fps = int(opts.get("fps") or w["fps"])
    width = opts.get("width") or None      # None -> the quality profile decides
    height = opts.get("height") or None
    quality = (opts.get("quality") or acfg.get("quality") or w["quality"])
    do_enhance = bool(opts.get("enhance", acfg.get("enhance", True)))
    fallback = (opts.get("motion_prompt") or "").strip()
    base_seed = opts.get("seed", 42)
    target_ids = [s["id"] for s in targets]

    # Anchor Wan to the same style the stills were rendered in: the project's
    # global style LEADS every clip prompt, a hold-the-style tail follows, and
    # the project negative + motion-quality terms replace the generic negative.
    gstyle = (video.get("global_style_suffix") or "").strip().strip(",").strip()
    gneg = (video.get("global_negative_prompt") or "").strip()
    style_lead = gstyle or ""
    style_tail = w["style_tail"]
    negative = ", ".join(p for p in (gneg, w["negative_motion"]) if p) or w["negative"]

    def task(progress: ProgressFn) -> Dict:
        proj = projects.get_project(pid)
        projects.ensure_dirs(pid)
        progress("Starting ComfyUI / Wan 2.2", 0.02)
        comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.02 + 0.08 * f))

        n = len(target_ids)
        done = 0
        pdir = projects.project_dir(pid)
        for sid in target_ids:
            sc = projects.get_scene(proj, sid)
            seed = (int(base_seed) + int(sid) if base_seed not in (None, -1)
                    else random.randint(0, 2**31 - 1))
            mp = scenes.build_motion_prompt(sc, video, fallback=fallback)
            full_prompt = ". ".join(p.strip().strip(".") for p in
                                    (style_lead, mp, style_tail) if p.strip())
            # Clip length follows the VOICE (user rule 2026-07-05): the clip
            # runs as long as the scene is on screen, clamped to Wan's sweet
            # range — past ~6 s the 14B model degrades and VRAM balloons, so
            # longer scenes still end on the assembler's drifting hold.
            sec = seconds
            if sec in (None, "", 0):
                sdur = float(sc.get("planned_dur") or 0) or None
                sec = min(6.0, max(2.5, sdur)) if sdur else None
            lead = 0.1 + 0.85 * done / max(n, 1)
            progress(f"Animating scene {sid} ({done + 1}/{n}, "
                     f"{sec or w['default_seconds']:.0f}s)", lead)

            still = str(pdir / sc["image_file"])
            cb = lambda s, f, _l=lead: progress(s, _l)
            data = wan_engine.animate(still, full_prompt, negative=negative,
                                      seconds=sec, fps=fps, width=width,
                                      height=height, seed=seed, quality=quality,
                                      progress=cb)

            rel = f"video/scene_{projects.scene_key(sid)}.mp4"
            raw = pdir / f"video/scene_{projects.scene_key(sid)}_raw.mp4"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(data)
            if do_enhance:
                enhance.enhance_clip(raw, pdir / rel, progress=cb,
                                     label=f"scene {sid}")
                try:
                    raw.unlink()
                except OSError:
                    pass
            else:
                raw.rename(pdir / rel)

            projects.set_scene_video(
                proj, sid, rel,
                {"engine": "wan", "quality": quality, "prompt": mp,
                 "seconds": sec or w["default_seconds"], "fps": fps,
                 "seed": seed, "enhanced": do_enhance})
            done += 1
            if done % 2 == 0:
                projects.save_project(proj)

        projects.save_project(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "animate", "project": pid, "project_name": proj["name"],
            "scenes": done,
            "text_preview": f"Animated {done} scene(s) of “{proj['name']}” (Wan 2.2)",
        })
        nready = sum(1 for s in proj["scenes"]
                     if s.get("status", {}).get("video") == "ready")
        return {"done": done, "video_done": nready}

    return jobs.submit("animate", task, pid=pid)
