"""Channels — persistent identities for running multiple YouTube channels.

A channel owns everything that should stay constant across its videos: the
niche, the art direction, the narrator voice, the editing preset, the engine /
quality choices, the music vibe, and how its scripts get written (pro model vs
assisted small-model mode). Creating a project inside a channel inherits all
of it; the storyboard only has to bring narration + picture subjects.

Storage (re-architected 2026-07-03): **each channel is a folder** —

    data/channels/<cid>/
        channel.json      the record (identity, defaults, brief, youtube…)
        projects/<pid>/   every video made in this channel (same layout as before)
        ui/               optional per-channel UI, vibe-code it freely:
                            ui.json    {"accent": "#e6a94b"} tints the studio UI
                            theme.css  injected into the studio UI inside this channel
                            index.html FULL custom UI, served at /ch/<cid>/

The only things channels share are the tools (Qwen3-TTS, krea2, Wan, ACE…).

The old single-file ``data/channels.json`` (five seed channels) is migrated on
first load: all of them are MERGED into one channel ("main") that keeps the
proven defaults, the combined topic banks / SEO pools, and the full originals
under ``merged_from`` (resurrect any of them later by copying that record into
a new channel). Existing projects move into its projects/ folder. The original
registry is kept as ``channels.legacy.json``.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import config, storage

# The engine keys create_project understands (projects._apply_engines).
_ENGINE_KEYS = ("image_model", "animate_engine", "quality", "preset", "authoring",
                "coverage")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _now() -> float:
    return time.time()


# --- paths -------------------------------------------------------------------
def _safe_cid(cid: str) -> str:
    cid = (cid or "").strip().lower()
    if not _ID_RE.match(cid):
        raise ValueError(f"bad channel id: {cid!r}")
    return cid


def channel_dir(cid: str) -> Path:
    return config.CHANNELS_DIR / _safe_cid(cid)


def projects_root(cid: str) -> Path:
    return channel_dir(cid) / "projects"


def ui_dir(cid: str) -> Path:
    return channel_dir(cid) / "ui"


def _record_file(cid: str) -> Path:
    return channel_dir(cid) / "channel.json"


def ensure_dirs(cid: str) -> Path:
    d = channel_dir(cid)
    for sub in ("projects", "ui"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


# --- per-channel UI ------------------------------------------------------------
def ui_info(cid: str) -> Dict:
    """What this channel's ui/ folder provides (drives theming + /ch/<cid>/)."""
    try:
        d = ui_dir(cid)
    except ValueError:
        return {}
    info = dict(storage.read_json(d / "ui.json", None) or {})
    info["theme_css"] = (d / "theme.css").exists()
    info["custom_index"] = (d / "index.html").exists()
    return info


# --- default channel (fresh install / migration target) -----------------------
DEFAULT_CHANNEL: Dict = {
    "id": "main",
    "name": "Main",
    "niche": "Everything channel — split real channels out of it as you go",
    "tagline": "The whole studio, one channel.",
    "cadence": "as produced",
    "defaults": {
        "image_model": "krea2", "animate_engine": "wan", "quality": "balanced",
        "preset": "cinematic", "authoring": "pro", "coverage": "heroes",
        "voice": "Ryan", "language": "English",
        "voice_instruct": ("Speak like a seasoned documentary narrator - dry, "
                           "confident, never rushed."),
        "style_suffix": ("1940s noir editorial-cartoon illustration: confident ink "
                         "linework, flat muted paper tones of charcoal, cream and "
                         "smoke gray with one scarlet accent per scene, dramatic "
                         "hard shadows, subtle paper grain, clean uncluttered "
                         "composition"),
        "negative_style": "photorealistic, 3d render, glossy, neon, cluttered",
        "music_vibe": "smoky noir jazz, upright bass, brushed drums, slow-building tension",
    },
    "brief": ("Open on the story's most outrageous moment, never on background. "
              "Escalate stake by stake; the payoff reveals the one detail that "
              "changes everything."),
    "topic_bank": [],
    "seo_keywords": ["documentary", "true story", "explained", "history"],
    "youtube": {},
}


# --- legacy migration ----------------------------------------------------------
_migrated = False


def _have_folders() -> bool:
    if not config.CHANNELS_DIR.exists():
        return False
    return any((d / "channel.json").exists() for d in config.CHANNELS_DIR.iterdir()
               if d.is_dir())


