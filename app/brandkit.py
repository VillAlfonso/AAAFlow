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
from typing import Callable, Dict, List, Optional, Tuple

from . import channels, config, enhance, jobs
from .comfy_engine import comfy_engine
from .wan_engine import wan_engine

ProgressFn = Callable[[str, float], None]

# The universal brand-impression slots — the CORE VIBE of a channel, grouped so
# it reads like a channel bible: Identity · Characters · Thumbnail models ·
# Ambiance. `{niche}` is filled from the channel; the channel's style_suffix is
# appended to every one (so each channel's impression is EXCLUSIVE — never shared
# or similar). Seeds are a fixed family for reproducibility; a per-run offset
# gives fresh variations. (label, group) live in `_SLOT_META`.
_SLOTS: List[Tuple[str, str, int, int, int]] = [
    # — Identity —
    ("profile", "a single bold iconic channel emblem or mascot logo mark, centered "
                "medallion, minimal, symmetrical, high contrast, plain dark background", 1024, 1024, 1313),
    ("banner", "a wide panoramic cinematic establishing hero image for a channel about {niche}, "
               "deep empty center with room for the channel name, atmospheric, no readable text", 1280, 720, 2020),
    ("thumbnail", "one striking hero subject for a video about {niche}, dramatic lighting, bold and "
                  "clickable, high contrast, large empty space in the upper-left for a title", 1280, 720, 7777),
    # — Characters (how the recurring cast LOOKS — the most important vibe anchor) —
    ("host", "a full-body character reference of the channel's recurring on-screen host/narrator for a "
             "show about {niche}, a distinctive memorable protagonist with a strong silhouette and signature "
             "costume, confident signature pose, single spotlight, plain backdrop, character sheet", 1024, 1280, 5150),
    ("character", "a haunting character portrait of a recurring figure from the world of {niche}, expressive "
                  "face, in-world costume, dramatic key light, emotive, character sheet", 1024, 1280, 5151),
    # — Thumbnail models (the click templates every video reuses) —
    ("thumb_face", "a bold YouTube thumbnail template for a video about {niche}: one intense reacting face in "
                   "the dark, extreme close-up, dramatic rim light, huge clean negative space on one side for a "
                   "big title, ultra high contrast, clickable", 1280, 720, 8801),
    ("thumb_reveal", "a bold YouTube thumbnail template for a video about {niche}: a single mysterious subject "
                     "about to be revealed under a hard spotlight, deep shadow, empty upper space for a title, "
                     "high contrast, clickable", 1280, 720, 8802),
    # — Ambiance (the feel/color/light of a typical scene; no people → no phantoms) —
    ("ambiance_wide", "a cinematic wide establishing shot that sets the mood of a story about {niche}, "
                      "atmospheric depth, deserted, no people, no readable text", 1280, 720, 4001),
    ("ambiance_detail", "a dramatic extreme close-up of a single meaningful object from a story about {niche}, "
                        "shallow focus, moody, no people", 1280, 720, 4002),
    ("ambiance_moment", "a moody mid-shot capturing the emotional feeling of a story about {niche}, cinematic "
                        "light and color, no readable text", 1280, 720, 4003),
]

# key -> (human label, group). Groups order the impression view.
_SLOT_META: Dict[str, Tuple[str, str]] = {
    "profile": ("Profile picture", "Identity"),
    "banner": ("Channel banner", "Identity"),
    "thumbnail": ("Signature thumbnail", "Identity"),
    "host": ("Host / narrator", "Characters"),
    "character": ("Recurring character", "Characters"),
    "thumb_face": ("Thumbnail model · reaction", "Thumbnail models"),
    "thumb_reveal": ("Thumbnail model · reveal", "Thumbnail models"),
    "ambiance_wide": ("Ambiance · wide", "Ambiance"),
    "ambiance_detail": ("Ambiance · detail", "Ambiance"),
    "ambiance_moment": ("Ambiance · moment", "Ambiance"),
}
_GROUP_ORDER = ["Identity", "Characters", "Thumbnail models", "Ambiance", "Other"]

# --- the editable slot dictionary (data/brandkit_slots.json) ------------------
# The channel-generator ARCHITECTURE is data, not code: every slot's prompt
# template / size / seed lives in one JSON (seeded from the built-ins above),
# editable in the Brand modal or via GET/PUT /api/brandkit_slots. build_graph
# reads it, so an edit changes what EVERY future impression renders.
SLOTS_FILE = config.DATA_DIR / "brandkit_slots.json"


def _default_slots() -> List[Dict]:
    out = []
    for key, tmpl, w, h, seed in _SLOTS:
        label, group = _SLOT_META.get(key, (key, "Other"))
        out.append({"key": key, "label": label, "group": group, "prompt": tmpl,
                    "width": w, "height": h, "seed": seed})
    return out


def slots() -> List[Dict]:
    """Active slot list: user file wins per-key; new built-in slots appear.
    Seeds the file on first load so it's always there to edit."""
    from . import storage
    data = storage.read_json(SLOTS_FILE, None)
    defaults = _default_slots()
    if not isinstance(data, dict) or not isinstance(data.get("slots"), list):
        storage.write_json(SLOTS_FILE, {
            "_why": ("The fixed channel-generator architecture, slot by slot — "
                     "`{niche}` fills from the channel, its style_suffix rides "
                     "every branch. Edit prompts here (or Brand modal · "
                     "Architecture) and every future impression uses them."),
            "slots": defaults})
        return defaults
    by_key = {s.get("key"): s for s in data["slots"] if s.get("key")}
    merged = []
    for d in defaults:
        u = by_key.pop(d["key"], None)
        merged.append({**d, **{k: v for k, v in (u or {}).items() if v not in (None, "")}})
    merged += [s for s in by_key.values() if (s.get("prompt") or "").strip()]
    return merged


