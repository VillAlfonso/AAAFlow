"""The audio scorer — picks the right bed and the right stingers, automatically.

Runs on every produce (and on demand). It carries the intelligence so a video
sounds *scored*, not just "has music":

1. **Mood** — read the channel's ``music_vibe`` plus the tone of the actual
   narration (dark / tense / money / calm / emotional / neutral) and turn it
   into a search query + human label.
2. **Bed** — fetch ONE mood-matched instrumental from the Jamendo library
   (commercial-safe, popularity-ranked, long enough for the whole video) into
   ``data/music/`` and set it as the project's ducked/faded bed. If the library
   is unavailable (no key / offline) it falls back to local ACE-Step generation,
   then to whatever bed already exists — the build never blocks on the network.
3. **Stingers** — make sure every scene has an ``audio_cue`` (inferring one from
   the narration beat when the author left it blank), then fetch a real
   Creative-Commons sound for each distinct cue from Freesound into
   ``data/sfx_library/`` (tagged so the assembler's matcher prefers it over the
   procedural synth). No key ⇒ the procedural stingers still play.

The plan (mood, chosen bed, cue→source map, and the licence/attribution lines)
is written to ``project.audio_plan``; the packager appends the credits to the
video description automatically.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from . import audiolib, autodirect, config, grammar, jobs, projects, sfx, storage

ProgressFn = Callable[[str, float], None]

# Mood buckets (tone keywords → label + query) live in the shared grammar
# dictionary now (app/grammar.py -> data/effects_dictionary.json), so the audio
# scorer and the auto-director speak the same cinematic language.


def _mood(project: Dict):
    """(label, jamendo_query, seconds) — channel vibe leads, narration tone refines."""
    scenes = project.get("scenes", [])
    narr = " ".join((s.get("narration") or "") for s in scenes)
    label, tone_q = grammar.mood_for(narr)
    vibe = ((project.get("settings", {}).get("music_vibe")) or "").strip()
    query = (f"{vibe} {tone_q}".strip() if vibe else tone_q)
    # bed must cover the whole video; timeline is the truth, else estimate.
    total = float((project.get("timeline") or {}).get("total_dur") or 0)
    if total <= 0:
        words = sum(len((s.get("narration") or "").split()) for s in scenes)
        total = max(30.0, words / 2.6 + len(scenes) * 0.5)
    return label, query, total


# --- bed ---------------------------------------------------------------------
def _set_bed(project: Dict, music: Dict) -> None:
    project.setdefault("settings", {})["music"] = music


def _pick_bed(project: Dict, label: str, query: str, seconds: float,
              progress: ProgressFn) -> Dict:
    """Choose a bed. Returns a small dict describing the source for the plan."""
    audio_cfg = storage.get_settings().get("audio") or {}
    prefer = audio_cfg.get("prefer", "library")

    # 1) Jamendo library — a real, mood-matched, commercial-safe instrumental.
    if prefer == "library" and audiolib.jamendo_id():
        progress(f"Finding a {label} music bed (Jamendo)…", 0.2)
        for cand in audiolib.search_music(query, seconds=seconds, instrumental=True):
            dest = config.MUSIC_DIR / f"jamendo_{cand['ext_id']}.wav"
            entry = audiolib.fetch(cand, dest, kind="music")
            if entry:
                _set_bed(project, {
                    "file": entry["file"], "volume": 0.16, "duck": True, "fade": 1.5,
                    "prompt": query, "source": "jamendo", "cache_id": entry["cache_id"],
                    "title": entry.get("title"), "attribution": entry.get("attribution"),
                })
                return {"source": "jamendo", "title": entry.get("title"),
                        "artist": entry.get("artist"), "license": entry.get("license"),
                        "attribution": entry.get("attribution"),
                        "cc0": "CC0" in (entry.get("license") or "")}

    # 2) ACE-Step — generate an original bed locally (no Content-ID risk at all).
    if config.music_env_ready() and config.music_model_ready():
        try:
            from .music_engine import music_engine
            progress(f"Generating a {label} bed (ACE-Step)…", 0.25)
            wav = music_engine.generate(
                query + ", instrumental background bed, loopable, no vocals",
                seconds=min(90.0, max(30.0, seconds)), steps=8, instrumental=True,
                progress=lambda s, f: progress(s, 0.25 + 0.45 * f))
            config.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
            base = f"score_{time.strftime('%Y%m%d_%H%M%S')}_{storage.new_id()[:6]}.wav"
            (config.MUSIC_DIR / base).write_bytes(wav)
            _set_bed(project, {"file": base, "volume": 0.16, "duck": True,
                               "fade": 1.5, "prompt": query, "source": "ace-step"})
            return {"source": "ace-step", "title": None, "license": "generated",
                    "cc0": True}
        except Exception as exc:  # noqa: BLE001 — fall through to keep existing bed
            progress(f"ACE-Step unavailable ({type(exc).__name__}) — keeping any bed", 0.3)

    # 3) Whatever bed is already on the project (user-set), else none.
    existing = (project.get("settings", {}).get("music") or {}).get("file")
    return {"source": "existing" if existing else "none",
            "title": None, "cc0": True}


# --- stingers ----------------------------------------------------------------
def _real_sfx_for_cue(cue: str) -> bool:
    """True when the library already holds a fetched (non-procedural) sound
    covering this cue — so we don't re-download it every produce."""
    want = set(sfx._words(cue))
    for e in sfx.library():
        if e.get("source") == "freesound" and want <= set(e.get("tags") or []):
            return True
    return False


