"""Assemble per-scene visuals + timed audio into one synced MP4 (moviepy 2.x).

Audio-led: each scene is shown for its timeline duration (real narration length
+ lead/tail, clamped to a minimum hold). Each scene's visual comes from the
style preset's source chain — animated clip (Wan), 2.5D parallax clip, or a
varied Ken Burns still (always the final fallback) — so one storyboard renders as
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
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from . import config, effects, grammar, jobs, projects, sfx, storage, transitions

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


def _date_chip(clip, text: str, W: int, H: int):
    """Typeset DATE STAMP — the one sanctioned on-screen text besides receipt
    stills (user rule amendment 2026-07-05: dates/backstory jumps carry a small
    date chip + click). Real fonts only; pops in low-left, fades out."""
    try:
        from moviepy import ColorClip, CompositeVideoClip, TextClip
        from moviepy.video.fx import CrossFadeIn, CrossFadeOut

        dur = min(2.6, max(1.2, float(clip.duration) - 0.5))
        fs = int(H * 0.046)
        font = next((f for f in ([r"C:\Windows\Fonts\georgiab.ttf"] + _FONTS)
                     if Path(f).exists()), FONT)
        x, y = int(W * 0.055), int(H * 0.82)
        txt = (TextClip(font=font, text=text, font_size=fs, color="#e8e0cc",
                        stroke_color="#0a0a10", stroke_width=max(2, fs // 14))
               .with_duration(dur).with_start(0.25).with_position((x, y))
               .with_effects([CrossFadeIn(0.16), CrossFadeOut(0.35)]))
        bar = (ColorClip(size=(max(60, int(len(text) * fs * 0.58)), 4),
                         color=(201, 162, 39))
               .with_duration(dur).with_start(0.25)
               .with_position((x, y + int(fs * 1.32)))
               .with_effects([CrossFadeIn(0.16), CrossFadeOut(0.35)]))
        return CompositeVideoClip([clip, txt, bar],
                                  size=(W, H)).with_duration(clip.duration)
    except Exception:  # noqa: BLE001
        return clip


def _emphasis_hits(scene: Dict, row: Optional[Dict], words, win_t0: float,
                   cfg: Dict, idx: int, offset: int = 0) -> List[Dict]:
    """Word-time-aligned micro-effect hits for a scene: find each emphasis
    phrase's first spoken occurrence inside the scene's narration span and
    return [{"t": sec_into_scene, "kind": ...}] (≤ max_per_scene, min gap)."""
    phrases = scene.get("emphasis") or []
    if not (phrases and row and words):
        return []
    t0, t1 = float(row["start"]) + win_t0, float(row["end"]) + win_t0
    span = [(w, a) for (w, a, _b) in words if t0 - 0.05 <= a < t1]
    if not span:
        return []
    import re as _re
    beat = grammar.beat_of(scene.get("narration") or "")
    kinds = cfg.get("effects") or ["zoom_bump"]
    kind = (cfg.get("by_beat") or {}).get(beat) or kinds[(idx + offset) % len(kinds)]
    max_n = max(1, int(cfg.get("max_per_scene", 1)))
    gap = float(cfg.get("min_gap_s", 2.5))
    hits: List[Dict] = []
    last = -1e9
    for phrase in phrases:
        toks = _re.findall(r"[a-z0-9']+", str(phrase).lower())
        if not toks:
            continue
        for j, (w, a) in enumerate(span):
            if w != toks[0]:
                continue
            if all(j + k < len(span) and span[j + k][0] == toks[k]
                   for k in range(min(len(toks), 3))):
                if a - last >= gap:
                    hits.append({"t": max(0.0, a - t0), "kind": kind})
                    last = a
                break
        if len(hits) >= max_n:
            break
    return hits


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
        if (opts or {}).get("preview"):
            # Edit-page live preview: a real slice of the edit, but never
            # listed in renders/history (it's a scratch look, not a cut).
            return {"url": f"/projects/{pid}/{out['rel']}", "preview": True,
                    "duration": out["duration"]}
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

    return jobs.submit("assemble", task, pid=pid)


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
    # the video's direction card bends camera energy + emphasis rotation
    card = (project.get("video") or {}).get("direction_card") or {}
    kb_strength *= float(card.get("kb_strength", 1.0) or 1.0)
    emph_off = int(card.get("emphasis_offset", 0) or 0)
    # video-wide film look (e.g. "vhs") — opts > preset; applied LAST per scene
    film_filter = str(asm.get("filter", preset.get("filter", "")) or "").lower()
    filter_cfg = (grammar.dictionary().get("filters") or {}).get(film_filter) or {}
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
    # Whisper word timestamps of the one-take narration → word-level emphasis
    emph_cfg = grammar.emphasis_cfg()
    words: List = []
    if narr and narr.get("words_file"):
        raw_words = storage.read_json(pdir / narr["words_file"], None) or []
        try:
            words = [(str(w).lower(), float(a), float(b)) for w, a, b in raw_words]
        except (TypeError, ValueError):
            words = []
    emph_events: List[float] = []             # absolute mix times for SFX ticks
    chip_events: List[float] = []             # date-chip appearances → click SFX
    ref_events: List[float] = []              # ref-card appearances → pop tick
    # researched reference photos (people/items/places) -> first-mention cards
    from . import refcards
    try:
        ref_plan = refcards.plan(project, pdir)
    except Exception as exc:  # noqa: BLE001 - cards are decoration, never fatal
        print(f"[assemble] ref plan failed: {exc}")
        ref_plan = {}
    # Optional time window [t0, t1] — renders just that slice of the timeline
    # (the Shorts cutter uses this with a 9:16 size). Scene starts shift to 0.
    window = asm.get("window")
    win_t0 = 0.0
    if window:
        win_t0, win_t1 = max(0.0, float(window[0])), float(window[1])
        rows, scenes = {}, []
        for r in tl["scenes"]:
            if r["end"] <= win_t0 or r["start"] >= win_t1:
                continue
            s = next((x for x in project["scenes"]
                      if str(x["id"]) == str(r["id"])), None)
            if not s:
                continue
            st = max(r["start"], win_t0) - win_t0
            en = min(r["end"], win_t1) - win_t0
            rows[str(r["id"])] = {**r, "start": round(st, 3), "end": round(en, 3),
                                  "dur": round(en - st, 3)}
            scenes.append(s)
        if not scenes:
            raise ValueError("window matches no scenes")
    else:
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
        # fill the rest of the (audio-led) scene with the last frame — but
        # DRIFTING, never frozen: motion dead-stopping reads as a glitch
        hold = dur - cd
        last = ImageClip(clip.get_frame(max(0.0, cd - 1e-3)))

        def zf(t):
            return 1.0 + 0.05 * (t / max(hold, 0.1))

        def pos(t):
            z = zf(t)
            return ((W - W * z) / 2, (H - H * z) / 2)
        drift = CompositeVideoClip([last.resized(zf).with_position(pos)],
                                   size=(W, H)).with_duration(hold)
        return concatenate_videoclips([clip, drift], method="compose").with_duration(dur)

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
        # receipt scenes (attached evidence screenshots) get the RECEIPT MOVE:
        # floating card → word-synced zoom into the referenced region →
        # animated marker highlight. They bypass Wan/parallax entirely.
        if s.get("receipt") and s.get("image_file"):
            rp = pdir / s["image_file"]
            if rp.exists():
                try:
                    from . import receipts
                    row = rows.get(str(s["id"]))
                    ts = receipts.sync_time(s, row, words, win_t0)
                    with_images += 1
                    return receipts.render_receipt_clip(
                        rp, dur, W=W, H=H, receipt=s["receipt"], sync_local=ts)
                except Exception as exc:  # noqa: BLE001 — fall to normal chain
                    print(f"[assemble] receipt move failed scene {s.get('id')}: {exc}")
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
                        amplitude=float(plx_cfg.get("amplitude", 0.018)))
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

    # Long timelines render in PARTS: each ~seg_limit scenes is composed,
    # hardware-encoded video-only, then all parts are stitched losslessly and
    # the one-pass audio mix is muxed on. Compositing a 15-minute video as a
    # single moviepy object would take hours and blow RAM; parts keep memory
    # flat and make long (11-20 min) videos practical.
    seg_limit = int(asm.get("segment_scenes", 24))
    segmented = n > int(asm.get("segment_threshold", 40))
    encoder = str(asm.get("encoder", "nvenc")).lower()
    work: Optional[Path] = None
    parts: List[Path] = []
    if segmented:
        import tempfile as _tf
        (pdir / "video").mkdir(parents=True, exist_ok=True)
        work = Path(_tf.mkdtemp(prefix="aaaflow_seg_", dir=str(pdir / "video")))

    def _write_video(vclip, path, *, with_sound=False):
        nonlocal encoder
        kw = dict(fps=fps, threads=os.cpu_count() or 4, logger=None)
        akw = dict(audio_codec="aac") if with_sound else dict(audio=False)
        if encoder == "nvenc":
            try:
                vclip.write_videofile(
                    str(path), codec="h264_nvenc", preset="p6",
                    ffmpeg_params=["-pix_fmt", "yuv420p", "-rc", "vbr",
                                   "-cq", "19", "-b:v", "0"], **kw, **akw)
                return
            except Exception as exc:  # noqa: BLE001 — no NVENC → CPU fallback
                print(f"[assemble] NVENC failed ({exc}); falling back to x264")
                encoder = "x264"
        vclip.write_videofile(
            str(path), codec="libx264", preset="medium",
            ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", "17"], **kw, **akw)

    def _flush_segment():
        nonlocal clips
        if not clips:
            return
        part = work / f"part_{len(parts):04d}.mp4"
        seg = concatenate_videoclips(clips, method="compose")
        _write_video(seg, part)
        try:
            seg.close()
            for c in clips:
                c.close()
        except Exception:  # noqa: BLE001
            pass
        parts.append(part)
        clips = []

    durs_sum = 0.0
    for i, s in enumerate(scenes):
        progress(f"Composing scene {s['id']} ({i + 1}/{n})",
                 0.04 + (0.56 if segmented else 0.60) * i / max(n, 1))
        dur = float(rows.get(str(s["id"]), {}).get("dur") or s.get("planned_dur") or 2.0)
        v = visual(s, dur, i)
        if s.get("fx"):
            v = transitions.apply_scene_fx(v, s["fx"], W=W, H=H)
        if do_transitions:
            kind = transitions.classify_transition(s.get("transition"))
            v = transitions.apply_transition(v, kind, dur=dur, W=W, H=H,
                                             raw=s.get("transition") or "")
        row = rows.get(str(s["id"]))
        hits = _emphasis_hits(s, row, words, win_t0, emph_cfg, i, offset=emph_off)
        if hits:
            v = transitions.apply_emphasis(v, hits, W=W, H=H)
            emph_events += [float(row["start"]) + h["t"] for h in hits]
        chip = (s.get("date_chip") or "").strip()
        if chip and FONT:
            v = _date_chip(v, chip, W, H)
            if row is not None:
                chip_events.append(float(row["start"]) + 0.25)
        rc = ref_plan.get(str(s["id"]))
        if rc:
            # first-mention reference card, synced to the spoken name
            try:
                from . import refcards as _rc
                t_loc = _rc.mention_time(
                    [rc.get("sync")] if rc.get("sync") else (rc.get("match") or []),
                    row, words, win_t0)
                v, t_shown = _rc.overlay(v, pdir / rc["file"],
                                         rc.get("label") or "", dur=dur,
                                         t0=t_loc, W=W, H=H,
                                         kind=rc.get("kind", ""))
                if row is not None and t_shown is not None:
                    ref_events.append(float(row["start"]) + t_shown)
            except Exception as exc:  # noqa: BLE001
                print(f"[assemble] ref card failed scene {s.get('id')}: {exc}")
        if film_filter:
            v = transitions.apply_filter(v, film_filter, W=W, H=H, cfg=filter_cfg)
        clips.append(v)
        durs_sum += dur
        if segmented and len(clips) >= seg_limit:
            progress(f"Encoding part {len(parts) + 1}", 0.04 + 0.56 * i / max(n, 1))
            _flush_segment()

    progress("Mixing audio", 0.66)
    # Per-scene transitions are self-contained entrances, so clips join cleanly.
    if segmented:
        _flush_segment()
        final = None
        total_dur = durs_sum
    else:
        final = concatenate_videoclips(clips, method="compose")
        total_dur = float(final.duration)

    # --- one audio session: narration + ducked bed + SFX + limiter ----------
    N = max(1, int(total_dur * SR))
    mix = np.zeros((N, 2), dtype=np.float32)

    if narr:
        # Narration-track projects: the whole recording laid over the timeline
        # as one continuous file (never cut per scene). A window slices it.
        track = _full_track(pdir / narr.get("file", ""), win_t0 + total_dur)
        if track is not None:
            track = track[int(win_t0 * SR):]
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

    # emphasis ticks: a tiny stinger exactly on each punched word
    e_sfx = emph_cfg.get("sfx") or {}
    if sfx_on and emph_events and e_sfx.get("cue"):
        arr = sfx.render(str(e_sfx["cue"]))
        if arr is not None:
            ev = max(0.0, min(1.0, float(e_sfx.get("volume", 0.16))))
            for tt in emph_events:
                off = int(tt * SR)
                end = min(N, off + len(arr))
                if end > off:
                    mix[off:end] += arr[: end - off] * ev

    # date chips land with a little mechanical click (user, 2026-07-05)
    if sfx_on and chip_events:
        arr = sfx.render("ui click")
        if arr is not None:
            for tt in chip_events:
                off = int(tt * SR)
                end = min(N, off + len(arr))
                if end > off:
                    mix[off:end] += arr[: end - off] * 0.4

    # reference cards land with a soft pop (tiny UI tick, allowed to synth)
    if sfx_on and ref_events:
        arr = sfx.render("pop")
        if arr is None:
            arr = sfx.render("ui click")
        if arr is not None:
            for tt in ref_events:
                off = int(tt * SR)
                end = min(N, off + len(arr))
                if end > off:
                    mix[off:end] += arr[: end - off] * 0.3

    peak = float(np.max(np.abs(mix)))
    if peak > 0.985:                           # keep the sum out of clipping
        mix *= 0.985 / peak
    progress("Encoding video", 0.74)

    out_name = (asm.get("out_name") or f"final_{time.strftime('%Y%m%d_%H%M%S')}")
    out_rel = f"video/{out_name}.mp4"
    out_abs = pdir / out_rel
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    # Near-lossless, GPU-first encode (user speed mandate 2026-07-03): NVENC
    # cq19 ≈ x264 crf17 on flat art at ~2-3x speed; x264 is the auto-fallback.
    if segmented:
        # lossless stitch of the already-encoded parts + one audio mux pass
        listf = work / "parts.txt"
        listf.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts),
                         encoding="utf-8")
        silent = work / "silent.mp4"
        r = subprocess.run([config.FFMPEG, "-y", "-v", "error", "-f", "concat",
                            "-safe", "0", "-i", str(listf), "-c", "copy",
                            str(silent)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"part stitch failed: {(r.stderr or '')[-300:]}")
        if peak > 0.0:
            import soundfile as sf
            wavf = work / "mix.wav"
            sf.write(str(wavf), mix, SR)
            progress("Muxing audio", 0.9)
            r = subprocess.run([config.FFMPEG, "-y", "-v", "error", "-i",
                                str(silent), "-i", str(wavf), "-c:v", "copy",
                                "-c:a", "aac", "-b:a", "192k", "-shortest",
                                str(out_abs)], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"audio mux failed: {(r.stderr or '')[-300:]}")
        else:
            shutil.move(str(silent), str(out_abs))
        shutil.rmtree(work, ignore_errors=True)
    else:
        if peak > 0.0:
            final = final.with_audio(AudioArrayClip(mix, fps=SR))
        _write_video(final, out_abs, with_sound=(peak > 0.0))
        try:
            final.close()
            for c in clips:
                c.close()
        except Exception:
            pass

    return {"rel": out_rel, "duration": round(total_dur, 2),
            "width": W, "height": H, "fps": fps, "scenes": n,
            "preset": preset.get("id"), "sources": sources,
            "with_audio": with_audio, "with_images": with_images,
            "with_videos": with_videos, "with_parallax": with_parallax,
            "with_sfx": with_sfx, "with_emphasis": len(emph_events)}
