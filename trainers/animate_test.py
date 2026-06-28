"""One-scene LTX-2 animation smoke test (run in its own terminal).

Picks the first rendered still it can find under data/projects (or a path given as
argv[1]), animates it with the app's LTX engine, and writes an mp4 next to it so
you can eyeball motion/quality and tune config.LTX2 before animating a whole project.

    .venv\\Scripts\\python.exe trainers\\animate_test.py [optional_image.png] [seconds]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config                       # noqa: E402  (sets HF_HOME etc.)
from app.ltx_engine import ltx_engine        # noqa: E402

PROMPT = ("subtle ambient cartoon motion, gentle idle movement and breathing, "
          "slow drifting camera, the scene stays composed and on-model")


def find_still() -> Path:
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        return Path(sys.argv[1])
    for proj in sorted(config.PROJECTS_DIR.glob("*/images")):
        pics = sorted(proj.glob("scene_*.png"))
        pics = [p for p in pics if not p.stem.endswith("_end")]
        if pics:
            return pics[0]
    sys.exit("No rendered still found. Generate images first, or pass an image path.")


def main():
    if not config.ltx2_ready():
        sys.exit("LTX-2 weights missing. Run download_ltx23.bat first.\n"
                 f"  expected in {config.comfy_models_dir()}")
    still = find_still()
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else config.LTX2["default_seconds"]
    out = still.with_name(still.stem + "_ltxtest.mp4")
    print(f"still   : {still}")
    print(f"seconds : {seconds}  fps {config.LTX2['fps']}  "
          f"{config.LTX2['width']}x{config.LTX2['height']}")
    print("animating (first run also starts ComfyUI + loads the 22B fp8 model)...",
          flush=True)

    def prog(stage, frac):
        print(f"  [{int(frac * 100):3d}%] {stage}", flush=True)

    data = ltx_engine.animate(str(still), PROMPT, seconds=seconds, seed=42, progress=prog)
    out.write_bytes(data)
    print(f"\nDONE -> {out}  ({len(data) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