def _fetch_sfx(cues: List[str], progress: ProgressFn) -> List[Dict]:
    """Fetch a real CC sound for each distinct cue; register it in the SFX
    library tagged so the assembler's matcher prefers it. Returns plan rows."""
    rows: List[Dict] = []
    manifest = storage.read_json(config.SFX_LIBRARY_FILE, []) or []
    have_files = {m.get("file") for m in manifest}
    for i, cue in enumerate(cues):
        if _real_sfx_for_cue(cue):
            rows.append({"cue": cue, "source": "library"})
            continue
        progress(f"Fetching SFX for “{cue}” ({i + 1}/{len(cues)})",
                 0.72 + 0.24 * i / max(len(cues), 1))
        cands = audiolib.search_sfx(cue, max_dur=6.0)
        if not cands:
            rows.append({"cue": cue, "source": "procedural"})
            continue
        cand = cands[0]
        dest = config.SFX_LIB_DIR / f"fs_{cand['ext_id']}.wav"
        entry = audiolib.fetch(cand, dest, kind="sfx", seconds=6.0)
        if not entry:
            rows.append({"cue": cue, "source": "procedural"})
            continue
        if entry["file"] not in have_files:
            manifest.append({
                "id": dest.stem, "file": entry["file"],
                "tags": sorted(set(sfx._words(cue)) | set(entry.get("tags") or [])),
                "source": "freesound", "pre": sfx.is_pre(cue),
                "license": entry.get("license"), "attribution": entry.get("attribution"),
            })
            have_files.add(entry["file"])
        rows.append({"cue": cue, "source": "freesound",
                     "title": entry.get("title"), "license": entry.get("license"),
                     "attribution": entry.get("attribution"),
                     "cc0": "0" in (entry.get("license") or "")})
    storage.write_json(config.SFX_LIBRARY_FILE, manifest)
    return rows


# --- the scorer --------------------------------------------------------------
def score(pid: str, progress: ProgressFn) -> Dict:
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    audio_cfg = storage.get_settings().get("audio") or {}

    progress("Reading mood…", 0.05)
    label, query, seconds = _mood(project)

    bed = _pick_bed(project, label, query, seconds, progress)

    # Every scene should carry a beat cue; infer the blanks (author cues kept).
    progress("Placing sound effects…", 0.7)
    scenes = project.get("scenes", [])
    hook_n = 0
    for i, s in enumerate(scenes):
        if not (s.get("audio_cue") or "").strip():
            cue = autodirect._pick_cue(f"{s.get('narration')} {s.get('image_prompt')}")
            if not cue and i in range(1, 4):
                cue = "quick whoosh"          # early cuts always carry energy
            if cue:
                s["audio_cue"] = cue
                hook_n += 1

    cues, seen = [], set()
    for s in scenes:
        c = (s.get("audio_cue") or "").strip()
        key = c.lower()
        if c and key not in seen:
            seen.add(key)
            cues.append(c)
    sfx_rows: List[Dict] = []
    if audio_cfg.get("sfx_from_freesound", True) and audiolib.freesound_token():
        sfx_rows = _fetch_sfx(cues[:10], progress)
    else:
        sfx_rows = [{"cue": c, "source": "procedural"} for c in cues]

    # Attribution: bed (unless CC0/generated) + any non-CC0 stingers.
    credits: List[str] = []
    if bed.get("attribution") and not bed.get("cc0"):
        credits.append("Music: " + bed["attribution"])
    for r in sfx_rows:
        if r.get("attribution") and not r.get("cc0"):
            credits.append("SFX: " + r["attribution"])

    plan = {
        "mood": label, "query": query, "seconds": round(seconds, 1),
        "bed": bed, "sfx": sfx_rows, "cues_placed": hook_n,
        "attribution": credits, "scored": time.time(),
    }
    project["audio_plan"] = plan
    projects.save_project(project)
    progress("Scored", 1.0)
    return {"mood": label, "bed": bed.get("source"),
            "bed_title": bed.get("title"),
            "sfx": {"fetched": sum(1 for r in sfx_rows if r["source"] == "freesound"),
                    "cues": len(cues)},
            "attribution": credits}


def submit_score(pid: str) -> str:
    if not projects.get_project(pid):
        raise ValueError("Project not found.")

    def task(progress: ProgressFn) -> Dict:
        return score(pid, progress)

    return jobs.submit("score", task)
