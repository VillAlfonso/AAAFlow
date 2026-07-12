"""GPU housekeeping: models load only when they are needed and are freed
automatically when they are not (user rule 2026-07-10).

Nothing heavy loads at server boot (every engine is lazy). The problem was
what LINGERED after use: Qwen3-TTS keeps up to ``max_loaded_models``
checkpoints resident forever, faster-whisper stays loaded after an alignment,
the parallax depth pipe caches itself, ComfyUI keeps the last krea2/Wan model
in VRAM after a render, and the ACE-Step sidecar preloads its 4B model with no
unload API. Result: VRAM stayed claimed while the app sat idle.

Two mechanisms fix it:

1. **Stage frees** - the produce orchestrator calls the targeted helpers the
   moment a stage no longer needs its model (TTS+Whisper after voice, ComfyUI
   after the last image/animate stage, depth after assemble, ACE after score).
2. **Idle reaper** - a daemon thread watches the job queue; once NOTHING has
   run for ``settings.gpu.idle_unload_min`` minutes (default 5, 0 disables),
   it calls :func:`release_all` so an idle app returns VRAM to the desktop.

Manual: ``POST /api/gpu/release``; status: ``GET /api/gpu``.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List

_last_activity = time.time()
_reaper: threading.Thread | None = None
_lock = threading.Lock()


def touch() -> None:
    """Record activity (a job started/finished). The reaper counts idle time
    from the most recent touch."""
    global _last_activity
    _last_activity = time.time()


# --- targeted frees (each safe to call at any time, never raises) -----------
def release_tts() -> bool:
    try:
        from .engine import engine
        return engine.release()
    except Exception:  # noqa: BLE001
        return False


def release_whisper() -> bool:
    try:
        from . import transcribe
        was = transcribe.status().get("loaded")
        transcribe.unload_model()
        _cuda_empty()
        return bool(was)
    except Exception:  # noqa: BLE001
        return False


def release_gatherer() -> bool:
    try:
        from . import gatherer
        was = gatherer.unload_model()
        _cuda_empty()
        return bool(was)
    except Exception:  # noqa: BLE001
        return False


def release_depth() -> bool:
    try:
        from .parallax import parallax_engine
        return parallax_engine.release()
    except Exception:  # noqa: BLE001
        return False


def release_diffusers() -> bool:
    try:
        from .image_engine import image_engine
        return image_engine.release()
    except Exception:  # noqa: BLE001
        return False


def free_comfy() -> bool:
    """Ask a RUNNING ComfyUI to drop its cached models (never starts one)."""
    try:
        from .comfy_engine import comfy_engine
        if not comfy_engine.alive():
            return False
        comfy_engine._post("/free", {"unload_models": True, "free_memory": True},
                           timeout=20)
        return True
    except Exception:  # noqa: BLE001
        return False


def kill_ace() -> bool:
    """Kill the ACE-Step sidecar process (it preloads and has no unload API)."""
    import re
    import subprocess
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=15).stdout
        for line in out.splitlines():
            if ":8765" in line and "LISTENING" in line:
                m = re.search(r"(\d+)\s*$", line)
                if m:
                    subprocess.run(["taskkill", "/PID", m.group(1), "/F"],
                                   capture_output=True, timeout=15)
                    return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _cuda_empty() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def release_all(reason: str = "") -> Dict:
    """Free every model this process (or its sidecars) holds on the GPU."""
    freed: List[str] = []
    if release_tts():
        freed.append("tts")
    if release_whisper():
        freed.append("whisper")
    if release_gatherer():
        freed.append("gatherer")
    if release_depth():
        freed.append("depth")
    if release_diffusers():
        freed.append("diffusers")
    if free_comfy():
        freed.append("comfy")
    if kill_ace():
        freed.append("ace")
    _cuda_empty()
    if freed:
        print(f"[gpu] released: {', '.join(freed)}"
              + (f" ({reason})" if reason else ""))
    return {"released": freed, "reason": reason}


def _busy() -> bool:
    """True while anything is queued/running (jobs or a produce pipeline)."""
    try:
        from . import jobs
        with jobs._lock:
            if any(j["status"] in ("queued", "running")
                   for j in jobs._jobs.values()):
                return True
    except Exception:  # noqa: BLE001
        return True
    try:
        from . import produce
        with produce._lock:
            if any((st or {}).get("status") == "running"
                   for st in produce._state.values()):
                return True
    except Exception:  # noqa: BLE001
        return True
    return False


def _idle_minutes() -> float:
    try:
        from . import storage
        g = (storage.get_settings() or {}).get("gpu") or {}
        return float(g.get("idle_unload_min", 5))
    except Exception:  # noqa: BLE001
        return 5.0


def status() -> Dict:
    out: Dict = {"idle_unload_min": _idle_minutes(),
                 "idle_s": round(time.time() - _last_activity),
                 "busy": _busy(), "loaded": {}}
    try:
        from .engine import engine
        out["loaded"]["tts"] = [f"{k[0]}/{k[1]}" for k in engine._models]
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import transcribe
        out["loaded"]["whisper"] = bool(transcribe.status().get("loaded"))
    except Exception:  # noqa: BLE001
        pass
    try:
        from .parallax import parallax_engine
        out["loaded"]["depth"] = parallax_engine._pipe is not None
    except Exception:  # noqa: BLE001
        pass
    try:
        from .image_engine import image_engine
        out["loaded"]["diffusers"] = image_engine._pipe is not None
    except Exception:  # noqa: BLE001
        pass
    try:
        from .music_engine import music_engine
        out["loaded"]["ace_sidecar"] = music_engine.alive()
    except Exception:  # noqa: BLE001
        pass
    return out


def _reap_loop() -> None:
    while True:
        time.sleep(30)
        try:
            mins = _idle_minutes()
            if mins <= 0:
                continue
            if _busy():
                touch()
                continue
            if time.time() - _last_activity >= mins * 60:
                res = release_all(f"idle {mins:.0f} min")
                touch()          # do not re-release every 30 s while idle
                if not res["released"]:
                    continue
        except Exception:  # noqa: BLE001
            pass


def start_reaper() -> None:
    global _reaper
    with _lock:
        if _reaper is None or not _reaper.is_alive():
            _reaper = threading.Thread(target=_reap_loop, name="gpu-reaper",
                                       daemon=True)
            _reaper.start()
