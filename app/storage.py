"""JSON-file persistence for settings, history, and custom voices.

Small, atomic, thread-safe. No database — this is a single-user local app.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List

from . import config

_lock = threading.RLock()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _read(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _deep_merge(base: Dict, patch: Dict) -> Dict:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# --- settings --------------------------------------------------------------
def get_settings() -> Dict[str, Any]:
    with _lock:
        return _deep_merge(config.DEFAULT_SETTINGS, _read(config.SETTINGS_FILE, {}))


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        cur = _deep_merge(config.DEFAULT_SETTINGS, _read(config.SETTINGS_FILE, {}))
        merged = _deep_merge(cur, patch or {})
        _write(config.SETTINGS_FILE, merged)
        return merged


# --- history ---------------------------------------------------------------
def get_history() -> List[Dict]:
    with _lock:
        return _read(config.HISTORY_FILE, [])


def add_history(entry: Dict) -> Dict:
    with _lock:
        items = _read(config.HISTORY_FILE, [])
        items.insert(0, entry)
        _write(config.HISTORY_FILE, items[:200])
        return entry


def delete_history(item_id: str) -> bool:
    with _lock:
        items = _read(config.HISTORY_FILE, [])
        kept = [x for x in items if x.get("id") != item_id]
        _write(config.HISTORY_FILE, kept)
        return len(kept) != len(items)


# --- custom voices (clones + designed voices) ------------------------------
def _resolve_ref(voice: Dict) -> Dict:
    """Resolve a voice's ref audio by filename against the current REFS_DIR.

    History: this project has been relocated more than once, so absolute paths
    baked into voices_custom.json (e.g. the old C:\\QwenTTS\\data\\refs\\...) go
    stale. Resolving by basename against config.REFS_DIR makes saved voices
    survive any future move without rewriting the file.
    """
    p = voice.get("ref_audio_path")
    if p:
        cand = config.REFS_DIR / Path(p).name
        if cand.exists() and str(cand) != p:
            voice = {**voice, "ref_audio_path": str(cand)}
    return voice


def get_custom_voices() -> List[Dict]:
    with _lock:
        return [_resolve_ref(v) for v in _read(config.CUSTOM_VOICES_FILE, [])]


def get_custom_voice(voice_id: str) -> Dict | None:
    with _lock:
        for v in _read(config.CUSTOM_VOICES_FILE, []):
            if v.get("id") == voice_id:
                return _resolve_ref(v)
    return None


def add_custom_voice(voice: Dict) -> Dict:
    with _lock:
        items = _read(config.CUSTOM_VOICES_FILE, [])
        items.insert(0, voice)
        _write(config.CUSTOM_VOICES_FILE, items)
        return voice


def delete_custom_voice(voice_id: str) -> bool:
    with _lock:
        items = _read(config.CUSTOM_VOICES_FILE, [])
        kept = [x for x in items if x.get("id") != voice_id]
        _write(config.CUSTOM_VOICES_FILE, kept)
        return len(kept) != len(items)


# --- generic json helpers (used by projects + image registry) --------------
def read_json(path: Path, default: Any) -> Any:
    with _lock:
        return _read(path, default)


def write_json(path: Path, data: Any) -> Any:
    with _lock:
        _write(path, data)
        return data


def deep_merge(base: Dict, patch: Dict) -> Dict:
    """Public recursive dict merge (patch wins). Used for settings updates."""
    return _deep_merge(base or {}, patch or {})


# --- image model / LoRA registry (imported checkpoints + LoRAs) -------------
def get_image_models() -> List[Dict]:
    with _lock:
        return _read(config.IMAGE_MODELS_FILE, [])


def get_image_model(model_id: str) -> Dict | None:
    with _lock:
        for m in _read(config.IMAGE_MODELS_FILE, []):
            if m.get("id") == model_id:
                return m
    return None


def add_image_model(entry: Dict) -> Dict:
    with _lock:
        items = _read(config.IMAGE_MODELS_FILE, [])
        items = [x for x in items if x.get("id") != entry.get("id")]
        items.insert(0, entry)
        _write(config.IMAGE_MODELS_FILE, items)
        return entry


def delete_image_model(model_id: str) -> bool:
    with _lock:
        items = _read(config.IMAGE_MODELS_FILE, [])
        kept = [x for x in items if x.get("id") != model_id]
        _write(config.IMAGE_MODELS_FILE, kept)
        return len(kept) != len(items)
