"""Channel studies (architecture v2): pick a reference channel, capture its
branding, gather its top videos as evidence packs, stage skill distillation.

A study is the INTAKE half of the skill-training loop:
  1. resolve the channel (any URL/@handle) via yt-dlp: name, subs, about,
     avatar + banner (saved into the study folder), and its uploads ranked
     by views (top ~300 most recent uploads, Shorts filtered out)
  2. pick the top N videos and run each through app.gatherer at dense
     sampling (the composition study needs per-second frames)
  3. Claude reads the packs + branding and writes the skill packs into
     data/studies/<sid>/skills/ following SKILL_PACKS.md (repo root)

"Get more samples" is first-class: the record keeps a ranked candidates list
so distillation can honestly request more evidence (POST .../gather {more}).

Records persist to data/studies/<sid>/study.json and survive restarts. The
study job itself is light (network only); the heavy GPU work is the gather
jobs it queues, which serialize on the shared worker.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from . import config, gatherer, jobs

STUDIES_DIR = config.DATA_DIR / "studies"
TRASH_DIR = config.TRASH_DIR / "studies"

MIN_LONGFORM_S = 75          # belt against Shorts leaking into the /videos tab
CANDIDATE_POOL = 30          # ranked candidates kept for "get more samples"
SCAN_LIMIT = 300             # most recent uploads scanned for the ranking

_records: Dict[str, Dict] = {}
_lock = threading.Lock()
_loaded = False


# ---------------------------------------------------------------- records

def _persist(sid: str) -> None:
    with _lock:
        rec = _records.get(sid)
        snap = dict(rec) if rec else None
    if not snap:
        return
    d = STUDIES_DIR / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                                  encoding="utf-8")


def _set(sid: str, **kw) -> None:
    with _lock:
        if sid in _records:
            _records[sid].update(kw)


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
    STUDIES_DIR.mkdir(parents=True, exist_ok=True)
    for jf in STUDIES_DIR.glob("*/study.json"):
        try:
            rec = json.loads(jf.read_text(encoding="utf-8"))
            if rec.get("status") in ("resolving",):
                rec["status"] = "error"
                rec["error"] = "interrupted (server restarted)"
                jf.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                              encoding="utf-8")
            with _lock:
                _records[rec["id"]] = rec
        except Exception:  # noqa: BLE001
            continue


def _skills_on_disk(sid: str) -> List[str]:
    d = STUDIES_DIR / sid / "skills"
    return sorted(p.name for p in d.glob("*.*")) if d.is_dir() else []


def list_records() -> List[Dict]:
    _load()
    with _lock:
        recs = [dict(r) for r in _records.values()]
    packs = {p["id"]: p for p in gatherer.list_records()}
    out = []
    for r in sorted(recs, key=lambda x: x.get("created", 0), reverse=True):
        vids = []
        for v in r.get("videos") or []:
            v = dict(v)
            g = packs.get(v.get("gid") or "")
            if g:
                v["gather"] = {"status": g["status"], "stage": g.get("stage"),
                               "pct": g.get("pct"),
                               "summary": {k: (g.get("summary") or {}).get(k)
                                           for k in ("shots", "cuts_per_min",
                                                     "wpm_speaking", "duration")}}
            vids.append(v)
        r["videos"] = vids
        r["skills"] = _skills_on_disk(r["id"])
        out.append(r)
    return out


# ---------------------------------------------------------------- resolve

def _normalize_channel(s: str) -> str:
    s = (s or "").strip().split("?")[0].rstrip("/")
    if not s:
        raise ValueError("no channel given")
    if re.fullmatch(r"UC[A-Za-z0-9_-]{20,24}", s):
        s = f"https://www.youtube.com/channel/{s}"
    elif s.startswith("@"):
        s = f"https://www.youtube.com/{s}"
    elif not s.startswith("http"):
        if "youtube.com" in s:
            s = "https://" + s.lstrip("/")
        else:
            s = f"https://www.youtube.com/@{s}"
    # a pasted tab URL should not double up when we append /videos
    for tab in ("/videos", "/featured", "/shorts", "/streams", "/community",
                "/playlists", "/about"):
        if s.endswith(tab):
            s = s[: -len(tab)]
            break
    return s


def _pick_branding(info: Dict) -> Dict[str, Optional[str]]:
    """Best-effort avatar + banner URLs from a channel page's thumbnails."""
    thumbs = info.get("thumbnails") or []
    avatar = banner = None
    for t in thumbs:
        tid = str(t.get("id") or "")
        if "avatar" in tid:
            avatar = t.get("url") or avatar
        if "banner" in tid:
            banner = t.get("url") or banner
    if not avatar:
        squares = [t for t in thumbs
                   if t.get("width") and t.get("height")
                   and 0.9 <= t["width"] / t["height"] <= 1.1]
        if squares:
            avatar = max(squares, key=lambda t: t["width"])["url"]
    if not banner:
        wides = [t for t in thumbs
                 if t.get("width") and t.get("height")
                 and t["width"] / t["height"] > 3.0]
        if wides:
            banner = max(wides, key=lambda t: t["width"])["url"]
    return {"avatar": avatar, "banner": banner}


