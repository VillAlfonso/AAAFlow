"""LTX-2 text-to-video — "Fern" documentary look test (low-poly mannequins).

Targets the YouTube-channel-Fern aesthetic: faceless low-poly gray mannequins,
low-fidelity Blender renders, muted desaturated palette, soft foggy light, slow
contemplative motion. The stock LTX negative bans "3d/render/cgi" (it's tuned
for FLAT 2D cartoons) — exactly wrong here — so this passes its own negative that
*keeps* the low-poly 3D render and only suppresses the flat/cartoon/photoreal look.

    .venv\\Scripts\\python.exe trainers\\ltx_fern.py ["prompt"] [seconds] [fps] [seed]

Writes ltx_fern_test.mp4 in the project root.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config                          # noqa: E402
from app.ltx_engine import ltx_engine           # noqa: E402

# Lead with the style declaration, then the subject, then the motion (LTX's own
# prompting guidance). v2: fog dialed WAY down + hard low-poly language so the
# faceted Blender geometry actually reads (v1 went soft/ghostly under thick fog).
PROMPT = (
    "Flat-shaded low-poly 3D model, minimalist Blender Eevee render, visible polygon "
    "facets and hard polygonal edges, blocky simple geometry, untextured matte clay "
    "material, crisp clean render, low fidelity. A single faceless stiff artist's "
    "mannequin — a wooden dummy with a smooth blank featureless head, no face, simple "
    "low-poly body — stands alone on a flat low-poly ground plane in a vast minimal "
    "empty landscape under a plain pale desaturated sky. Thin distant haze only near "
    "the horizon, clear air, the figure clearly visible and in focus. Muted desaturated "
    "palette of soft grey, bone-white and dull blue, soft even ambient light. Lonely, "
    "still, melancholic, contemplative documentary mood. Very slow gentle camera "
    "push-in; the mannequin stands almost perfectly still with the faintest sway."
)

# Keep the crisp low-poly 3D render; ban fog/softness AND flat-cartoon AND photoreal.
NEGATIVE = (
    "thick fog, heavy haze, mist, smoke, obscured, blurry, soft focus, out of focus, "
    "depth of field, bokeh, ghostly, translucent, smooth organic skin, 2D, flat "
    "illustration, cartoon, vector, line art, anime, sketch, comic, photorealistic, "
    "realistic human skin, detailed face, facial features, eyes, nose, mouth, hair, "
    "busy cluttered background, vibrant saturated colors, neon, text, watermark, logo, "
    "deformed, distorted, melting, warping, glitch, flickering, extra limbs"
)

PROMPT = sys.argv[1] if len(sys.argv) > 1 else PROMPT
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
FPS = int(sys.argv[3]) if len(sys.argv) > 3 else 16
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 42


def main():
    print(f"FERN T2V test  |  seconds {SECS}  fps {FPS}  {config.LTX2['width']}x{config.LTX2['height']}  seed {SEED}")
    print(f"prompt: {PROMPT[:160]}…\n")
    data = ltx_engine.text2video(
        PROMPT, seconds=SECS, fps=FPS, negative=NEGATIVE, seed=SEED,
        progress=lambda s, f: print(f"  [{int(f * 100):3d}%] {s}", flush=True))
    out = ROOT / "ltx_fern_test.mp4"
    out.write_bytes(data)
    print(f"\nDONE -> {out}  ({len(data) // 1024} KB)")


if __name__ == "__main__":
    main()
