"""Clip enhance chain — the anti-mush post-pass for animated clips.

Wan renders at a modest 832x480@16 (smooth motion, low VRAM); this module makes
it crisp: ffmpeg ``minterpolate`` lifts the frame rate to the assemble target
(motion-compensated, no extra model), then Real-ESRGAN's ``realesr-animevideov3``
(tiny ncnn-vulkan binary in tools/realesrgan/) re-sharpens the linework at 2x —
the practical stand-in for the ToonCrafter + 4x-UltraSharp studio chain, in
seconds instead of minutes. Degrades gracefully: no upscaler binary -> keep the
interpolated clip; any failure -> return the original clip untouched.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from . import config

ProgressFn = Callable[[str, float], None]


def _run(cmd, timeout=1800):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "")[-400:])


def upscale_image(src: Path, dst: Path, *, scale: int = 2) -> Optional[Path]:
    """Line-sharpening upscale for one still (used before parallax/Ken Burns
    so 720p art survives a 1080p+ frame). Returns None when unavailable."""
    if not config.enhance_ready():
        return None
    try:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        _run([config.ENHANCE["exe"], "-i", src, "-o", dst,
              "-n", config.ENHANCE["model"], "-s", scale], timeout=300)
        return Path(dst) if Path(dst).exists() else None
    except Exception as exc:  # noqa: BLE001
        print(f"[enhance] image upscale failed ({exc})")
        return None


def _src_fps(src: Path) -> float:
    """Source frame rate via ffprobe (fallback 16 — Wan's native rate)."""
    try:
        r = subprocess.run([config.FFPROBE, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=r_frame_rate",
                            "-of", "csv=p=0", str(src)],
                           capture_output=True, text=True, timeout=30)
        num, _, den = r.stdout.strip().partition("/")
        return float(num) / float(den or 1)
    except Exception:  # noqa: BLE001
        return 16.0


def enhance_clip(src: Path, dst: Path, *, fps: Optional[int] = None,
                 scale: Optional[int] = None, progress: Optional[ProgressFn] = None,
                 label: str = "") -> Path:
    """Upscale/sharpen ``src`` into ``dst``; returns the produced path.

    Frame INTERPOLATION is off by default (config.ENHANCE["interpolate"]):
    minterpolate ghosted flat art badly (2026-07-03 — birds grew doubles,
    lattices tore). Clips keep their native rate; the assembler duplicates
    frames into its 30 fps timeline, which reads as ordinary cartoon timing.
    """
    scale = int(scale or config.ENHANCE["scale"])
    src, dst = Path(src), Path(dst)
    work = Path(tempfile.mkdtemp(prefix="aaaflow_enh_", dir=str(dst.parent)))
    try:
        stage_src = src
        out_fps = _src_fps(src)
        if config.ENHANCE.get("interpolate"):
            # legacy opt-in path — known to artifact on stylized art
            out_fps = int(fps or config.ENHANCE["fps"])
            interp = work / "interp.mp4"
            if progress:
                progress(f"Enhancing {label}: interpolating to {out_fps} fps", 0.0)
            _run([config.FFMPEG, "-y", "-i", src,
                  "-vf", f"minterpolate=fps={out_fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                  "-pix_fmt", "yuv420p", "-an", interp])
            stage_src = interp

        # anime-video upscale (frame folder round-trip; the ncnn binary
        # takes image dirs, not video)
        if scale > 1 and config.enhance_ready():
            if progress:
                progress(f"Enhancing {label}: {scale}x line-sharpening upscale", 0.3)
            fin = work / "in"
            fout = work / "out"
            fin.mkdir()
            fout.mkdir()
            _run([config.FFMPEG, "-y", "-i", stage_src, str(fin / "f_%05d.png")])
            _run([config.ENHANCE["exe"], "-i", fin, "-o", fout,
                  "-n", config.ENHANCE["model"], "-s", scale, "-f", "png"])
            if progress:
                progress(f"Enhancing {label}: re-encoding", 0.85)
            _run([config.FFMPEG, "-y", "-framerate", f"{out_fps:.6f}",
                  "-i", str(fout / "f_%05d.png"),
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                  "-pix_fmt", "yuv420p", "-an", dst])
        elif stage_src != src:
            shutil.copyfile(stage_src, dst)
        else:
            shutil.copyfile(src, dst)
        return dst
    except Exception as exc:  # noqa: BLE001 — never lose the raw clip
        print(f"[enhance] failed ({exc}); keeping raw clip")
        try:
            shutil.copyfile(src, dst)
        except Exception:
            return src
        return dst
    finally:
        shutil.rmtree(work, ignore_errors=True)
