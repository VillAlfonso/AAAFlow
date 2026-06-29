"""Orchestration: turn API requests into background jobs that chunk text,
run the engine, post-process audio, and record history."""
from __future__ import annotations

import time
from typing import Callable, Dict

import numpy as np

from . import audio, config, humanize, jobs, storage
from .chunking import chunk_text, count_chars
from .engine import engine
from .voices import display_name, preview_text

ProgressFn = Callable[[str, float], None]


def _scaled(progress: ProgressFn, lo: float, hi: float) -> ProgressFn:
    def cb(stage: str, frac: float) -> None:
        progress(stage, lo + (hi - lo) * max(0.0, min(1.0, frac)))
    return cb


def _basename(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{storage.new_id()[:6]}"


def submit_tts(req: Dict) -> str:
    settings = storage.get_settings()
    text = (req.get("text") or "").strip()
    if not text:
        raise ValueError("Please enter some text to synthesize.")

    mode = req.get("mode", "custom")
    language = req.get("language") or settings.get("default_language", "Auto")
    is_preview = bool(req.get("preview"))
    chunks = chunk_text(text, int(settings.get("max_chars", 240)))
    if not chunks:
        raise ValueError("Nothing to synthesize.")

    fmt = "mp3" if is_preview else (req.get("format") or settings.get("output_format", "mp3"))
    loudnorm = False if is_preview else bool(
        req.get("loudnorm", settings.get("loudnorm", True)))
    loudnorm_i = float(settings.get("loudnorm_i", -16.0))
    speed = max(0.5, min(2.0, float(req.get("speed") or 1.0)))   # pacing: <1 slower, >1 faster

    speaker = req.get("speaker") or settings.get("default_speaker", "Ryan")
    instruct = (req.get("instruct") or "").strip() or None
    voice_id = req.get("voice_id")

    def task(progress: ProgressFn) -> Dict:
        synth = _scaled(progress, 0.05, 0.9)
        if mode == "custom":
            progress("Loading voice model", 0.02)
            segs, sr = engine.synth_custom(chunks, speaker, language, instruct, synth)
            voice_label = display_name(speaker)
            meta = {"mode": "custom", "speaker": speaker, "instruct": instruct}
        elif mode == "clone":
            voice = storage.get_custom_voice(voice_id)
            if not voice:
                raise ValueError("Selected voice was not found.")
            progress("Loading clone model", 0.02)
            segs, sr = engine.synth_clone(chunks, voice, language, synth, instruct=instruct)
            voice_label = voice.get("name", "Cloned voice")
            meta = {"mode": "clone", "voice_id": voice_id}
        else:
            raise ValueError(f"Unknown synthesis mode: {mode}")

        progress("Stitching & normalizing", 0.93)
        stitched = audio.stitch(
            segs, sr,
            int(settings.get("gap_ms", 180)),
            int(settings.get("paragraph_gap_ms", 480)),
            bool(settings.get("trim_silence", True)),
        )
        basename = _basename("preview" if is_preview else "tts")
        out = audio.export(stitched, sr, basename, loudnorm=loudnorm,
                           loudnorm_i=loudnorm_i, fmt=fmt, speed=speed)

        # Voice filter ("humanizer") — runs right after the record to lay down the
        # real-mic/real-room/analog character synthetic TTS lacks. Becomes the
        # delivered file, so any later transcription times the *filtered* audio.
        filt = req.get("humanize")
        humanized = False
        if filt and not is_preview:
            progress("Applying voice filter…", 0.95)
            src = out["files"].get("wav") or out["files"].get("mp3")
            hp = filt if isinstance(filt, dict) else {"preset": "natural"}
            hout = humanize.process(str(config.OUTPUTS_DIR / src), hp,
                                    _basename("filtered"))
            for f in out["files"].values():       # drop the pre-filter file(s)
                try:
                    (config.OUTPUTS_DIR / f).unlink()
                except OSError:
                    pass
            out = {"files": hout["files"], "duration": hout["duration"]}
            humanized = True

        entry = {
            "id": storage.new_id(),
            "created": time.time(),
            "preview": is_preview,
            "voice": voice_label,
            "language": language,
            "chars": count_chars(text),
            "chunks": len(chunks),
            "duration": out["duration"],
            "files": out["files"],
            "humanized": humanized,
            "text": text,                 # full script (lets a saved clip be reloaded + re-transcribed)
            "text_preview": text[:160],
            **meta,
        }
        if not is_preview:
            storage.add_history(entry)
        return {"item": entry}

    return jobs.submit("preview" if is_preview else "tts", task)


def submit_design(req: Dict) -> str:
    name = (req.get("name") or "Designed voice").strip()
    instruct = (req.get("instruct") or "").strip()
    if not instruct:
        raise ValueError("Describe the voice you want in the instruction box.")
    language = req.get("language") or "English"
    ptext = (req.get("preview_text") or preview_text(language)).strip()

    def task(progress: ProgressFn) -> Dict:
        progress("Loading voice design model", 0.05)
        wav, sr = engine.design_preview(ptext, instruct, language,
                                        _scaled(progress, 0.1, 0.78))
        arr = np.asarray(wav, dtype=np.float32).reshape(-1)
        vid = storage.new_id()
        ref_path = config.REFS_DIR / f"design_{vid}.wav"
        audio.save_wav(arr, sr, str(ref_path))

        progress("Saving voice", 0.9)
        basename = _basename("design")
        out = audio.export(arr, sr, basename, loudnorm=False, loudnorm_i=-16.0,
                           fmt="mp3")
        voice = {
            "id": vid, "name": name, "type": "design", "language": language,
            "ref_audio_path": str(ref_path), "ref_text": ptext,
            "instruct": instruct, "created": time.time(),
            "preview_file": out["files"].get("mp3") or out["files"].get("wav"),
        }
        storage.add_custom_voice(voice)
        return {"voice": voice}

    return jobs.submit("design", task)


def register_clone(name: str, ref_src_path: str, ref_text: str,
                   language: str) -> Dict:
    """Synchronously register an uploaded clone sample (prompt built on first use)."""
    vid = storage.new_id()
    ref_path = config.REFS_DIR / f"clone_{vid}.wav"
    audio.prepare_reference(str(ref_src_path), str(ref_path))
    voice = {
        "id": vid, "name": (name or "My voice").strip(), "type": "clone",
        "language": language or "Auto",
        "ref_audio_path": str(ref_path),
        "ref_text": (ref_text or "").strip() or None,
        "created": time.time(),
    }
    storage.add_custom_voice(voice)
    return voice


def submit_chunk(req: Dict) -> str:
    """Render a single chunk with its own tone (no stitching)."""
    settings = storage.get_settings()
    text = (req.get("text") or "").strip()
    if not text:
        raise ValueError("Empty chunk text.")
    mode = req.get("mode", "custom")
    language = req.get("language") or settings.get("default_language", "Auto")
    speaker = req.get("speaker") or settings.get("default_speaker", "Ryan")
    instruct = (req.get("instruct") or "").strip() or None
    voice_id = req.get("voice_id")

    def task(progress: ProgressFn) -> Dict:
        progress("Rendering line", 0.1)
        wav, sr = engine.synth_single(mode, text, language, speaker=speaker,
                                      voice_id=voice_id, instruct=instruct)
        progress("Saving", 0.92)
        name = f"chunk_{storage.new_id()}.wav"
        audio.save_wav(wav, sr, str(config.OUTPUTS_DIR / name))
        return {"file": name, "duration": float(len(np.asarray(wav)) / sr), "sr": sr}

    return jobs.submit("chunk", task)


def submit_export(req: Dict) -> str:
    """Stitch already-rendered chunk WAVs into one normalized file."""
    settings = storage.get_settings()
    chunks = req.get("chunks") or []
    if not chunks:
        raise ValueError("No rendered lines to export yet.")
    fmt = req.get("format") or settings.get("output_format", "mp3")
    loudnorm = bool(req.get("loudnorm", settings.get("loudnorm", True)))
    loudnorm_i = float(settings.get("loudnorm_i", -16.0))
    title = (req.get("title") or "").strip()
    voice_label = req.get("voice") or "Mixed"
    language = req.get("language") or settings.get("default_language", "Auto")

    def task(progress: ProgressFn) -> Dict:
        segs = []
        sr = 24000
        for i, ch in enumerate(chunks):
            wav, sr = audio.read_wav(str(config.OUTPUTS_DIR / ch["file"]))
            segs.append({"wav": wav, "paragraph": ch.get("paragraph", 0)})
            progress("Loading lines", 0.05 + 0.35 * (i + 1) / len(chunks))
        progress("Stitching & normalizing", 0.5)
        stitched = audio.stitch(
            segs, sr, int(settings.get("gap_ms", 180)),
            int(settings.get("paragraph_gap_ms", 480)),
            bool(settings.get("trim_silence", True)))
        out = audio.export(stitched, sr, _basename("export"), loudnorm=loudnorm,
                           loudnorm_i=loudnorm_i, fmt=fmt)
        entry = {
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "voice": voice_label, "language": language,
            "chars": sum(len(c.get("text", "")) for c in chunks),
            "chunks": len(chunks), "duration": out["duration"],
            "files": out["files"],
            "text_preview": title or (chunks[0].get("text", "")[:160] if chunks else ""),
            "mode": "chunked",
        }
        storage.add_history(entry)
        return {"item": entry}

    return jobs.submit("export", task)


def submit_humanize(req: Dict) -> str:
    """Run the de-AI humanizer on an already-rendered output file."""
    source = (req.get("source") or "").strip()
    if not source or "/" in source or "\\" in source or ".." in source:
        raise ValueError("Pick a valid source clip.")
    src_path = config.OUTPUTS_DIR / source
    if not src_path.exists():
        raise ValueError("Source audio not found.")
    params = req.get("params") or {}
    label = (req.get("voice") or "Narration").strip()

    def task(progress: ProgressFn) -> Dict:
        out = humanize.process(str(src_path), params, _basename("polished"), progress)
        entry = {
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "voice": f"{label} · polished", "language": req.get("language") or "",
            "chars": 0, "chunks": 0, "duration": out["duration"], "files": out["files"],
            "text_preview": "AI-fingerprints removed", "mode": "humanized",
            "humanized": True, "source": source,
        }
        storage.add_history(entry)
        return {"item": entry}

    return jobs.submit("humanize", task)


def store_ambiance(src_path: str, filename: str) -> str:
    """Convert an uploaded ambiance bed to mono 24k WAV; return its stored name."""
    name = f"amb_{storage.new_id()}.wav"
    dst = humanize.AMB_DIR / name
    audio.prepare_reference(str(src_path), str(dst), max_seconds=600)
    return name


def submit_preload(task_name: str) -> str:
    def task(progress: ProgressFn) -> Dict:
        progress(f"Downloading / loading {task_name} model", 0.1)
        engine.get_model(task_name)
        progress("Ready", 1.0)
        return {"task": task_name, "loaded": True}

    return jobs.submit("preload", task)
