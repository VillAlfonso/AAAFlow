"""Animate ONE scene with Wan 2.2 14B i2v (test).

    .venv\\Scripts\\python.exe trainers\\wan_one.py <pid> <scene_id> [seconds]

Writes images/scene_XXXX_wantest.mp4.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, projects, scenes      # noqa: E402
from app.wan_engine import wan_engine          # noqa: E402

pid = sys.argv[1] if len(sys.argv) > 1 else None
sid = sys.argv[2] if len(sys.argv) > 2 else "6"
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
if not pid:
    cands = sorted(config.PROJECTS_DIR.glob("*/project.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    pid = cands[0].parent.name

proj = projects.get_project(pid)
sc = projects.get_scene(proj, sid)
mp = scenes.build_motion_prompt(sc, proj.get("video", {}))
print(f"scene {sid}  seconds {secs}\nprompt: {mp[:140]}...")
img = str(projects.project_dir(pid) / sc["image_file"])
data = wan_engine.animate(img, mp, seconds=secs, seed=42 + int(sid),
                          progress=lambda s, f: print(f"  [{int(f*100):3d}%] {s}", flush=True))
out = projects.project_dir(pid) / f"images/scene_{projects.scene_key(sid)}_wantest.mp4"
out.write_bytes(data)
print(f"DONE -> {out}  ({len(data)//1024} KB)")
