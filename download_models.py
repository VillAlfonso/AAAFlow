"""Download AAAFlow image-model weights into ./models (resumable; safe to re-run).

  python download_models.py          # SD 1.5 DreamShaper 8  (~2 GB, the default)
  python download_models.py flux     # FLUX schnell GGUF + T5 + sketch LoRA (~16 GB)

Run it from C:\\AAAFlow using the project venv:
  .\\.venv\\Scripts\\python.exe download_models.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HF_HOME"] = os.path.join(HERE, "models")
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"   # classic downloader (hf_transfer stalls here)
os.environ["HF_HUB_DISABLE_XET"] = "1"          # Xet backend hangs here; use plain LFS CDN

from huggingface_hub import hf_hub_download, snapshot_download


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "sd").lower()
    if which.startswith("flux"):
        log("Downloading FLUX schnell: GGUF transformer (~7 GB)…")
        hf_hub_download("city96/FLUX.1-schnell-gguf", "flux1-schnell-Q4_K_S.gguf")
        log("Downloading FLUX text encoders + VAE (~9.5 GB)…")
        snapshot_download(
            "black-forest-labs/FLUX.1-schnell",
            allow_patterns=["model_index.json", "*.txt", "text_encoder/*",
                            "text_encoder_2/*", "tokenizer/*", "tokenizer_2/*",
                            "vae/*", "scheduler/*"],
        )
        log("Downloading built-in sketch LoRA…")
        hf_hub_download("Shakker-Labs/FLUX.1-dev-LoRA-Children-Simple-Sketch",
                        "FLUX-dev-lora-children-simple-sketch.safetensors")
        log("FLUX ready.")
    else:
        log("Downloading SD 1.5 (Lykon/dreamshaper-8, ~2 GB)…")
        snapshot_download(
            "Lykon/dreamshaper-8",
            allow_patterns=["*.json", "*.txt", "tokenizer/*", "scheduler/*",
                            "text_encoder/*.safetensors", "vae/*.safetensors",
                            "unet/*.safetensors", "feature_extractor/*"],
        )
        log("SD 1.5 ready.")
    log("Done — go to the browser, open Images, and click Generate.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Cancelled (re-run to resume).")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        log("FAILED:", type(e).__name__, e)
    print("\n(You can close this window. Press Enter to exit.)")
    try:
        input()
    except EOFError:
        pass
