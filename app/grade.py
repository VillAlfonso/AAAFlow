"""Cinematic grade — the 'Lumetri' pass a pro editor adds LAST.

One ffmpeg ``filter_complex`` over the finished mp4: a film colour grade
(contrast / gamma / three-way colour balance) + halation **bloom**
(split → gaussian blur → screen-blend the highlights back over the image) +
lens **vignette** + fine film **grain**. This is the "through ffmpeg" pro-look
layer the user asked for — it turns a flat render into a graded, glowing,
textured one and, because it is a post-process, it can be applied to ANY
existing render on demand WITHOUT re-assembling the timeline.

The looks live in the effects dictionary (``grammar['grades']``) so teaching
the system a new film look is a one-JSON edit, same as every other reflex.
Mood → look via ``grammar.grade_for``; Menagerie's ``ember`` warms gold
highlights over crushed cool shadows to match its ember-glow art direction.

Public API
----------
build_filter_complex(look)   -> ffmpeg -filter_complex string ([0:v]…[v])
apply(src, dst, look, audio) -> run ffmpeg (NVENC cq19, x264 crf17 fallback)
resolve_look(project, channel, name=None) -> (name, look_dict)
grade_render(pid, look=None) -> grade the project's newest render in place
"""
from __future__ import annotations

import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import config

# Fallback looks — the authoritative copy is seeded into grammar['grades'].
LOOKS: Dict[str, Dict] = {
    "ember": {
        "why": "Menagerie: gold ember highlights over crushed cool shadows, "
               "soft halation bloom, heavy vignette, fine grain",
        "contrast": 1.11, "saturation": 1.04, "gamma": 0.93, "brightness": -0.010,
        "shadows": [-0.05, -0.02, 0.06], "mids": [0.02, 0.00, -0.02],
        "highlights": [0.09, 0.035, -0.07],
        "glow": 0.36, "glow_sigma": 15, "glow_lift": 0.02,
        "vignette": 0.74, "grain": 9,
    },
    "cinematic": {
        "why": "default film grade — teal shadows, warm highlights, mild bloom",
        "contrast": 1.09, "saturation": 1.08, "gamma": 0.97, "brightness": 0.0,
        "shadows": [-0.04, 0.00, 0.05], "mids": [0.0, 0.0, 0.0],
        "highlights": [0.06, 0.03, -0.05],
        "glow": 0.26, "glow_sigma": 12, "glow_lift": 0.02,
        "vignette": 0.55, "grain": 6,
    },
    "noir": {
        "why": "cold desaturated thriller — high contrast, heavy vignette",
        "contrast": 1.18, "saturation": 0.72, "gamma": 0.95, "brightness": -0.015,
        "shadows": [-0.03, 0.0, 0.04], "mids": [0.0, 0.0, 0.01],
        "highlights": [-0.02, 0.0, 0.03],
        "glow": 0.20, "glow_sigma": 10, "glow_lift": 0.0,
        "vignette": 0.85, "grain": 8,
    },
    "warm": {
        "why": "golden-hour warmth for money / emotional beats",
        "contrast": 1.06, "saturation": 1.10, "gamma": 0.99, "brightness": 0.005,
        "shadows": [0.02, 0.0, -0.02], "mids": [0.02, 0.0, -0.02],
        "highlights": [0.08, 0.04, -0.06],
        "glow": 0.30, "glow_sigma": 13, "glow_lift": 0.03,
        "vignette": 0.45, "grain": 5,
    },
    "soft": {
        "why": "gentle low-contrast calm look, airy bloom, light grain",
        "contrast": 1.02, "saturation": 1.03, "gamma": 1.02, "brightness": 0.01,
        "shadows": [0.02, 0.02, 0.03], "mids": [0.0, 0.0, 0.0],
        "highlights": [0.03, 0.03, 0.0],
        "glow": 0.34, "glow_sigma": 18, "glow_lift": 0.03,
        "vignette": 0.35, "grain": 4,
    },
    "none": {"why": "no grade"},
}


def _f(x, d=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float(d)


def _triplet(v):
    v = v or [0.0, 0.0, 0.0]
    return [_f(v[0]), _f(v[1]), _f(v[2])]


def build_filter_complex(look: Dict) -> Optional[str]:
    """ffmpeg -filter_complex string grading [0:v] into [v]. None = no-op look."""
    if not look:
        return None
    contrast = _f(look.get("contrast"), 1.0)
    sat = _f(look.get("saturation"), 1.0)
    gamma = _f(look.get("gamma"), 1.0)
    bright = _f(look.get("brightness"), 0.0)
    sh, mi, hi = _triplet(look.get("shadows")), _triplet(look.get("mids")), _triplet(look.get("highlights"))
    glow = _f(look.get("glow"), 0.0)
    gsig = _f(look.get("glow_sigma"), 12.0)
    glift = _f(look.get("glow_lift"), 0.0)
    vig = _f(look.get("vignette"), 0.0)
    grain = _f(look.get("grain"), 0.0)

    # nothing meaningful to do?
    if (abs(contrast - 1) < 1e-3 and abs(sat - 1) < 1e-3 and abs(gamma - 1) < 1e-3
            and abs(bright) < 1e-3 and glow < 1e-3 and vig < 1e-3 and grain < 1e-3
            and not any(abs(x) > 1e-3 for x in sh + mi + hi)):
        return None

    # work in planar RGB so bloom/screen behaves like a real light bloom
    base = (f"eq=contrast={contrast:.3f}:saturation={sat:.3f}:gamma={gamma:.3f}"
            f":brightness={bright:.3f},"
            f"colorbalance=rs={sh[0]:.3f}:gs={sh[1]:.3f}:bs={sh[2]:.3f}"
            f":rm={mi[0]:.3f}:gm={mi[1]:.3f}:bm={mi[2]:.3f}"
            f":rh={hi[0]:.3f}:gh={hi[1]:.3f}:bh={hi[2]:.3f}")
    chain = f"[0:v]format=gbrp,{base}[cg];"
    last = "cg"
    if glow > 1e-3:
        # bloom/halation: blur a brightened copy, screen it back over the base
        chain += (f"[{last}]split[cgA][cgB];"
                  f"[cgB]gblur=sigma={gsig:.1f}:steps=2,eq=brightness={glift:.3f}[glw];"
                  f"[cgA][glw]blend=all_mode=screen:all_opacity={glow:.3f}[lit];")
        last = "lit"
    post = []
    if vig > 1e-3:
        # strength 0..1  ->  angle PI/3 (subtle) .. PI/6 (strong)
        ang = (math.pi / 3.0) - max(0.0, min(1.0, vig)) * (math.pi / 3.0 - math.pi / 6.0)
        post.append(f"vignette=angle={ang:.4f}")
    post.append("format=yuv420p")
    if grain > 1e-3:
        post.append(f"noise=alls={int(round(grain))}:allf=t")
    chain += f"[{last}]" + ",".join(post) + "[v]"
    return chain


def _encode_args(nvenc: bool):
    if nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]


