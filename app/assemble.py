"""Assemble per-scene visuals + timed audio into one synced MP4 (moviepy 2.x).

Audio-led: each scene is shown for its timeline duration (real narration length
+ lead/tail, clamped to a minimum hold). Each scene's visual comes from the
style preset's source chain — LTX clip, 2.5D parallax clip, or a varied
Ken Burns still (always the final fallback) — so one storyboard renders as
"cinematic", "parallax slides" or "simple slides" without re-generating
anything. No on-screen text is burned in (it reads as AI; narration + visuals
carry the video). Scenes missing an image fall back to a cream card and scenes
missing audio play silence — a partial project still assembles.

Audio is built as ONE mix: narration placed on the timeline, the music bed
ducked under speech (sidechain-style), stinger SFX from each scene's
``audio_cue`` (library file or synth), then a peak limiter — like a human
editor's session.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from . import config, effects, jobs, projects, sfx, storage, transitions

ProgressFn = Callable[[str, float], None]

CREAM = (236, 230, 214)         # matches the storyboard's cream paper background
INK = "#1a1a1a"
SR = 44100

# A reliable Windows font for composited captions.
_FONTS = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
          r"C:\Windows\Fonts\arial.ttf"]
FONT = next((f for f in _FONTS if Path(f).exists()), None)


def _as_stereo(wav: np.ndarray, sr: int) -> np.ndarray:
    if sr != SR:
        wav = _resample(wav, sr, SR)
    if wav.ndim == 1:
        wav = np.stack([wav, wav], axis=-1)
    elif wav.shape[-1] == 1:
        wav = np.repeat(wav, 2, axis=-1)
    return wav.astype(np.float32)


def _duck_gain(speech: np.ndarray, duck_gain: float = 0.35,
               thresh: float = 0.02) -> np.ndarray:
    """Per-sample gain curve that lowers the bed while narration plays.

    Block-max envelope -> speech mask -> smoothed (~350 ms) so the music
    breathes back up in pauses instead of pumping.
    """
    win = int(SR * 0.04)
    nb = int(np.ceil(len(speech) / win)) or 1
    env = np.pad(speech, (0, nb * win - len(speech))).reshape(nb, win).max(axis=1)
    mask = (env > thresh).astype(np.float32)
    kern = np.ones(9, dtype=np.float32) / 9.0
    m = np.clip(np.convolve(mask, kern, mode="same") * 1.4, 0.0, 1.0)
    gain = 1.0 - (1.0 - duck_gain) * m
    return np.repeat(gain, win)[: len(speech)]


def _read_wav(path: Path):
    import soundfile as sf
    wav, sr = sf.read(str(path), dtype="float32", always_2d=False)
    return wav, int(sr)


def _full_track(path: Optional[Path], dur: float) -> Optional[np.ndarray]:
    """Whole narration recording as stereo float32 @ SR, padded/trimmed to `dur` sec."""
    if not path or not path.exists() or dur <= 0:
        return None
    try:
        wav, sr = _read_wav(path)
    except Exception:
        return None
    if sr != SR:
        wav = _resample(wav, sr, SR)
    if wav.ndim == 1:
        wav = np.stack([wav, wav], axis=-1)
    elif wav.shape[-1] == 1:
        wav = np.repeat(wav, 2, axis=-1)
    n = max(1, int(dur * SR))
    if wav.shape[0] < n:
        wav = np.pad(wav, ((0, n - wav.shape[0]), (0, 0)))
    return wav[:n].astype(np.float32)


def _background_bed(music: Optional[Dict], total_dur: float) -> Optional[np.ndarray]:
    """Looped/trimmed, faded, volume-scaled stereo music bed for the whole video."""
    if not music or not music.get("file") or total_dur <= 0:
        return None
    path = config.MUSIC_DIR / music["file"]
    if not path.exists():
        return None
    try:
        wav, sr = _read_wav(path)
    except Exception:
        return None
    if sr != SR:
        wav = _resample(wav, sr, SR)
    if wav.ndim == 1:
        wav = np.stack([wav, wav], axis=-1)
    elif wav.shape[-1] == 1:
        wav = np.repeat(wav, 2, axis=-1)
    if wav.shape[0] == 0:
        return None
    n = int(total_dur * SR)
    reps = int(np.ceil(n / wav.shape[0]))
    bed = np.tile(wav, (reps, 1))[:n].astype(np.float32)
    bed *= max(0.0, min(1.0, float(music.get("volume", 0.18))))
    fade = max(0.0, float(music.get("fade", 1.5)))
    f = int(fade * SR)
    if f > 0 and 2 * f < n:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)[:, None]
        bed[:f] *= ramp
        bed[-f:] *= ramp[::-1]
    return bed


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
    from moviepy import (AudioArrayClip, ColorClip, CompositeAudioClip,
                         CompositeVideoClip, ImageClip, TextClip, VideoFileClip,
                         concatenate_videoclips)

    project = projects.get_project(pid)
    asm = {**project["settings"].get("assemble", {}), **(opts or {})}
    # Style preset: settings/opts override individual preset fields.
    preset = effects.get(asm.get("preset") or "cinematic")
    sources = [s for s in (asm.get("sources") or preset.get("sources") or ["stills"])
               if s in ("clips", "parallax", "stills")]
    plx_cfg = {**(preset.get("parallax") or {}), **(asm.get("parallax") or {})}
    kb_strength = float(asm.get("kb_strength", preset.get("kb_strength", 1.0)))
    W = int(asm.get("width", 1920)); H = int(asm.get("height", 1080)); fps = int(asm.get("fps", 30))
    kb = bool(asm.get("ken_burns", preset.get("ken_burns", True)))
    do_transitions = bool(asm.get("transitions", preset.get("transitions", True)))
    sfx_on = bool(asm.get("sfx", preset.get("sfx", True)))
    sfx_vol = float(asm.get("sfx_volume", preset.get("sfx_volume", 0.5)))
    duck_gain = float(asm.get("music_duck", preset.get("music_duck", 0.35)))
    sync = project["settings"].get("sync", {})
    lead = float(sync.get("lead_in_ms", 120)) / 1000.0

    pdir = projects.project_dir(pid)
    narr = project.get("narration")           # one continuous voiceover track, if attached
    tl = projects.recompute_timeline(project)
    rows = {str(r["id"]): r for r in tl["scenes"]}
    scenes = project["scenes"]
    n = len(scenes)
    with_audio = with_images = with_videos = with_parallax = 0
    # legacy toggle: use_animation False drops "clips" from the chain
    if asm.get("use_animation") is False:
        sources = [s for s in sources if s != "clips"]
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

    def _ken_burns(base, dur, idx):
        """Varied, deterministic move per scene: alternate zoom in/out and
        drift direction so long runs of stills don't feel like a metronome."""
        amt = 0.075 * max(0.2, kb_strength)
        zin = idx % 2 == 0
        z0, z1 = (1.0, 1.0 + amt) if zin else (1.01 + amt, 1.005)
        dxs = (0, -1, 0, 1)[idx % 4]
        dys = (-1, 0, 1, 0)[idx % 4]

        def zf(t):
            return z0 + (z1 - z0) * (t / max(dur, 0.1))

        def pos(t):
            z = zf(t)
            mx, my = (z - 1) * W / 2, (z - 1) * H / 2
            return ((W - W * z) / 2 + dxs * 0.5 * mx,
                    (H - H * z) / 2 + dys * 0.5 * my)
        zc = base.resized(zf).with_position(pos)
        return CompositeVideoClip([zc], size=(W, H)).with_duration(dur)

    def _try_clip(path, dur):
        try:
            clip = VideoFileClip(str(path))
            if clip.audio is not None:
                clip = clip.without_audio()
            return _fit_clip(clip, dur)
        except Exception:
            return None

    def visual(s, dur, idx):
        nonlocal with_images, with_videos, with_parallax
        for src in list(sources) + ["stills"]:
            if src == "clips" and s.get("video_file"):
                p = pdir / s["video_file"]
                if p.exists():
                    v = _try_clip(p, dur)
                    if v is not None:
                        with_videos += 1
                        return v
            elif src == "parallax":
                try:
                    from .parallax import parallax_engine
                    pc = parallax_engine.ensure_scene_clip(
                        pdir, s, dur=dur, width=W, height=H, fps=fps, idx=idx,
                        amplitude=float(plx_cfg.get("amplitude", 0.024)))
                    if pc:
                        v = _try_clip(pc, dur)
                        if v is not None:
                            with_parallax += 1
                            return v
                except Exception as exc:  # noqa: BLE001 - fall through to stills
                    print(f"[assemble] parallax failed for scene {s.get('id')}: {exc}")
            elif src == "stills":
                imgp = pdir / s["image_file"] if s.get("image_file") else None
                if imgp and imgp.exists():
                    with_images += 1
                    base = ImageClip(str(imgp))
                    scale = max(W / base.w, H / base.h)
                    base = base.resized(scale)
                    base = base.cropped(x_center=base.w / 2, y_center=base.h / 2,
                                        width=W, height=H)
                    if kb:
                        return _ken_burns(base, dur, idx)
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

    for i, s in enumerate(scenes):
        progress(f"Composing scene {s['id']} ({i + 1}/{n})", 0.04 + 0.60 * i / max(n, 1))
        dur = float(rows.get(str(s["id"]), {}).get("dur") or s.get("planned_dur") or 2.0)
        v = visual(s, dur, i)
        if do_transitions:
            kind = transitions.classify_transition(s.get("transition"))
            v = transitions.apply_transition(v, kind, dur=dur, W=W, H=H,
                                             raw=s.get("transition") or "")
        clips.append(v)

    progress("Mixing audio", 0.66)
    # Per-scene transitions are self-contained entrances, so clips join cleanly.
    final = concatenate_videoclips(clips, method="compose")

    # --- one audio session: narration + ducked bed + SFX + limiter ----------
    total_dur = float(final.duration)
    N = max(1, int(total_dur * SR))
    mix = np.zeros((N, 2), dtype=np.float32)

    if narr:
        # Narration-track projects: the whole recording laid over the timeline
        # as one continuous file (never cut per scene).
        track = _full_track(pdir / narr.get("file", ""), total_dur)
        if track is not None:
            with_audio = n
            mix[: len(track)] += track[:N]
    else:
        for s in scenes:
            r = rows.get(str(s["id"]))
            ap = (pdir / s["audio_file"]) if s.get("audio_file") else None
            if r is None or not (ap and ap.exists()):
                continue
            try:
                wav = _as_stereo(*_read_wav(ap))
            except Exception:
                continue
            with_audio += 1
            off = int((float(r["start"]) + lead) * SR)
            end = min(N, off + len(wav))
            if end > off:
                mix[off:end] += wav[: end - off]

    speech = np.abs(mix).max(axis=1)          # narration-only envelope (pre-bed)

    music_cfg = project["settings"].get("music") or {}
    bed = _background_bed(music_cfg, total_dur)
    if bed is not None:
        if music_cfg.get("duck", True) and speech.any():
            bed = bed * _duck_gain(speech, duck_gain=duck_gain)[:, None][: len(bed)]
        mix[: len(bed)] += bed[:N]

    with_sfx = 0
    if sfx_on:
        vol = sfx_vol
        for s in scenes:
            cue = (s.get("audio_cue") or "").strip()
            r = rows.get(str(s["id"]))
            if not cue or r is None:
                continue
            arr = sfx.render(cue)
            if arr is None:
                continue
            off = int(float(r["start"]) * SR)
            if sfx.is_pre(cue):                # risers END on the cut
                off = max(0, off - len(arr))
            end = min(N, off + len(arr))
            if end > off:
                mix[off:end] += arr[: end - off] * vol
                with_sfx += 1

    peak = float(np.max(np.abs(mix)))
    if peak > 0.985:                           # keep the sum out of clipping
        mix *= 0.985 / peak
    if peak > 0.0:
        final = final.with_audio(AudioArrayClip(mix, fps=SR))
    progress("Encoding video", 0.74)

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
            "preset": preset.get("id"), "sources": sources,
            "with_audio": with_audio, "with_images": with_images,
            "with_videos": with_videos, "with_parallax": with_parallax,
            "with_sfx": with_sfx}
