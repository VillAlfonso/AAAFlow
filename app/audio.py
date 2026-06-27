"""Audio post-processing: stitch chunk waveforms, normalize loudness, export.

Stitching is done in numpy (precise gaps, light silence trimming); loudness
normalization and MP3 encoding are handed to ffmpeg. The result is a single
YouTube-ready file with consistent loudness.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List

import numpy as np
import soundfile as sf

from . import config


def _run(args: List[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-800:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{tail}")


def ffmpeg_ok() -> bool:
    try:
        subprocess.run([config.FFMPEG, "-version"], capture_output=True, text=True)
        return True
    except (OSError, FileNotFoundError):
        return False


def _silence(ms: int, sr: int) -> np.ndarray:
    return np.zeros(max(0, int(sr * ms / 1000)), dtype=np.float32)


def trim_silence(wav: np.ndarray, sr: int, thresh_db: float = -42.0,
                 pad_ms: int = 40) -> np.ndarray:
    if wav.size == 0:
        return wav
    thresh = 10.0 ** (thresh_db / 20.0)
    above = np.where(np.abs(wav) > thresh)[0]
    if above.size == 0:
        return wav
    pad = int(sr * pad_ms / 1000)
    start = max(0, int(above[0]) - pad)
    end = min(wav.size, int(above[-1]) + pad)
    return wav[start:end]


def stitch(segments: List[Dict], sr: int, gap_ms: int, paragraph_gap_ms: int,
           do_trim: bool) -> np.ndarray:
    """Concatenate segment waveforms with sentence/paragraph gaps.

    Each segment: {"wav": np.ndarray, "paragraph": int}.
    """
    out: List[np.ndarray] = []
    prev_para = None
    for i, seg in enumerate(segments):
        wav = np.asarray(seg["wav"], dtype=np.float32).reshape(-1)
        if do_trim:
            wav = trim_silence(wav, sr)
        if i > 0:
            gap = paragraph_gap_ms if seg.get("paragraph") != prev_para else gap_ms
            out.append(_silence(gap, sr))
        out.append(wav)
        prev_para = seg.get("paragraph")
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out)


def export(stitched: np.ndarray, sr: int, basename: str, *, loudnorm: bool,
           loudnorm_i: float, fmt: str) -> Dict:
    """Write stitched audio to disk in the requested format(s).

    Returns {"files": {"mp3": name, "wav": name}, "duration": seconds}.
    """
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.OUTPUTS_DIR / f"{basename}.src.wav"

    peak = float(np.max(np.abs(stitched))) if stitched.size else 0.0
    if peak > 1.0:
        stitched = stitched / peak
    sf.write(str(tmp), stitched, sr, subtype="PCM_16")

    af = f"loudnorm=I={loudnorm_i}:TP=-1.5:LRA=11" if loudnorm else None
    targets = []
    if fmt in ("wav", "both"):
        targets.append(("wav", config.OUTPUTS_DIR / f"{basename}.wav"))
    if fmt in ("mp3", "both") or not targets:
        targets.append(("mp3", config.OUTPUTS_DIR / f"{basename}.mp3"))

    files: Dict[str, str] = {}
    for kind, path in targets:
        try:
            args = [config.FFMPEG, "-y", "-i", str(tmp)]
            if af:
                args += ["-af", af]
            if kind == "mp3":
                args += ["-c:a", "libmp3lame", "-q:a", "2"]
            else:
                args += ["-c:a", "pcm_s16le", "-ar", str(sr)]
            args += [str(path)]
            _run(args)
            files[kind] = path.name
        except Exception:
            # Fallback: if ffmpeg is unavailable, at least deliver a raw WAV.
            if kind == "wav":
                fallback = config.OUTPUTS_DIR / f"{basename}.wav"
                sf.write(str(fallback), stitched, sr, subtype="PCM_16")
                files["wav"] = fallback.name
    try:
        tmp.unlink()
    except OSError:
        pass

    duration = float(len(stitched) / sr) if sr else 0.0
    return {"files": files, "duration": duration}


def prepare_reference(src: str, dst: str, max_seconds: int = 60) -> None:
    """Convert an uploaded clone sample to mono 24kHz WAV, capped in length."""
    _run([config.FFMPEG, "-y", "-i", str(src), "-ac", "1", "-ar", "24000",
          "-t", str(max_seconds), str(dst)])


def save_wav(wav: np.ndarray, sr: int, path: str) -> None:
    sf.write(str(path), np.asarray(wav, dtype=np.float32).reshape(-1), sr,
             subtype="PCM_16")


def read_wav(path: str):
    wav, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if wav.ndim > 1:
        wav = np.mean(wav, axis=-1).astype(np.float32)
    return wav, int(sr)
