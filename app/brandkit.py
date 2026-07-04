"""Channel brand-preview generator — a FIXED ComfyUI node architecture you point
at any channel concept to see its niche + visual style, for brainstorming.

ONE krea2 graph, shared UNET/CLIP/VAE loaders feeding six parallel branded
branches (profile · banner · thumbnail · 3 representative scene frames). The
channel's ``style_suffix`` is the visual DNA on every branch and its ``niche``
seeds the scene frames, so the same fixed architecture previews a con-artist
noir channel or a low-poly money channel just by swapping the channel. Every
output PNG carries the graph embedded — drag one into ComfyUI (127.0.0.1:8188)
to edit the nodes and re-queue; change a branch's seed to regenerate one asset.

Assets + the graph land in ``data/channels/<cid>/brand/``. Run headless via
``POST /api/channels/{cid}/preview`` (a background job) or reuse the saved
``graphs/channel_preview.json`` directly in ComfyUI.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from . import channels, config, enhance, jobs
from .comfy_engine import comfy_engine
from .wan_engine import wan_engine

ProgressFn = Callable[[str, float], None]

# The six universal brand slots. `{niche}` is filled from the channel; the
# channel's style_suffix is appended to every one. Seeds are a fixed family so
# results are reproducible; a per-run offset gives fresh variations.
_SLOTS: List[Tuple[str, str, int, int, int]] = [
    ("profile", "a single bold iconic channel emblem or mascot logo mark, centered "
                "medallion, minimal, symmetrical, high contrast, plain dark background", 1024, 1024, 1313),
    ("banner", "a wide panoramic cinematic establishing hero image for a channel about {niche}, "
               "deep empty center with room for the channel name, atmospheric, no readable text", 1280, 720, 2020),
    ("thumbnail", "one striking hero subject for a video about {niche}, dramatic lighting, bold and "
                  "clickable, high contrast, large empty space in the upper-left for a title", 1280, 720, 7777),
    ("scene_wide", "a cinematic wide establishing shot for a story about {niche}, atmospheric depth, "
                   "no readable text", 1280, 720, 4001),
    ("scene_detail", "a dramatic extreme close-up of a single meaningful object from a story about "
                     "{niche}, shallow focus, moody", 1280, 720, 4002),
    ("scene_moment", "a moody representative mid-shot capturing the feeling of a story about {niche}, "
                     "cinematic", 1280, 720, 4003),
]


def brand_dir(cid: str) -> Path:
    return channels.channel_dir(cid) / "brand"


def _branch(base: int, subject: str, style: str, neg: str, w: int, h: int,
            seed: int, key: str, cid: str) -> Dict:
    n = lambda k: str(base + k)
    return {
        n(0): {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["2", 0], "text": f"{subject}. {style}"}},
        n(1): {"class_type": "ConditioningKrea2Rebalance",
               "inputs": {"conditioning": [n(0), 0], "multiplier": 4.0,
                          "per_layer_weights": config.KREA2_PER_LAYER}},
        # NEG is carried in the kit; at krea2 turbo cfg 1.0 ComfyUI skips the
        # uncond pass — raise cfg > 1 in the editor to make it bite.
        n(2): {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": neg}},
        n(3): {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": [n(0), 0]}},
        n(4): {"class_type": "EmptyLatentImage",
               "inputs": {"width": w, "height": h, "batch_size": 1}},
        n(5): {"class_type": "KSampler",
               "inputs": {"model": ["1", 0], "positive": [n(1), 0], "negative": [n(3), 0],
                          "latent_image": [n(4), 0], "seed": seed & 0xFFFFFFFFFFFFFF,
                          "steps": 8, "cfg": 1.0, "sampler_name": "euler",
                          "scheduler": "simple", "denoise": 1.0}},
        n(6): {"class_type": "VAEDecode", "inputs": {"samples": [n(5), 0], "vae": ["3", 0]}},
        n(7): {"class_type": "SaveImage",
               "inputs": {"images": [n(6), 0], "filename_prefix": f"{cid}/{key}"}},
    }


def build_graph(channel: Dict, seed_offset: int = 0) -> Tuple[Dict, Dict]:
    """The fixed 6-output krea2 node architecture for this channel. Returns
    (workflow, prefix→key map)."""
    cid = channel["id"]
    d = channel.get("defaults") or {}
    style = (d.get("style_suffix") or "").strip() or config.KREA2_STYLE
    neg = (d.get("negative_style") or "").strip() or "photorealistic, text, watermark, cluttered"
    niche = (channel.get("niche") or channel.get("name") or "mysterious true stories").strip()
    mdef = config.IMAGE_BASES["krea2"]

    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": mdef["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": mdef["clip"], "type": mdef.get("clip_type", "krea2"),
                         "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": mdef["vae"]}},
    }
    prefix_map = {}
    base = 100
    for (key, tmpl, w, h, seed) in _SLOTS:
        subject = tmpl.format(niche=niche)
        wf.update(_branch(base, subject, style, neg, w, h, seed + seed_offset, key, cid))
        prefix_map[f"{cid}/{key}"] = key
        base += 10
    return wf, prefix_map


def brand_video_dir(cid: str) -> Path:
    return brand_dir(cid) / "video"


def assets(cid: str) -> List[Dict]:
    """Every brand still PNG present (any generator), profile/banner/thumbnail first."""
    bd = brand_dir(cid)
    if not bd.exists():
        return []
    order = {k: i for i, k in enumerate(["profile", "banner", "thumbnail"])}
    files = [p for p in bd.glob("*.png") if p.is_file()]
    files.sort(key=lambda p: (order.get(p.stem, 99), p.stem))
    return [{"key": p.stem, "kind": "image",
             "url": f"/channels/{cid}/brand/{p.name}?t={int(p.stat().st_mtime)}"}
            for p in files]


def video_snippets(cid: str) -> List[Dict]:
    """Rendered Wan brand-motion snippets (the moving part of the identity)."""
    vd = brand_video_dir(cid)
    if not vd.exists():
        return []
    return [{"key": p.stem, "kind": "video",
             "url": f"/channels/{cid}/brand/video/{p.name}?t={int(p.stat().st_mtime)}"}
            for p in sorted(vd.glob("*.mp4"))]


def identity(cid: str) -> Dict:
    """The whole YouTube identity kit: stills + video snippets."""
    return {"stills": assets(cid), "videos": video_snippets(cid)}


# Subtle brand motion per still (the project style leads; motion only animates
# the drawing, never repaints it — same doctrine as scene animation).
_SNIPPET_MOTION = {
    "profile": "the emblem holds perfectly steady while the spotlight flickers gently and fine "
               "dust drifts through the beam, subtle ambient motion, no camera cuts",
    "banner": "the marquee lights shimmer faintly, the curtains sway a little, low fog drifts, "
              "subtle ambient motion",
    "thumbnail": "a slow gentle push toward the object, dust motes floating in the spotlight beam, "
                 "subtle ambient motion",
    "_default": "subtle ambient motion, a gentle drift of light and dust, faint atmosphere, no cuts",
}


def submit_snippets(cid: str, keys: Optional[List[str]] = None, seconds: float = 3.0,
                    quality: str = "balanced") -> str:
    """Animate chosen brand stills into short Wan 2.2 motion snippets (a logo
    sting, a moving teaser) — the video half of the identity template."""
    ch = channels.get(cid)
    if not ch:
        raise ValueError("channel not found")
    bd = brand_dir(cid)
    keys = keys or ["profile", "thumbnail"]
    stills = [(k, bd / f"{k}.png") for k in keys]
    stills = [(k, p) for k, p in stills if p.exists()]
    if not stills:
        raise ValueError("no brand stills yet — generate the brand preview first")
    style = ((ch.get("defaults") or {}).get("style_suffix") or "").strip()

    def task(progress: ProgressFn) -> Dict:
        vd = brand_video_dir(cid)
        vd.mkdir(parents=True, exist_ok=True)
        gdir = brand_dir(cid) / "graphs"          # persist the Wan i2v node graph too
        gdir.mkdir(parents=True, exist_ok=True)
        progress("Starting ComfyUI / Wan 2.2…", 0.03)
        comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.03 + 0.05 * f))
        out = []
        n = len(stills)
        for i, (k, p) in enumerate(stills):
            motion = _SNIPPET_MOTION.get(k, _SNIPPET_MOTION["_default"])
            prompt = ". ".join(x for x in (style, motion) if x)
            base = 0.1 + 0.85 * i / max(n, 1)
            progress(f"Animating “{k}” ({i + 1}/{n}) · Wan 2.2 balanced ~3-4 min", base)
            data = wan_engine.animate(str(p), prompt, seconds=seconds, quality=quality,
                                      seed=1313 + i,
                                      progress=lambda s, f, _b=base: progress(s, _b),
                                      save_graph=gdir / f"snippet_{k}.json")
            raw = vd / f"{k}_raw.mp4"
            raw.write_bytes(data)
            outp = vd / f"{k}.mp4"
            try:
                enhance.enhance_clip(raw, outp,
                                     progress=lambda s, f, _b=base: progress(s, _b), label=k)
                raw.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 — keep the raw clip if enhance fails
                raw.rename(outp)
            out.append({"key": k, "kind": "video",
                        "url": f"/channels/{cid}/brand/video/{k}.mp4?t={int(time.time())}"})
        return {"snippets": out, "count": len(out)}

    return jobs.submit("brand_snippets", task)


def submit_preview(cid: str, seed_offset: int = 0) -> str:
    ch = channels.get(cid)
    if not ch:
        raise ValueError("channel not found")

    def task(progress: ProgressFn) -> Dict:
        wf, prefix_map = build_graph(ch, seed_offset)
        bd = brand_dir(cid)
        (bd / "graphs").mkdir(parents=True, exist_ok=True)
        (bd / "graphs" / "channel_preview.json").write_text(
            json.dumps(wf, indent=2), encoding="utf-8")
        progress("Starting ComfyUI / krea2…", 0.05)
        comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.05 + 0.1 * f))
        progress("Rendering the 6-output brand graph (~4-5 min)…", 0.2)
        infos = comfy_engine.run_workflow(wf, want=("images",), timeout=900,
                                          progress=lambda s, f: progress("Rendering brand kit…", f))
        saved = []
        for info in infos:
            fn = info["filename"]
            key = next((v for p, v in prefix_map.items() if v in fn), None) or fn.split(".")[0]
            (bd / f"{key}.png").write_bytes(comfy_engine.fetch(info))
            saved.append(key)
        manifest = {"channel": cid, "generated": time.time(), "seed_offset": seed_offset,
                    "assets": saved, "graph": "brand/graphs/channel_preview.json"}
        (bd / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"assets": assets(cid), "count": len(saved)}

    return jobs.submit("brand_preview", task)
