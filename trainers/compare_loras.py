"""Compare every Crayon-Capital LoRA epoch on the same challenging prompts.

For each checkpoint (epoch) it renders the same prompts with the same seeds through
krea2 + that LoRA (via ComfyUI), saves them per-epoch, and builds one labeled grid
(rows = prompts, cols = epochs) so you can pick which checkpoint to keep.
"""
import io, json, os, shutil, subprocess, sys, time, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFont

ROOT = r"C:\AAAFlow"
COMFY_DIR = os.path.join(ROOT, "ComfyUI_windows_portable")
COMFY_PY = os.path.join(COMFY_DIR, "python_embeded", "python.exe")
COMFY_MAIN = os.path.join(COMFY_DIR, "ComfyUI", "main.py")
LORAS = os.path.join(COMFY_DIR, "ComfyUI", "models", "loras")
SRC = os.path.join(ROOT, "training", "krea2", "Crayon-Capital", "output")
OUTDIR = os.path.join(ROOT, "training", "krea2", "Crayon-Capital", "compare")
URL = "http://127.0.0.1:8188"
PER_LAYER = "1.0,1.0,1.0,1.0,1.0,1.0,1.0,2.5,5.0,1.1,4.0,1.0"
W, H = 1024, 576

MAPPING = [("ep1", "Crayon-Capital-000001.safetensors"),
           ("ep2", "Crayon-Capital-000002.safetensors"),
           ("ep3", "Crayon-Capital-000003.safetensors"),
           ("ep4", "Crayon-Capital-000004.safetensors"),
           ("ep5", "Crayon-Capital-000005.safetensors"),
           ("ep6", "Crayon-Capital.safetensors")]

PROMPTS = [
    ("furious_boss", "crayoncapital, a furious businessman in a suit slamming both fists on a wooden desk, papers flying everywhere, bulging angry eyes, gritted teeth, dramatic hard side-lighting and long shadows"),
    ("crowd_protest", "crayoncapital, a large crowd of diverse people protesting in a city street at dusk, holding blank signs, many varied dynamic poses, warm sunset glow on the buildings"),
    ("bar_chart", "crayoncapital, a hand-drawn bar chart on a cream board, a short teal bar labeled WAGES beside a giant red bar labeled PRICES shooting off the top of the frame, bold black outlines"),
    ("boulder_run", "crayoncapital, a panicked character sprinting away from a giant rolling boulder down a jungle path, speed lines, dust cloud, wide dynamic action shot"),
    ("sunset_window", "crayoncapital, a lone figure standing at a tall window at sunset, long dramatic shadows stretching across the floor, warm orange rim-light, soft gradient sky, cinematic shading"),
    ("lab_glow", "crayoncapital, a scientist character in a dark lab holding up a glowing green chemical flask, eerie under-lighting on the face, soft volumetric glow, moody shadows"),
]


def get(path, t=10):
    with urllib.request.urlopen(URL + path, timeout=t) as r:
        return json.load(r)


def post(path, payload, t=30):
    req = urllib.request.Request(URL + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.load(r)


def alive():
    try:
        get("/system_stats", 3)
        return True
    except Exception:
        return False


def ensure_comfy():
    if alive():
        print("ComfyUI already running"); return
    print("starting ComfyUI (loading nodes; first krea2 gen warms the model)...", flush=True)
    subprocess.Popen([COMFY_PY, "-s", COMFY_MAIN, "--windows-standalone-build", "--port", "8188"],
                     cwd=COMFY_DIR)
    for _ in range(150):
        if alive():
            print("ComfyUI ready"); return
        time.sleep(2)
    sys.exit("ComfyUI did not start in time")


def workflow(lora, prompt, seed):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea2_turbo_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_4b_fp8_scaled.safetensors", "type": "krea2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "L": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": 1.0}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "ConditioningKrea2Rebalance", "inputs": {"conditioning": ["4", 0], "multiplier": 4.0, "per_layer_weights": PER_LAYER}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "7": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["L", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "cc_cmp"}},
    }


def generate(lora, prompt, seed):
    r = post("/prompt", {"prompt": workflow(lora, prompt, seed), "client_id": "cmp"})
    if "error" in r:
        raise RuntimeError(json.dumps(r.get("node_errors") or r["error"])[:300])
    pid = r["prompt_id"]; t0 = time.time()
    while time.time() - t0 < 400:
        h = get(f"/history/{pid}")
        if pid in h:
            for _n, o in (h[pid].get("outputs") or {}).items():
                if o.get("images"):
                    info = o["images"][0]
                    q = urllib.parse.urlencode({"filename": info["filename"], "subfolder": info.get("subfolder", ""), "type": info.get("type", "output")})
                    return urllib.request.urlopen(URL + "/view?" + q, timeout=90).read()
            if h[pid].get("status", {}).get("status_str") == "error":
                raise RuntimeError("comfy reported error")
        time.sleep(1.5)
    raise RuntimeError("timeout")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    present = []
    for label, fn in MAPPING:
        src = os.path.join(SRC, fn)
        if os.path.exists(src):
            dst = os.path.join(LORAS, f"cc-{label}.safetensors")
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            present.append((label, f"cc-{label}.safetensors"))
        else:
            print("missing:", fn)
    print("testing checkpoints:", [l for l, _ in present], "| prompts:", len(PROMPTS), flush=True)

    ensure_comfy()

    results = {}
    for label, lora in present:
        epdir = os.path.join(OUTDIR, label); os.makedirs(epdir, exist_ok=True)
        for pi, (name, prompt) in enumerate(PROMPTS):
            seed = 1000 + pi
            print(f"  [{label}] {name} (seed {seed}) ...", flush=True)
            try:
                t = time.time()
                data = generate(lora, prompt, seed)
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img.save(os.path.join(epdir, f"{pi:02d}_{name}.png"))
                results[(pi, label)] = img
                print(f"      ok ({time.time()-t:.1f}s)", flush=True)
            except Exception as e:
                print("      FAILED:", e, flush=True)

    # labeled grid: rows = prompts, cols = epochs
    tw, th, pad, labh, lw = 300, 169, 4, 24, 130
    cols = present
    grid = Image.new("RGB", (lw + len(cols) * (tw + pad) + pad, labh + len(PROMPTS) * (th + pad) + pad), (18, 18, 18))
    dr = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arialbd.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    for ci, (label, _) in enumerate(cols):
        dr.text((lw + pad + ci * (tw + pad) + 4, 4), label, fill=(255, 235, 0), font=font)
    for ri, (name, _) in enumerate(PROMPTS):
        y = labh + ri * (th + pad)
        dr.text((6, y + th // 2 - 6), name, fill=(225, 225, 225), font=font)
        for ci, (label, _) in enumerate(cols):
            im = results.get((ri, label))
            if im:
                grid.paste(im.resize((tw, th)), (lw + pad + ci * (tw + pad), y))
    gpath = os.path.join(OUTDIR, "COMPARISON_GRID.png")
    grid.save(gpath)
    print("\nDONE.\n  Grid:", gpath, "\n  Per-epoch folders in:", OUTDIR, flush=True)


if __name__ == "__main__":
    main()
