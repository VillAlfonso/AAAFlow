"""AnimateDiff-SDXL test — 2D cartoon motion in our style (no melt).

    .venv\\Scripts\\python.exe trainers\\animatediff_test.py [pid] [scene_id]

First run downloads the SDXL motion adapter. Writes images/scene_XXXX_admtest.mp4.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, projects, scenes               # noqa: E402
from app.animatediff_engine import animatediff_engine   # noqa: E402

pid = sys.argv[1] if len(sys.argv) > 1 else None
sid = sys.argv[2] if len(sys.argv) > 2 else "6"
if not pid:
    cands = sorted(config.PROJECTS_DIR.glob("*/project.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    pid = cands[0].parent.name

proj = projects.get_project(pid)
sc = projects.get_scene(proj, sid)
# keep the prompt short — CLIP truncates at 77 tokens; IP-Adapter carries the style
subject = " ".join((sc.get("image_prompt") or sc.get("narration") or "").split()[:18])
prompt = (f"flat 2D cartoon, Cyanide and Happiness style, bold black outlines, flat "
          f"colors, {subject}, gentle subtle motion")
print(f"scene {sid}")
print(f"prompt: {prompt}")
frames = animatediff_engine.generate(
    prompt, "realistic, 3d, photo, blurry, deformed, ugly, extra limbs",
    num_frames=16, steps=20, guidance=7.0, ip_scale=0.7, width=768, height=432, seed=42,
    progress=lambda s, f: print(f"  [{int(f*100):3d}%] {s}", flush=True))
out = str(projects.project_dir(pid) / f"images/scene_{projects.scene_key(sid)}_admtest.mp4")
animatediff_engine.to_mp4(frames, out, fps=12)
print(f"DONE -> {out}  ({len(frames)} frames)")