def _merged_channel(old: List[Dict]) -> Dict:
    """Fold every legacy channel into one 'main' record. Nothing is lost:
    the untouched originals ride along under merged_from."""
    base = next((c for c in old if c.get("id") == "grift"), old[0] if old else {})
    ch = storage.deep_merge(dict(DEFAULT_CHANNEL), {
        "defaults": dict(base.get("defaults") or {}),
        "brief": base.get("brief") or DEFAULT_CHANNEL["brief"],
    })
    ch["id"], ch["name"] = "main", "Main"
    topics: List[str] = []
    seo: List[str] = []
    for c in old:
        topics.extend(t for t in (c.get("topic_bank") or []) if t not in topics)
        seo.extend(k for k in (c.get("seo_keywords") or []) if k not in seo)
    if topics:
        ch["topic_bank"] = topics
    if seo:
        ch["seo_keywords"] = seo[:30]
    yt = next((c.get("youtube") for c in old
               if (c.get("youtube") or {}).get("client_id")), None)
    ch["youtube"] = dict(yt or {})
    if old:
        ch["merged_from"] = old
        ch["niche"] = ("Everything channel — " +
                       ", ".join(c.get("name", "?") for c in old) +
                       " merged; split them back out as you create real channels")
    ch["created"] = ch["updated"] = _now()
    ch["stats"] = {"projects": 0, "last_project": None}
    return ch


