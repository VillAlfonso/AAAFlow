"""Reusable editing-style presets — the video-wide "look" pulled up per project.

Presets live in ``data/effects_presets.json`` so they persist across videos and
can be edited (UI or by hand). Each preset decides which motion source each
scene uses (LTX clips, 2.5D parallax, Ken Burns stills), how strong the camera
moves are, and whether stinger SFX are mixed in. The assembler resolves:

    settings.assemble/opts  >  preset fields  >  built-in defaults

``sources`` is a priority chain per scene: the first available source wins,
with plain stills always the final fallback ("krea only" = stills/parallax,
"ltx" = clips first, "both" = clips then parallax).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import config, storage

DEFAULT_PRESETS: List[Dict] = [
    {
        "id": "cinematic",
        "label": "Cinematic — parallax + LTX clips + SFX",
        "sources": ["clips", "parallax"],
        "parallax": {"amplitude": 0.024, "fps": 30},
        "ken_burns": True, "kb_strength": 1.0,
        "transitions": True,
        "sfx": True, "sfx_volume": 0.5,
        "music_duck": 0.35,
    },
    {
        "id": "parallax-slides",
        "label": "Parallax slides — 2.5D depth moves on every still (no LTX)",
        "sources": ["parallax"],
        "parallax": {"amplitude": 0.024, "fps": 30},
        "ken_burns": True, "kb_strength": 1.0,
        "transitions": True,
        "sfx": True, "sfx_volume": 0.45,
        "music_duck": 0.35,
    },
    {
        "id": "dynamic-slides",
        "label": "Dynamic slides — varied Ken Burns + transitions + SFX",
        "sources": ["stills"],
        "ken_burns": True, "kb_strength": 1.2,
        "transitions": True,
        "sfx": True, "sfx_volume": 0.5,
        "music_duck": 0.35,
    },
    {
        "id": "simple-slides",
        "label": "Simple slides — gentle fades, no SFX",
        "sources": ["stills"],
        "ken_burns": True, "kb_strength": 0.6,
        "transitions": False,
        "sfx": False,
        "music_duck": 0.5,
    },
]


def load() -> List[Dict]:
    """All presets; the file is (re)seeded with defaults when missing/empty."""
    data = storage.read_json(config.EFFECTS_PRESETS_FILE, None)
    if not data or not isinstance(data, list):
        save(DEFAULT_PRESETS)
        return [dict(p) for p in DEFAULT_PRESETS]
    return data


def save(presets: List[Dict]) -> List[Dict]:
    storage.write_json(config.EFFECTS_PRESETS_FILE, presets)
    return presets


def get(preset_id: Optional[str]) -> Dict:
    presets = load()
    for p in presets:
        if p.get("id") == preset_id:
            return dict(p)
    return dict(presets[0]) if presets else dict(DEFAULT_PRESETS[0])


def upsert(preset: Dict) -> List[Dict]:
    """Add or replace one preset by id (the 'save this look for later' path)."""
    pid = (preset.get("id") or "").strip()
    if not pid:
        raise ValueError("Preset needs an id.")
    presets = load()
    presets = [p for p in presets if p.get("id") != pid] + [preset]
    return save(presets)
