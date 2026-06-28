"""Standalone cartoon-RAG image smoke test (run in its own terminal).

Generates one image with the no-ComfyUI path (SDXL + IP-Adapter style transfer over
the reference pack) so you can eyeball whether it matches your krea2 cartoon look and
tune `config.IP_ADAPTER` / `ip_scale`. First run downloads SDXL + IP-Adapter (~9 GB).

    .venv\\Scripts\\python.exe trainers\\cartoon_test.py ["a prompt"] [ip_scale]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, storage, style_refs        # noqa: E402
from app.image_engine import image_engine          # noqa: E402

PROMPT = sys.argv[1] if len(sys.argv) > 1 else (
    "a furious businessman in a suit slamming both fists on a wooden desk, "
    "papers flying, bulging angry eyes, dramatic side lighting")
IP = float(sys.argv[2]) if len(sys.argv) > 2 else config.IP_ADAPTER["default_scale"]


def main():
    # force the standalone cartoon-rag model for this run
    storage.save_settings({"image": {"model": "cartoon-rag", "use_refs": True, "ip_scale": IP}})
    if style_refs.count() == 0:
        for proj in config.PROJECTS_DIR.glob("*"):
            if (proj / "project.json").exists():
                n = style_refs.seed_from_project(proj.name, 24)
                if n:
                    print(f"seeded {n} refs from {proj.name}")
                    break
    refs = style_refs.retrieve({}, k=config.IP_ADAPTER["top_k"])
    print(f"references: {len(refs)} | ip_scale {IP}")
    print(f"prompt: {PROMPT}")
    print("loading SDXL + IP-Adapter (first run downloads ~9 GB)...", flush=True)

    def prog(stage, frac):
        print(f"  [{int(frac * 100):3d}%] {stage}", flush=True)

    full = f"{config.CARTOON_STYLE}. {PROMPT}"
    mdef = config.IMAGE_BASES["cartoon-rag"]
    img = image_engine.generate(
        full, "photorealistic, 3d, blurry, ugly, deformed",
        width=mdef["width"], height=mdef["height"], steps=mdef["steps"],
        guidance=mdef["guidance"], seed=42, ref_images=refs, ip_scale=IP, progress=prog)
    out = ROOT / "cartoon_rag_test.png"
    img.save(out)
    st = image_engine.status()
    print(f"\nDONE -> {out}  (ip_loaded={st['ip_loaded']})")


if __name__ == "__main__":
    main()
