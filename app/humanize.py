"""Audio "humanizer" — strips the digital fingerprints that AI-voice detectors
look for, while keeping the narration clean.

Pipeline (each step optional / configurable):
  1. Tempo jitter   — resample random sections by tiny amounts so the pacing is
                      no longer mathematically uniform (numpy).
  2. Tone EQ        — roll off ultra-crisp highs, add low-mid vocal warmth.
  3. Tube saturation— gentle tanh soft-clip = analog harmonic grit.
  4. Wow & flutter  — slow micro pitch drift, like tape.
  5. Ambiance bed   — quiet room tone so the gaps are never true digital silence.
  6. Downsample+MP3 — 32 kHz / 128 kbps blends the frequency profile.

Everything runs through ffmpeg except the tempo jitter (numpy). Defaults are
deliberately gentle — Qwen already sounds human, so this only removes the tells.
"""
from __future__ import annotations

import copy
import random
import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np
import soundfile as sf

from . import config

ProgressFn = Callable[[str, float], None]

AMB_DIR = config.DATA_DIR / "ambiance"
AMB_DIR.mkdir(parents=True, exist_ok=True)

WORK_SR = 24000  # internal working sample rate (Qwen native)

# Full default parameter set — process() always has every key available.
DEFAULTS: Dict = {
    "tempo_jitter": {"enabled": True, "amount": 1.2, "segments": 6},
    "eq": {"enabled": True, "high_freq": 10000, "high_gain": -4.0, "warmth_gain": 1.5},
    "saturation": {"enabled": True, "amount": 10},
    "wow": {"enabled": True, "amount": 18},
    "ambiance": {"enabled": True, "type": "room", "level_db": -32, "file": None},
    "output": {"sample_rate": 32000, "bitrate": 128},
}

PRESETS: Dict[str, Dict] = {
    "minimal": {
        "tempo_jitter": {"enabled": False, "amount": 0.8, "segments": 4},
        "eq": {"enabled": True, "high_freq": 11000, "high_gain": -3.0, "warmth_gain": 1.0},
        "saturation": {"enabled": True, "amount": 6},
        "wow": {"enabled": False, "amount": 10},
        "ambiance": {"enabled": True, "type": "room", "level_db": -36, "file": None},
        "output": {"sample_rate": 32000, "bitrate": 128},
    },
    "balanced": {
        "tempo_jitter": {"enabled": True, "amount": 1.2, "segments": 6},
        "eq": {"enabled": True, "high_freq": 10000, "high_gain": -4.0, "warmth_gain": 1.5},
        "saturation": {"enabled": True, "amount": 10},
        "wow": {"enabled": True, "amount": 18},
        "ambiance": {"enabled": True, "type": "room", "level_db": -32, "file": None},
        "output": {"sample_rate": 32000, "bitrate": 128},
    },
    "heavy": {
        "tempo_jitter": {"enabled": True, "amount": 2.0, "segments": 9},
        "eq": {"enabled": True, "high_freq": 9000, "high_gain": -5.0, "warmth_gain": 2.0},
        "saturation": {"enabled": True, "amount": 16},
        "wow": {"enabled": True, "amount": 30},
        "ambiance": {"enabled": True, "type": "rain", "level_db": -28, "file": None},
        "output": {"sample_rate": 32000, "bitrate": 128},
    },
}

AMBIANCE_TYPES = ["room", "air", "rain", "vinyl"]

# Synthesized ambiance beds (ffmpeg source + shaping; volume/seed appended later)
_AMB_SYNTH = {
    "room": "anoisesrc=color=brown:a=1:r={sr}:seed={seed},lowpass=f=600",
    "air": "anoisesrc=color=pink:a=1:r={sr}:seed={seed},highpass=f=1800,lowpass=f=9000",
    "rain": "anoisesrc=color=pink:a=1:r={sr}:seed={seed},highpass=f=600,lowpass=f=7000",
    "vinyl": "anoisesrc=color=brown:a=1:r={sr}:seed={seed},lowpass=f=3500",
}


def _run(args) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{(proc.stderr or '')[-900:]}")


def _deep_merge(base: Dict, patch: Optional[Dict]) -> Dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def resolve_params(params: Optional[Dict]) -> Dict:
    """Merge DEFAULTS <- preset (if named) <- explicit params; clamp to safe ranges."""
    params = params or {}
    merged = copy.deepcopy(DEFAULTS)
    preset = params.get("preset")
    if preset in PRESETS:
        merged = _deep_merge(merged, PRESETS[preset])
    merged = _deep_merge(merged, {k: v for k, v in params.items() if k != "preset"})

    eq = merged["eq"]
    eq["high_freq"] = _clamp(eq["high_freq"], 5000, 16000)
    eq["high_gain"] = _clamp(eq["high_gain"], -10, 0)
    eq["warmth_gain"] = _clamp(eq["warmth_gain"], 0, 6)
    merged["saturation"]["amount"] = _clamp(merged["saturation"]["amount"], 0, 50)
    merged["wow"]["amount"] = _clamp(merged["wow"]["amount"], 0, 80)
    merged["tempo_jitter"]["amount"] = _clamp(merged["tempo_jitter"]["amount"], 0, 4)
    merged["tempo_jitter"]["segments"] = int(_clamp(merged["tempo_jitter"]["segments"], 2, 20))
    merged["ambiance"]["level_db"] = _clamp(merged["ambiance"]["level_db"], -50, -12)
    if merged["ambiance"].get("type") not in AMBIANCE_TYPES:
        if not merged["ambiance"].get("file"):
            merged["ambiance"]["type"] = "room"
    merged["output"]["sample_rate"] = int(merged["output"].get("sample_rate", 32000))
    merged["output"]["bitrate"] = int(merged["output"].get("bitrate", 128))
    return merged


