"""Voiceover synthesis + timing.

**Canonical flow — one-take** (``submit_onetake``): the WHOLE script is
narrated in a single Qwen3-TTS pass so tone and prosody flow across scene
boundaries, saved as the project's continuous *narration track*, then
Whisper word-timestamps align each scene's text back to the recording to set
its start/end. Per-scene synthesis (``submit_voiceover``) remains for quick
single-scene fixes, but chaining it across a whole video sounds cut-up and
out of tone — don't.

Both paths QA the audio: the recording is transcribed and fuzzy-compared to
the script so TTS hallucinations (it happens — trailing commas invite the
model to keep talking) never ship silently.

Reuses the existing TTS stack: chunking.chunk_text, engine.synth_custom /
synth_clone, audio.stitch / save_wav.
"""
from __future__ import annotations

import re
import shutil
import time
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from . import audio, channels, config, humanize, jobs, projects, storage
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

    return jobs.submit("voiceover", task, pid=pid)


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


# --- one-take narration (the canonical voice flow) ---------------------------
def _norm_words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _find_anchor(words: List[Tuple[str, float, float]], start: int,
                 anchor: List[str], window: int = 80) -> Optional[int]:
    """First position >= start (within window) matching the anchor words,
    tolerating one mismatch — TTS/Whisper disagree on names and numbers."""
    n = len(anchor)
    if not n:
        return None
    lo, hi = max(0, start), min(len(words) - n, start + window)
    for i in range(lo, hi + 1):
        hits = sum(1 for a, (w, _s, _e) in zip(anchor, words[i:i + n]) if a == w)
        if hits >= max(1, n - 1):
            return i
    return None


def _align_scenes(scene_texts: List[str],
                  words: List[Tuple[str, float, float]]) -> List[Optional[Tuple[float, float]]]:
    """Monotonic fuzzy alignment: (start_sec, end_sec) per scene text."""
    spans: List[Optional[Tuple[float, float]]] = []
    ptr = 0
    for text in scene_texts:
        sw = _norm_words(text)
        if not sw or not words:
            spans.append(None)
            continue
        head = sw[: min(4, len(sw))]
        k = _find_anchor(words, ptr, head)
        if k is None:
            k = min(ptr, len(words) - 1)
        tail = sw[-min(4, len(sw)):]
        exp_end = k + len(sw) - len(tail)
        j = _find_anchor(words, max(k, exp_end - 8), tail, window=24)
        j_end = (j + len(tail) - 1) if j is not None else min(k + len(sw) - 1,
                                                              len(words) - 1)
        j_end = max(j_end, k)
        spans.append((words[k][1], words[j_end][2]))
        ptr = j_end + 1
    return spans


