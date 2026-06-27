#!/usr/bin/env python
"""One-command Krea 2 LoRA training (musubi-tuner).

Trains on Krea-2-RAW (the recommended fine-tune base) and produces a LoRA that
runs on Krea-2-Turbo in the ComfyUI workflow / AAAFlow Images page.

    python trainers/train_krea2_lora.py --name my-style --trigger mystyle --autocaption

Steps it runs end-to-end:
  1. write dataset.toml for training/krea2/<name>/dataset
  2. (optional) auto-caption images that lack a .txt
  3. cache latents (VAE) and text-encoder outputs
  4. train the LoRA (fp8 + block-swap, fits 16 GB)
  5. copy the finished .safetensors into ComfyUI/models/loras
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\AAAFlow")
MUSUBI = ROOT / "trainers" / "musubi-tuner"
PY = MUSUBI / ".venv" / "Scripts" / "python.exe"
ACCEL = MUSUBI / ".venv" / "Scripts" / "accelerate.exe"
SRC = MUSUBI / "src" / "musubi_tuner"
RAW = ROOT / "trainers" / "weights" / "krea2_raw.safetensors"
TE = ROOT / "trainers" / "weights" / "qwen3vl_4b_bf16.safetensors"
VAE = ROOT / "ComfyUI_windows_portable" / "ComfyUI" / "models" / "vae" / "qwen_image_vae.safetensors"
COMFY_LORAS = ROOT / "ComfyUI_windows_portable" / "ComfyUI" / "models" / "loras"
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def run(cmd, cwd):
    print("\n>>", " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd))
    if r.returncode != 0:
        sys.exit(f"!! step failed (exit {r.returncode}): {Path(str(cmd[0])).name} / {Path(str(cmd[1])).name if len(cmd)>1 else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="LoRA name = folder under training/krea2/")
    ap.add_argument("--trigger", default="", help="trigger word (used for auto-captions)")
    ap.add_argument("--epochs", type=int, default=16)
    ap.add_argument("--dim", type=int, default=32, help="network_dim (alpha = dim)")
    ap.add_argument("--blocks-to-swap", type=int, default=24, help="0-26; raise if OOM, lower for speed (24 = stable on 16 GB)")
    ap.add_argument("--resolution", type=int, default=1024)
    ap.add_argument("--lr", default="1e-4")
    ap.add_argument("--autocaption", action="store_true", help="write trigger as caption for images missing a .txt")
    a = ap.parse_args()

    base = ROOT / "training" / "krea2" / a.name
    ds, out, cache = base / "dataset", base / "output", base / "cache"
    if not ds.exists():
        sys.exit(f"no dataset folder: {ds}\nMake training/krea2/{a.name}/dataset and put images there.")
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    for p, label in [(PY, "musubi venv"), (RAW, "Krea-2-RAW weights"),
                     (TE, "qwen3vl_4b_bf16 text encoder"), (VAE, "qwen_image VAE")]:
        if not Path(p).exists():
            sys.exit(f"missing {label}: {p}\n(weights may still be downloading)")

    imgs = sorted(p for p in ds.iterdir() if p.suffix.lower() in IMG_EXT)
    if not imgs:
        sys.exit(f"no images found in {ds}")
    print(f"{len(imgs)} training images in {ds}")

    if a.autocaption:
        n = 0
        for im in imgs:
            txt = im.with_suffix(".txt")
            if not txt.exists():
                txt.write_text((a.trigger or a.name).strip(), encoding="utf-8")
                n += 1
        print(f"auto-captioned {n} image(s) with trigger '{a.trigger or a.name}'")

    toml = base / "dataset.toml"
    toml.write_text(
        f"[general]\n"
        f"resolution = [{a.resolution}, {a.resolution}]\n"
        f'caption_extension = ".txt"\n'
        f"batch_size = 1\n"
        f"enable_bucket = true\n"
        f"bucket_no_upscale = false\n\n"
        f"[[datasets]]\n"
        f'image_directory = "{ds.as_posix()}"\n'
        f'cache_directory = "{cache.as_posix()}"\n'
        f"num_repeats = 1\n",
        encoding="utf-8")
    print("wrote", toml)

    # 1) cache latents
    run([PY, SRC / "krea2_cache_latents.py", "--dataset_config", toml, "--vae", VAE], MUSUBI)
    # 2) cache text-encoder outputs
    run([PY, SRC / "krea2_cache_text_encoder_outputs.py", "--dataset_config", toml,
         "--text_encoder", TE, "--batch_size", "1"], MUSUBI)
    # 3) train (low-VRAM path for 16 GB: fp8 base + block swap + grad checkpointing)
    run([ACCEL, "launch", "--num_processes", "1", "--num_cpu_threads_per_process", "1",
         "--mixed_precision", "bf16", SRC / "krea2_train_network.py",
         "--dit", RAW, "--vae", VAE, "--dataset_config", toml,
         "--sdpa", "--mixed_precision", "bf16",
         "--timestep_sampling", "shift", "--weighting_scheme", "none", "--discrete_flow_shift", "2.5",
         "--optimizer_type", "adamw8bit", "--learning_rate", a.lr, "--gradient_checkpointing",
         "--max_data_loader_n_workers", "2", "--persistent_data_loader_workers",
         "--network_module", "networks.lora_krea2", "--network_dim", str(a.dim), "--network_alpha", str(a.dim),
         "--max_train_epochs", str(a.epochs), "--save_every_n_epochs", "1", "--seed", "42",
         "--fp8_base", "--fp8_scaled", "--blocks_to_swap", str(a.blocks_to_swap),
         "--output_dir", out, "--output_name", a.name], MUSUBI)

    cands = sorted(out.glob(f"{a.name}*.safetensors"), key=lambda p: p.stat().st_mtime)
    if not cands:
        sys.exit(f"training finished but no .safetensors in {out}")
    final = cands[-1]
    COMFY_LORAS.mkdir(parents=True, exist_ok=True)
    dest = COMFY_LORAS / f"{a.name}.safetensors"
    shutil.copy2(final, dest)
    print(f"\n DONE. LoRA: {final}\n copied to ComfyUI loras: {dest}\n"
          f" Use trigger '{a.trigger or a.name}' in your prompts.")


if __name__ == "__main__":
    main()