def _apply_tempo_jitter(y: np.ndarray, segments: int, amount_pct: float) -> np.ndarray:
    """Resample contiguous sections by tiny random factors (breaks AI's uniform
    rhythm). A ±1% resample shifts pitch imperceptibly but timing measurably."""
    n = len(y)
    if n < WORK_SR // 2 or amount_pct <= 0:
        return y
    # don't make segments shorter than ~250 ms
    segments = max(2, min(segments, n // (WORK_SR // 4)))
    bounds = np.linspace(0, n, segments + 1).astype(int)
    out = []
    for i in range(segments):
        seg = y[bounds[i]:bounds[i + 1]]
        if len(seg) < 8:
            out.append(seg)
            continue
        factor = 1.0 + random.uniform(-amount_pct, amount_pct) / 100.0
        m = max(4, int(round(len(seg) / factor)))
        idx = np.linspace(0, len(seg) - 1, m)
        out.append(np.interp(idx, np.arange(len(seg)), seg).astype(np.float32))
    return np.concatenate(out)


def _voice_chain(p: Dict) -> str:
    chain = []
    eq = p["eq"]
    if eq["enabled"]:
        if eq["warmth_gain"]:
            chain.append(f"equalizer=f=350:t=q:w=1.2:g={eq['warmth_gain']:.2f}")
        if eq["high_gain"]:
            chain.append(f"treble=g={eq['high_gain']:.2f}:f={int(eq['high_freq'])}")
    sat = p["saturation"]
    if sat["enabled"] and sat["amount"] > 0:
        drive = sat["amount"] / 100.0 * 9.0          # up to ~9 dB pre-gain
        chain.append(f"volume={drive:.2f}dB")
        chain.append("asoftclip=type=tanh")
        chain.append(f"volume={-drive * 0.7:.2f}dB")  # partial makeup -> net subtle
    wow = p["wow"]
    if wow["enabled"] and wow["amount"] > 0:
        depth = min(0.5, wow["amount"] / 100.0 * 0.15)
        chain.append(f"vibrato=f=3:d={depth:.3f}")
    return ",".join(chain) if chain else "anull"


def process(src_path: str, params: Optional[Dict], basename: str,
            progress: Optional[ProgressFn] = None) -> Dict:
    p = resolve_params(params)
    out_dir = config.OUTPUTS_DIR
    work = out_dir / f"{basename}.work.wav"
    out_mp3 = out_dir / f"{basename}.mp3"

    def prog(stage, frac):
        if progress:
            progress(stage, frac)

    # 1) decode source -> mono working wav
    prog("Decoding source", 0.08)
    _run([config.FFMPEG, "-y", "-i", str(src_path), "-ac", "1", "-ar",
          str(WORK_SR), "-c:a", "pcm_s16le", str(work)])

    # 2) tempo jitter (numpy)
    y, sr = sf.read(str(work), dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = np.mean(y, axis=-1).astype(np.float32)
    if p["tempo_jitter"]["enabled"]:
        prog("Breaking AI pacing", 0.25)
        y = _apply_tempo_jitter(y, int(p["tempo_jitter"]["segments"]),
                                float(p["tempo_jitter"]["amount"]))
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 1.0:
        y = y / peak
    sf.write(str(work), y, sr, subtype="PCM_16")
    duration = float(len(y) / sr) if sr else 0.0

    # 3) ffmpeg chain: EQ / saturation / wow + ambiance + downsample/encode
    prog("Applying analog character", 0.5)
    voice = _voice_chain(p)
    amb = p["ambiance"]
    out_args = ["-ar", str(p["output"]["sample_rate"]), "-c:a", "libmp3lame",
                "-b:a", f"{p['output']['bitrate']}k"]

    if amb["enabled"] and amb.get("file"):
        amb_path = AMB_DIR / amb["file"]
        if not amb_path.exists():
            amb_path = None
        if amb_path:
            fc = (f"[0:a]{voice}[v];"
                  f"[1:a]aresample={WORK_SR},volume={amb['level_db']:.1f}dB[amb];"
                  f"[v][amb]amix=inputs=2:duration=first:normalize=0[out]")
            _run([config.FFMPEG, "-y", "-i", str(work), "-stream_loop", "-1",
                  "-i", str(amb_path), "-filter_complex", fc, "-map", "[out]",
                  *out_args, str(out_mp3)])
        else:
            amb = {**amb, "file": None, "enabled": True}

    if not (amb["enabled"] and amb.get("file")):
        if amb["enabled"]:
            seed = random.randint(0, 2_000_000)
            synth = _AMB_SYNTH.get(amb.get("type") or "room",
                                   _AMB_SYNTH["room"]).format(sr=WORK_SR, seed=seed)
            fc = (f"[0:a]{voice}[v];"
                  f"{synth},volume={amb['level_db']:.1f}dB[amb];"
                  f"[v][amb]amix=inputs=2:duration=first:normalize=0[out]")
            _run([config.FFMPEG, "-y", "-i", str(work), "-filter_complex", fc,
                  "-map", "[out]", *out_args, str(out_mp3)])
        else:
            _run([config.FFMPEG, "-y", "-i", str(work), "-af", voice,
                  *out_args, str(out_mp3)])

    prog("Finishing", 0.95)
    try:
        work.unlink()
    except OSError:
        pass
    return {"files": {"mp3": out_mp3.name}, "duration": duration, "params": p}