def _save_image(url: Optional[str], dest: Path) -> Optional[str]:
    if not url:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read()
        raw = dest.with_suffix(".raw")
        raw.write_bytes(data)
        from PIL import Image
        with Image.open(raw) as im:
            im.convert("RGB").save(dest, "JPEG", quality=90)
        raw.unlink(missing_ok=True)
        return dest.name
    except Exception:  # noqa: BLE001
        return None


def _fetch_channel(url: str) -> Dict:
    """Channel meta + up to SCAN_LIMIT most recent long-form uploads (flat)."""
    import yt_dlp
    opts = {
        "extract_flat": "in_playlist",
        "playlistend": SCAN_LIMIT,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    ck = gatherer._cookies_file()
    if ck:
        opts["cookiefile"] = str(ck)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url + "/videos", download=False)

    entries = []
    for e in info.get("entries") or []:
        if not e:
            continue
        dur = e.get("duration")
        views = e.get("view_count")
        if dur is not None and dur < MIN_LONGFORM_S:
            continue
        if e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        entries.append({
            "id": e.get("id"),
            "url": e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}",
            "title": e.get("title") or "?",
            "views": int(views or 0),
            "duration": float(dur or 0),
        })
    entries.sort(key=lambda v: v["views"], reverse=True)

    return {
        "name": info.get("channel") or info.get("uploader") or info.get("title") or "?",
        "channel_id": info.get("channel_id") or info.get("id"),
        "handle": info.get("uploader_id") or "",
        "url": info.get("channel_url") or info.get("uploader_url") or url,
        "subs": info.get("channel_follower_count"),
        "description": (info.get("description") or "").strip(),
        "keywords": info.get("tags") or [],
        "branding_urls": _pick_branding(info),
        "scanned": len(entries),
        "entries": entries,
    }


# ---------------------------------------------------------------- submit

def submit(channel: str, count: int = 5, sampling: str = "1s",
           model: str = "large-v3", auto_gather: bool = True,
           keep_video: bool = False) -> str:
    """Create a study and queue its resolve job. Returns the study id."""
    _load()
    url = _normalize_channel(channel)
    if model not in gatherer.ALLOWED_MODELS:
        raise ValueError(f"model must be one of {gatherer.ALLOWED_MODELS}")
    if sampling not in gatherer.SAMPLING:
        raise ValueError(f"sampling must be one of {list(gatherer.SAMPLING)}")
    count = max(1, min(12, int(count)))

    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    rec = {
        "id": sid, "created": time.time(),
        "status": "resolving", "error": None,
        "input": channel, "options": {"count": count, "sampling": sampling,
                                      "model": model,
                                      "auto_gather": bool(auto_gather),
                                      # keep the mp4s (LoRA dataset, 2026-07-14)
                                      "keep_video": bool(keep_video)},
        "channel": {"url": url, "name": "?"},
        "videos": [], "candidates": [], "job_id": None,
    }
    with _lock:
        _records[sid] = rec
    jid = jobs.submit("study", _runner(sid))
    _set(sid, job_id=jid)
    _persist(sid)
    return sid


