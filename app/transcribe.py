"""Local speech-to-text with accurate, sentence-level timestamps.

After a scene is voiced, its narration clip is transcribed with Whisper
(faster-whisper — runs on the NVIDIA GPU, auto-falls back to CPU) at *word*
resolution. The recognized words are then aligned back onto the **known script**
(the scene's ``narration``), so every sentence block carries your exact script
wording while its start/end times come from the audio. That anchoring is what
makes the timing trustworthy: the words are fixed, only the clock is measured.

Everything is local — the Whisper weights download once into ``./models``.

Two layers live here:

* the engine — :func:`transcribe_clip` turns one WAV + its script into
  sentence blocks (times relative to that clip);
* the orchestration — :func:`submit_transcribe` runs a background job over a
  project's scenes and writes ``transcript/`` (transcript.json + .srt + .vtt)
  with absolute times laid out on the audio-led timeline.
"""
from __future__ import annotations

import difflib
import re
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import config, jobs, projects, storage
from .chunking import split_paragraphs, split_sentences

ProgressFn = Callable[[str, float], None]

# --- whisper model cache ----------------------------------------------------
_lock = threading.RLock()
_model = None
_model_key: Optional[Tuple[str, str, str]] = None     # (name, device, compute)
_import_error: Optional[str] = None

# Full language name (app's voice picker) -> Whisper language code. "Auto" and
# anything unknown become None so Whisper detects the language itself.
_LANG_CODE = {
    "auto": None, "english": "en", "chinese": "zh", "japanese": "ja",
    "korean": "ko", "german": "de", "french": "fr", "russian": "ru",
    "portuguese": "pt", "spanish": "es", "italian": "it",
}

# Sentence terminators (Latin + CJK) for the no-script verbatim fallback.
_SENT_END_CH = ".!?…。！？"
# Drop everything but letters/digits when comparing a spoken word to a script
# word (so "Germany," == "germany" and "1923." == "1923").
_NONWORD = re.compile(r"\W+", re.UNICODE)


def _norm(word: str) -> str:
    return _NONWORD.sub("", (word or "").lower())


# --- settings ---------------------------------------------------------------
def _settings() -> Dict:
    s = (storage.get_settings().get("transcribe") or {})
    return {
        "model": s.get("model", "medium"),
        "device": (s.get("device") or "auto").lower(),     # auto | cuda | cpu
        "compute_type": (s.get("compute_type") or "auto").lower(),
        "beam_size": int(s.get("beam_size", 5)),
        "write_subtitles": bool(s.get("write_subtitles", True)),
    }


def lang_code(language: Optional[str]) -> Optional[str]:
    return _LANG_CODE.get((language or "auto").strip().lower(), None)


def _device_candidates(cfg: Dict) -> List[Tuple[str, str]]:
    """Ordered (device, compute_type) attempts. CUDA first, CPU as the safety net."""
    ct = cfg["compute_type"]
    if cfg["device"] == "cpu":
        return [("cpu", "int8" if ct == "auto" else ct)]
    cuda = ("cuda", "float16" if ct == "auto" else ct)
    if cfg["device"] == "cuda":
        return [cuda]
    return [cuda, ("cpu", "int8" if ct == "auto" else ct)]


def _whisper_dir():
    d = config.MODELS_DIR / "whisper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_model(progress: Optional[ProgressFn] = None):
    """Lazily load (and cache) the configured Whisper model, GPU then CPU."""
    global _model, _model_key, _import_error
    cfg = _settings()
    name = cfg["model"]
    with _lock:
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001
            _import_error = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(
                "faster-whisper is not installed. Run: "
                "pip install faster-whisper") from exc

        last: Optional[Exception] = None
        for device, compute in _device_candidates(cfg):
            key = (name, device, compute)
            if _model is not None and _model_key == key:
                return _model
            try:
                if progress:
                    progress(f"Loading Whisper “{name}” ({device})…", 0.04)
                model = WhisperModel(name, device=device, compute_type=compute,
                                     download_root=str(_whisper_dir()))
                _model, _model_key, _import_error = model, key, None
                return model
            except Exception as exc:  # noqa: BLE001 - try the next device
                last = exc
                _model = None
                _model_key = None
        raise RuntimeError(f"Could not load Whisper model '{name}': {last}")


def unload_model() -> None:
    global _model, _model_key
    with _lock:
        _model = None
        _model_key = None


def status() -> Dict:
    cfg = _settings()
    try:
        import faster_whisper  # noqa: F401
        available = True
    except Exception as exc:  # noqa: BLE001
        available = False
        globals()["_import_error"] = f"{type(exc).__name__}: {exc}"
    return {
        "available": available,
        "model": cfg["model"],
        "device": (_model_key[1] if _model_key else cfg["device"]),
        "loaded": _model is not None,
        "import_error": _import_error,
    }


