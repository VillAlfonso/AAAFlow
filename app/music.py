"""Background music + sound-effect generation via the ACE-Step sidecar.

Generates an instrumental clip from a text prompt (DiT-only), saves it to a
reusable library under ``data/music/``, and records it in history. Long-running,
so it runs as a background job; the 4B XL model downloads (~9 GB) on first use.
"""
from __future__ import annotations

import subprocess
import time
from typing import Callable, Dict

from . import audio, config, jobs, storage
from .music_engine import music_engine

ProgressFn = Callable[[str, float], None]

# Ready-made prompts so the feature is approachable (music beds + a few SFX).
MUSIC_PRESETS = [
    {"name": "Calm documentary bed", "kind": "music", "seconds": 40,
     "prompt": "calm cinematic ambient underscore, soft warm pads, gentle piano, "
               "slow evolving, minimal, unobtrusive documentary background bed, instrumental"},
    {"name": "Suspense / tension", "kind": "music", "seconds": 40,
     "prompt": "dark suspenseful ambient drone, low pulsing bass, tense strings, "
               "ominous slow build, eerie cinematic underscore, instrumental"},
    {"name": "Upbeat explainer", "kind": "music", "seconds": 40,
     "prompt": "light upbeat corporate background music, soft plucks, gentle beat, "
               "optimistic, clean, modern, unobtrusive, instrumental"},
    {"name": "Lo-fi chill", "kind": "music", "seconds": 40,
     "prompt": "lo-fi hip hop chill beat, mellow keys, soft vinyl crackle, relaxed, "
               "warm, looping background, instrumental"},
    {"name": "Emotional piano", "kind": "music", "seconds": 40,
     "prompt": "emotional solo piano, slow, reflective, melancholic, sparse, "
               "intimate, cinematic, instrumental"},
    {"name": "Whoosh transition", "kind": "sfx", "seconds": 3,
     "prompt": "a single quick cinematic whoosh transition sound effect, airy swish"},
    {"name": "Soft impact", "kind": "sfx", "seconds": 3,
     "prompt": "a soft deep cinematic impact hit, low boom, short"},
]


def _save_clip(wav_bytes: bytes, base: str) -> Dict:
    config.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    wav_path = config.MUSIC_DIR / f"{base}.wav"
    wav_path.write_bytes(wav_bytes)
    files = {"wav": wav_path.name}
    mp3_path = config.MUSIC_DIR / f"{base}.mp3"
    try:
        subprocess.run([config.FFMPEG, "-y", "-i", str(wav_path),
                        "-c:a", "libmp3lame", "-q:a", "3", str(mp3_path)],
                       capture_output=True, text=True, check=True)
        files["mp3"] = mp3_path.name
    except Exception:  # noqa: BLE001 - ffmpeg optional; wav is enough
        pass
    try:
        w, sr = audio.read_wav(str(wav_path))
        dur = float(len(w) / sr) if sr else 0.0
    except Exception:  # noqa: BLE001
        dur = 0.0
    return {"files": files, "duration": round(dur, 2)}


def submit_music(req: Dict) -> str:
    prompt = (req.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Describe the music or sound you want.")
    if not music_engine.available():
        raise ValueError("ACE-Step music engine isn't installed yet.")
    kind = "sfx" if req.get("kind") == "sfx" else "music"
    seconds = float(req.get("seconds") or (3.0 if kind == "sfx" else 30.0))
    seconds = max(2.0, min(seconds, 240.0))
    seed = int(req.get("seed", -1))
    steps = int(req.get("steps") or 8)
    instrumental = bool(req.get("instrumental", True))

    def task(progress: ProgressFn) -> Dict:
        wav = music_engine.generate(prompt, seconds=seconds, seed=seed, steps=steps,
                                    instrumental=instrumental, progress=progress)
        progress("Saving clip…", 0.96)
        base = f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{storage.new_id()[:6]}"
        saved = _save_clip(wav, base)
        entry = {
            "id": storage.new_id(), "created": time.time(), "kind": kind,
            "prompt": prompt, "seconds": seconds, "seed": seed,
            "files": saved["files"], "duration": saved["duration"],
            "model": config.ACE_MODEL,
        }
        storage.add_music(entry)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "music", "music_kind": kind, "prompt": prompt,
            "duration": saved["duration"],
            "url": f"/music/{saved['files'].get('mp3') or saved['files'].get('wav')}",
            "text_preview": f"{kind.upper()}: {prompt[:140]}",
        })
        return {"item": entry}

    return jobs.submit("music", task)


def submit_music_download() -> str:
    """Warm the engine: start the sidecar + load the model (downloads ~9 GB once)."""
    def task(progress: ProgressFn) -> Dict:
        progress("Starting music engine…", 0.05)
        music_engine.warm(progress=progress)
        return {"ready": True, "status": music_engine.status()}

    return jobs.submit("music_download", task)