def _runner(sid: str):
    def fn(progress) -> Dict:
        with _lock:
            rec = dict(_records.get(sid) or {})
        opts = rec.get("options") or {}
        d = STUDIES_DIR / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / "skills").mkdir(exist_ok=True)
        try:
            progress("resolve channel", 0.1)
            ch = _fetch_channel(rec["channel"]["url"])
            entries = ch.pop("entries")
            branding = ch.pop("branding_urls")
            if not entries:
                raise RuntimeError("no long-form uploads found on this channel")

            progress("save branding", 0.55)
            ch["avatar"] = _save_image(branding.get("avatar"), d / "avatar.jpg")
            ch["banner"] = _save_image(branding.get("banner"), d / "banner.jpg")

            count = int(opts.get("count", 5))
            top = entries[:count]
            candidates = entries[:max(CANDIDATE_POOL, count)]
            videos = [{"id": v["id"], "url": v["url"], "title": v["title"],
                       "views": v["views"], "duration": v["duration"], "gid": None}
                      for v in top]
            _set(sid, channel=ch, videos=videos, candidates=candidates)
            _persist(sid)

            if opts.get("auto_gather", True):
                progress("queue gathers", 0.8)
                _gather_videos(sid, [v["id"] for v in videos])
            _set(sid, status="ready")
            return {"sid": sid, "videos": len(videos), "channel": ch["name"]}
        except jobs.JobCancelled:
            _set(sid, status="cancelled", error="cancelled by user")
            raise
        except Exception as exc:  # noqa: BLE001
            _set(sid, status="error", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            _persist(sid)
    return fn


def _gather_videos(sid: str, video_ids: List[str]) -> List[str]:
    """Queue gather jobs for the given study videos (skips already-gathered)."""
    with _lock:
        rec = _records.get(sid)
        if not rec:
            raise ValueError("no such study")
        opts = rec.get("options") or {}
        todo = [v for v in rec["videos"] if v["id"] in video_ids and not v.get("gid")]
        urls = [v["url"] for v in todo]
    if not urls:
        return []
    gids = gatherer.submit(urls, {"model": opts.get("model", "large-v3"),
                                  "quality": 720,
                                  "sampling": opts.get("sampling", "1s"),
                                  "keep_video": bool(opts.get("keep_video")),
                                  "include_words": True})
    with _lock:
        rec = _records.get(sid)
        if rec:
            by_id = {v["id"]: v for v in rec["videos"]}
            for v, gid in zip(todo, gids):
                if v["id"] in by_id:
                    by_id[v["id"]]["gid"] = gid
    _persist(sid)
    return gids


def gather_more(sid: str, more: int = 2) -> Dict:
    """Honest sample expansion: promote the next ranked candidates into the
    study and gather them (the distillation step calls for this when rules
    do not converge on the initial sample)."""
    _load()
    with _lock:
        rec = _records.get(sid)
        if not rec:
            raise ValueError("no such study")
        have = {v["id"] for v in rec["videos"]}
        nxt = [c for c in rec.get("candidates") or [] if c["id"] not in have][:max(1, int(more))]
        for c in nxt:
            rec["videos"].append({"id": c["id"], "url": c["url"], "title": c["title"],
                                  "views": c["views"], "duration": c["duration"],
                                  "gid": None})
        ids = [c["id"] for c in nxt]
    if not ids:
        raise ValueError("no more ranked candidates; scan a wider window")
    gids = _gather_videos(sid, ids)
    _persist(sid)
    return {"added": ids, "gather_ids": gids}


def delete(sid: str) -> None:
    """Move the study folder to trash (never destroy)."""
    _load()
    with _lock:
        rec = _records.pop(sid, None)
    if rec is None and not (STUDIES_DIR / sid).exists():
        raise ValueError("no such study")
    src = STUDIES_DIR / sid
    if src.exists():
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(TRASH_DIR / f"{sid}-{int(time.time())}"))


def file_path(sid: str, name: str) -> Path:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", sid or ""):
        raise ValueError("no such study")
    base = (STUDIES_DIR / sid).resolve()
    p = (base / name).resolve()
    if base not in p.parents or not p.is_file():
        raise ValueError("no such file")
    return p