# --- script <-> recognized-word alignment ----------------------------------
def _script_words(sentences: List[str]) -> List[Dict]:
    """Flatten script sentences into ordered word records carrying their sentence."""
    out: List[Dict] = []
    for si, sent in enumerate(sentences):
        for disp in sent.split():
            out.append({"disp": disp, "tok": _norm(disp), "si": si,
                        "start": None, "end": None})
    return out


def _distribute(words: List[Dict], t0: float, t1: float) -> None:
    """Spread a run of timeless words across [t0, t1] weighted by length."""
    if not words:
        return
    t0 = max(0.0, t0)
    t1 = max(t0, t1)
    weights = [max(1, len(w["disp"])) for w in words]
    total = sum(weights) or 1
    cur = t0
    for w, wt in zip(words, weights):
        d = (t1 - t0) * wt / total
        w["start"], w["end"] = cur, cur + d
        cur += d


def _interpolate(words: List[Dict], clip_dur: float) -> None:
    """Fill any unaligned words, then clamp to a monotonic [0, clip_dur] timeline."""
    known = [i for i, w in enumerate(words)
             if w["start"] is not None and w["end"] is not None]
    if not known:
        _distribute(words, 0.0, clip_dur)
    else:
        if known[0] > 0:
            _distribute(words[:known[0]], 0.0, words[known[0]]["start"])
        for a, b in zip(known, known[1:]):
            if b - a > 1:
                _distribute(words[a + 1:b], words[a]["end"], words[b]["start"])
        if known[-1] < len(words) - 1:
            _distribute(words[known[-1] + 1:], words[known[-1]]["end"], clip_dur)
    prev = 0.0
    for w in words:
        s = max(prev, min(float(w["start"]), clip_dur))
        e = max(s, min(float(w["end"]), clip_dur))
        w["start"], w["end"] = round(s, 3), round(e, 3)
        prev = e


