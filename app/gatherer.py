"""YouTube evidence-pack gatherer (the standalone AAADataGatherer, integrated).

Paste YouTube URLs; each becomes one queued "gather" job that downloads the
video, transcribes it with faster-whisper (word timestamps), detects shots,
labels camera motion (optical flow, no ML), builds labeled contact sheets,
measures a loudness envelope and writes an evidence pack under
data/gatherer/<gid>/:

  report.md    the single all-in-one text file (paste into any Claude)
  report.json  same data machine-readable
  sheet_NN.jpg timestamped frame sheets
  pack.pdf     report text + every sheet in one attachable file
  thumbnail.jpg the video's cover

Packs feed RULE_EXTRACTION_PROMPT.md (repo root) to reverse-engineer a
creator's style into numeric rules the studio can follow.

Jobs run through app.jobs so Whisper serializes with the studio's other GPU
work and shows on the Queue page. Records persist to gather.json per pack and
survive restarts; packs made by the old standalone app (AAADataGatherer/,
port 8765, which collides with the ACE sidecar) migrate in on first load.
"""
from __future__ import annotations

import gc
import json
import math
import os
import re
import shutil
import subprocess
import textwrap
import threading
import time
import uuid
import wave
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from . import config, jobs

GATHER_DIR = config.DATA_DIR / "gatherer"
WHISPER_DIR = config.MODELS_DIR / "whisper"          # shared with app.transcribe
LEGACY_DIR = config.BASE_DIR / "AAADataGatherer" / "data"

ALLOWED_MODELS = ["large-v3", "large-v2", "distil-large-v3", "medium", "small",
                  "base", "tiny"]
SAMPLING = {"shots": None, "2s": 2.0, "1s": 1.0}
# Per-stage spans of the overall job progress (roughly time-proportional).
STAGES = [("download", 0.00, 0.12), ("transcribe", 0.12, 0.42),
          ("shots", 0.42, 0.58), ("motion", 0.58, 0.68),
          ("frames", 0.68, 0.80), ("audio", 0.80, 0.84),
          ("report", 0.84, 1.00)]
STAGE_NAMES = [s[0] for s in STAGES]

# Contact sheet geometry: 6x5 tiles at 320px wide keeps every tile legible even
# after a vision model downscales the sheet to ~1568px on the long side.
TILE_W, TILE_H = 320, 180
SHEET_COLS, SHEET_ROWS = 6, 5
MAX_TILES = 600            # cap in shots-only mode
MAX_TILES_DENSE = 1500     # cap when dense sampling is on

LONG_SHOT_STEP = 10.0      # extra thumbnail roughly every 10s inside long shots
MAX_EXTRA_PER_SHOT = 3
PAUSE_MIN = 0.5            # inter-word gap (s) that counts as a spoken pause
FADE_LUMA = 18.0           # mean luma below this at a boundary = fade-through-dark
CUT_THRESHOLD = 27.0       # PySceneDetect ContentDetector threshold
MIN_SHOT_FRAMES = 12       # ~0.4s at 30fps; allows fast-cut content without noise

WRAP_WIDTH = 96
SENT_END = (".", "!", "?", "…")

_records: Dict[str, Dict] = {}
_lock = threading.Lock()
_loaded = False


# ---------------------------------------------------------------- records