def save_slots(patch: List[Dict]) -> List[Dict]:
    from . import storage
    if not isinstance(patch, list) or not patch:
        raise ValueError("slots must be a non-empty list")
    for s in patch:
        if not (s.get("key") and (s.get("prompt") or "").strip()):
            raise ValueError("every slot needs a key and a prompt")
    data = storage.read_json(SLOTS_FILE, None) or {}
    data["slots"] = patch
    storage.write_json(SLOTS_FILE, data)
    return slots()


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


def build_graph(channel: Dict, seed_offset: int = 0,
                only: Optional[List[str]] = None) -> Tuple[Dict, Dict]:
    """The fixed krea2 node architecture for this channel. Returns
    (workflow, prefix→key map). ``only`` limits the branches (the channel
    roulette renders a fast 5-slot subset instead of all ten)."""
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
    for slot in slots():
        key = slot["key"]
        if only and key not in only:
            continue
        try:
            subject = str(slot["prompt"]).format(niche=niche)
        except (KeyError, IndexError, ValueError):
            subject = str(slot["prompt"]).replace("{niche}", niche)
        wf.update(_branch(base, subject, style, neg,
                          int(slot.get("width", 1280)), int(slot.get("height", 720)),
                          int(slot.get("seed", 1000)) + seed_offset, key, cid))
        prefix_map[f"{cid}/{key}"] = key
        base += 10
    return wf, prefix_map


def brand_video_dir(cid: str) -> Path:
    return brand_dir(cid) / "video"


def _slot_meta(stem: str) -> Tuple[str, str]:
    for s in slots():
        if s["key"] == stem:
            return (s.get("label") or stem, s.get("group") or "Other")
    return _SLOT_META.get(stem, (stem.replace("_", " ").title(), "Other"))


def publish_graph_to_comfy(name: str, wf) -> Optional[Path]:
    """Drop a node graph straight into ComfyUI's workflow library (sidebar →
    Workflows → AAAFlow) the moment it's generated — no PNG dragging. `wf` is
    a dict or a Path to a saved graph JSON. Never raises (publishing is a
    convenience; generation must not die on it)."""
    try:
        dest = config.COMFY_DIR / "ComfyUI" / "user" / "default" / "workflows" / "AAAFlow"
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / (name if name.endswith(".json") else f"{name}.json")
        if isinstance(wf, (str, Path)):
            out.write_text(Path(wf).read_text(encoding="utf-8"), encoding="utf-8")
        else:
            out.write_text(json.dumps(wf, indent=2), encoding="utf-8")
        return out
    except Exception:  # noqa: BLE001
        return None


def export_graphs_to_comfy(cid: str) -> Dict:
    """Copy this channel's saved node graphs into ComfyUI's workflow library
    (user/default/workflows/AAAFlow/) so they appear in the ComfyUI sidebar,
    editable. Always (re)writes channel_preview.json from the CURRENT slot
    dictionary first, so what you open is what the system would render."""
    ch = channels.get(cid)
    if not ch:
        raise ValueError("channel not found")
    gdir = brand_dir(cid) / "graphs"
    gdir.mkdir(parents=True, exist_ok=True)
    wf, _pm = build_graph(ch)
    (gdir / "channel_preview.json").write_text(json.dumps(wf, indent=2),
                                               encoding="utf-8")
    dest = config.COMFY_DIR / "ComfyUI" / "user" / "default" / "workflows" / "AAAFlow"
    dest.mkdir(parents=True, exist_ok=True)
    exported = []
    for f in sorted(gdir.glob("*.json")):
        out = dest / f"{cid}_{f.name}"
        out.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        exported.append(out.name)
    return {"exported": exported, "folder": str(dest),
            "url": config.COMFY_URL,
            "note": "ComfyUI sidebar → Workflows → AAAFlow (API-format JSON — "
                    "ComfyUI lays the nodes out on open; PNGs drag in too)"}


def assets(cid: str) -> List[Dict]:
    """Every brand still PNG present (any generator), grouped + ordered as the
    channel impression (Identity · Characters · Thumbnail models · Ambiance)."""
    bd = brand_dir(cid)
    if not bd.exists():
        return []
    slot_order = {k: i for i, (k, *_rest) in enumerate(_SLOTS)}
    files = [p for p in bd.glob("*.png") if p.is_file()]

    def sort_key(p: Path):
        _label, group = _slot_meta(p.stem)
        gi = _GROUP_ORDER.index(group) if group in _GROUP_ORDER else len(_GROUP_ORDER)
        return (gi, slot_order.get(p.stem, 99), p.stem)

    files.sort(key=sort_key)
    out = []
    for p in files:
        label, group = _slot_meta(p.stem)
        out.append({"key": p.stem, "kind": "image", "label": label, "group": group,
                    "url": f"/channels/{cid}/brand/{p.name}?t={int(p.stat().st_mtime)}"})
    return out


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
            publish_graph_to_comfy(f"{cid}_snippet_{k}", gdir / f"snippet_{k}.json")
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
        publish_graph_to_comfy(f"{cid}_channel_preview", wf)
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
