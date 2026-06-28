"""LTX-2 text-to-video from scratch (no reference image) — quick look test.

    .venv\\Scripts\\python.exe trainers\\ltx_t2v.py ["a prompt"] [seconds]

Writes ltx_t2v_test.mp4 in the project root.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config                          # noqa: E402
from app.ltx_engine import ltx_engine           # noqa: E402

PROMPT = sys.argv[1] if len(sys.argv) > 1 else (
    "a simple 2D cartoon stick figure man standing on a plain white background, "
    "he waves hello then gives a little bouncy jump, clean and minimal")
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5


def main():
    print(f"prompt: {PROMPT}")
    print(f"seconds {SECS}  fps {config.LTX2['fps']}  {config.LTX2['width']}x{config.LTX2['height']}")
    data = ltx_engine.text2video(
        PROMPT, seconds=SECS, seed=42,
        progress=lambda s, f: print(f"  [{int(f*100):3d}%] {s}", flush=True))
    out = ROOT / "ltx_t2v_test.mp4"
    out.write_bytes(data)
    print(f"DONE -> {out}  ({len(data)//1024} KB)")


if __name__ == "__main__":
    main()
