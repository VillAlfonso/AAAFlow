"""Assemble per-scene images + timed audio into one synced MP4 (moviepy 2.x).

Audio-led: each scene is shown for its timeline duration (real narration length
+ lead/tail, clamped to a minimum hold). Stills get an optional Ken Burns
zoom; on_screen_text is composited in post (the image models aren't used for
spelling); scenes missing an image fall back to a cream title card and scenes
missing audio play silence — so a partial project still assembles.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from . import config, jobs, projects, storage, transitions

ProgressFn = Callable[[str, float], None]

CREAM = (236, 230, 214)         # matches the storyboard's cream paper background
INK = "#1a1a1a"
SR = 44100

# A reliable Windows font for composited captions.
_FONTS = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
          r"C:\Windows\Fonts\arial.ttf"]
FONT = next((f for f in _FONTS if Path(f).exists()), None)


def _audio_array(path: Optional[Path], dur: float, lead: float) -> np.ndarray:
    """Stereo float array of exactly `dur` seconds with narration placed at `lead`."""
    total = np.zeros((max(1, int(dur * SR)), 2), dtype=np.float32)
    if path and path.exists():
        try:
            wav, sr = _read_wav(path)
            if sr != SR:
                wav = _resample(wav, sr, SR)
            if wav.ndim == 1:
                wav = np.stack([wav, wav], axis=-1)
            elif wav.shape[-1] == 1:
                wav = np.repeat(wav, 2, axis=-1)
            off = int(min(lead, max(0.0, dur - len(wav) / SR)) * SR)
            end = min(total.shape[0], off + wav.shape[0])
            total[off:end] = wav[: end - off]
        except Exception:
            pass
    return total


def _read_wav(path: Path):
    import soundfile as sf
    wav, sr = sf.read(str(path), dtype="float32", always_2d=False)
    return wav, int(sr)


def _resample(wav: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target or wav.size == 0:
        return wav
    n = int(round(wav.shape[0] * target / sr))
    xp = np.linspace(0, 1, wav.shape[0], endpoint=False)
    x = np.linspace(0, 1, n, endpoint=False)
    if wav.ndim == 1:
        return np.interp(x, xp, wav).astype(np.float32)
    return np.stack([np.interp(x, xp, wav[:, c]) for c in range(wav.shape[1])], axis=-1).astype(np.float32)


def submit_assemble(pid: str, opts: Optional[Dict] = None) -> str:
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    if not project.get("scenes"):
        raise ValueError("Project has no scenes.")

    def task(progress: ProgressFn) -> Dict:
        out = _render(pid, opts or {}, progress)
        proj = projects.get_project(pid)
        render = {
            "id": storage.new_id(), "created": time.time(),
            "file": out["rel"], "duration": out["duration"],
            "width": out["width"], "height": out["height"], "fps": out["fps"],
            "scenes": out["scenes"], "with_audio": out["with_audio"],
            "with_images": out["with_images"], "with_videos": out.get("with_videos", 0),
        }
        proj.setdefault("renders", []).insert(0, render)
        projects.save_project(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "video", "project": pid, "project_name": proj["name"],
            "duration": out["duration"], "file": out["rel"],
            "url": f"/projects/{pid}/{out['rel']}",
            "text_preview": f"Assembled “{proj['name']}” ({out['scenes']} scenes, {out['duration']:.0f}s)",
        })
        return {"render": render, "url": f"/projects/{pid}/{out['rel']}"}

    return jobs.submit("assemble", task)


def _render(pid: str, opts: Dict, progress: ProgressFn) -> Dict:
    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", config.FFMPEG)
    from moviepy import (AudioArrayClip, ColorClip, CompositeVideoClip,
                         ImageClip, TextClip, VideoFileClip, concatenate_videoclips)

    project = projects.get_project(pid)
    asm = {**project["settings"].get("assemble", {}), **(opts or {})}
    W = int(asm.get("width", 1920)); H = int(asm.get("height", 1080)); fps = int(asm.get("fps", 30))
    kb = bool(asm.get("ken_burns", True)); burn = bool(asm.get("burn_text", True))
    do_transitions = bool(asm.get("transitions", True))
    sync = project["settings"].get("sync", {})
    lead = float(sync.get("lead_in_ms", 120)) / 1000.0

    pdir = projects.project_dir(pid)
    tl = projects.recompute_timeline(project)
    rows = {str(r["id"]): r for r in tl["scenes"]}
    scenes = project["scenes"]
    n = len(scenes)
    with_audio = with_images = with_videos = 0
    use_anim = bool(asm.get("use_animation", True))
    clips = []

    def _fit_clip(clip, dur):
        """Cover-fit a VideoFileClip to WxH and make it exactly `dur` seconds."""
        scale = max(W / clip.w, H / clip.h)
        clip = clip.resized(scale)
        clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=W, height=H)
        cd = float(clip.duration or dur)
        if cd >= dur:
            return clip.subclipped(0, dur)
        # hold the last frame to fill the (audio-led) scene duration
        last = ImageClip(clip.get_frame(max(0.0, cd - 1e-3))).with_duration(dur - cd)
        return concatenate_videoclips([clip, last], method="compose").with_duration(dur)

    def visual(s, dur):
        nonlocal with_images, with_videos
        vidp = pdir / s["video_file"] if s.get("video_file") else None
        if use_anim and vidp and vidp.exists():
            try:
                clip = VideoFileClip(str(vidp))
                if clip.audio is not None:
                    clip = clip.without_audio()
                with_videos += 1
                return _fit_clip(clip, dur)
            except Exception:
                pass
        imgp = pdir / s["image_file"] if s.get("image_file") else None
        if imgp and imgp.exists():
            with_images += 1
            base = ImageClip(str(imgp))
            scale = max(W / base.w, H / base.h)
            base = base.resized(scale)
            base = base.cropped(x_center=base.w / 2, y_center=base.h / 2, width=W, height=H)
            if kb:
                z = base.resized(lambda t: 1 + 0.06 * (t / max(dur, 0.1)))
                return CompositeVideoClip([z.with_position("center")], size=(W, H)).with_duration(dur)
            return base.with_duration(dur)
        # placeholder cream card
        bg = ColorClip(size=(W, H), color=CREAM).with_duration(dur)
        if FONT:
            try:
                lab = TextClip(font=FONT, text=f"scene {s['id']}", font_size=int(H * 0.07),
                               color="#9a9488").with_duration(dur).with_position("center")
                return CompositeVideoClip([bg, lab], size=(W, H)).with_duration(dur)
            except Exception:
                pass
        return bg

    def caption(s, dur):
        txt = (s.get("on_screen_text") or "").strip()
        if not (burn and txt and FONT):
            return None
        try:
            t = TextClip(font=FONT, text=txt, font_size=int(H * 0.058), color=INK,
                         method="caption", size=(int(W * 0.8), None), text_align="center",
                         stroke_color="white", stroke_width=2).with_duration(dur)
            pos = ("center", int(H * 0.76))
            kind = transitions.classify_text_anim(s.get("text_anim"))
            return transitions.apply_text_anim(t, kind, dur=dur, W=W, H=H, pos=pos)
        except Exception:
            return None

    for i, s in enumerate(scenes):
        progress(f"Composing scene {s['id']} ({i + 1}/{n})", 0.04 + 0.66 * i / max(n, 1))
        dur = float(rows.get(str(s["id"]), {}).get("dur") or s.get("planned_dur") or 2.0)
        v = visual(s, dur)
        cap = caption(s, dur)
        if cap is not None:
            v = CompositeVideoClip([v, cap], size=(W, H)).with_duration(dur)
        ap = (pdir / s["audio_file"]) if s.get("audio_file") else None
        if ap and ap.exists():
            with_audio += 1
        arr = _audio_array(ap, dur, lead)
        v = v.with_audio(AudioArrayClip(arr, fps=SR))
        if do_transitions:
            kind = transitions.classify_transition(s.get("transition"))
            v = transitions.apply_transition(v, kind, dur=dur, W=W, H=H)
        clips.append(v)

    progress("Encoding video", 0.74)
    # Per-scene transitions are self-contained entrances, so clips join cleanly.
    final = concatenate_videoclips(clips, method="compose")

    out_rel = f"video/final_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    out_abs = pdir / out_rel
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(out_abs), fps=fps, codec="libx264", audio_codec="aac",
        preset="medium", threads=os.cpu_count() or 4, logger=None,
        ffmpeg_params=["-pix_fmt", "yuv420p"],
    )
    try:
        final.close()
        for c in clips:
            c.close()
    except Exception:
        pass

    return {"rel": out_rel, "duration": round(float(tl["total_dur"]), 2),
            "width": W, "height": H, "fps": fps, "scenes": n,
            "with_audio": with_audio, "with_images": with_images,
            "with_videos": with_videos}
