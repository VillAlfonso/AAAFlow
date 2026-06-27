"""Per-scene timed voiceover (audio-led sync).

Each scene's narration is synthesized with Qwen3-TTS, stitched, saved as a WAV
under the project's ``audio/`` dir, and its real duration measured. The project
timeline is then rebuilt from those real durations (audio-led) so the images
stay in sync with the narration regardless of the JSON's planned timecodes.

Reuses the existing TTS stack: chunking.chunk_text, engine.synth_custom /
synth_clone, audio.stitch / save_wav.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

import numpy as np

from . import audio, jobs, projects, storage
from .chunking import chunk_text
from .engine import engine
from .voices import display_name

ProgressFn = Callable[[str, float], None]


def _counts(project: Dict) -> Dict:
    sc = project.get("scenes", [])
    return {
        "total": len(sc),
        "audio": sum(1 for s in sc if s.get("status", {}).get("audio") == "ready"),
        "image": sum(1 for s in sc if s.get("status", {}).get("image") == "ready"),
    }


def _select_targets(scenes: List[Dict], scope: str, scene_id) -> List[Dict]:
    def voiced(s):  # has narration worth synthesizing
        return bool((s.get("narration") or "").strip())
    if scope == "scene":
        return [s for s in scenes if str(s.get("id")) == str(scene_id) and voiced(s)]
    if scope == "all":
        return [s for s in scenes if voiced(s)]
    # default: missing or stale
    return [s for s in scenes
            if voiced(s) and s.get("status", {}).get("audio") != "ready"]


def _save_scene_audio(pid: str, scene_id, wav: np.ndarray, sr: int):
    rel = f"audio/scene_{projects.scene_key(scene_id)}.wav"
    abspath = projects.project_dir(pid) / rel
    audio.save_wav(wav, sr, str(abspath))
    arr = np.asarray(wav, dtype=np.float32).reshape(-1)
    dur = float(len(arr) / sr) if sr else 0.0
    return rel, dur


def submit_voiceover(pid: str, voice: Dict, scope: str = "missing",
                     scene_id=None) -> str:
    """Queue a background job that voices the selected scenes."""
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    settings = storage.get_settings()
    voice = dict(voice or {})
    mode = voice.get("mode", "custom")
    language = voice.get("language") or settings.get("default_language", "Auto")
    instruct = (voice.get("instruct") or "").strip() or None

    targets = _select_targets(project["scenes"], scope, scene_id)
    if not targets:
        raise ValueError("No scenes need voiceover for that selection.")

    # Resolve + validate the voice once, up front.
    if mode == "clone":
        cv = storage.get_custom_voice(voice.get("voice_id"))
        if not cv:
            raise ValueError("Selected custom voice was not found.")
        label = cv.get("name", "Cloned voice")
    else:
        cv = None
        speaker = voice.get("speaker") or settings.get("default_speaker", "Ryan")
        label = display_name(speaker)

    target_ids = [s["id"] for s in targets]

    def task(progress: ProgressFn) -> Dict:
        # Re-read so we don't clobber concurrent edits, then remember the voice.
        proj = projects.get_project(pid)
        proj["settings"]["voice"] = voice
        gap = int(settings.get("gap_ms", 180))
        pgap = int(settings.get("paragraph_gap_ms", 480))
        trim = bool(settings.get("trim_silence", True))
        max_chars = int(settings.get("max_chars", 240))

        n = len(target_ids)
        done = 0
        for sid in target_ids:
            sc = projects.get_scene(proj, sid)
            text = (sc.get("narration") or "").strip() if sc else ""
            progress(f"Voicing scene {sid} ({done + 1}/{n})", done / max(n, 1))
            if not text:
                continue
            chunks = chunk_text(text, max_chars)
            if mode == "clone":
                segs, sr = engine.synth_clone(chunks, cv, language)
            else:
                segs, sr = engine.synth_custom(chunks, speaker, language, instruct)
            stitched = audio.stitch(segs, sr, gap, pgap, trim)
            rel, dur = _save_scene_audio(pid, sid, stitched, sr)
            projects.set_scene_audio(proj, sid, rel, dur, label)
            done += 1
            # persist incrementally so progress survives a crash / is visible live
            if done % 5 == 0:
                projects.recompute_timeline(proj)
                projects.save_project(proj)

        projects.recompute_timeline(proj)
        projects.save_project(proj)
        counts = _counts(proj)

        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "voiceover", "project": pid, "project_name": proj["name"],
            "voice": label, "language": language, "scenes": done,
            "duration": proj["timeline"]["total_dur"],
            "text_preview": f"Voiced {done} scene(s) of “{proj['name']}”",
        })
        return {"done": done, "voice": label,
                "timeline": proj["timeline"], "counts": counts}

    return jobs.submit("voiceover", task)