def apply(src: Path, dst: Path, look: Dict, *, audio: bool = True) -> Dict:
    """Grade src->dst with ffmpeg. Returns {'filter','encoder'} or raises."""
    fc = build_filter_complex(look)
    if not fc:
        if src != dst:
            shutil.copy2(src, dst)
        return {"filter": None, "encoder": "copy"}
    dst.parent.mkdir(parents=True, exist_ok=True)

    def _run(nvenc: bool):
        cmd = [config.FFMPEG, "-y", "-v", "error", "-i", str(src),
               "-filter_complex", fc, "-map", "[v]"]
        if audio:
            cmd += ["-map", "0:a?", "-c:a", "copy"]
        cmd += _encode_args(nvenc) + ["-movflags", "+faststart", str(dst)]
        return subprocess.run(cmd, capture_output=True, text=True)

    r = _run(True)
    enc = "h264_nvenc"
    if r.returncode != 0:
        r = _run(False)   # NVENC unavailable / filter issue -> x264
        enc = "libx264"
        if r.returncode != 0:
            raise RuntimeError(f"grade ffmpeg failed: {(r.stderr or '')[-400:]}")
    return {"filter": fc, "encoder": enc}


def resolve_look(project: Dict, channel: Optional[Dict],
                 name: Optional[str] = None) -> Tuple[str, Dict]:
    """Pick the look: explicit name > project/preset grade > channel > mood."""
    from . import effects, grammar
    grades = (grammar.dictionary().get("grades") or {})
    looks = {**LOOKS, **(grades.get("looks") or {})}
    asm = (project.get("settings", {}) or {}).get("assemble", {}) or {}
    preset = effects.get(asm.get("preset") or "cinematic")

    chosen = (name or asm.get("grade") or preset.get("grade")
              or ((channel or {}).get("defaults", {}) or {}).get("grade"))
    if not chosen:
        # mood-driven default (dark story / music_vibe -> ember, etc.)
        try:
            narration = " ".join((s.get("narration") or "") for s in project.get("scenes", []))
            vibe = ((channel or {}).get("defaults", {}) or {}).get("music_vibe", "")
            mood, _q = grammar.mood_for(f"{narration} {vibe}")
        except Exception:
            mood = "default"
        chosen = grammar.grade_for(mood)
    chosen = (chosen or "cinematic").lower()
    return chosen, dict(looks.get(chosen) or looks.get("cinematic") or {})


def grade_render(pid: str, look: Optional[str] = None,
                 progress=None) -> Dict:
    """Grade the project's newest render in place; register a graded render."""
    from . import channels, projects, storage
    p = projects.get_project(pid)
    if not p:
        raise ValueError("project not found")
    renders = p.get("renders") or []
    if not renders:
        raise ValueError("no render to grade — assemble first")
    ch = channels.get(p.get("channel"))
    name, cfg = resolve_look(p, ch, look)
    if progress:
        progress(f"Grading with '{name}' look…", 0.1)

    pdir = projects.project_dir(pid)
    src = pdir / renders[0]["file"]
    if not src.exists():
        raise ValueError(f"render file missing: {src}")
    dst = src.with_name(src.stem.replace("_graded", "") + "_graded.mp4")
    info = apply(src, dst, cfg, audio=True)
    if progress:
        progress("Graded", 0.95)

    rel = f"video/{dst.name}"
    render = {**renders[0], "id": storage.new_id(), "created": time.time(),
              "file": rel, "graded": name, "grade_encoder": info["encoder"]}
    p.setdefault("renders", []).insert(0, render)
    projects.save_project(p)
    return {"look": name, "file": rel, "encoder": info["encoder"],
            "filter": info["filter"]}


def submit_grade(pid: str, look: Optional[str] = None) -> str:
    """Run grade_render as a background job (the produce 'grade' stage / UI)."""
    from . import jobs, projects
    if not projects.get_project(pid):
        raise ValueError("project not found")

    def task(progress):
        return grade_render(pid, look, progress=progress)

    return jobs.submit("grade", task, pid=pid)
