"""Optional Remotion overlay renderer (user request, 2026-07-10).

The assembler's built-in PIL/moviepy overlays (ref cards, date chips) remain
the DEFAULT: they are fast and dependency-free. This module drives the
Remotion project in tools/remotion/ for richer, spring-animated versions of
the same overlays, rendered as TRANSPARENT vp8 webm that moviepy composites.

Enable per render with assemble opts {"overlay_engine": "remotion"} or a
preset field of the same name. Degrades silently to the PIL path whenever
node/deps/render are missing or fail, so a broken node install can never
block a video.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

from . import config

RDIR = config.BASE_DIR / "tools" / "remotion"


def available() -> bool:
    return (RDIR / "node_modules" / "remotion").exists()


def render_overlay(comp: str, props: Dict, out: Path, *, seconds: float,
                   fps: int = 30, width: int = 1920, height: int = 1080,
                   timeout: int = 300) -> Optional[Path]:
    """Render one overlay composition to a transparent webm; None on failure."""
    if not available():
        return None
    frames = max(2, int(seconds * fps))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     dir=str(RDIR), encoding="utf-8") as fh:
        json.dump(props, fh)
        props_file = fh.name
    try:
        r = subprocess.run(
            ["npx", "remotion", "render", "src/index.ts", comp, str(out),
             f"--props={props_file}", "--codec=vp8",
             "--pixel-format=yuva420p", f"--frames=0-{frames - 1}",
             "--log=error"],
            cwd=str(RDIR), capture_output=True, text=True, timeout=timeout,
            shell=True)
        if r.returncode != 0:
            print(f"[remotion] {comp} failed: {(r.stderr or r.stdout)[-300:]}")
            return None
        return out if out.exists() else None
    except Exception as exc:  # noqa: BLE001
        print(f"[remotion] {comp} failed: {exc}")
        return None
    finally:
        try:
            Path(props_file).unlink(missing_ok=True)
        except OSError:
            pass


def status() -> Dict:
    return {"available": available(), "dir": str(RDIR),
            "compositions": ["RefCard", "DateChip"]}
