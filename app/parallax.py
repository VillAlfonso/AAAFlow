"""2.5D parallax clips from stills — the "alive, not flat" look without a video model.

A tiny monocular depth net (Depth-Anything-V2 small, ~100 MB, lazy-downloaded)
turns each still into a depth map; frames are then warped on the GPU
(``grid_sample``) so near pixels drift more than far ones while a virtual
camera performs a slow move (dolly / pan / tilt / arc). Rendered straight to a
cached H.264 clip via an ffmpeg pipe — a few seconds per scene, reused across
re-assembles.

Camera moves are picked per scene: an explicit ``move`` wins, else the scene's
shot/transition text hints, else a deterministic per-index rotation so a whole
video never repeats one move back-to-back.
"""
from __future__ import annotations

import math
import subprocess
import threading
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from . import config

_lock = threading.RLock()

DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"

# move name -> f(p in 0..1) -> (dx, dy, zoom); dx/dy in fractions of the frame
# (positive dx pans the camera right), zoom >= 1 keeps borders covered.
def _ease(p: float) -> float:
    return p * p * (3 - 2 * p)          # smoothstep


CAMERA_MOVES: Dict[str, Callable[[float], Tuple[float, float, float]]] = {
    "dolly_in":  lambda p: (0.0, -0.004 * _ease(p), 1.045 + 0.05 * _ease(p)),
    "dolly_out": lambda p: (0.0, 0.003 * _ease(p), 1.095 - 0.05 * _ease(p)),
    "pan_right": lambda p: (0.016 * (2 * _ease(p) - 1), 0.0, 1.065),
    "pan_left":  lambda p: (-0.016 * (2 * _ease(p) - 1), 0.0, 1.065),
    "tilt_up":   lambda p: (0.0, -0.012 * (2 * _ease(p) - 1), 1.06),
    "arc":       lambda p: (0.014 * math.sin(math.pi * p),
                            0.006 * (1 - math.cos(math.pi * p)),
                            1.05 + 0.03 * _ease(p)),
}
_MOVE_ORDER = ["dolly_in", "pan_right", "arc", "tilt_up", "pan_left", "dolly_out"]

_HINTS = [
    (("push", "punch", "zoom in", "close", "macro", "insert"), "dolly_in"),
    (("pull", "zoom out", "wide", "establish", "aerial"), "dolly_out"),
    (("whip-pan left", "pan left"), "pan_left"),
    (("whip", "pan"), "pan_right"),
    (("tilt", "rise", "tower", "tall"), "tilt_up"),
    (("orbit", "arc", "sweep"), "arc"),
]


def pick_move(idx: int, hint: str = "") -> str:
    h = (hint or "").lower()
    for keys, name in _HINTS:
        if any(k in h for k in keys):
            return name
    return _MOVE_ORDER[idx % len(_MOVE_ORDER)]


