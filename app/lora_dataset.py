"""Wan LoRA dataset prep: kept study videos -> shot-aligned training clips.

USER DECISION 2026-07-14 (overrides the 2026-07-12 "prompt DNA only" rule,
risk disclosed): reference-channel footage may be used to train a Wan 2.2
style LoRA. The dataset follows the standing technical rule: SHOT-ALIGNED
2-4 s clips cut at the gatherer's detected boundaries, never reassembled
screenshots. Clips are short, low-res (training buckets), transformative in
purpose (style transfer), and never ship in any video.

Flow (per study):
  1. every kept video (data/gatherer/<gid>/video.mp4) + its report.json shots
  2. pick clips: within-shot 2-4 s windows, skipping the first 0.3 s after a
     cut (transition blur) and shots < 1.6 s; spread evenly across the video
  3. ffmpeg-cut + scale to the training bucket (default 384x216 @ 16 fps)
  4. caption each clip's mid-frame with the local VLM (style-forward wording)
  5. write musubi-tuner dataset TOML + a manifest with provenance

Output: data/lora_datasets/<name>/clips/*.mp4 + *.txt + dataset.toml
Training itself is driven by trainers/musubi-tuner (see the mission notes);
this module only builds the dataset.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import config, vlm
from .gatherer import GATHER_DIR

DATASETS_DIR = config.DATA_DIR / "lora_datasets"

CAPTION_PROMPT = (
    "Describe this documentary frame in one flowing sentence for a video "
    "generation model: shot type, subject, lighting, color grade, camera "
    "feel. Plain factual words, no lists, no quotes.")


def _shots_of(gid: str) -> List[Dict]:
    """report.json stores shots compactly as [t0, t1, transition, motion]."""
    rep = GATHER_DIR / gid / "report.json"
    if not rep.exists():
        return []
    data = json.loads(rep.read_text(encoding="utf-8"))
    out: List[Dict] = []
    for s in data.get("shots") or []:
        if isinstance(s, dict):
            out.append({"t0": float(s["t0"]), "t1": float(s["t1"]),
                        "mo": s.get("mo", "static")})
        elif isinstance(s, (list, tuple)) and len(s) >= 2:
            out.append({"t0": float(s[0]), "t1": float(s[1]),
                        "mo": (s[3] if len(s) > 3 else "static") or "static"})
    return out


def _video_of(gid: str) -> Optional[Path]:
    d = GATHER_DIR / gid
    for name in ("video.mp4", "source.mp4"):
        if (d / name).exists():
            return d / name
    hits = sorted(d.glob("*.mp4"))
    hits = [h for h in hits if not h.name.startswith("pack")]
    return hits[0] if hits else None


def build(name: str, gids: List[str], *, clips_per_video: int = 40,
          clip_len: float = 3.0, width: int = 384, height: int = 216,
          fps: int = 16, caption: bool = True, progress=None) -> Dict:
    """Cut + caption a training set from kept gather videos. Idempotent-ish:
    re-running overwrites clips of the same index."""
    def note(msg, frac):
        if progress:
            progress(msg, frac)

    out = DATASETS_DIR / name
    clips_dir = out / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest: List[Dict] = []
    made = 0
    for vi, gid in enumerate(gids):
        src = _video_of(gid)
        shots = _shots_of(gid)
        if not src or not shots:
            note(f"{gid}: no kept video or shots — skipped", vi / len(gids))
            continue
        # candidate windows: one per usable shot, longest shots first, then
        # thinned evenly so the set spans the whole runtime
        usable = [s for s in shots
                  if (s["t1"] - s["t0"]) >= max(1.6, clip_len * 0.6)]
        usable.sort(key=lambda s: s["t0"])
        if len(usable) > clips_per_video:
            step = len(usable) / clips_per_video
            usable = [usable[int(k * step)] for k in range(clips_per_video)]
        for ci, sh in enumerate(usable):
            t0 = sh["t0"] + 0.3
            dur = min(clip_len, sh["t1"] - t0 - 0.05)
            if dur < 1.2:
                continue
            clip = clips_dir / f"{gid[-4:]}_{ci:03d}.mp4"
            r = subprocess.run(
                [config.FFMPEG, "-y", "-ss", f"{t0:.2f}", "-i", str(src),
                 "-t", f"{dur:.2f}",
                 "-vf", f"scale={width}:{height}:force_original_aspect_ratio="
                        f"increase,crop={width}:{height}",
                 "-r", str(fps), "-an", "-c:v", "libx264", "-crf", "18",
                 "-pix_fmt", "yuv420p", str(clip)],
                capture_output=True)
            if r.returncode != 0 or not clip.exists():
                continue
            manifest.append({"file": clip.name, "gid": gid,
                             "t0": round(t0, 2), "dur": round(dur, 2),
                             "motion": sh.get("mo", "static")})
            made += 1
            if made % 10 == 0:
                note(f"{made} clips cut", (vi + ci / max(len(usable), 1)) / len(gids))

    if caption and vlm.available():
        note("Captioning clips (local VLM)", 0.85)
        import cv2
        for i, m in enumerate(manifest):
            txt = clips_dir / (Path(m["file"]).stem + ".txt")
            if txt.exists():
                continue
            cap = cv2.VideoCapture(str(clips_dir / m["file"]))
            cap.set(cv2.CAP_PROP_POS_FRAMES, 8)
            ok, fr = cap.read()
            cap.release()
            if not ok:
                continue
            tmp = clips_dir / "_frame.jpg"
            cv2.imwrite(str(tmp), fr)
            try:
                line = vlm.describe(tmp, CAPTION_PROMPT).strip().replace("\n", " ")
                # motion word from the gatherer keeps the caption honest
                if m["motion"] not in ("static", "hand"):
                    line += f" Camera {m['motion'].replace('-', ' ')}."
                txt.write_text(line, encoding="utf-8")
            except Exception:  # noqa: BLE001 — uncaptioned clip still trains
                pass
            if i % 10 == 0:
                note(f"captioned {i + 1}/{len(manifest)}", 0.85 + 0.13 * i / max(len(manifest), 1))
        try:
            (clips_dir / "_frame.jpg").unlink(missing_ok=True)
        except OSError:
            pass
        vlm.unload()

    toml = f"""# musubi-tuner dataset — generated {time.strftime('%Y-%m-%d %H:%M')}
[general]
resolution = [{width}, {height}]
caption_extension = ".txt"
batch_size = 1
enable_bucket = true
bucket_no_upscale = false

[[datasets]]
video_directory = "{(clips_dir).as_posix()}"
cache_directory = "{(out / 'cache').as_posix()}"
target_frames = [1, 17, 33, 49]
frame_extraction = "head"
num_repeats = 1
"""
    (out / "dataset.toml").write_text(toml, encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps({"name": name, "gids": gids, "clips": manifest,
                    "built": time.strftime("%Y-%m-%d %H:%M")},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    note("dataset ready", 1.0)
    return {"name": name, "clips": len(manifest), "dir": str(out)}