def _persist(gid: str) -> None:
    with _lock:
        rec = _records.get(gid)
        snap = dict(rec) if rec else None
    if not snap:
        return
    d = GATHER_DIR / gid
    d.mkdir(parents=True, exist_ok=True)
    (d / "gather.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                                   encoding="utf-8")


def _set(gid: str, **kw) -> None:
    with _lock:
        if gid in _records:
            _records[gid].update(kw)


def _migrate_legacy() -> None:
    """One-time copy of packs made by the standalone app into data/gatherer/."""
    src = LEGACY_DIR / "jobs"
    if not src.is_dir():
        return
    for jf in sorted(src.glob("*/job.json")):
        dst = GATHER_DIR / jf.parent.name
        if dst.exists():
            continue
        try:
            shutil.copytree(jf.parent, dst)
            rec = json.loads((dst / "job.json").read_text(encoding="utf-8"))
            rec.pop("cancel", None)
            (dst / "gather.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            (dst / "job.json").unlink(missing_ok=True)
            print(f"[gatherer] migrated legacy pack {jf.parent.name}")
        except Exception as exc:  # noqa: BLE001 - a bad pack must not block boot
            print(f"[gatherer] legacy migration failed for {jf.parent.name}: {exc}")


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
    GATHER_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy()
    for jf in GATHER_DIR.glob("*/gather.json"):
        try:
            rec = json.loads(jf.read_text(encoding="utf-8"))
            rec.pop("cancel", None)
            # The in-memory queue died with the previous server process.
            if rec.get("status") in ("running", "queued"):
                rec["status"] = "error"
                rec["error"] = rec["msg"] = "interrupted (server restarted)"
                jf.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                              encoding="utf-8")
            with _lock:
                _records[rec["id"]] = rec
        except Exception:  # noqa: BLE001
            continue


def _slim_meta(meta: Dict) -> Dict:
    m = dict(meta or {})
    for k in ("description", "tags", "chapters"):   # keep the poll payload light
        m.pop(k, None)
    return m


def list_records() -> List[Dict]:
    _load()
    with _lock:
        recs = [dict(r) for r in _records.values()]
    out = []
    for r in sorted(recs, key=lambda x: x.get("created", 0), reverse=True):
        # A job cancelled from the Queue page while still queued never runs its
        # fn, so the record would stay "queued" forever without this sync.
        if r.get("status") in ("queued", "running") and r.get("job_id"):
            j = jobs.get_job(r["job_id"])
            if j is None:
                r["status"] = "error"
                r["error"] = r["msg"] = "interrupted (server restarted)"
                _set(r["id"], status=r["status"], error=r["error"], msg=r["msg"])
                _persist(r["id"])
            elif j["status"] == "cancelled" and r["status"] != "cancelled":
                r["status"], r["msg"] = "cancelled", "cancelled by user"
                _set(r["id"], status="cancelled", msg=r["msg"])
                _persist(r["id"])
        r["meta"] = _slim_meta(r.get("meta"))
        out.append(r)
    return out


def submit(urls: List[str], opts: Dict) -> List[str]:
    _load()
    gids = []
    for url in urls:
        gid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        rec = {
            "id": gid, "url": url.strip(),
            "status": "queued", "stage": "", "pct": 0.0,
            "msg": "waiting in queue", "created": time.time(),
            "options": dict(opts), "meta": {}, "summary": {}, "outputs": [],
            "error": None, "job_id": None,
        }
        with _lock:
            _records[gid] = rec
        jid = jobs.submit("gather", _runner(gid))
        _set(gid, job_id=jid)
        _persist(gid)
        gids.append(gid)
    return gids


def cancel(gid: str) -> bool:
    _load()
    with _lock:
        rec = _records.get(gid)
        if not rec:
            raise ValueError("no such pack")
        jid, status = rec.get("job_id"), rec["status"]
    ok = jobs.cancel(jid) if jid else False
    if status == "queued":       # dropped from the queue; fn will never run
        _set(gid, status="cancelled", msg="cancelled by user")
        _persist(gid)
    elif status == "running":
        _set(gid, msg="cancelling, stops at the next checkpoint")
        _persist(gid)
    return ok


def delete(gid: str) -> None:
    _load()
    with _lock:
        rec = _records.get(gid)
        if rec and rec["status"] == "running":
            raise ValueError("cancel the job before deleting it")
        _records.pop(gid, None)
    shutil.rmtree(GATHER_DIR / gid, ignore_errors=True)


def file_path(gid: str, name: str) -> Path:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", gid or ""):
        raise ValueError("no such pack")
    base = (GATHER_DIR / gid).resolve()
    p = (base / name).resolve()
    if p.parent != base or not p.is_file():
        raise ValueError("no such file")
    return p


def rule_prompt() -> str:
    p = config.BASE_DIR / "RULE_EXTRACTION_PROMPT.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# ---------------------------------------------------------------- runner

def _more_gathers_queued() -> bool:
    try:
        with jobs._lock:
            return any(j["kind"] == "gather" and j["status"] == "queued"
                       for j in jobs._jobs.values())
    except Exception:  # noqa: BLE001
        return False


def _runner(gid: str) -> Callable:
    def fn(progress) -> Dict:
        job_dir = GATHER_DIR / gid
        job_dir.mkdir(parents=True, exist_ok=True)
        with _lock:
            rec = dict(_records.get(gid) or {})
        opts = rec.get("options") or {}
        url = rec.get("url", "")

        hit = {"cancelled": False}
        last_save = [0.0]
        span = {"name": "download", "a": 0.0, "b": 0.12}

        def _jp(frac: float) -> None:
            try:
                progress(span["name"], frac)
            except jobs.JobCancelled:
                hit["cancelled"] = True
                raise

        def set_stage(name: str, msg: str = "") -> None:
            for n, a, b in STAGES:
                if n == name:
                    span.update(name=n, a=a, b=b)
                    break
            _set(gid, stage=name, pct=0.0, msg=msg or name)
            _persist(gid)
            _jp(span["a"])

        def tick(pct: float) -> None:
            pct = max(0.0, min(100.0, float(pct)))
            _set(gid, pct=round(pct, 1))
            now = time.time()
            if now - last_save[0] > 2.0:
                last_save[0] = now
                _persist(gid)
            _jp(span["a"] + (span["b"] - span["a"]) * pct / 100.0)

        def set_msg(msg: str) -> None:
            _set(gid, msg=msg)
            _persist(gid)

        try:
            _set(gid, status="running")
            _persist(gid)

            set_stage("download", "Downloading video...")
            video_path, meta = _download(url, job_dir, int(opts.get("quality", 720)),
                                         tick, hit)
            _set(gid, meta=meta)
            duration = meta["duration"]
            thumb_name = _fetch_thumbnail(meta, job_dir)
            _persist(gid)

            set_stage("transcribe", "Loading Whisper model...")
            model, device = _load_whisper(opts.get("model", "large-v3"), set_msg)
            set_msg(f"Transcribing on {device.upper()} ({opts.get('model', 'large-v3')})...")
            segments, lang = _transcribe(model, video_path, duration, tick)

            set_stage("shots", "Detecting cuts / shot boundaries...")
            shots = _detect_shots(video_path, duration, tick)
            if duration <= 0 and shots:
                duration = shots[-1]["t1"]
                meta["duration"] = duration

            set_stage("motion", f"Classifying motion in {len(shots)} shots...")
            _classify_motion(video_path, shots, tick)

            dense_step = SAMPLING.get(opts.get("sampling", "2s"), 2.0)
            set_stage("frames", "Grabbing frames...")
            tiles = _grab_tiles(video_path, shots, dense_step, tick)

            set_stage("audio", "Measuring loudness envelope...")
            loud5 = _loudness_track(video_path)
            tick(100.0)

            set_stage("report", "Building frame sheets + report + pack.pdf...")
            tt = _thumb_tile(job_dir)
            if tt:
                tiles.insert(0, tt)
            sheets = _build_sheets(tiles, job_dir, meta.get("title", gid))
            tick(40.0)
            metrics, _ = compute_metrics(meta, shots, segments, loud5, duration)
            outputs = _write_outputs(job_dir, meta, metrics, shots, segments,
                                     loud5, lang, sheets,
                                     include_words=bool(opts.get("include_words")))
            tick(60.0)
            pack = _build_pack_pdf(job_dir, meta, sheets)
            outputs.insert(0, pack)
            if thumb_name:
                outputs.append(thumb_name)
            if not opts.get("keep_video"):
                video_path.unlink(missing_ok=True)
            else:
                outputs.append(video_path.name)
            tick(95.0)

            summary = {
                "duration": metrics["duration"],
                "shots": metrics["shots"],
                "cuts_per_min": metrics["cuts_per_min"],
                "wpm_speaking": metrics["wpm_speaking"],
                "words": metrics["words"],
                "sheets": len(sheets),
                "report_kb": round((job_dir / "report.md").stat().st_size / 1024, 1),
                "pack_mb": round((job_dir / "pack.pdf").stat().st_size / 1048576, 2),
            }
            _set(gid, summary=summary, outputs=outputs, status="done",
                 pct=100.0, msg="complete")
            return {"gid": gid, "summary": summary}
        except jobs.JobCancelled:
            _set(gid, status="cancelled", msg="cancelled by user")
            raise
        except Exception as exc:  # noqa: BLE001 - surface into the record
            _set(gid, status="error", error=f"{type(exc).__name__}: {exc}",
                 msg=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            _persist(gid)
            # Keep the model warm across a pasted batch, drop it before the
            # studio's own GPU work resumes.
            if not _more_gathers_queued():
                unload_model()

    return fn


# ---------------------------------------------------------------- download

def _ffmpeg_exe() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _cookies_file() -> Optional[Path]:
    for p in (GATHER_DIR / "cookies.txt", LEGACY_DIR / "cookies.txt"):
        if p.is_file():
            return p
    return None


def _download(url: str, job_dir: Path, height_cap: int, tick, hit):
    import yt_dlp

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                tick(min(99.0, (d.get("downloaded_bytes") or 0) / total * 100.0))

    fmt = (
        f"bv*[height<={height_cap}][ext=mp4]+ba[ext=m4a]/"
        f"bv*[height<={height_cap}]+ba/"
        f"b[height<={height_cap}]/b"
    )
    opts = {
        "format": fmt,
        "outtmpl": str(job_dir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "ffmpeg_location": _ffmpeg_exe(),
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "retries": 3,
    }
    ck = _cookies_file()
    if ck:
        opts["cookiefile"] = str(ck)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception:
        # A cancel raised inside the hook comes back wrapped in DownloadError.
        if hit["cancelled"]:
            raise jobs.JobCancelled()
        raise
    if info and "entries" in info:
        info = next((e for e in info["entries"] if e), info)

    path = None
    for f in sorted(job_dir.glob("video.*")):
        if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".m4v"):
            path = f
            break
    if path is None:
        raise RuntimeError("Download finished but no video file was produced.")

    meta = {
        "title": info.get("title") or url,
        "channel": info.get("channel") or info.get("uploader") or "?",
        "upload_date": info.get("upload_date"),
        "duration": float(info.get("duration") or 0.0),
        "views": info.get("view_count"),
        "url": info.get("webpage_url") or url,
        "video_id": info.get("id"),
        # SEO / channel signals for the niche analyzer
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "categories": info.get("categories") or [],
        "likes": info.get("like_count"),
        "comments": info.get("comment_count"),
        "subs": info.get("channel_follower_count"),
        "chapters": [{"t": float(c.get("start_time") or 0), "title": c.get("title") or ""}
                     for c in (info.get("chapters") or [])],
        "thumbnail_url": info.get("thumbnail"),
    }
    return path, meta


def _fetch_thumbnail(meta, job_dir: Path):
    """Download the video's cover thumbnail as thumbnail.jpg (best effort)."""
    url = meta.get("thumbnail_url")
    if not url:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read()
        raw = job_dir / "_thumb_raw"
        raw.write_bytes(data)
        from PIL import Image
        with Image.open(raw) as im:
            im.convert("RGB").save(job_dir / "thumbnail.jpg", "JPEG", quality=88)
        raw.unlink(missing_ok=True)
        return "thumbnail.jpg"
    except Exception:  # noqa: BLE001
        return None


def _thumb_tile(job_dir: Path):
    """The YouTube cover as the first tile of sheet 1, so packaging style is visible."""
    import cv2
    p = job_dir / "thumbnail.jpg"
    if not p.exists():
        return None
    img = cv2.imread(str(p))
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = min(TILE_W / w, TILE_H / h)
    img = cv2.resize(img, (max(2, round(w * scale)), max(2, round(h * scale))),
                     interpolation=cv2.INTER_AREA)
    return {"shot": -1, "t": -1.0, "kind": "thumb", "img": img}


# ---------------------------------------------------------------- whisper

_model_cache = {"key": None, "model": None, "device": None}


def _add_cuda_dll_dirs() -> None:
    """Make cuBLAS/cuDNN visible to ctranslate2 on Windows: torch's bundled
    DLLs first (this venv ships torch cu128), pip nvidia wheels as backup."""
    if os.name != "nt":
        return
    try:
        import torch
        lib = Path(torch.__file__).resolve().parent / "lib"
        if lib.is_dir():
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    except Exception:  # noqa: BLE001
        pass
    try:
        import nvidia   # namespace package, walk __path__
        for base in nvidia.__path__:
            for p in Path(base).glob("*/bin"):
                if any(p.glob("*.dll")):
                    os.add_dll_directory(str(p))
                    os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
    except Exception:  # noqa: BLE001
        pass


def _load_whisper(model_name: str, set_msg):
    if model_name not in ALLOWED_MODELS:
        raise ValueError(f"model must be one of {ALLOWED_MODELS}")
    key = model_name
    if _model_cache["key"] == key and _model_cache["model"] is not None:
        return _model_cache["model"], _model_cache["device"]
    _model_cache.update({"key": None, "model": None, "device": None})
    gc.collect()

    from faster_whisper import WhisperModel
    WHISPER_DIR.mkdir(parents=True, exist_ok=True)

    if not any(WHISPER_DIR.glob(f"models--*{model_name}*")):
        set_msg(f"Downloading Whisper model '{model_name}' (first run only)...")

    model, device = None, "cpu"
    if shutil.which("nvidia-smi"):
        _add_cuda_dll_dirs()
        try:
            model = WhisperModel(model_name, device="cuda", compute_type="float16",
                                 download_root=str(WHISPER_DIR))
            # cuBLAS/cuDNN load lazily on first compute; warm up now so a broken
            # GPU stack falls back to CPU here instead of failing mid-job.
            list(model.transcribe(np.zeros(16000, dtype=np.float32),
                                  without_timestamps=True)[0])
            device = "cuda"
        except Exception as e:  # noqa: BLE001
            set_msg(f"GPU unavailable ({type(e).__name__}), using CPU...")
            model = None
    if model is None:
        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             download_root=str(WHISPER_DIR))
    _model_cache.update({"key": key, "model": model, "device": device})
    return model, device


def unload_model() -> bool:
    """Drop the cached Whisper model (gpu.release_all + end-of-batch hook)."""
    was = _model_cache["model"] is not None
    _model_cache.update({"key": None, "model": None, "device": None})
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return was


def status() -> Dict:
    return {"loaded": _model_cache["model"] is not None,
            "model": _model_cache["key"], "device": _model_cache["device"]}


def _transcribe(model, media_path: Path, duration: float, tick):
    """Returns (segments, lang). Each segment: {s, e, text, words:[{w,s,e}]}.

    word_timestamps=True is what gives us prosody-adjacent signal: real pause
    lengths between words, speech rate, and sentence timing.
    """
    seg_iter, info = model.transcribe(
        str(media_path),
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    segments = []
    for seg in seg_iter:
        words = [
            {"w": w.word, "s": round(float(w.start), 2), "e": round(float(w.end), 2)}
            for w in (seg.words or [])
        ]
        text = seg.text.strip()
        if text:
            segments.append({
                "s": round(float(seg.start), 2),
                "e": round(float(seg.end), 2),
                "text": text,
                "words": words,
            })
        if duration > 0:
            tick(min(99.0, float(seg.end) / duration * 100.0))
    lang = {
        "language": getattr(info, "language", "?"),
        "prob": round(float(getattr(info, "language_probability", 0.0) or 0.0), 2),
    }
    return segments, lang


# ---------------------------------------------------------------- shots

def _detect_shots(video_path: Path, duration: float, tick):
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(video_path))
    try:
        total_frames = max(1, int(video.duration.get_frames()))
    except Exception:  # noqa: BLE001
        total_frames = max(1, int(duration * 30))

    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=CUT_THRESHOLD,
                                         min_scene_len=MIN_SHOT_FRAMES))

    def cb(_img, frame_num):
        fn = frame_num.get_frames() if hasattr(frame_num, "get_frames") else int(frame_num)
        tick(min(99.0, fn / total_frames * 100.0))

    manager.detect_scenes(video, callback=cb, show_progress=False)
    try:
        scene_list = manager.get_scene_list(start_in_scene=True)
    except TypeError:
        scene_list = manager.get_scene_list()

    shots = [
        {"t0": round(s.get_seconds(), 2), "t1": round(e.get_seconds(), 2)}
        for s, e in scene_list
        if e.get_seconds() - s.get_seconds() > 0.05
    ]
    if not shots:
        shots = [{"t0": 0.0, "t1": round(max(duration, 0.1), 2)}]
    return shots


