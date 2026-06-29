"""Per-scene timed voiceover (audio-led sync).

Each scene's narration is synthesized with Qwen3-TTS, stitched, saved as a WAV
under the project's ``audio/`` dir, and its real duration measured. The project
timeline is then rebuilt from those real durations (audio-led) so the images
stay in sync with the narration regardless of the JSON's planned timecodes.

Reuses the existing TTS stack: chunking.chunk_text, engine.synth_custom /
synth_clone, audio.stitch / save_wav.
"""
from __future__ import annotations

import shutil
import time
from typing import Callable, Dict, List, Optional

import numpy as np

from . import audio, config, jobs, projects, storage
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
                segs, sr = engine.synth_clone(chunks, cv, language, instruct=instruct)
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


def _ingest_narration(master, pid: str):
    """Bring the master recording into the project as audio/narration.wav (a single
    continuous track the browser and moviepy can both read); return (rel, dur)."""
    rel = "audio/narration.wav"
    dst = projects.project_dir(pid) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if str(master).lower().endswith(".wav"):
        shutil.copyfile(str(master), str(dst))
    else:
        audio._run([config.FFMPEG, "-y", "-i", str(master), str(dst)])
    arr, sr = audio.read_wav(str(dst))
    return rel, (float(len(arr) / sr) if sr else 0.0)


def submit_attach_recording(pid: str, src_file: str,
                            voice_label: str = "Imported recording") -> str:
    """Attach an already-made master recording as the project's *narration track*.

    The voiceover is kept whole — one continuous audio file — rather than cut into
    per-scene clips, so playback and the final render never gap/cut between scenes.
    Each scene's image is simply timed to the recording using the ``planned_start``
    it inherited from this recording's Whisper transcript. Scenes are marked voiced
    and the timeline is rebuilt (transcript-led) from those timings.
    """
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    out = config.OUTPUTS_DIR.resolve()
    try:
        master = (out / src_file).resolve()
        master.relative_to(out)               # reject paths outside the outputs dir
    except (ValueError, OSError):
        raise ValueError("Invalid recording path.")
    if not master.exists():
        raise ValueError("Recording file not found.")

    scenes = [s for s in project.get("scenes", []) if (s.get("narration") or "").strip()]
    if not scenes:
        raise ValueError("This project has no narrated scenes to attach audio to.")
    last_end = max((float(s.get("planned_end") or 0.0) for s in scenes), default=0.0)

    def task(progress: ProgressFn) -> Dict:
        progress("Importing narration track", 0.15)
        rel, dur = _ingest_narration(master, pid)
        # Guard against an obviously-wrong pick (a different / shorter clip).
        if last_end > dur + 3.0:
            try:
                (projects.project_dir(pid) / rel).unlink()
            except OSError:
                pass
            raise ValueError(
                f"That recording is only {dur:.0f}s but this storyboard runs to "
                f"{last_end:.0f}s — looks like the wrong clip for this project.")

        progress("Timing scenes to the voiceover", 0.7)
        proj = projects.get_project(pid)
        proj["narration"] = {"file": rel, "dur": round(dur, 3),
                             "voice": voice_label, "source": src_file}
        done = 0
        for s in proj["scenes"]:
            if not (s.get("narration") or "").strip():
                continue
            s["audio_file"] = None             # audio lives in the single master track
            s["audio_dur"] = s.get("planned_dur")
            s["audio_voice"] = voice_label
            s["status"]["audio"] = "ready"
            done += 1
        projects.recompute_timeline(proj)
        projects.save_project(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "voiceover", "project": pid, "project_name": proj["name"],
            "voice": voice_label, "scenes": done,
            "duration": proj["timeline"]["total_dur"],
            "text_preview": f"Attached narration to “{proj['name']}” ({done} scenes)",
        })
        return {"done": done, "scenes": len(scenes),
                "duration": proj["timeline"]["total_dur"],
                "recording_dur": round(dur, 3)}

    return jobs.submit("attach_voiceover", task)