class ParallaxEngine:
    def __init__(self) -> None:
        self._pipe = None
        self._torch = None

    def release(self) -> bool:
        """Unload the cached depth pipeline (GPU housekeeping); reloads lazily."""
        with _lock:
            had = self._pipe is not None
            self._pipe = None
            try:
                if self._torch is not None and self._torch.cuda.is_available():
                    self._torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass
            return had

    def _ensure(self, progress=None):
        with _lock:
            if self._pipe is not None:
                return
            import torch
            from transformers import pipeline as hf_pipeline
            self._torch = torch
            dev = 0 if torch.cuda.is_available() else -1
            if progress:
                progress("Loading depth model (parallax)", 0.05)
            self._pipe = hf_pipeline("depth-estimation", model=DEPTH_MODEL, device=dev)

    def _depth(self, img) -> "object":
        """PIL image -> depth tensor (H, W) in 0..1, 1 = near, on the compute device."""
        torch = self._torch
        out = self._pipe(img)
        d = out["predicted_depth"]
        if d.dim() == 3:
            d = d[0]
        d = d.float()
        d = (d - d.min()) / (d.max() - d.min() + 1e-6)   # Depth-Anything: larger = nearer
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        return d.to(dev)

    # -------------------------------------------------------------------
    def render_clip(self, image_path: str, out_path: str, *, dur: float,
                    width: int, height: int, fps: int = 30, move: str = "auto",
                    idx: int = 0, hint: str = "", amplitude: float = 0.018,
                    progress=None) -> str:
        """Render a 2.5D camera-move clip for one still; returns out_path."""
        self._ensure(progress=progress)
        torch = self._torch
        import numpy as np
        from PIL import Image

        dev = "cuda" if torch.cuda.is_available() else "cpu"
        img = Image.open(image_path).convert("RGB")
        # cover-fit the still to the output size before warping
        scale = max(width / img.width, height / img.height)
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
        left, top = (img.width - width) // 2, (img.height - height) // 2
        img = img.crop((left, top, left + width, top + height))

        depth = self._depth(img)
        depth = torch.nn.functional.interpolate(
            depth[None, None], size=(height, width), mode="bilinear",
            align_corners=False)[0, 0]                      # (H, W)
        # parallax weight: -0.5 (far) .. +0.5 (near), softened
        pw = (depth - depth.median()).clamp(-0.5, 0.5)

        t_img = torch.from_numpy(np.asarray(img)).to(dev).float().div_(255.0)
        t_img = t_img.permute(2, 0, 1)[None]                # (1,3,H,W)

        ys = torch.linspace(-1, 1, height, device=dev)
        xs = torch.linspace(-1, 1, width, device=dev)
        gy, gx = torch.meshgrid(ys, xs, indexing="ij")

        mv = CAMERA_MOVES.get(move if move != "auto" else pick_move(idx, hint),
                              CAMERA_MOVES["dolly_in"])
        n_frames = max(2, int(round(dur * fps)))

        cmd = [config.FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
               "-pix_fmt", "yuv420p", str(out_path)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with torch.no_grad():
                for f in range(n_frames):
                    p = f / max(n_frames - 1, 1)
                    dx, dy, z = mv(p)
                    # 2.5D layer model: the camera offset moves everything, and
                    # near pixels (pw > 0) follow it harder than far ones; pure
                    # dollies get a gentle depth-scaled sway so depth still
                    # reads. Dividing by z zooms in, hiding warped borders.
                    drift = amplitude * math.sin(math.pi * p)
                    offx = (dx * (1.0 + 1.8 * pw) + drift * pw) * 2
                    offy = (dy * (1.0 + 1.2 * pw)) * 2
                    grid = torch.stack((gx / z - offx, gy / z - offy), dim=-1)[None]
                    frame = torch.nn.functional.grid_sample(
                        t_img, grid, mode="bilinear", padding_mode="border",
                        align_corners=True)[0]
                    arr = (frame.clamp(0, 1) * 255).byte().permute(1, 2, 0).cpu().numpy()
                    proc.stdin.write(arr.tobytes())
            proc.stdin.close()
            if proc.wait(timeout=120) != 0:
                raise RuntimeError("ffmpeg failed while encoding parallax clip")
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            raise
        return str(out_path)

    # -------------------------------------------------------------------
    def ensure_scene_clip(self, pdir: Path, scene: Dict, *, dur: float, width: int,
                          height: int, fps: int = 30, idx: int = 0,
                          amplitude: float = 0.018, progress=None) -> Optional[str]:
        """Cached per-scene parallax clip; (re)rendered when missing or stale."""
        if not scene.get("image_file"):
            return None
        img = pdir / scene["image_file"]
        if not img.exists():
            return None
        key = f"{width}x{height}_{int(round(min(dur, 14.0) * 10))}"
        out = pdir / "video" / f"scene_{int(scene['id']):04d}_plx_{key}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if out.exists() and out.stat().st_mtime >= img.stat().st_mtime:
                return str(out)
        except OSError:
            pass
        # quality-over-everything: warp from a line-sharpened 2x still when the
        # upscaler is installed, so 720p art stays crisp inside a 1080p+ frame
        src = img
        try:
            from . import enhance
            up = img.parent / f"{img.stem}_up2x.png"
            if not (up.exists() and up.stat().st_mtime >= img.stat().st_mtime):
                up = enhance.upscale_image(img, up) or img
            if Path(up).exists() and Path(up) != img:
                src = Path(up)
        except Exception:  # noqa: BLE001
            src = img
        hint = f"{scene.get('shot') or ''} {scene.get('transition') or ''}"
        self.render_clip(str(src), str(out), dur=min(dur, 14.0), width=width,
                         height=height, fps=fps, idx=idx, hint=hint,
                         amplitude=amplitude, progress=progress)
        return str(out)


parallax_engine = ParallaxEngine()