# ---------------------------------------------------------------- tiles

def _grab_tiles(video_path: Path, shots: list, dense_step, tick):
    """Grab one frame per shot start, plus in-shot frames: every `dense_step`
    seconds when dense sampling is on, else a few extras inside long shots.
    Also classifies each shot's incoming transition (cut vs fade-through-dark)."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not open the downloaded video.")

    def frame_at(t):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, fr = cap.read()
        return fr if ok else None

    tiles = []
    for i, sh in enumerate(shots):
        dur = sh["t1"] - sh["t0"]

        if i == 0:
            sh["trans"] = "start"
        else:
            boundary = frame_at(sh["t0"])
            luma = float(boundary.mean()) if boundary is not None else 255.0
            sh["trans"] = "fade" if luma < FADE_LUMA else "cut"

        # shot-start frame slightly after the cut to avoid transition blur
        times = [(sh["t0"] + min(0.5, dur * 0.25), "start")]
        if dense_step:
            t = sh["t0"] + dense_step
            while t < sh["t1"] - dense_step * 0.4:
                times.append((t, "in"))
                t += dense_step
        elif dur > LONG_SHOT_STEP * 1.2:
            n = min(MAX_EXTRA_PER_SHOT, int(dur // LONG_SHOT_STEP))
            for k in range(1, n + 1):
                times.append((sh["t0"] + dur * k / (n + 1), "in"))

        for t, kind in times:
            fr = frame_at(t)
            if fr is None:
                continue
            h, w = fr.shape[:2]
            scale = min(TILE_W / w, TILE_H / h)
            fr = cv2.resize(fr, (max(2, round(w * scale)), max(2, round(h * scale))),
                            interpolation=cv2.INTER_AREA)
            tiles.append({"shot": i, "t": t, "kind": kind, "img": fr})
        tick((i + 1) / len(shots) * 100.0)

    cap.release()

    cap_n = MAX_TILES_DENSE if dense_step else MAX_TILES
    if len(tiles) > cap_n:
        starts = [t for t in tiles if t["kind"] == "start"]
        extras = [t for t in tiles if t["kind"] != "start"]
        room = cap_n - len(starts)
        if room > 0 and extras:
            step = len(extras) / room
            extras = [extras[int(k * step)] for k in range(room)]
        elif room <= 0:
            step = len(starts) / cap_n
            starts = [starts[int(k * step)] for k in range(cap_n)]
            extras = []
        tiles = sorted(starts + extras, key=lambda x: x["t"])
    return tiles


# ---------------------------------------------------------------- motion

def _classify_motion(video_path: Path, shots: list, tick):
    """Label each shot's camera/content motion without any ML model.

    Sparse optical flow on 3 frame pairs per shot, fit a similarity transform:
      static | hand (slight movement) | zoom-in | zoom-out | pan-L | pan-R | motion
    Stored as shot["mo"]; "static" is stored but treated as the default elsewhere.
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return

    def gray_at(t):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, fr = cap.read()
        if not ok:
            return None
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        h, w = g.shape[:2]
        return cv2.resize(g, (256, max(2, round(h * 256 / w))))

    for i, sh in enumerate(shots):
        dur = sh["t1"] - sh["t0"]
        if dur < 0.45:
            tick((i + 1) / len(shots) * 100.0)
            continue
        dt = min(0.4, dur * 0.4)
        mags, scales, txs = [], [], []
        for frac in (0.2, 0.5, 0.78):
            t = sh["t0"] + dur * frac
            a = gray_at(t)
            b = gray_at(min(t + dt, sh["t1"] - 0.05))
            if a is None or b is None or a.shape != b.shape:
                continue
            p0 = cv2.goodFeaturesToTrack(a, maxCorners=200, qualityLevel=0.01,
                                         minDistance=8)
            if p0 is None or len(p0) < 8:
                continue
            p1, st, _ = cv2.calcOpticalFlowPyrLK(a, b, p0, None)
            if p1 is None:
                continue
            good = st.reshape(-1) == 1
            if good.sum() < 6:
                continue
            q0 = p0[good].reshape(-1, 2)
            q1 = p1[good].reshape(-1, 2)
            flow = q1 - q0
            mags.append(float(np.median(np.linalg.norm(flow, axis=1))))
            M, _inl = cv2.estimateAffinePartial2D(q0, q1)
            if M is not None:
                scales.append(float(np.hypot(M[0, 0], M[0, 1])))
                txs.append(float(M[0, 2]))
        if not mags:
            tick((i + 1) / len(shots) * 100.0)
            continue
        # normalize movement to a per-0.4s rate so short pairs compare fairly
        k = 0.4 / dt
        mag = float(np.median(mags)) * k
        scale = (float(np.mean(scales)) - 1.0) * k + 1.0 if scales else 1.0
        tx = float(np.mean(txs)) * k if txs else 0.0
        same_dir = len(txs) == 1 or all(x > 0 for x in txs) or all(x < 0 for x in txs)

        if mag < 0.35:
            mo = "static"
        elif scale > 1.012:
            mo = "zoom-in"
        elif scale < 0.988:
            mo = "zoom-out"
        elif abs(tx) > 1.4 and same_dir:
            mo = "pan-R" if tx > 0 else "pan-L"
        elif mag > 3.0:
            mo = "motion"
        else:
            mo = "hand"
        sh["mo"] = mo
        tick((i + 1) / len(shots) * 100.0)
    cap.release()