def _assign_times(swords: List[Dict], rwords: List[Dict], clip_dur: float) -> None:
    """Copy recognized word times onto the script words via a difflib alignment."""
    s_pos = [i for i, w in enumerate(swords) if w["tok"]]
    r_pos = [j for j, w in enumerate(rwords) if w["tok"]]
    if r_pos:
        s_toks = [swords[i]["tok"] for i in s_pos]
        r_toks = [rwords[j]["tok"] for j in r_pos]
        sm = difflib.SequenceMatcher(a=s_toks, b=r_toks, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    sw = swords[s_pos[i1 + k]]
                    rw = rwords[r_pos[j1 + k]]
                    sw["start"], sw["end"] = rw["start"], rw["end"]
            elif tag == "replace":
                n, m = i2 - i1, j2 - j1
                for k in range(n):
                    if m:
                        rw = rwords[r_pos[j1 + min(m - 1, (k * m) // n)]]
                        sw = swords[s_pos[i1 + k]]
                        sw["start"], sw["end"] = rw["start"], rw["end"]
            # 'delete' (script words Whisper missed) stay None -> interpolated
            # 'insert' (words Whisper added) are ignored
    _interpolate(swords, clip_dur)


def _block(index: int, text: str, words: List[Dict]) -> Dict:
    start = words[0]["start"]
    end = words[-1]["end"]
    return {
        "index": index,
        "text": text,
        "start": round(float(start), 3),
        "end": round(float(end), 3),
        "dur": round(float(end) - float(start), 3),
        "words": [{"word": w["disp"], "start": w["start"], "end": w["end"]}
                  for w in words],
    }


def _anchored_sentences(ref_text: str, rwords: List[Dict], clip_dur: float
                        ) -> List[Dict]:
    sentences: List[str] = []
    for para in split_paragraphs(ref_text):
        sentences.extend(split_sentences(para))
    sentences = [s for s in sentences if s.strip()]
    if not sentences:
        return []
    swords = _script_words(sentences)
    if not swords:
        return []
    _assign_times(swords, rwords, clip_dur)
    blocks: List[Dict] = []
    for si, text in enumerate(sentences):
        ws = [w for w in swords if w["si"] == si]
        if ws:
            blocks.append(_block(len(blocks) + 1, text, ws))
    return blocks


def _verbatim_sentences(rwords: List[Dict], clip_dur: float) -> List[Dict]:
    """No script to anchor to: cut sentences at spoken punctuation instead."""
    blocks: List[Dict] = []
    cur: List[Dict] = []

    def flush():
        text = " ".join(x["disp"] for x in cur).strip()
        if text:
            blocks.append(_block(len(blocks) + 1, text, cur))

    for w in rwords:
        cur.append(w)
        if (w["disp"].strip()[-1:] or "") in _SENT_END_CH:
            flush()
            cur = []
    if cur:
        flush()
    return blocks


# --- engine: one clip -------------------------------------------------------
def transcribe_clip(wav_path: str, ref_text: Optional[str] = None,
                    language: Optional[str] = None,
                    progress: Optional[ProgressFn] = None) -> Dict:
    """Transcribe one audio clip into sentence blocks (times relative to the clip).

    ``ref_text`` is the known script; when given, each sentence block reads with
    your exact wording and timing is aligned to it. Without it, sentences are
    cut at the punctuation Whisper itself produces (verbatim).
    """
    model = load_model(progress)
    cfg = _settings()
    code = lang_code(language)
    segments, info = model.transcribe(
        wav_path, language=code, word_timestamps=True,
        beam_size=cfg["beam_size"], vad_filter=False,
    )

    rwords: List[Dict] = []
    verbatim_parts: List[str] = []
    for seg in segments:
        verbatim_parts.append(seg.text)
        for w in (seg.words or []):
            disp = (w.word or "").strip()
            if not disp:
                continue
            rwords.append({"disp": disp, "tok": _norm(disp),
                           "start": float(w.start), "end": float(w.end),
                           "prob": round(float(w.probability or 0.0), 3)})

    clip_dur = float(getattr(info, "duration", 0.0) or 0.0)
    if rwords:
        clip_dur = max(clip_dur, rwords[-1]["end"])
    verbatim = " ".join(p.strip() for p in verbatim_parts).strip()

    ref = (ref_text or "").strip()
    if ref:
        sentences = _anchored_sentences(ref, rwords, clip_dur)
        anchored = True
    else:
        sentences = _verbatim_sentences(rwords, clip_dur)
        anchored = False

    return {
        "language": code or getattr(info, "language", None),
        "duration": round(clip_dur, 3),
        "model": cfg["model"],
        "anchored": anchored,
        "verbatim": verbatim,
        "sentences": sentences,
    }


# ===========================================================================
#  Orchestration: transcribe a whole project, write transcript/ outputs
# ===========================================================================
def _has_audio(s: Dict) -> bool:
    return bool(s.get("audio_file")) and s.get("status", {}).get("audio") == "ready"


def _transcript_state(s: Dict) -> str:
    return s.get("status", {}).get("transcript", "none")


def _select_targets(scenes: List[Dict], scope: str, scene_id) -> List[Dict]:
    if scope == "scene":
        return [s for s in scenes if str(s.get("id")) == str(scene_id) and _has_audio(s)]
    if scope == "all":
        return [s for s in scenes if _has_audio(s)]
    # default: audio present but no fresh transcript yet
    return [s for s in scenes if _has_audio(s) and _transcript_state(s) != "ready"]


def _scene_offset(row: Dict, audio_dur: Optional[float], lead: float) -> float:
    """Where this scene's narration audio starts inside its timeline slot.

    Mirrors assemble._audio_array: the clip sits at ``lead`` seconds in, unless
    the slot is too short to fit both the lead-in and the clip.
    """
    dur = float(row.get("dur") or 0.0)
    clip = float(audio_dur or 0.0)
    return min(lead, max(0.0, dur - clip))


def _ts(t: float, sep: str = ",") -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _write_srt(path, blocks: List[Dict]) -> None:
    lines: List[str] = []
    for i, b in enumerate(blocks, 1):
        lines.append(str(i))
        lines.append(f"{_ts(b['start'])} --> {_ts(b['end'])}")
        lines.append(b["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_vtt(path, blocks: List[Dict]) -> None:
    lines = ["WEBVTT", ""]
    for b in blocks:
        lines.append(f"{_ts(b['start'], '.')} --> {_ts(b['end'], '.')}")
        lines.append(b["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_project_transcript(project: Dict) -> Dict:
    """Lay every scene's sentence blocks onto absolute timeline seconds."""
    tl = projects.recompute_timeline(project)
    rows = {str(r["id"]): r for r in tl["scenes"]}
    sync = project.get("settings", {}).get("sync", {})
    lead = float(sync.get("lead_in_ms", 120)) / 1000.0

    flat: List[Dict] = []
    scene_out: List[Dict] = []
    for s in project.get("scenes", []):
        tr = s.get("transcript")
        if not tr or not tr.get("sentences"):
            continue
        row = rows.get(str(s.get("id")), {})
        base = float(row.get("start") or 0.0) + _scene_offset(row, s.get("audio_dur"), lead)
        sents = []
        for b in tr["sentences"]:
            abs_b = {
                "index": len(flat) + 1,
                "scene": s.get("id"),
                "text": b["text"],
                "start": round(base + b["start"], 3),
                "end": round(base + b["end"], 3),
                "dur": b.get("dur"),
            }
            flat.append(abs_b)
            sents.append({**b, "start": round(base + b["start"], 3),
                          "end": round(base + b["end"], 3)})
        scene_out.append({"id": s.get("id"), "start": round(base, 3),
                          "language": tr.get("language"), "sentences": sents})

    return {
        "project": project.get("id"),
        "name": project.get("name"),
        "generated": time.time(),
        "model": _settings()["model"],
        "total_dur": tl.get("total_dur"),
        "sentence_count": len(flat),
        "scenes": scene_out,
        "sentences": flat,
    }


def get_transcript(pid: str) -> Optional[Dict]:
    path = projects.project_dir(pid) / "transcript" / "transcript.json"
    if not path.exists():
        return None
    return storage.read_json(path, None)


def _write_outputs(pid: str, doc: Dict) -> Dict:
    d = projects.project_dir(pid) / "transcript"
    d.mkdir(parents=True, exist_ok=True)
    storage.write_json(d / "transcript.json", doc)
    files = {"json": "transcript/transcript.json"}
    if _settings()["write_subtitles"]:
        _write_srt(d / "captions.srt", doc["sentences"])
        _write_vtt(d / "captions.vtt", doc["sentences"])
        files["srt"] = "transcript/captions.srt"
        files["vtt"] = "transcript/captions.vtt"
    return files


def submit_transcribe(pid: str, scope: str = "missing", scene_id=None) -> str:
    """Queue a background job that transcribes the selected voiced scenes."""
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    targets = _select_targets(project["scenes"], scope, scene_id)
    if not targets:
        raise ValueError("No voiced scenes to transcribe for that selection.")
    target_ids = [s["id"] for s in targets]
    default_lang = (project.get("settings", {}).get("voice", {}) or {}).get("language")

    def task(progress: ProgressFn) -> Dict:
        progress("Loading transcription model…", 0.02)
        load_model(progress)

        proj = projects.get_project(pid)
        n = len(target_ids)
        done = 0
        for sid in target_ids:
            sc = projects.get_scene(proj, sid)
            if not sc or not _has_audio(sc):
                continue
            progress(f"Transcribing scene {sid} ({done + 1}/{n})", done / max(n, 1))
            wav = projects.project_dir(pid) / sc["audio_file"]
            if not wav.exists():
                continue
            result = transcribe_clip(str(wav), ref_text=sc.get("narration"),
                                     language=default_lang)
            sc["transcript"] = {
                "language": result["language"],
                "model": result["model"],
                "anchored": result["anchored"],
                "verbatim": result["verbatim"],
                "duration": result["duration"],
                "sentences": result["sentences"],
                "updated": time.time(),
            }
            sc.setdefault("status", {})["transcript"] = "ready"
            done += 1
            if done % 5 == 0:
                projects.save_project(proj)

        progress("Writing transcript…", 0.95)
        doc = _build_project_transcript(proj)
        projects.save_project(proj)
        files = _write_outputs(pid, doc)

        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "transcript", "project": pid, "project_name": proj["name"],
            "scenes": done, "sentences": doc["sentence_count"],
            "url": f"/projects/{pid}/{files['json']}",
            "text_preview": f"Transcribed {done} scene(s) of “{proj['name']}” "
                            f"· {doc['sentence_count']} sentences",
        })
        return {"done": done, "sentences": doc["sentence_count"],
                "files": files, "transcript": doc}

    return jobs.submit("transcribe", task)


def submit_file_transcribe(file_name: str, ref_text: Optional[str] = None,
                           language: Optional[str] = None,
                           item_id: Optional[str] = None) -> str:
    """Queue a job that transcribes one generated clip in data/outputs.

    The standalone "paste a script → voice → JSON" tool: the audio was just
    synthesized from ``ref_text``, so we anchor to it and return timed sentence
    blocks ready to copy. The transcript is also saved beside the clip
    (``<clip>.transcript.json``) and linked onto its saved history entry, so the
    timestamps persist and reappear in the web app after a reload.
    """
    if not file_name or "/" in file_name or "\\" in file_name or ".." in file_name:
        raise ValueError("Bad audio filename.")
    path = config.OUTPUTS_DIR / file_name
    if not path.exists():
        raise ValueError("Audio file not found — generate the voice first.")

    sidecar = f"{Path(file_name).stem}.transcript.json"

    def task(progress: ProgressFn) -> Dict:
        progress("Loading transcription model…", 0.05)
        result = transcribe_clip(str(path), ref_text=ref_text, language=language,
                                 progress=progress)
        progress("Saving timestamps…", 0.97)
        storage.write_json(config.OUTPUTS_DIR / sidecar, result)
        if item_id:
            storage.update_history(item_id, {
                "transcript_file": sidecar,
                "sentence_count": len(result.get("sentences", [])),
                "transcribed": time.time(),
            })
        progress("Done", 1.0)
        return {"transcript": result, "transcript_file": sidecar}

    return jobs.submit("transcribe", task)