def _migrate() -> None:
    """One-time: single-file registry + flat data/projects → folder-per-channel.
    Idempotent — a data/channels/*/channel.json existing means it already ran."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    if _have_folders():
        return
    # Disaster restore first: if the channel folders are gone but the
    # registry snapshot survived, rebuild every channel record from it
    # instead of re-merging the 2026-07-03 legacy backup (which silently
    # forgets every channel created since, as happened on 2026-07-09).
    backup = storage.read_json(config.DATA_DIR / "channels.backup.json", None)
    if isinstance(backup, list) and backup:
        restored = 0
        for rec in backup:
            if isinstance(rec, dict) and rec.get("id"):
                try:
                    d = ensure_dirs(rec["id"])
                except ValueError:
                    continue
                storage.write_json(d / "channel.json", rec)
                restored += 1
        if restored:
            print(f"[channels] restored {restored} channel record(s) "
                  "from channels.backup.json")
            return
    legacy = storage.read_json(config.CHANNELS_FILE, None)
    merged = _merged_channel(legacy if isinstance(legacy, list) else [])
    d = ensure_dirs("main")

    # Adopt every existing flat project into the merged channel's folder.
    moved: List[Path] = []
    if config.PROJECTS_DIR.exists():
        for p in sorted(config.PROJECTS_DIR.iterdir()):
            if not (p / "project.json").exists():
                continue
            dest = d / "projects" / p.name
            shutil.move(str(p), str(dest))
            pj = storage.read_json(dest / "project.json", None)
            if isinstance(pj, dict):
                pj["channel"] = "main"
                storage.write_json(dest / "project.json", pj)
            moved.append(dest)
    if moved:
        moved.sort(key=lambda x: (x / "project.json").stat().st_mtime)
        merged["stats"] = {"projects": len(moved), "last_project": moved[-1].name}
    storage.write_json(d / "channel.json", merged)

    if config.CHANNELS_FILE.exists():        # keep the old registry as a backup
        bak = config.DATA_DIR / "channels.legacy.json"
        try:
            bak.unlink(missing_ok=True)
            config.CHANNELS_FILE.rename(bak)
        except OSError:
            pass


# --- registry API (signatures unchanged from the single-file era) --------------
def load() -> List[Dict]:
    """All channels, oldest first, each with a live ``ui`` info block."""
    _migrate()
    out: List[Dict] = []
    if not config.CHANNELS_DIR.exists():
        return out
    for d in config.CHANNELS_DIR.iterdir():
        rec = storage.read_json(d / "channel.json", None) if d.is_dir() else None
        if isinstance(rec, dict) and rec.get("id"):
            rec["ui"] = ui_info(rec["id"])
            # expose only WHETHER the vault holds a connection, never the keys
            try:
                sec = storage.read_json(_secrets_file(rec["id"]), None) or {}
                rec.setdefault("youtube", {})["connected"] = bool(
                    sec.get("refresh_token"))
            except (ValueError, OSError):
                pass
            out.append(rec)
    out.sort(key=lambda c: c.get("created") or 0)
    return out


def _backup_registry() -> None:
    """Snapshot every channel record to data/channels.backup.json on each
    write. That file is gitignored (data/*.json), so it survives the
    git-clean class of accident that wiped data/channels/ on 2026-07-09;
    _migrate restores channels from it before falling back to the legacy
    merge. Records only, no projects, no secrets (those live in the vault)."""
    try:
        recs = []
        for d in config.CHANNELS_DIR.iterdir():
            rec = storage.read_json(d / "channel.json", None) if d.is_dir() else None
            if isinstance(rec, dict) and rec.get("id"):
                recs.append(rec)
        if recs:
            storage.write_json(config.DATA_DIR / "channels.backup.json", recs)
    except Exception:  # noqa: BLE001 - never let the safety net block a write
        pass


def _write(ch: Dict) -> Dict:
    rec = {k: v for k, v in ch.items() if k != "ui"}   # ui/ folder is the truth
    ensure_dirs(rec["id"])
    storage.write_json(_record_file(rec["id"]), rec)
    _backup_registry()
    return dict(rec, ui=ui_info(rec["id"]))


# --- YouTube secrets vault (user rule 2026-07-05: keys must be PRIVATE on
# GitHub). channel.json (tracked in git) never holds credentials; they live in
# data/secrets/<cid>.json which .gitignore excludes. get() merges them back in
# memory so youtube.py keeps working unchanged.
_SECRET_KEYS = ("client_id", "client_secret", "refresh_token", "token",
                "access_token")


def _secrets_file(cid: str) -> Path:
    d = config.DATA_DIR / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe_cid(cid)}.json"


def _split_secrets(rec: Dict) -> Dict:
    """Move credential fields out of rec['youtube'] into the vault (merging
    with what's already there); rec keeps only non-secret fields (privacy)."""
    yt = rec.get("youtube")
    if not isinstance(yt, dict):
        return rec
    secrets = {k: yt.pop(k) for k in list(yt) if k in _SECRET_KEYS and yt[k]}
    for k in _SECRET_KEYS:
        yt.pop(k, None)
    if secrets:
        cur = storage.read_json(_secrets_file(rec["id"]), {}) or {}
        cur.update(secrets)
        storage.write_json(_secrets_file(rec["id"]), cur)
    return rec


def _merge_secrets(rec: Dict) -> Dict:
    try:
        sec = storage.read_json(_secrets_file(rec["id"]), None)
        if isinstance(sec, dict) and sec:
            rec["youtube"] = {**(rec.get("youtube") or {}), **sec}
    except (ValueError, OSError):
        pass
    return rec


def get(cid: Optional[str]) -> Optional[Dict]:
    if not cid:
        return None
    _migrate()
    try:
        rec = storage.read_json(_record_file(cid), None)
    except ValueError:
        return None
    if isinstance(rec, dict) and rec.get("id"):
        rec["ui"] = ui_info(rec["id"])
        return _merge_secrets(rec)
    return None


def upsert(channel: Dict) -> Dict:
    cid = (channel.get("id") or "").strip()
    if not cid:
        cid = re.sub(r"[^a-z0-9]+", "-", (channel.get("name") or "").lower()).strip("-")
        if not cid:
            raise ValueError("Channel needs an id or a name.")
        channel["id"] = cid
    _safe_cid(cid)
    old = get(cid)
    if old:
        old.pop("ui", None)
        merged = storage.deep_merge(old, channel)
        merged["updated"] = _now()
        return _write(_split_secrets(merged))
    channel.setdefault("defaults", {})
    channel.setdefault("youtube", {})
    channel.setdefault("stats", {"projects": 0, "last_project": None})
    channel["created"] = channel["updated"] = _now()
    return _write(_split_secrets(channel))


def remove(cid: str) -> bool:
    """Delete = move the whole channel folder (projects included) to data/trash.
    Nothing is destroyed; restore by moving it back."""
    try:
        d = channel_dir(cid)
    except ValueError:
        return False
    if not d.exists():
        return False
    dest = config.TRASH_DIR / "channels" / f"{cid}-{int(_now())}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return True


def note_project(cid: str, pid: str) -> None:
    """Remember that a project was created in this channel (stats on the card)."""
    ch = get(cid)
    if not ch:
        return
    st = ch.setdefault("stats", {})
    st["projects"] = int(st.get("projects") or 0) + 1
    st["last_project"] = pid
    ch["updated"] = _now()
    _write(ch)


def default_engines(channel: Dict) -> Dict:
    """The channel's defaults in the shape projects._apply_engines expects."""
    d = (channel or {}).get("defaults") or {}
    return {k: d[k] for k in _ENGINE_KEYS if d.get(k)}


def authoring_prompt(channel: Dict, topic: Optional[str] = None) -> str:
    """The full copy-paste prompt for writing this channel's next script.

    Bundles the storyboard authoring spec with the channel's brief, tone and
    topic bank, so ANY model (including a small one in assisted mode) receives
    identical instructions. The channel supplies the art direction - the writer
    must leave global_style_suffix empty.
    """
    spec = ""
    tpl = config.BASE_DIR / "storyboard_v3_prompt.md"
    if tpl.exists():
        spec = tpl.read_text(encoding="utf-8")
    d = (channel or {}).get("defaults") or {}
    lines = [
        f"# CHANNEL BRIEF — {channel.get('name')} ({channel.get('niche')})",
        "",
        f"Tagline: {channel.get('tagline', '')}",
        f"Audience: {channel.get('audience', '')}",
        f"Writing brief: {channel.get('brief', '')}",
        "",
        "Rules for THIS channel:",
        "- Leave video.global_style_suffix EMPTY — the channel's art direction "
        "is applied automatically on import.",
        "- Write picture subjects that suit this look: " + (d.get("style_suffix") or "")[:160] + "…",
        f"- Narration will be voiced by one narrator ({d.get('voice', 'Ryan')}); "
        "write for a single continuous read.",
    ]
    if topic:
        lines += ["", f"TODAY'S TOPIC: {topic}"]
    else:
        bank = channel.get("topic_bank") or []
        if bank:
            lines += ["", "Pick ONE topic (or take the first unused):"]
            lines += [f"- {t}" for t in bank]
    return spec + "\n\n---\n\n" + "\n".join(lines) + "\n"