def fmt_t(s: float) -> str:
    s = max(0.0, float(s))
    h = int(s // 3600)
    m = int(s % 3600 // 60)
    sec = s - h * 3600 - m * 60
    if h:
        return f"{h}:{m:02d}:{sec:04.1f}"
    return f"{m}:{sec:04.1f}"


def _load_font(size: int):
    from PIL import ImageFont
    for name in ("consola.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _build_sheets(tiles: list, job_dir: Path, title: str):
    import cv2
    from PIL import Image, ImageDraw

    if not tiles:
        return []
    font = _load_font(13)
    hfont = _load_font(15)
    pad, header_h, label_h = 2, 26, 18
    per_sheet = SHEET_COLS * SHEET_ROWS
    n_sheets = math.ceil(len(tiles) / per_sheet)
    names = []

    for si in range(n_sheets):
        chunk = tiles[si * per_sheet:(si + 1) * per_sheet]
        rows = math.ceil(len(chunk) / SHEET_COLS)
        cols = min(len(chunk), SHEET_COLS)
        W = cols * (TILE_W + pad) + pad
        H = header_h + rows * (TILE_H + pad) + pad
        sheet = Image.new("RGB", (W, H), (12, 12, 14))
        draw = ImageDraw.Draw(sheet)
        draw.text((6, 5), f"{title[:80]}  -  sheet {si + 1}/{n_sheets}  -  tile label = shot id @ time",
                  fill=(225, 225, 225), font=hfont)

        for j, t in enumerate(chunk):
            r, c = divmod(j, SHEET_COLS)
            x = pad + c * (TILE_W + pad)
            y = header_h + pad + r * (TILE_H + pad)
            img = Image.fromarray(cv2.cvtColor(t["img"], cv2.COLOR_BGR2RGB))
            ox = x + (TILE_W - img.width) // 2
            oy = y + (TILE_H - img.height) // 2
            sheet.paste(img, (ox, oy))
            if t.get("kind") == "thumb":
                label, color = "THUMB (video cover)", (130, 215, 255)
            elif t.get("kind") == "start":
                label, color = f"S{t['shot'] + 1:03d} {fmt_t(t['t'])}", (255, 235, 90)
            else:
                label, color = f"S{t['shot'] + 1:03d}| {fmt_t(t['t'])}", (210, 210, 210)
            draw.rectangle([x, y + TILE_H - label_h, x + TILE_W, y + TILE_H], fill=(0, 0, 0))
            draw.text((x + 4, y + TILE_H - label_h + 2), label, fill=color, font=font)

        name = f"sheet_{si + 1:02d}.jpg"
        sheet.save(job_dir / name, "JPEG", quality=82, optimize=True)
        names.append(name)
    return names


# ---------------------------------------------------------------- loudness

def _loudness_track(video_path: Path):
    """Relative loudness 0-9 per 5s window. Cheap stand-in for sound design:
    shows music swells, quiet beats, and overall dynamics without any ML."""
    wav = video_path.parent / "_audio_tmp.wav"
    try:
        subprocess.run(
            [_ffmpeg_exe(), "-y", "-v", "error", "-i", str(video_path),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
            check=True, capture_output=True)
        with wave.open(str(wav), "rb") as w:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        data = data.astype(np.float32) / 32768.0
        win = 5 * 16000
        digits = []
        for i in range(0, len(data), win):
            chunk = data[i:i + win]
            rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
            db = 20.0 * math.log10(rms + 1e-9)
            digits.append(int(np.clip(round((db + 50.0) / 5.0), 0, 9)))
        return digits
    except Exception:  # noqa: BLE001
        return []
    finally:
        wav.unlink(missing_ok=True)


# ---------------------------------------------------------------- reporting

def _flat_words(segments):
    return [w for s in segments for w in s["words"]]


def _pauses(words):
    """Gaps >= PAUSE_MIN between consecutive words (includes VAD-silence gaps)."""
    out = []
    for a, b in zip(words, words[1:]):
        gap = b["s"] - a["e"]
        if gap >= PAUSE_MIN:
            out.append({"t": a["e"], "d": round(gap, 2)})
    return out


def _sentence_ends(words):
    return [w["e"] for w in words if w["w"].strip().rstrip("\"')").endswith(SENT_END)]


def compute_metrics(meta, shots, segments, loud5, duration):
    words = _flat_words(segments)
    pauses = _pauses(words)
    sent_ends = _sentence_ends(words)
    cuts = [sh["t0"] for sh in shots[1:]]
    durs = sorted(sh["t1"] - sh["t0"] for sh in shots)
    n = len(durs)

    speech_time = sum(s["e"] - s["s"] for s in segments)
    minutes = max(1, int(duration // 60) + (1 if duration % 60 > 1 else 0))

    cpm_line = [0] * minutes
    for c in cuts:
        cpm_line[min(minutes - 1, int(c // 60))] += 1
    wpm_line = [0] * minutes
    for w in words:
        wpm_line[min(minutes - 1, int(((w["s"] + w["e"]) / 2) // 60))] += 1

    # gap intervals in the speech stream (for "cut lands in a pause" alignment)
    gaps = []
    if words:
        if words[0]["s"] > 0.3:
            gaps.append((0.0, words[0]["s"]))
        for a, b in zip(words, words[1:]):
            if b["s"] - a["e"] >= 0.3:
                gaps.append((a["e"], b["s"]))
        if duration - words[-1]["e"] > 0.3:
            gaps.append((words[-1]["e"], duration))
    else:
        gaps.append((0.0, duration))

    def cut_in_pause(c):
        return any(g0 - 0.15 <= c <= g1 + 0.15 for g0, g1 in gaps)

    def cut_on_sentence(c):
        return any(se - 0.2 <= c <= se + 0.6 for se in sent_ends)

    aligned_pause = sum(1 for c in cuts if cut_in_pause(c))
    aligned_sent = sum(1 for c in cuts if cut_on_sentence(c))
    fades = sum(1 for sh in shots if sh.get("trans") == "fade")

    longest_shot = max(shots, key=lambda s: s["t1"] - s["t0"])
    longest_pause = max(pauses, key=lambda p: p["d"], default=None)

    first15_cuts = sum(1 for c in cuts if c <= 15.0)
    first15_words = sum(1 for w in words if w["s"] <= 15.0)

    motion = {}
    for sh in shots:
        mo = sh.get("mo")
        if mo:
            motion[mo] = motion.get(mo, 0) + 1

    m = {
        "duration": round(duration, 1),
        "shots": len(shots),
        "cuts_per_min": round(len(cuts) / (duration / 60), 1) if duration else 0,
        "avg_shot": round(sum(durs) / n, 2) if n else 0,
        "median_shot": round(durs[n // 2], 2) if n else 0,
        "longest_shot": round(longest_shot["t1"] - longest_shot["t0"], 1),
        "longest_shot_at": round(longest_shot["t0"], 1),
        "fast_cut_share": round(100 * sum(1 for d in durs if d < 1.0) / n) if n else 0,
        "fades": fades,
        "speech_share": round(100 * speech_time / duration) if duration else 0,
        "words": len(words),
        "wpm_speaking": round(len(words) / (speech_time / 60)) if speech_time > 1 else 0,
        "wpm_overall": round(len(words) / (duration / 60)) if duration > 1 else 0,
        "pauses": len(pauses),
        "avg_pause": round(sum(p["d"] for p in pauses) / len(pauses), 2) if pauses else 0,
        "longest_pause": longest_pause["d"] if longest_pause else 0,
        "longest_pause_at": round(longest_pause["t"], 1) if longest_pause else 0,
        "cuts_on_sentence_pct": round(100 * aligned_sent / len(cuts)) if cuts else 0,
        "cuts_in_pause_pct": round(100 * aligned_pause / len(cuts)) if cuts else 0,
        "first15s": {"cuts": first15_cuts, "words": first15_words},
        "motion": motion,
        "cpm_per_min": cpm_line,
        "wpm_per_min": wpm_line,
    }
    return m, pauses


def _shot_texts(shots, segments):
    """Assign each word to the shot containing its midpoint; insert pause markers."""
    words = _flat_words(segments)
    texts = [[] for _ in shots]
    wi = 0
    for si, sh in enumerate(shots):
        parts, prev_end = [], None
        while wi < len(words):
            w = words[wi]
            mid = (w["s"] + w["e"]) / 2
            if mid >= sh["t1"] and si < len(shots) - 1:
                break
            if prev_end is not None and w["s"] - prev_end >= PAUSE_MIN:
                parts.append(f" (…{w['s'] - prev_end:.1f}s)")
            parts.append(w["w"])
            prev_end = w["e"]
            wi += 1
        texts[si] = "".join(parts).strip()
    return texts


def build_report_md(meta, metrics, shots, segments, loud5, lang, sheets):
    L = []
    L.append("# VIDEO EVIDENCE PACK v1")
    L.append("LEGEND: Sxxx = shot (start time, +duration). Every new shot = hard cut unless marked ~fade.")
    L.append("A shot header may end with its camera/content motion: zoom-in, zoom-out, pan-L/R (image drift")
    L.append("direction), hand (slight shake), motion (busy action/b-roll); no label = static camera.")
    L.append('Text under a shot = words spoken during it; "·" = no speech. (…1.2s) = spoken pause of 1.2s.')
    L.append("Frame sheets: label Sxxx t = first frame of shot Sxxx; Sxxx| t = later frame inside the same")
    L.append("shot (dense time sampling, NOT a new cut). THUMB = the video's YouTube cover thumbnail.")
    L.append("LOUD = relative loudness 0(silent)-9(max) per 5s, | = minute mark. CPM = cuts/min, WPM = words/min.")
    L.append("")
    L.append("## META")
    up = meta.get("upload_date") or "?"
    if len(str(up)) == 8:
        up = f"{up[:4]}-{up[4:6]}-{up[6:]}"
    views = meta.get("views")
    views_s = f"{views:,}" if isinstance(views, int) else "?"
    L.append(f"Title: {meta.get('title', '?')}")
    L.append(f"Channel: {meta.get('channel', '?')} | Uploaded: {up} | Views: {views_s}")
    L.append(f"Duration: {fmt_t(metrics['duration'])} | Language: {lang.get('language', '?')} "
             f"({lang.get('prob', 0)}) | URL: {meta.get('url', '?')}")
    L.append(f"Sheets: {len(sheets)} image(s), {metrics['shots']} shots total")
    L.append("")
    L.append("## SEO & CHANNEL SIGNALS")
    cats = ", ".join(meta.get("categories") or []) or "?"
    tags = meta.get("tags") or []
    if tags:
        tag_s = ", ".join(tags[:25]) + (f" (+{len(tags) - 25} more)" if len(tags) > 25 else "")
    else:
        tag_s = "none"
    L.append(f"Category: {cats} | Tags({len(tags)}): {tag_s}")
    views = meta.get("views")
    eng = []
    if isinstance(meta.get("likes"), int):
        s = f"{meta['likes']:,} likes"
        if views:
            s += f" ({100 * meta['likes'] / views:.2f}% of views)"
        eng.append(s)
    if isinstance(meta.get("comments"), int):
        s = f"{meta['comments']:,} comments"
        if views:
            s += f" ({100 * meta['comments'] / views:.2f}%)"
        eng.append(s)
    if views and meta.get("upload_date"):
        try:
            days = max(1, (date.today() - datetime.strptime(str(meta["upload_date"]),
                                                            "%Y%m%d").date()).days)
            eng.append(f"~{round(views / days):,} views/day over {days:,} days")
        except Exception:  # noqa: BLE001
            pass
    subs = meta.get("subs")
    if views and isinstance(subs, int) and subs > 0:
        eng.append(f"views = {views / subs:.1f}x subscribers ({subs:,} subs)")
    L.append("Engagement: " + (" | ".join(eng) if eng else "?"))
    if meta.get("thumbnail_url"):
        L.append("Thumbnail: first tile of sheet 1 (label THUMB); analyze its composition/text.")
    chapters = meta.get("chapters") or []
    if chapters:
        L.append("Chapters: " + " | ".join(f"{fmt_t(c['t'])} {c['title']}"
                                           for c in chapters[:24]))
    desc = (meta.get("description") or "").strip()
    if desc:
        clean = re.sub(r"\n{2,}", "\n", desc)
        n_links = len(re.findall(r"https?://", clean))
        n_hash = len(re.findall(r"#\w+", clean))
        L.append(f"Description ({len(clean)} chars, {n_links} links, {n_hash} hashtags):")
        shown = clean[:400]
        for dl in shown.splitlines():
            for wl in (textwrap.wrap(dl, WRAP_WIDTH) or [""]):
                L.append("  " + wl)
        if len(clean) > 400:
            L.append(f"  (… +{len(clean) - 400} more chars not shown)")
    L.append("")
    L.append("## METRICS")
    m = metrics
    L.append(f"Shots {m['shots']} | Cuts/min {m['cuts_per_min']} | Avg shot {m['avg_shot']}s | "
             f"Median {m['median_shot']}s | Longest {m['longest_shot']}s @ {fmt_t(m['longest_shot_at'])} | "
             f"Shots<1s: {m['fast_cut_share']}% | Fades: {m['fades']}")
    L.append(f"Speech {m['speech_share']}% of runtime | {m['words']} words | "
             f"{m['wpm_speaking']} wpm speaking ({m['wpm_overall']} overall) | "
             f"Pauses>={PAUSE_MIN}s: {m['pauses']} (avg {m['avg_pause']}s, "
             f"max {m['longest_pause']}s @ {fmt_t(m['longest_pause_at'])})")
    L.append(f"Cuts on sentence end: {m['cuts_on_sentence_pct']}% | Cuts inside speech pause: {m['cuts_in_pause_pct']}%")
    if m.get("motion"):
        parts = [f"{k} {v}" for k, v in sorted(m["motion"].items(), key=lambda x: -x[1])]
        L.append("Motion (shots): " + ", ".join(parts))
    L.append(f"First 15s (hook): {m['first15s']['cuts']} cuts, {m['first15s']['words']} words")
    L.append("CPM/min: " + ",".join(str(x) for x in m["cpm_per_min"]))
    L.append("WPM/min: " + ",".join(str(x) for x in m["wpm_per_min"]))
    if loud5:
        groups = ["".join(str(d) for d in loud5[i:i + 12]) for i in range(0, len(loud5), 12)]
        track = "|".join(groups)
        L.append("LOUD/5s: " + "\n         ".join(textwrap.wrap(track, 78)))
    L.append("")
    L.append("## TIMELINE")
    texts = _shot_texts(shots, segments)
    for i, sh in enumerate(shots):
        dur = sh["t1"] - sh["t0"]
        head = f"S{i + 1:03d} {fmt_t(sh['t0'])} +{dur:.1f}s"
        if sh.get("trans") == "fade":
            head += " ~fade"
        mo = sh.get("mo")
        if mo and mo != "static":
            head += " " + mo
        L.append(head)
        body = texts[i] if i < len(texts) else ""
        if body:
            for line in textwrap.wrap(body, WRAP_WIDTH):
                L.append("  " + line)
        else:
            L.append("  ·")
    L.append("")
    return "\n".join(L)


def build_report_json(meta, metrics, shots, segments, loud5, lang, sheets, include_words):
    data = {
        "version": 1,
        "meta": meta,
        "language": lang,
        "metrics": metrics,
        "shots": [[sh["t0"], sh["t1"], sh.get("trans", "cut"), sh.get("mo", "?")]
                  for sh in shots],
        "segments": [{"s": s["s"], "e": s["e"], "text": s["text"]} for s in segments],
        "loud5s": loud5,
        "sheets": sheets,
    }
    if include_words:
        data["words"] = [[w["w"], w["s"], w["e"]] for s in segments for w in s["words"]]
    return data


def _write_outputs(job_dir: Path, meta, metrics, shots, segments, loud5, lang, sheets,
                   include_words=False):
    md = build_report_md(meta, metrics, shots, segments, loud5, lang, sheets)
    (job_dir / "report.md").write_text(md, encoding="utf-8")
    data = build_report_json(meta, metrics, shots, segments, loud5, lang, sheets,
                             include_words)
    (job_dir / "report.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return ["report.md", "report.json"] + sheets


def _build_pack_pdf(job_dir: Path, meta, sheets):
    """One self-contained file: report text (real, extractable text) followed by
    every frame sheet as a full page. This is the artifact to hand to an AI.
    Claude reads PDF text exactly and sees each page as an image."""
    from fpdf import FPDF
    from PIL import Image

    md = (job_dir / "report.md").read_text(encoding="utf-8")
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_title(f"Evidence pack - {str(meta.get('title', ''))[:100]}")
    pdf.set_auto_page_break(True, margin=10)

    mono = Path("C:/Windows/Fonts/consola.ttf")
    mono_b = Path("C:/Windows/Fonts/consolab.ttf")
    if mono.exists():
        pdf.add_font("mono", "", str(mono))
        pdf.add_font("mono", "B", str(mono_b if mono_b.exists() else mono))
        family = "mono"
    else:
        family = "helvetica"
        md = md.replace("…", "...").replace("·", ".")

    pdf.add_page()
    pdf.set_font(family, "", 7.6)
    for line in md.splitlines():
        if line.startswith("# "):
            pdf.set_font(family, "B", 11)
            pdf.multi_cell(0, 5.2, line[2:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(family, "", 7.6)
        elif line.startswith("## "):
            pdf.ln(1.2)
            pdf.set_font(family, "B", 9)
            pdf.multi_cell(0, 4.4, line[3:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(family, "", 7.6)
        else:
            pdf.multi_cell(0, 3.3, line if line.strip() else " ", new_x="LMARGIN", new_y="NEXT")

    mm_per_px = 287.0 / (6 * 322 + 2)   # full-width 6-column sheet spans the page
    for name in sheets:
        p = job_dir / name
        if not p.exists():
            continue
        with Image.open(p) as im:
            w_px, _ = im.size
        pdf.add_page(orientation="L")
        pdf.image(str(p), x=5, y=6, w=min(287.0, w_px * mm_per_px))

    out = job_dir / "pack.pdf"
    pdf.output(str(out))
    return out.name