def qa_transcript(script: str, heard: str) -> Dict:
    """Fuzzy script-vs-transcript check (hallucination / truncation guard)."""
    want, got = _norm_words(script), _norm_words(heard)
    overlap = len(set(want) & set(got)) / max(len(set(want)), 1)
    return {"script_words": len(want), "heard_words": len(got),
            "extra_words": len(got) - len(want), "overlap": round(overlap, 3),
            "ok": (len(got) - len(want)) <= max(6, len(want) // 20)
                  and overlap >= 0.75}


def submit_onetake(pid: str, voice: Dict) -> str:
    """Narrate the WHOLE script in one pass, then align scenes to the take."""
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    settings = storage.get_settings()
    voice = dict(voice or {})
    mode = voice.get("mode", "custom")
    language = voice.get("language") or settings.get("default_language", "Auto")
    instruct = (voice.get("instruct") or "").strip() or None
    scenes = [s for s in project.get("scenes", []) if (s.get("narration") or "").strip()]
    if not scenes:
        raise ValueError("No narrated scenes to voice.")
    if mode == "clone":
        cv = storage.get_custom_voice(voice.get("voice_id"))
        if not cv:
            raise ValueError("Selected custom voice was not found.")
        label = cv.get("name", "Cloned voice")
    else:
        cv = None
        speaker = voice.get("speaker") or settings.get("default_speaker", "Ryan")
        label = display_name(speaker)

    def task(progress: ProgressFn) -> Dict:
        proj = projects.get_project(pid)
        proj["settings"]["voice"] = voice
        gap = int(settings.get("gap_ms", 180))
        pgap = int(settings.get("paragraph_gap_ms", 480))
        trim = bool(settings.get("trim_silence", True))
        max_chars = int(settings.get("max_chars", 240))

        script = "\n\n".join((s.get("narration") or "").strip() for s in scenes)

        # Ending-aware tone (user, 2026-07-10): the narrator should KNOW the
        # video is ending. The final scenes are synthesized as the tail of the
        # same take with a wind-down instruct, split at a scene boundary (a
        # natural pause), so prosody inside each half stays continuous.
        # voice.outro > channel defaults.voice_outro > on by default;
        # "off" disables, any other string replaces the wind-down wording.
        outro = voice.get("outro")
        if outro is None:
            ch = channels.get(proj.get("channel")) if proj.get("channel") else None
            outro = ((ch or {}).get("defaults") or {}).get("voice_outro")
        outro_off = (outro is not None
                     and str(outro).lower() in ("off", "false", "none", "0"))
        n_out = max(1, min(3, round(len(scenes) * 0.10))) if len(scenes) >= 6 else 0
        outro_instruct = None
        if n_out and not outro_off:
            base = (instruct or "").rstrip(". ")
            tail = (outro if isinstance(outro, str)
                    and outro.lower() not in ("settle", "on", "true", "1", "")
                    else "The story is ending now: ease the pace down slightly, "
                         "lower the energy, and settle to a calm, final close.")
            outro_instruct = (base + ". " if base else "") + tail

        progress("Narrating the full script (one take)", 0.05)
        if outro_instruct:
            body_txt = "\n\n".join((s.get("narration") or "").strip()
                                   for s in scenes[:-n_out])
            out_txt = "\n\n".join((s.get("narration") or "").strip()
                                  for s in scenes[-n_out:])
            chunks = chunk_text(body_txt, max_chars)
            out_chunks = chunk_text(out_txt, max_chars)
            off = max((c["paragraph"] for c in chunks), default=-1) + 1
            for c in out_chunks:
                c["paragraph"] += off
        else:
            chunks = chunk_text(script, max_chars)
            out_chunks = []
        if mode == "clone":
            segs, sr = engine.synth_clone(chunks, cv, language, instruct=instruct)
            if out_chunks:
                progress("Narrating the ending (wind-down tone)", 0.45)
                seg2, _ = engine.synth_clone(out_chunks, cv, language,
                                             instruct=outro_instruct)
                segs += seg2
        else:
            segs, sr = engine.synth_custom(chunks, speaker, language, instruct)
            if out_chunks:
                progress("Narrating the ending (wind-down tone)", 0.45)
                seg2, _ = engine.synth_custom(out_chunks, speaker, language,
                                              outro_instruct)
                segs += seg2
        stitched = audio.stitch(segs, sr, gap, pgap, trim)
        # The take is done: drop the TTS checkpoint BEFORE Whisper loads so the
        # two never overlap in VRAM (GPU housekeeping, 2026-07-10).
        engine.release()

        rel = "audio/narration.wav"
        dst = projects.project_dir(pid) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        audio.save_wav(stitched, sr, str(dst))
        arr = np.asarray(stitched, dtype=np.float32).reshape(-1)
        dur = float(len(arr) / sr) if sr else 0.0

        # Humanize the take BEFORE alignment (mic/room/analog character +
        # pacing jitter — strips the AI-voice tells) so Whisper times the audio
        # that actually ships. voice.humanize > channel default > settings >
        # "natural"; pass false/"off" to skip.
        hum = voice.get("humanize")
        if hum is None:
            ch = channels.get(proj.get("channel")) if proj.get("channel") else None
            hum = ((ch or {}).get("defaults") or {}).get("voice_humanize")
        if hum is None:
            hum = (settings.get("audio") or {}).get("voice_humanize", "natural")
        applied_hum = None
        if hum and str(hum).lower() not in ("off", "false", "none", "0"):
            progress("Humanizing the take (mic · room · pacing)", 0.55)
            try:
                params = hum if isinstance(hum, dict) else {"preset": str(hum)}
                dur = humanize.polish_wav(dst, dst, params) or dur
                applied_hum = params.get("preset") or "custom"
            except Exception as exc:  # noqa: BLE001 — raw take still usable
                progress(f"Humanize skipped ({type(exc).__name__})", 0.56)

        progress("Aligning scenes to the take (Whisper)", 0.62)
        from . import transcribe as _tr
        model = _tr.load_model(progress=lambda s, f: progress(s, 0.62))
        segments, _info = model.transcribe(str(dst), word_timestamps=True,
                                           vad_filter=True)
        words: List[Tuple[str, float, float]] = []
        heard_parts: List[str] = []
        for seg in segments:
            heard_parts.append(seg.text)
            for w in (seg.words or []):
                nw = re.sub(r"[^a-z0-9']", "", (w.word or "").lower())
                if nw:
                    words.append((nw, float(w.start), float(w.end)))
        heard = " ".join(heard_parts)

        spans = _align_scenes([s.get("narration") or "" for s in scenes], words)
        progress("Timing scenes", 0.9)
        prev_start = -1.0
        done = 0
        for s, span in zip(scenes, spans):
            sc = projects.get_scene(proj, s["id"])
            if span is None:
                st = max(prev_start + 0.4, 0.0)
                en = st + float(sc.get("planned_dur") or 2.0)
            else:
                st = max(0.0, span[0] - 0.10)
                en = span[1] + 0.15
            st = 0.0 if done == 0 else max(st, prev_start + 0.4)
            en = max(en, st + 0.6)
            sc["planned_start"] = round(st, 3)
            sc["planned_end"] = round(min(en, dur), 3)
            sc["planned_dur"] = round(sc["planned_end"] - st, 3)
            sc["audio_file"] = None          # audio lives in the master track
            sc["audio_dur"] = sc["planned_dur"]
            sc["audio_voice"] = label
            sc["status"]["audio"] = "ready"
            prev_start = st
            done += 1

        # The last line must never feel clipped (user, 2026-07-10: the ending
        # "cuts off midsentence"): give the final scene extra tail room up to
        # the real end of the recording, so the falling cadence breathes.
        if scenes:
            last = projects.get_scene(proj, scenes[-1]["id"])
            if last:
                last["planned_end"] = round(min(dur, float(last["planned_end"]) + 0.8), 3)
                last["planned_dur"] = round(last["planned_end"] - last["planned_start"], 3)
                last["audio_dur"] = last["planned_dur"]

        qa = qa_transcript(script, heard)
        # persist the word timestamps — the assembler lands word-level emphasis
        # effects (grammar "emphasis") on these exact times
        words_rel = "audio/words.json"
        storage.write_json(projects.project_dir(pid) / words_rel,
                           [[w, round(a, 3), round(b, 3)] for w, a, b in words])
        proj["narration"] = {"file": rel, "dur": round(dur, 3), "voice": label,
                             "source": "onetake", "qa": qa,
                             "words_file": words_rel,
                             "humanize": applied_hum,
                             "outro_scenes": n_out if outro_instruct else 0}
        projects.recompute_timeline(proj)
        projects.save_project(proj)
        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "voiceover", "project": pid, "project_name": proj["name"],
            "voice": label, "language": language, "scenes": done,
            "duration": proj["timeline"]["total_dur"],
            "text_preview": f"One-take narration for “{proj['name']}” ({dur:.0f}s)",
        })
        return {"done": done, "voice": label, "duration": round(dur, 3),
                "qa": qa, "timeline": proj["timeline"]}

    return jobs.submit("voiceover_onetake", task, pid=pid)
