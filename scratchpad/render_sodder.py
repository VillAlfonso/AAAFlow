"""Offline final render for the Sodder video (project 851d875a0974).

Bypasses the server + the in-memory produce thread (which kept dying on
external restarts). Calls app.assemble._render directly, so nothing but this
process can kill it. Wires the already-scored music bed into settings.music,
turns SFX on, renders, then registers the render into project.renders +
history exactly like the normal assemble job would.

Run from C:\\AAAFlow with the venv python:
    .venv\\Scripts\\python.exe scratchpad\\render_sodder.py
Log -> scratchpad\\render_sodder.log
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

# repo root = parent of scratchpad/ — so `import app` works from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PID = "851d875a0974"
BED = "score_20260705_210618_60760b.wav"   # calm-dark-ambient ACE bed, Sodder run
LOG = Path(__file__).with_name("render_sodder.log")


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    log("=== Sodder offline render start ===")
    from app import assemble, config, projects, storage

    # 1) wire the scored bed + enable SFX (music is read from settings.music,
    #    which _render does NOT merge from opts, so it must be persisted)
    proj = projects.get_project(PID)
    if not proj:
        log("ERROR: project not found"); return 2

    bed_path = config.MUSIC_DIR / BED
    if not bed_path.exists():
        log(f"ERROR: bed missing {bed_path}"); return 3

    settings = proj.setdefault("settings", {})
    settings["music"] = {
        "file": BED, "volume": 0.16, "duck": True, "fade": 1.5,
        "prompt": "calm dark ambient, slow airy drones, sparse detuned "
                  "music-box notes, low distant cello, quiet unease, minimal",
        "source": "ace-step",
    }
    settings.setdefault("assemble", {})["sfx"] = True
    projects.save_project(proj)
    log(f"bed wired: {BED} ({bed_path.stat().st_size/1e6:.1f} MB); sfx=on")

    nscenes = len(proj.get("scenes", []))
    heroes = [s.get("id") for s in proj.get("scenes", []) if s.get("video_file")]
    log(f"scenes={nscenes}  wan_heroes={len(heroes)}  preset="
        f"{settings.get('assemble',{}).get('preset')}")

    # 2) render
    def progress(msg, frac=0.0):
        try:
            log(f"{float(frac)*100:5.1f}%  {msg}")
        except Exception:
            log(str(msg))

    t0 = time.time()
    out = assemble._render(PID, {"sfx": True}, progress)
    dt = time.time() - t0
    log(f"RENDER OK in {dt/60:.1f} min -> {out.get('rel')}  "
        f"dur={out.get('duration'):.1f}s  {out.get('width')}x{out.get('height')}  "
        f"scenes={out.get('scenes')} imgs={out.get('with_images')} "
        f"vids={out.get('with_videos')} plx={out.get('with_parallax')}")

    # 3) register the render like the normal assemble job does
    proj = projects.get_project(PID)
    render = {
        "id": storage.new_id(), "created": time.time(),
        "file": out["rel"], "duration": out["duration"],
        "width": out["width"], "height": out["height"], "fps": out["fps"],
        "scenes": out["scenes"], "with_audio": out["with_audio"],
        "with_images": out["with_images"], "with_videos": out.get("with_videos", 0),
    }
    proj.setdefault("renders", []).insert(0, render)
    projects.save_project(proj)
    storage.add_history({
        "id": storage.new_id(), "created": time.time(), "preview": False,
        "kind": "video", "project": PID, "project_name": proj["name"],
        "duration": out["duration"], "file": out["rel"],
        "url": f"/projects/{PID}/{out['rel']}",
        "text_preview": f"Assembled “{proj['name']}” "
                        f"({out['scenes']} scenes, {out['duration']:.0f}s)",
    })
    abs_path = projects.project_dir(PID) / out["rel"]
    log(f"registered render {render['id']}; abs={abs_path}")
    log("=== DONE ===")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"FATAL {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        log("=== FAILED ===")
        sys.exit(1)
