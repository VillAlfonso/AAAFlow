"""Animate EVERY scene of a project with LTX-2 — standalone + resumable.

Run this in its own terminal; it does not touch the web server's job queue. It:
  * auto-fills a motion_prompt for any scene missing one,
  * starts ComfyUI (visible) and opens its web UI so you can watch,
  * renders video/scene_XXXX.mp4 for every scene that has a still and no clip yet,
  * saves project.json after each scene, so you can stop/restart any time (resumable).

Usage:
    .venv\\Scripts\\python.exe trainers\\animate_all.py [project_id] [--force]

On a 16 GB GPU the 19B model runs ~10-13 min/clip, so a full 162-scene project is a
long, unattended job — that's expected. Ctrl-C to stop; re-run to resume.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, projects, scenes, animate          # noqa: E402
from app.comfy_engine import comfy_engine                  # noqa: E402
from app.ltx_engine import ltx_engine                      # noqa: E402

FORCE = "--force" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("-")]


def pick_pid() -> str:
    if args:
        return args[0]
    cands = sorted(config.PROJECTS_DIR.glob("*/project.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        sys.exit("No projects found.")
    return cands[0].parent.name


def main():
    if not config.ltx2_ready():
        sys.exit("LTX-2 weights missing. Open the Animate page and click "
                 "'Download LTX-2 weights', or run the in-app download first.")
    pid = pick_pid()
    proj = projects.get_project(pid)
    if not proj:
        sys.exit(f"Project {pid} not found.")
    print(f"project: {proj.get('name')} ({pid})")

    filled = animate.fill_motion_prompts(pid, overwrite=False)
    print(f"motion prompts: filled {filled['filled']}/{filled['total']}")
    proj = projects.get_project(pid)
    video = proj.get("video", {})
    cfg = config.LTX2
    pdir = projects.project_dir(pid)
    projects.ensure_dirs(pid)

    todo = []
    for s in proj["scenes"]:
        if s.get("status", {}).get("image") != "ready" or not s.get("image_file"):
            continue
        rel = f"video/scene_{projects.scene_key(s['id'])}.mp4"
        done = (pdir / rel).exists() and s.get("status", {}).get("video") == "ready"
        if done and not FORCE:
            continue
        todo.append(s["id"])

    total_imgs = sum(1 for s in proj["scenes"] if s.get("status", {}).get("image") == "ready")
    print(f"to animate: {len(todo)} of {total_imgs} stills "
          f"({total_imgs - len(todo)} already done)\n")
    if not todo:
        print("Nothing to do — every still already has a clip.")
        return

    print("starting ComfyUI (a window + browser tab will open so you can watch)...",
          flush=True)
    comfy_engine.ensure_running()
    comfy_engine.open_ui()

    t_start = time.time()
    for i, sid in enumerate(todo):
        proj = projects.get_project(pid)
        sc = projects.get_scene(proj, sid)
        seed = 42 + int(sid)
        mp = scenes.build_motion_prompt(sc, video)
        end_path = None
        if scenes.wants_end_frame(sc):
            try:
                end_rel = animate._krea2_end_frame(
                    proj, sc, video, sid, seed, cfg["width"], cfg["height"])
                end_path = str(pdir / end_rel) if end_rel else None
            except Exception as exc:  # noqa: BLE001
                print(f"  scene {sid}: end frame failed ({exc}); ambient i2v")

        dt0 = time.time()
        print(f"[{i+1}/{len(todo)}] scene {sid}: {mp[:90]}...", flush=True)
        try:
            data = ltx_engine.animate(
                str(pdir / sc["image_file"]), mp, seconds=cfg["default_seconds"],
                fps=cfg["fps"], width=cfg["width"], height=cfg["height"],
                seed=seed, end_image_path=end_path)
        except Exception as exc:  # noqa: BLE001
            print(f"     FAILED: {exc}  (continuing)", flush=True)
            continue
        rel = f"video/scene_{projects.scene_key(sid)}.mp4"
        (pdir / rel).write_bytes(data)
        projects.set_scene_video(proj, sid, rel,
                                 {"prompt": mp, "seconds": cfg["default_seconds"],
                                  "fps": cfg["fps"], "seed": seed,
                                  "end_frame": bool(end_path)},
                                 end_rel=(end_path and f"images/scene_{projects.scene_key(sid)}_end.png"))
        projects.save_project(proj)
        dt = time.time() - dt0
        eta = (time.time() - t_start) / (i + 1) * (len(todo) - i - 1)
        print(f"     ok ({dt:.0f}s, {len(data)//1024} KB)  ETA {eta/60:.0f} min\n",
              flush=True)

    print(f"DONE — animated {len(todo)} scene(s) in {(time.time()-t_start)/60:.0f} min.")
    print("Assemble the final video in the web app (it uses the clips automatically).")


if __name__ == "__main__":
    main()
