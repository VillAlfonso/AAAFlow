"""Animate scenes with AnimateDiff-SDXL (on-style 2D), resumable.

Loads the pipeline ONCE, then renders video/scene_XXXX.mp4 for each scene that has a
still, saving project.json after each so clips show up live in the web app (refresh
the Animate page). Resumable: skip scenes that already have a clip unless --force.

    .venv\\Scripts\\python.exe trainers\\animatediff_all.py [pid] [count] [--force]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, projects, scenes               # noqa: E402
from app.animatediff_engine import animatediff_engine   # noqa: E402

FORCE = "--force" in sys.argv
nums = [a for a in sys.argv[1:] if not a.startswith("-")]
pid = nums[0] if nums else None
limit = int(nums[1]) if len(nums) > 1 else 10**9
if not pid:
    cands = sorted(config.PROJECTS_DIR.glob("*/project.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    pid = cands[0].parent.name

proj = projects.get_project(pid)
pdir = projects.project_dir(pid)
projects.ensure_dirs(pid)
NEG = "realistic, 3d, photo, blurry, deformed, ugly, extra limbs, melting, morphing"

todo = []
for s in proj["scenes"]:
    if s.get("status", {}).get("image") != "ready" or not s.get("image_file"):
        continue
    rel = f"video/scene_{projects.scene_key(s['id'])}.mp4"
    if (pdir / rel).exists() and s.get("status", {}).get("video") == "ready" and not FORCE:
        continue
    todo.append(s["id"])
    if len(todo) >= limit:
        break

print(f"project {pid}: {len(todo)} scene(s) to animate (AnimateDiff-SDXL)\n", flush=True)
if not todo:
    sys.exit("Nothing to animate (all done; use --force to redo).")

print("loading AnimateDiff pipeline (one-time)...", flush=True)
animatediff_engine.load(progress=lambda s, f: print(f"  [{int(f*100):3d}%] {s}", flush=True))

t0 = time.time()
for i, sid in enumerate(todo):
    proj = projects.get_project(pid)
    sc = projects.get_scene(proj, sid)
    subject = " ".join((sc.get("image_prompt") or sc.get("narration") or "").split()[:18])
    prompt = (f"flat 2D cartoon, Cyanide and Happiness style, bold black outlines, "
              f"flat colors, {subject}, gentle subtle motion")
    print(f"[{i+1}/{len(todo)}] scene {sid}", flush=True)
    try:
        frames = animatediff_engine.generate(
            prompt, NEG, num_frames=16, steps=20, guidance=7.0, ip_scale=0.7,
            width=768, height=432, seed=42 + int(sid))
    except Exception as exc:  # noqa: BLE001
        print(f"     FAILED: {exc}", flush=True)
        continue
    rel = f"video/scene_{projects.scene_key(sid)}.mp4"
    animatediff_engine.to_mp4(frames, str(pdir / rel), fps=12)
    projects.set_scene_video(proj, sid, rel, {"engine": "animatediff", "prompt": prompt})
    projects.save_project(proj)
    eta = (time.time() - t0) / (i + 1) * (len(todo) - i - 1)
    print(f"     ok  ETA {eta/60:.0f} min\n", flush=True)

print(f"DONE — {len(todo)} scenes in {(time.time()-t0)/60:.0f} min. Refresh the Animate page.")
