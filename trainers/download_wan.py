"""Download Wan 2.2 5B TI2V weights into ComfyUI (resumable, skips present files)."""
import os
import shutil
import sys
from pathlib import Path

os.environ["HF_HUB_DISABLE_XET"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402
from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url  # noqa: E402

REPO = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"
TARGETS = [
    ("split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors", "diffusion_models"),
    ("split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "text_encoders"),
    ("split_files/vae/wan2.2_vae.safetensors", "vae"),
]
mroot = config.comfy_models_dir()
for rfile, sub in TARGETS:
    dest = mroot / sub / Path(rfile).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        want = get_hf_file_metadata(hf_hub_url(REPO, rfile)).size
    except Exception:
        want = None
    if dest.exists() and want and dest.stat().st_size == want:
        print(f"have {dest.name}", flush=True)
        continue
    print(f"downloading {dest.name} ...", flush=True)
    cached = hf_hub_download(REPO, rfile)
    if not dest.exists() or os.path.getsize(cached) != dest.stat().st_size:
        shutil.copy2(cached, dest)
    print(f"done {dest.name}", flush=True)
print("WAN 2.2 5B READY", flush=True)
